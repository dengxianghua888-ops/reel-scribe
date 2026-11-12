"""Target-environment dependency inventory for the portable Skill bundle.

This module never downloads, installs, renders, loads a model, or opens a host
project. A positive observation means only that declared prerequisites were
found at probe time. It does not certify an operation or creative quality.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sqlite3
import sys
import subprocess
from fractions import Fraction
from contextlib import contextmanager
from threading import RLock

SCHEMA = 'editing-install-diagnostics/1'
ASR_PACKAGES = ('faster-whisper', 'ctranslate2', 'av', 'tokenizers', 'numpy',
                'onnxruntime', 'huggingface-hub')
PACKAGE_NAMES = ('Pillow', 'numpy') + ASR_PACKAGES
# Profiles describe only this optional local runtime, not requirements for using
# a generic Skill with the running Agent's own editor tools. Added local atomic
# IDs fail closed until a dependency profile is declared.
ATOMIC_REQUIREMENTS = {
    'audio-extract': ('ffmpeg', 'ffprobe'),
    'audio-mix': ('ffmpeg', 'ffprobe'),
    'caption-burn': ('ffmpeg', 'ffprobe'),
    'caption-map': ('ffprobe',),
    'frame-extract': ('ffmpeg', 'ffprobe'),
    'media-inspect': ('ffprobe',),
    'media-qc': ('ffmpeg', 'ffprobe'),
    'speech-plan-compile': ('ffprobe',),
    'timeline-patch': ('ffprobe',),
    'timeline-render': ('ffmpeg', 'ffprobe'),
    'transcript-import': ('ffprobe',),
    'tts-macos': ('say', 'ffmpeg', 'ffprobe'),
    'screen-focus': ('ffmpeg', 'ffprobe'),
    'tutorial-plan-compile': ('ffprobe',),
    'timeline-revise': ('ffprobe',),
    'style-recipe-compile': ('ffprobe',),
    'creation-brief-prepare': ('sqlite',),
    'creation-recommendation': ('sqlite',),
    'reference-transfer-prepare': ('sqlite', 'ffprobe'),
    'result-preview-compile': ('sqlite', 'ffprobe'),
    'style-recipe-preview': ('sqlite', 'ffmpeg', 'ffprobe'),
    'revision-impact-inspect': ('ffprobe',),
    'work-render': ('sqlite', 'ffmpeg', 'ffprobe'),
    'work-version': ('sqlite',),
    'sync-offset-measure': ('ffprobe',),
    'multicam-plan-compile': ('ffprobe',),
    'evidence-plan-compile': ('ffprobe',),
    'media-signal-scan': ('ffmpeg', 'ffprobe'),
    'event-plan-compile': ('ffprobe',),
    'audio-envelope': ('ffmpeg', 'ffprobe'),
    'caption-coverage-check': ('ffprobe',),
    'cue-alignment-check': ('ffprobe',),
    'color-lut-apply': ('ffmpeg', 'ffprobe'),
    'still-image-render': ('ffmpeg', 'ffprobe', 'Pillow'),
    'localization-plan-compile': ('ffprobe',),
    'work-variant-create': ('sqlite', 'ffprobe', 'fcntl'),
    'work-batch-render': ('sqlite', 'fcntl'),
    'video-reframe': ('ffmpeg', 'ffprobe'),
    'speech-transcribe-local': ('ffmpeg', 'ffprobe', 'asr-environment', 'asr-model'),
    'transcript-reference-compare': ('ffprobe',),
    'visual-layer-render': ('ffmpeg', 'ffprobe'),
}


# A request selects one local runtime branch. Missing request data is not a
# successful branch observation; it is reported as conditional unknown.
BRANCH_KEYS = {'work-version': 'action', 'work-batch-render': 'action',
               'sync-offset-measure': 'method', 'caption-burn': 'font',
               'work-render': 'document', 'speech-transcribe-local': 'locks',
               'style-recipe-compile': 'recipe.layout_constraints',
               'style-recipe-preview': 'variants[].recipe.layout_constraints'}


def _selected_requirements(identifier, request):
    required = list(ATOMIC_REQUIREMENTS[identifier])
    unknown = []
    branch = None
    if identifier == 'work-version':
        branch = request.get('action') if request else None
        if branch in ('init', 'commit', 'set-protection', 'restore'):
            required.append('ffprobe')
        elif branch == 'relink-style-resources':
            required.append('style-resources')
        elif branch != 'read':
            unknown.append('action: read, relink-style-resources or document-validating mutation')
    elif identifier == 'work-batch-render':
        branch = request.get('action') if request else None
        if branch in ('prepare', 'run'):
            required += ['ffmpeg', 'ffprobe']
        elif branch != 'status':
            unknown.append('action: status, prepare or run')
        if branch == 'run':
            unknown.append('selected stored WorkDocument content and nested render branches')
    elif identifier == 'sync-offset-measure':
        branch = request.get('method') if request else None
        if branch == 'audio-correlation':
            required += ['ffmpeg', 'numpy']
        elif branch not in ('declared-clock', 'declared-markers'):
            unknown.append('method: declared-clock, declared-markers or audio-correlation')
    elif identifier in ('style-recipe-compile', 'style-recipe-preview'):
        if request is None:
            unknown.append('optional recipe layout constraints require actual FFmpeg/Pillow coverage checks')
        else:
            recipes = ([request.get('recipe')] if identifier == 'style-recipe-compile' else
                       [v.get('recipe') for v in request.get('variants', []) if isinstance(v, dict)])
            if any(isinstance(recipe, dict) and 'layout_constraints' in recipe for recipe in recipes):
                required += ['ffmpeg', 'Pillow']
                branch = 'actual-static-caption-layout'
            else:
                branch = 'no-layout-constraints'
    elif identifier == 'caption-burn':
        if request is None:
            unknown.append('request.font path and hash')
        else:
            required.append('font')
    elif identifier == 'work-render':
        if request is None:
            unknown.append('stored WorkDocument captions, overlays and audio tracks')
    elif identifier == 'speech-transcribe-local' and request is None:
        unknown.append('request model/environment lock identity')
    return tuple(dict.fromkeys(required)), unknown, branch


def _stored_work_document(request):
    """Read a selected Work head without changing its store or validating media."""
    raw = request.get('store')
    if not isinstance(raw, str) or not Path(raw).is_absolute():
        return None, 'absolute work store path not supplied'
    store = Path(raw)
    if not store.is_file():
        return None, 'selected work store missing'
    try:
        db = sqlite3.connect(store.resolve().as_uri() + '?mode=ro', uri=True, timeout=0)
        try:
            if db.execute('PRAGMA user_version').fetchone()[0] != 1:
                return None, 'work store schema not verified'
            metadata = dict(db.execute('SELECT key,value FROM metadata'))
            if 'head' not in metadata or 'work_id' not in metadata:
                return None, 'work head or identity missing'
            sequence = int(metadata['head'])
            row = db.execute('SELECT version,digest,document FROM revisions WHERE sequence=?', (sequence,)).fetchone()
            if row is None or request.get('expected_version') != row[0]:
                return None, 'work version missing or differs from request'
            document = json.loads(row[2])
            canonical = json.dumps(document, ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'), allow_nan=False).encode()
            if hashlib.sha256(canonical).hexdigest() != row[1]:
                return None, 'stored document hash mismatch'
            version_payload = {'work_id': metadata['work_id'], 'sequence': sequence,
                               'document_sha256': row[1]}
            version_bytes = json.dumps(version_payload, ensure_ascii=False, sort_keys=True,
                                       separators=(',', ':'), allow_nan=False).encode()
            if hashlib.sha256(version_bytes).hexdigest() != row[0]:
                return None, 'work version hash mismatch'
            return document, None
        finally:
            db.close()
    except (OSError, ValueError, sqlite3.Error, TypeError, KeyError):
        return None, 'work store could not be read consistently'


def _preview_work_document(request, base_document):
    """Read a hash-bound candidate for dependency diagnosis, without adopting it."""
    ref = request.get('preview_candidate')
    if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'}:
        return None, 'preview_candidate path and sha256 required'
    raw, expected = ref['path'], ref['sha256']
    if not isinstance(raw, str) or not Path(raw).is_absolute() or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        return None, 'preview_candidate identity invalid'
    path = Path(raw)
    if not path.is_file():
        return None, 'preview_candidate file missing'
    try:
        raw_bytes = path.read_bytes()
        if hashlib.sha256(raw_bytes).hexdigest() != expected:
            return None, 'preview_candidate hash mismatch'
        bundle = json.loads(raw_bytes.decode('utf-8'))
        base_bytes = json.dumps(base_document, ensure_ascii=False, sort_keys=True,
                                separators=(',', ':'), allow_nan=False).encode()
        base_digest = hashlib.sha256(base_bytes).hexdigest()
        if (not isinstance(bundle, dict) or bundle.get('schema') != 'work-candidate/1'
                or bundle.get('base_version') != request.get('expected_version')
                or bundle.get('base_document_sha256') != base_digest
                or not isinstance(bundle.get('document'), dict)):
            return None, 'preview_candidate base or document invalid'
        return bundle['document'], None
    except (OSError, UnicodeError, ValueError, TypeError):
        return None, 'preview_candidate could not be read consistently'


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def _bundle_core_binding(root: Path):
    """Check only diagnostic-critical files against a built bundle manifest."""
    manifest = root / 'bundle-manifest.json'
    if not manifest.is_file():
        manifest = root / 'plugin-package-manifest.json'
    if not manifest.is_file():
        return {'status': 'WORKTREE_OR_UNMANIFESTED_ROOT',
                'limit': 'No built-bundle identity claim.'}
    try:
        data = json.loads(manifest.read_text())
        if data.get('schema') not in ('editing-portable-bundle/1', 'editing-codex-plugin-package/1'):
            raise ValueError('BUNDLE_MANIFEST_SCHEMA_INVALID')
        rows = {row['path']: row for row in data['files']}
        required = ('registry/skills.json', 'runtime/tool_identity.py',
                    'runtime/dependency_discovery.py', 'scripts/install_doctor.py',
                    'runtime/editing_runtime.py', 'runtime/vorbis_group_clock.py')
        checked = []
        for name in required:
            file = root / name
            row = rows.get(name)
            if row is None or not file.is_file() or file.is_symlink():
                raise ValueError('BUNDLE_DIAGNOSTIC_FILE_MISSING: ' + name)
            actual = digest(file)
            if actual != row['sha256'] or file.stat().st_size != row['bytes']:
                raise ValueError('BUNDLE_DIAGNOSTIC_FILE_DRIFT: ' + name)
            checked.append({'path': name, 'sha256': actual})
        return {'status': 'DIAGNOSTIC_CORE_MATCHES_MANIFEST',
                'manifest_sha256': digest(manifest), 'checked': checked,
                'limit': 'Manifest is local data, not a signature or complete bundle audit.'}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return {'status': 'BUNDLE_DIAGNOSTIC_IDENTITY_FAILED', 'reason': str(exc),
                'recovery': 'Restore the exact manifest-bound diagnostic files or build a new reviewed bundle.'}


def _load_tool_identity(root: Path):
    source = root / 'runtime' / 'tool_identity.py'
    if not source.is_file() or source.is_symlink():
        raise ValueError('TOOL_IDENTITY_MODULE_MISSING_OR_SYMLINK')
    raw = source.read_bytes()
    before = hashlib.sha256(raw).hexdigest()
    spec = importlib.util.spec_from_file_location('_editing_install_tool_identity', source)
    module = importlib.util.module_from_spec(spec)
    exec(compile(raw, str(source), 'exec'), module.__dict__)
    if digest(source) != before:
        raise ValueError('TOOL_IDENTITY_MODULE_DRIFT')
    return module, {'path': str(source), 'sha256': before}


def _tool_candidate(name: str, cli_value: str | None, env: dict[str, str]):
    key = 'EDITING_' + name.upper()
    if cli_value is not None:
        return cli_value, 'cli'
    if key in env:
        return env[key], key
    return shutil.which(name, path=env.get('PATH')), 'PATH'


def _inspect_media_tool(name, cli_value, env, identity):
    path, origin = _tool_candidate(name, cli_value, env)
    if not path:
        return {'status': 'MISSING', 'origin': origin,
                'reason': 'NO_CONFIGURED_OR_PATH_EXECUTABLE',
                'recovery': f'Provide --{name} /absolute/verified/{name} or EDITING_{name.upper()} and rerun on the target host.'}
    if not Path(path).is_absolute():
        return {'status': 'UNRESOLVED', 'origin': origin, 'configured_path': path,
                'reason': 'ABSOLUTE_TOOL_PATH_REQUIRED',
                'recovery': f'Use an absolute --{name} path; do not rely on a relative working directory.'}
    observed = identity.inspect_tool(path)
    status = ('PRESENT_IDENTITY_OBSERVED' if observed['status'] == 'RESOLVED_EXECUTABLE_CHAIN'
              and observed['version_probe'] == 'SUCCEEDED' else 'UNRESOLVED')
    return {'status': status, 'origin': origin, 'configured_path': path,
            'identity': observed, 'recovery': None if status == 'PRESENT_IDENTITY_OBSERVED'
            else f'Resolve the recorded {name} chain/error and rerun; do not accept a wrapper hash alone.'}


def _python_probe():
    executable = Path(sys.executable)
    resolved = executable.resolve()
    row = {'status': 'OBSERVED_NOT_COMPATIBILITY_CERTIFIED', 'executable': str(executable),
           'resolved_executable': str(resolved), 'version': sys.version,
           'implementation': platform.python_implementation(), 'platform': platform.platform(),
           'machine': platform.machine(), 'sqlite_version': sqlite3.sqlite_version,
           'sha256': digest(resolved) if resolved.is_file() else None,
           'recovery': 'Run this command with the same Python interpreter used by the target runtime.'}
    try:
        import fcntl  # noqa: F401 - presence is the POSIX lock prerequisite
        row['posix_fcntl'] = True
    except ImportError:
        row['posix_fcntl'] = False
        row['lock_support'] = 'MISSING_FCNTL_FOR_BATCH_ONLY'
    return row


def _package_probe(name):
    try:
        version = importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return {'status': 'MISSING', 'version': None,
                'recovery': f'Install the pinned {name} distribution in the target Python environment, then rerun.'}
    return {'status': 'PRESENT_METADATA_ONLY', 'version': version,
            'recovery': None, 'limit': 'Import, native libraries and operation execution not checked.'}


def _bound_file(reference, label, allowed_suffixes=None):
    if not isinstance(reference, dict) or set(reference) != {'path', 'sha256'}:
        return {'status': 'INVALID_BINDING', 'reason': 'PATH_AND_SHA256_REQUIRED',
                'recovery': f'Provide {label} as an absolute path plus expected SHA-256.'}
    raw, expected = reference['path'], reference['sha256']
    if not isinstance(raw, str) or not Path(raw).is_absolute() or not isinstance(expected, str) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        return {'status': 'INVALID_BINDING', 'reason': 'ABSOLUTE_PATH_AND_SHA256_REQUIRED',
                'recovery': f'Correct the {label} path and 64-character SHA-256.'}
    path = Path(raw)
    if not path.is_file():
        return {'status': 'MISSING', 'path': raw, 'reason': 'BOUND_FILE_NOT_FOUND',
                'recovery': f'Restore the bound {label} file and rerun; never substitute a different byte stream silently.'}
    if allowed_suffixes and path.suffix.lower() not in allowed_suffixes:
        return {'status': 'INVALID_BINDING', 'path': raw, 'reason': 'UNSUPPORTED_FILE_SUFFIX',
                'recovery': f'Use a declared {label} format: {sorted(allowed_suffixes)}.'}
    try:
        actual = digest(path)
    except OSError as exc:
        return {'status': 'UNRESOLVED', 'path': raw, 'reason': str(exc),
                'recovery': f'Make the bound {label} readable and rerun.'}
    return {'status': 'PRESENT_HASH_BOUND' if actual == expected else 'HASH_MISMATCH',
            'path': str(path.resolve()), 'expected_sha256': expected, 'actual_sha256': actual,
            'bytes': path.stat().st_size,
            'recovery': None if actual == expected else f'Restore the expected {label} bytes or create a new reviewed binding.'}


def _style_resources_probe(request):
    """Read-only prerequisites, never a migration or media/protection validation."""
    rows=request.get('relocations')
    if not isinstance(rows,list) or not rows:
        return {'status':'NEEDS_BINDING','reason':'NONEMPTY_STYLE_RELOCATIONS_REQUIRED',
                'recovery':'Provide exact existing from refs and prepared same-SHA regular target files.'}
    document,reason=_stored_work_document(request)
    if document is None:
        return {'status':'UNRESOLVED','reason':reason,'recovery':'Read the actual current Work token first.'}
    bindings=document.get('style_bindings',{});seen=set();targets=[]
    for row in rows:
        if (not isinstance(row,dict) or set(row)!={'style_key','from','to'} or
                not isinstance(row.get('style_key'),str) or row['style_key'] not in bindings or
                row['style_key'] in seen or row['from']!=bindings[row['style_key']].get('card') or
                not isinstance(row['to'],dict) or not isinstance(row['from'],dict) or
                row['to'].get('sha256')!=row['from'].get('sha256')):
            return {'status':'INVALID_BINDING','reason':'STYLE_RELOCATION_DECLARATION_INVALID',
                    'recovery':'Keep the existing card SHA and use each existing style key once.'}
        seen.add(row['style_key'])
        target=_bound_file(row['to'],'relocated style card')
        if target['status']!='PRESENT_HASH_BOUND':return target
        path=Path(row['to']['path'])
        if (str(path.resolve())!=row['to']['path'] or any(p.is_symlink() for p in (path,*path.parents)) or
                not isinstance(row['from'].get('path'),str) or not Path(row['from']['path']).is_absolute() or
                Path(row['from']['path']).resolve()==path.resolve()):
            return {'status':'INVALID_BINDING','reason':'STYLE_RELOCATION_PATH_INVALID',
                    'recovery':'Use a distinct canonical regular-file target, without symlinks.'}
        targets.append({'style_key':row['style_key'],'target':target})
    return {'status':'PRESENT_HASH_BOUND','targets':targets,'recovery':None,
            'scope':'Work/current-token and target-file prerequisites only; no maintenance, media or protection execution.'}


def _asr_lock(root, reference, kind):
    label = 'ASR ' + kind + ' lock'
    bound = _bound_file(reference, label)
    if bound['status'] != 'PRESENT_HASH_BOUND':
        return bound
    # Reuse the exact current runtime lock validators. They hash the declared
    # model/package files but do not load the model or run inference.
    sys.path.insert(0, str(root / 'runtime'))
    try:
        import asr_ops
        if kind == 'model':
            _, lock, _ = asr_ops.verify_model(reference)
        else:
            _, lock = asr_ops.verify_environment(reference)
        return {**bound, 'status': 'PRESENT_LOCK_VERIFIED_NOT_EXECUTED',
                'lock_schema': lock['schema'], 'recovery': None}
    except (OSError, ValueError, KeyError, ImportError) as exc:
        return {**bound, 'status': 'LOCK_REJECTED', 'reason': str(exc),
                'recovery': f'Repair the exact {label} and its declared files/environment, then rerun.'}
    finally:
        sys.path.remove(str(root / 'runtime'))


def _say_probe(env):
    if platform.system() != 'Darwin':
        return {'status': 'UNSUPPORTED_PLATFORM', 'recovery': 'Use a declared TTS provider for this platform; macOS say is unavailable.'}
    path = shutil.which('say', path=env.get('PATH'))
    if not path:
        return {'status': 'MISSING', 'recovery': 'Make the macOS say binary available in the target environment.'}
    resolved = Path(path).resolve()
    return {'status': 'PRESENT_NOT_INVOKED', 'path': str(resolved), 'sha256': digest(resolved),
            'recovery': None, 'limit': 'Voice installation and audio generation not checked.'}


def _dependency_status(name, components):
    if name in ('python', 'sqlite'):
        return 'PRESENT'
    return components[name]['status']


def _capability_status(requirements, components):
    statuses = {name: _dependency_status(name, components) for name in requirements}
    if any(v in ('MISSING', 'UNRESOLVED', 'HASH_MISMATCH', 'LOCK_REJECTED',
                 'INVALID_BINDING', 'UNSUPPORTED_PLATFORM') for v in statuses.values()):
        return 'DEPENDENCY_BLOCKED', statuses
    if any(v == 'NEEDS_BINDING' for v in statuses.values()):
        return 'NEEDS_BINDING', statuses
    return 'DECLARED_DEPENDENCIES_PRESENT_NOT_EXECUTED', statuses


_TARGET_RUNTIME_LOCK = RLock()


@contextmanager
def _target_clock_runtime(root):
    """Temporarily bind exact target modules; restore caller modules even on error."""
    root = Path(root).resolve()
    names = ('tool_identity', 'vorbis_group_clock', 'editing_runtime')
    with _TARGET_RUNTIME_LOCK:
        prior = {name: sys.modules.get(name) for name in names}
        identities = []
        try:
            for name in names:
                path = root / 'runtime' / (name + '.py')
                if not path.is_file() or path.is_symlink():
                    raise ValueError('TARGET_RUNTIME_MODULE_MISSING_OR_SYMLINK: ' + str(path))
                raw = path.read_bytes()
                before = hashlib.sha256(raw).hexdigest()
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                exec(compile(raw, str(path), 'exec'), module.__dict__)
                if digest(path) != before:
                    raise ValueError('TARGET_RUNTIME_MODULE_DRIFT: ' + str(path))
                identities.append({'path': str(path), 'sha256': before})
            yield sys.modules['editing_runtime'], identities
            for row in identities:
                if digest(Path(row['path'])) != row['sha256']:
                    raise ValueError('TARGET_RUNTIME_MODULE_DRIFT: ' + row['path'])
        finally:
            for name, module in prior.items():
                if module is None:
                    sys.modules.pop(name, None)
                else:
                    sys.modules[name] = module


def _stretch_probe(request, document, ffprobe_component, root=None):
    root = Path(root).resolve() if root is not None else Path(__file__).resolve().parents[1]
    # 1x/mute/legacy paths need no target DSP/clock modules.
    plan = request.get('plan') if isinstance(request, dict) and request.get('operation') == 'timeline-render' else (document or {}).get('plan')
    try:
        needed = (isinstance(request, dict) and request.get('operation') in ('timeline-render', 'work-render')
                  and not (isinstance(request.get('audio_backend'), dict) and request['audio_backend'].get('kind') == 'ffmpeg-atempo')
                  and isinstance(plan, dict) and any(Fraction(str(c.get('speed', '1'))) != 1
                      and not c.get('mute', False) and c['gain_db'] > -120 for c in plan.get('clips', [])))
        if not needed:
            return _stretch_probe_bound(request, document, ffprobe_component, None, [])
        with _target_clock_runtime(root) as (runtime, identities):
            return _stretch_probe_bound(request, document, ffprobe_component, runtime, identities)
    except (OSError, ValueError, TypeError, KeyError, ZeroDivisionError, ImportError) as exc:
        return {'status': 'NEEDS_BINDING', 'required': False, 'target_root': str(root)}, str(exc)


def _stretch_probe_bound(request, document, ffprobe_component, runtime, runtime_sources):
    """Read bound selected decoded audio windows; never DSP/render/install."""
    if request is None or request.get('operation') not in ('timeline-render', 'work-render'):
        return {'status': 'NOT_SELECTED', 'required': False}, None
    plan = request.get('plan') if request['operation'] == 'timeline-render' else (document or {}).get('plan')
    if not isinstance(plan, dict):
        return {'status': 'NEEDS_BINDING', 'required': False}, 'selected audio retime plan unknown'
    spec = request.get('audio_backend')
    if isinstance(spec, dict) and spec.get('kind') == 'ffmpeg-atempo':
        return {'status': 'NOT_REQUIRED', 'required': False, 'policy': 'explicit legacy atempo'}, None
    selected = []
    try:
        for clip in plan.get('clips', []):
            if (Fraction(str(clip.get('speed', '1'))) == 1 or clip.get('mute', False) or clip['gain_db'] <= -120):
                continue
            selected.append((plan['sources'][clip['source_id']], clip))
    except (ValueError, TypeError, KeyError, ZeroDivisionError):
        return {'status': 'NEEDS_BINDING', 'required': False}, 'valid selected retime clips unknown'
    if not selected:
        return {'status': 'NOT_REQUIRED', 'required': False, 'policy': '1x or muted; no DSP helper'}, None
    identity = ffprobe_component.get('identity', {}).get('resolved_binary')
    if not identity:
        return {'status': 'NEEDS_BINDING', 'required': False}, 'selected source audio stream presence unknown'
    observations = []
    try:
        clock_tools = runtime.Tools(ffprobe=identity['path'])
        audible = False
        any_audio_track = False
        for ref, clip in selected:
            path = Path(ref['path'])
            if not path.is_absolute() or digest(path) != ref['sha256']:
                raise ValueError('selected retime source identity invalid')
            media = clock_tools.probe(path)
            has_audio = any(x.get('codec_type') == 'audio' for x in media['streams'])
            any_audio_track = any_audio_track or has_audio
            start, end = runtime.span(clip['start'], clip['end'], media['duration'])
            speed, fps = Fraction(str(clip.get('speed', '1'))), Fraction(str(plan['fps']))
            if not Fraction(1, 2) <= speed <= 2 or not 1 <= fps <= 120:
                raise ValueError('selected retime speed or fps invalid')
            frames = round((Fraction(str(end))-Fraction(str(start)))*fps/speed)
            if frames <= 0:
                raise ValueError('selected retime subframe clip')
            effective_end = min(end, float(Fraction(str(start))+frames/fps*speed))
            clock = (runtime.windowed_mix_clock(clock_tools, str(path), media, end,
                        kind='audio', start=start, allow_no_audio=True, playback=True)
                     if has_audio else None)
            consumed = clock is not None and runtime.audio_intersection(
                clock, start, effective_end, playback=True)
            if digest(path) != ref['sha256'] or digest(Path(identity['path'])) != identity['sha256']:
                raise ValueError('selected retime observation identity changed')
            observations.append({'source': ref, 'clip_id': clip.get('id'),
                'effective_source_window': [start, effective_end],
                'selected_audio_clock': clock, 'audio_consumed': consumed,
                'scope': 'current bounded decoded frame-clock observation only; no DSP/render'})
            audible = audible or consumed
        if not audible:
            return {'status': 'NOT_REQUIRED', 'required': False,
                    'policy': ('selected retimed effective windows consume no audio' if any_audio_track
                               else 'retimed sources contain no audio'),
                    'observations': observations, 'selected_runtime_sources': runtime_sources}, None
        kind = spec.get('kind') if isinstance(spec, dict) else 'rubberband-r3-stream-v5'
        expected = runtime.RUBBERBAND_STREAM_SHA256 if kind == 'rubberband-r3-stream-v5' else runtime.RUBBERBAND_V4_SHA256 if kind == 'rubberband-r3-v4' else None
        if expected is None:
            raise ValueError('selected audio backend unsupported')
        ref = spec.get('helper') if isinstance(spec, dict) else {'path': str(Path(runtime.__file__).parent / 'rubberband-offline-f32-stream-v5'), 'sha256': expected}
        if not isinstance(ref, dict) or set(ref) != {'path', 'sha256'} or not Path(ref['path']).is_absolute():
            raise ValueError('selected retime helper identity required')
        helper = Path(ref['path'])
        status = 'MISSING' if not helper.is_file() else 'HASH_MISMATCH' if ref['sha256'] != expected or digest(helper) != expected else 'PRESENT_NOT_INVOKED' if os.access(helper, os.X_OK) else 'UNRESOLVED'
        return {'status': status, 'required': True, 'kind': kind, 'helper': ref, 'observations': observations,
                'selected_runtime_source': {'path': runtime.__file__, 'sha256': digest(Path(runtime.__file__))},
                'selected_runtime_sources': runtime_sources,
                'recovery': None if status == 'PRESENT_NOT_INVOKED' else 'Provide the pinned helper for this actual audio retime request.',
                'limit': 'Identity and bounded decoded-window diagnosis only; DSP, listening and strict sample preservation unverified'}, None
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError, OverflowError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return {'status': 'NEEDS_BINDING', 'required': False, 'observations': observations, 'selected_runtime_sources': runtime_sources}, str(exc)


def inspect(root, *, ffmpeg=None, ffprobe=None, bindings=None, env=None, request=None):
    root = Path(root).resolve()
    env = dict(os.environ if env is None else env)
    registry = root / 'registry' / 'skills.json'
    if not registry.is_file():
        raise ValueError('REGISTRY_MISSING: ' + str(registry))
    data = json.loads(registry.read_text())
    if data.get('schema') != 'skill-registry/1' or not isinstance(data.get('entries'), list):
        raise ValueError('REGISTRY_SCHEMA_INVALID')
    bindings = {} if bindings is None else bindings
    if request is not None and (not isinstance(request, dict) or not isinstance(request.get('operation'), str)):
        raise ValueError('REQUEST_OPERATION_REQUIRED')
    if not isinstance(bindings, dict) or set(bindings) - {'font', 'asr_model_lock', 'asr_environment_lock'}:
        raise ValueError('BINDINGS_SCHEMA_INVALID')
    bundle_identity = _bundle_core_binding(root)
    if bundle_identity['status'] == 'BUNDLE_DIAGNOSTIC_IDENTITY_FAILED':
        return {'schema': SCHEMA, 'status': 'BUNDLE_DIAGNOSTIC_IDENTITY_FAILED',
                'root': str(root), 'bundle_identity': bundle_identity, 'components': {},
                'limit': 'Manifest-bound diagnostic core rejected before target dependency probes.'}
    identity, identity_source = _load_tool_identity(root)
    packages = {name: _package_probe(name) for name in dict.fromkeys(PACKAGE_NAMES)}
    components = {'python': _python_probe(), 'sqlite': {'status': 'PRESENT', 'version': sqlite3.sqlite_version},
                  'ffmpeg': _inspect_media_tool('ffmpeg', ffmpeg, env, identity),
                  'ffprobe': _inspect_media_tool('ffprobe', ffprobe, env, identity),
                  'say': _say_probe(env), 'Pillow': packages['Pillow'], 'numpy': packages['numpy']}
    components['style-resources'] = (_style_resources_probe(request)
        if request is not None and request.get('operation')=='work-version' and request.get('action')=='relink-style-resources'
        else {'status':'NEEDS_BINDING','recovery':'Select a concrete relink-style-resources request.'})
    components['fcntl'] = ({'status': 'PRESENT', 'recovery': None}
                           if components['python']['posix_fcntl'] else
                           {'status': 'MISSING', 'recovery': 'Use a Python environment with fcntl for local batch locking.'})
    components['font'] = (_bound_file(bindings['font'], 'font', {'.ttf', '.otf', '.ttc'})
                          if 'font' in bindings else {'status': 'NEEDS_BINDING',
                          'recovery': 'Pass --bindings with font.path and font.sha256 for caption-burn.'})
    if request is not None and request['operation'] == 'caption-burn':
        components['font'] = _bound_file(request.get('font'), 'request font', {'.ttf', '.otf', '.ttc'})
    components['asr-model'] = (_asr_lock(root, bindings['asr_model_lock'], 'model')
                               if 'asr_model_lock' in bindings else {'status': 'NEEDS_BINDING',
                               'recovery': 'Bind a current local ASR model lock with path and SHA-256.'})
    components['asr-environment'] = (_asr_lock(root, bindings['asr_environment_lock'], 'environment')
                                     if 'asr_environment_lock' in bindings else {'status': 'NEEDS_BINDING',
                                     'recovery': 'Bind a current ASR environment lock with path and SHA-256.'})
    if request is not None and request['operation'] == 'speech-transcribe-local':
        components['asr-model'] = _asr_lock(root, request.get('model_lock'), 'model')
        components['asr-environment'] = _asr_lock(root, request.get('environment_lock'), 'environment')
    selected_document, work_content_reason = (None, None)
    base_document = None
    if request is not None and request['operation'] == 'work-render':
        base_document, work_content_reason = _stored_work_document(request)
        selected_document = base_document
        if selected_document is not None and 'preview_candidate' in request:
            selected_document, work_content_reason = _preview_work_document(request, selected_document)
            # revision_diff validates the stored base as well as the candidate.
            if base_document.get('caption_style') is not None:
                style = base_document['caption_style']
                components['base-font'] = _bound_file(style.get('font') if isinstance(style, dict) else None,
                                                       'stored base work font', {'.ttf', '.otf', '.ttc'})
        if selected_document is not None and selected_document.get('caption_style') is not None:
            style = selected_document.get('caption_style')
            components['font'] = _bound_file(style.get('font') if isinstance(style, dict) else None,
                                             'selected work font', {'.ttf', '.otf', '.ttc'})
    stretch, stretch_unknown = _stretch_probe(request, selected_document, components['ffprobe'], root=root)
    components['audio-time-stretch'] = stretch
    entries = data['entries']
    atomics = {e['id']: e for e in entries if e.get('layer') == 'atomic'}
    if request is not None and request['operation'] not in atomics:
        raise ValueError('REQUEST_LOCAL_ATOMIC_OPERATION_UNKNOWN')
    missing_declarations = sorted(set(atomics) - set(ATOMIC_REQUIREMENTS))
    obsolete_declarations = sorted(set(ATOMIC_REQUIREMENTS) - set(atomics))
    atomic_rows = {}
    for identifier in sorted(atomics):
        selected = request if request is not None and request['operation'] == identifier else None
        profile, unknown, branch = _selected_requirements(identifier, selected) if identifier in ATOMIC_REQUIREMENTS else ((), [], None)
        if identifier == 'work-render' and selected is not None:
            if work_content_reason:
                unknown.append('selected WorkDocument: ' + work_content_reason)
            elif 'preview_candidate' in selected and base_document.get('caption_style') is not None:
                profile += ('base-font',)
            elif selected_document.get('caption_style') is not None:
                profile += ('font',)
            if not work_content_reason and selected_document.get('caption_style') is not None and 'font' not in profile:
                profile += ('font',)
        if identifier in ('timeline-render', 'work-render') and selected is not None:
            if stretch.get('required'):
                profile += ('audio-time-stretch',)
            if stretch_unknown:
                unknown.append(stretch_unknown)
        requirements = ('python',) + profile
        if identifier not in ATOMIC_REQUIREMENTS:
            atomic_rows[identifier] = {'status': 'UNDECLARED_DEPENDENCIES', 'requirements': [],
                                       'recovery': 'Add an explicit dependency profile before declaring this atomic capability.'}
            continue
        status, observations = _capability_status(requirements, components)
        if unknown and status == 'DECLARED_DEPENDENCIES_PRESENT_NOT_EXECUTED':
            status = 'CONDITIONAL_DEPENDENCIES_UNKNOWN'
        if identifier == 'speech-transcribe-local' and any(packages[n]['status'] == 'MISSING' for n in ASR_PACKAGES):
            status = 'DEPENDENCY_BLOCKED'
        atomic_rows[identifier] = {'status': status, 'requirements': list(requirements),
                                   'branch': branch, 'conditional_unknown': unknown,
                                   'observations': observations,
                                   'recovery': [components[k]['recovery'] for k in requirements if components[k].get('recovery')]}
        if identifier == 'speech-transcribe-local':
            atomic_rows[identifier]['asr_package_metadata'] = {n: packages[n] for n in ASR_PACKAGES}
    complex_rows = {}
    for entry in entries:
        if entry.get('layer') != 'complex':
            continue
        dependencies = entry.get('atomic_dependencies')
        if not isinstance(dependencies, list):
            complex_rows[entry['id']] = {'status': 'UNDECLARED_DEPENDENCIES',
                                         'recovery': 'Declare atomic_dependencies in registry.'}
            continue
        unknown = sorted(set(dependencies) - set(atomic_rows))
        states = {name: atomic_rows[name]['status'] for name in dependencies if name in atomic_rows}
        # A complex Skill can choose among its atomic routes. An inventory of all
        # possible routes cannot establish that the selected route is blocked.
        status = ('UNDECLARED_DEPENDENCIES' if unknown or any(s == 'UNDECLARED_DEPENDENCIES' for s in states.values())
                  else 'CONDITIONAL_DEPENDENCIES_UNKNOWN')
        complex_rows[entry['id']] = {'status': status, 'atomic_dependencies': dependencies,
                                     'unknown_atomic_dependencies': unknown,
                                     'atomic_statuses': states,
                                     'limit': 'Local runtime dependencies only; no generic Agent tool readiness, route, style, host, media, human or production test.'}
    if obsolete_declarations:
        raise ValueError('OBSOLETE_ATOMIC_PROFILES: ' + ','.join(obsolete_declarations))
    overall = ('BUNDLE_DIAGNOSTIC_IDENTITY_FAILED' if bundle_identity['status'] == 'BUNDLE_DIAGNOSTIC_IDENTITY_FAILED'
               else 'DIAGNOSTIC_ONLY_NOT_INSTALLATION_ACCEPTANCE')
    return {'schema': SCHEMA, 'status': overall, 'bundle_identity': bundle_identity,
            'scope': 'OPTIONAL_LOCAL_RUNTIME_ONLY_NOT_GENERIC_SKILL_READINESS',
            'root': str(root), 'registry': {'path': str(registry), 'sha256': digest(registry),
            'atomic_count': len(atomics), 'complex_count': len(complex_rows)},
            'tool_identity_module': identity_source, 'selected_request': {'operation': request['operation'],
                'action': request.get('action'), 'method': request.get('method'),
                'work_content': ({'captions': len(selected_document.get('captions', {})),
                                  'audio_tracks': len(selected_document.get('audio_tracks', {})),
                                  'visual_layers': len(selected_document.get('visual_layers', []))}
                                 if selected_document is not None else None),
                'work_content_unknown': work_content_reason} if request else None,
            'components': components,
            'optional_package_metadata': packages, 'atomic': atomic_rows, 'complex': complex_rows,
            'missing_atomic_declarations': missing_declarations,
            'unverified': ['FFmpeg codec/filter availability', 'Pillow/NumPy import and execution',
                           'model inference', 'font rendering and license', 'remote providers',
                           'native host discovery', 'media output and creative quality'],
            'next_action': 'Resolve only the dependencies for selected local runtime operations; other editor tools require their own capability and result readback checks.'}
