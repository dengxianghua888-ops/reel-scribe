"""Versioned, task-local source observations and optional copied execution bytes.

Copies protect against changes to the originals, not a malicious process running
as the same user. Boundary checks cannot observe a completed A -> B -> A change.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import copy
import hashlib
import os
from pathlib import Path
import re
import shutil
import time


ACTIVE_BINDING = ContextVar('source_consumption_binding', default=None)
CHUNK_BYTES = 1024 * 1024


def selection(spec=None):
    from editing_runtime import exact_keys, require
    if spec is None:
        spec = {'schema': 'source-consumption/1', 'mode': 'boundary'}
    exact_keys(spec, ['schema', 'mode', 'prepare_timeout_seconds', 'reserve_bytes'], ['schema', 'mode'])
    require(spec['schema'] == 'source-consumption/1', 'SOURCE_CONSUMPTION_SCHEMA_UNSUPPORTED')
    require(spec['mode'] in ('boundary', 'snapshot'), 'SOURCE_CONSUMPTION_MODE_UNSUPPORTED')
    timeout = spec.get('prepare_timeout_seconds', 300)
    reserve = spec.get('reserve_bytes', 64 * 1024 * 1024)
    require(type(timeout) is int and 1 <= timeout <= 7200, 'SOURCE_PREPARATION_TIMEOUT_INVALID')
    require(type(reserve) is int and reserve >= CHUNK_BYTES, 'SOURCE_RESERVE_BYTES_INVALID')
    return {**spec, 'prepare_timeout_seconds': timeout, 'reserve_bytes': reserve}


def document_references(document):
    """Only declared render resources; do not traverse arbitrary user notes."""
    from editing_runtime import require
    require(isinstance(document, dict) and isinstance(document.get('plan'), dict) and
            isinstance(document['plan'].get('sources'), dict), 'SOURCES_REQUIRED')
    for field in ('audio_tracks', 'visual_layers'):
        require(isinstance(document.get(field, {}), dict), 'ID_MAP_REQUIRED: ' + field)
    refs = list(document['plan']['sources'].values())
    refs.extend(track['source'] for track in document.get('audio_tracks', {}).values())
    refs.extend(layer['source'] for layer in document.get('visual_layers', {}).values())
    if document.get('caption_style'):
        refs.append(document['caption_style']['font'])
    from work_color import lut_references
    refs.extend(lut_references(document))
    return refs


def execution_path(path):
    binding = ACTIVE_BINDING.get()
    return binding.execution_path(path) if binding else str(path)


def _stat_identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _deadline_check(deadline):
    from editing_runtime import require
    require(time.monotonic() <= deadline, 'SOURCE_PREPARATION_TIMEOUT')


def stable_digest(path, deadline):
    """Bounded memory; metadata observes ordinary concurrent replacement/writes."""
    from editing_runtime import require
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        before = os.fstat(stream.fileno())
        while True:
            _deadline_check(deadline)
            chunk = stream.read(CHUNK_BYTES)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    require(_stat_identity(before) == _stat_identity(after) == _stat_identity(Path(path).stat()),
            'SOURCE_CHANGED_DURING_READ: ' + str(path))
    return digest.hexdigest(), after.st_size


class SourceBinding:
    def __init__(self, refs, spec, directory):
        self.spec = selection(spec)
        self.directory = Path(directory)
        self.root = self.directory.resolve()
        self.sources = []
        self.paths = {}
        self.observations = []
        self.refs = copy.deepcopy(refs)
        self.preparation = {}

    def deadline(self):
        return time.monotonic() + self.spec['prepare_timeout_seconds']

    def prepare(self):
        from editing_runtime import exact_keys, require
        deadline = self.deadline()
        by_path = {}
        for ref in self.refs:
            exact_keys(ref, ['path', 'sha256'], ['path', 'sha256'])
            require(isinstance(ref['path'], str) and Path(ref['path']).expanduser().is_absolute(),
                    'ABSOLUTE_SOURCE_PATH_REQUIRED')
            require(isinstance(ref['sha256'], str) and re.fullmatch('[0-9a-f]{64}', ref['sha256']), 'SHA256_REQUIRED')
            logical = str(Path(ref['path']).expanduser())
            resolved = str(Path(logical).resolve(strict=True))
            require(Path(resolved).is_file(), 'SOURCE_NOT_FOUND: ' + logical)
            if resolved in by_path:
                item = by_path[resolved]
                require(item['sha256'] == ref['sha256'], 'SOURCE_BINDING_CONFLICT')
                if logical not in item['logical_paths']:
                    item['logical_paths'].append(logical)
                self.paths[logical] = item
                continue
            digest, size = stable_digest(resolved, deadline)
            require(digest == ref['sha256'], 'SOURCE_HASH_MISMATCH: ' + logical)
            item = {'logical_paths': [logical], 'path': resolved, 'sha256': digest, 'bytes': size,
                    'execution_path': resolved}
            by_path[resolved] = item
            self.sources.append(item)
            self.paths[logical] = self.paths[resolved] = item
        if self.spec['mode'] == 'snapshot':
            required = sum(s['bytes'] for s in self.sources) + self.spec['reserve_bytes']
            free = shutil.disk_usage(self.directory).free
            self.preparation.update(snapshot_bytes=sum(s['bytes'] for s in self.sources),
                                    required_free_bytes=required, observed_free_bytes=free)
            require(free >= required, 'SOURCE_SNAPSHOT_DISK_INSUFFICIENT')
            target = self.directory / 'source-snapshots'
            target.mkdir(mode=0o700, exist_ok=False)
            for index, item in enumerate(self.sources):
                suffix = Path(item['path']).suffix
                if not re.fullmatch(r'\.[A-Za-z0-9]{1,10}', suffix):
                    suffix = '.bin'
                final = target / ('source-%04d' % index + suffix)
                partial = final.with_name(final.name + '.partial')
                digest = hashlib.sha256()
                try:
                    with Path(item['path']).open('rb') as src, partial.open('xb') as dst:
                        before = os.fstat(src.fileno())
                        while True:
                            _deadline_check(deadline)
                            chunk = src.read(CHUNK_BYTES)
                            if not chunk:
                                break
                            dst.write(chunk)
                            digest.update(chunk)
                        dst.flush()
                        os.fsync(dst.fileno())
                        require(_stat_identity(before) == _stat_identity(os.fstat(src.fileno())) ==
                                _stat_identity(Path(item['path']).stat()), 'SOURCE_CHANGED_DURING_COPY')
                    require(digest.hexdigest() == item['sha256'], 'SOURCE_CHANGED_DURING_COPY')
                    actual, size = stable_digest(partial, deadline)
                    require(actual == item['sha256'] and size == item['bytes'], 'SOURCE_SNAPSHOT_COPY_MISMATCH')
                    partial.chmod(0o400)
                    partial.rename(final)
                except BaseException:
                    partial.unlink(missing_ok=True)
                    raise
                item['execution_path'] = str(final)
                snapshot_stat = final.stat()
                item['snapshot_file_identity'] = {'device': snapshot_stat.st_dev, 'inode': snapshot_stat.st_ino}
                self.paths[str(final)] = item
            target.chmod(0o500)
        self.observe('prepared', deadline=deadline)

    def covers(self, refs):
        return all(isinstance(ref, dict) and isinstance(ref.get('path'), str) and
                   str(Path(ref['path']).expanduser()) in self.paths and
                   self.paths[str(Path(ref['path']).expanduser())]['sha256'] == ref.get('sha256') for ref in refs)

    def execution_path(self, path):
        item = self.paths.get(str(path))
        return item['execution_path'] if item else str(path)

    def command(self, command):
        touched = []
        mapped = []
        for argument in command:
            item = self.paths.get(str(argument))
            if item is not None and item not in touched:
                touched.append(item)
            mapped.append(item['execution_path'] if item else argument)
        return mapped, touched

    def observe(self, phase, items=None, deadline=None):
        from editing_runtime import require
        deadline = self.deadline() if deadline is None else deadline
        for item in self.sources if items is None else items:
            observation = {'phase': phase, 'path': item['path'], 'expected_sha256': item['sha256']}
            self.observations.append(observation)
            try:
                for logical in item['logical_paths']:
                    require(str(Path(logical).resolve(strict=True)) == item['path'], 'SOURCE_PATH_CHANGED: ' + logical)
                digest, size = stable_digest(item['path'], deadline)
                observation.update(sha256=digest, bytes=size)
                require(digest == item['sha256'] and size == item['bytes'], 'SOURCE_IDENTITY_CHANGED: ' + item['path'])
                if self.spec['mode'] == 'snapshot':
                    snapshot = Path(item['execution_path'])
                    require(self.directory.resolve() == self.root and not snapshot.is_symlink() and
                            not snapshot.parent.is_symlink() and snapshot.resolve().is_relative_to(self.root),
                            'SOURCE_SNAPSHOT_PATH_CHANGED')
                    identity = snapshot.stat()
                    require(identity.st_nlink == 1 and {'device': identity.st_dev, 'inode': identity.st_ino} ==
                            item['snapshot_file_identity'], 'SOURCE_SNAPSHOT_FILE_CHANGED')
                    digest, size = stable_digest(snapshot, deadline)
                    observation['snapshot_sha256'] = digest
                    require(digest == item['sha256'] and size == item['bytes'], 'SOURCE_SNAPSHOT_IDENTITY_CHANGED')
                observation['status'] = 'MATCHED'
            except BaseException as exc:
                observation.update(status='FAILED', error=str(exc) or type(exc).__name__)
                raise

    def evidence(self, status, error=None):
        return {'schema': 'source-consumption-receipt/1', 'selection': self.spec,
                'status': status, 'adoptable': status == 'VERIFIED',
                'preparation': copy.deepcopy(self.preparation),
                'sources': copy.deepcopy(self.sources), 'observations': copy.deepcopy(self.observations),
                'protection': 'task-owned independent copies; no isolation from malicious same-user processes'
                              if self.spec['mode'] == 'snapshot' else 'pre/post full hashes; A-to-B-to-A can be unobserved',
                'creative_or_sample_precision_evidence': 'NOT_GRANTED',
                **({'error': error} if error else {})}


class BoundTools:
    """Map Python clock readers too; subprocess mapping is also enforced below."""
    def __init__(self, tools, binding):
        self.tools = tools
        self.binding = binding

    def __getattr__(self, name):
        target = getattr(self.tools, name)
        if name in ('probe', 'selected_video_clock', 'selected_audio_clock'):
            def consume(path, *args, **kwargs):
                return target(self.binding.execution_path(path), *args, **kwargs)
            return consume
        return target


@contextmanager
def consumption_session(refs, spec, directory, tools):
    from editing_runtime import require, write_json
    selected = selection(spec)
    inherited = ACTIVE_BINDING.get()
    binding = inherited or SourceBinding(refs, selected, directory)
    token = None
    status, error = 'FAILED', None
    try:
        if inherited is not None:
            require(inherited.spec == selected and inherited.covers(refs), 'SOURCE_CONSUMPTION_NESTING_MISMATCH')
        else:
            started = time.monotonic()
            try:
                binding.prepare()
            finally:
                binding.preparation['elapsed_seconds'] = time.monotonic() - started
            token = ACTIVE_BINDING.set(binding)
        binding.observe('before-consumption')
        yield binding, BoundTools(tools, binding)
        binding.observe('after-consumption')
        status = 'VERIFIED'
    except BaseException as exc:
        error = str(exc) or type(exc).__name__
        raise
    finally:
        if token is not None:
            ACTIVE_BINDING.reset(token)
        write_json(Path(directory) / 'source-binding.json', binding.evidence(status, error))
