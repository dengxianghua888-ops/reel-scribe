"""Public package regression tests. All media are synthetic; no network clients."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('packaging_test_common', ROOT / 'scripts/packaging_common.py')
common = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(common)
BUILDERS = ('build_portable_bundle.py', 'build_codex_plugin.py')
MANIFESTS = ('bundle-manifest.json', 'plugin-package-manifest.json')
DIRECTORIES = {'workflows', 'atomic', 'styles', 'contracts', 'runtime', 'registry'}


def run(*args, cwd, env=None, check=True):
    result = subprocess.run([str(arg) for arg in args], cwd=cwd, env=env,
                            text=True, capture_output=True, timeout=120)
    if check:
        assert result.returncode == 0, result.stdout + result.stderr
    return result


@pytest.fixture(scope='session')
def frozen_source(tmp_path_factory):
    """Freeze one candidate, avoiding test contamination and recursive disk dirt."""
    source = Path(os.environ.get('EDITING_PACKAGING_TEST_SOURCE', ROOT)).resolve()
    target = tmp_path_factory.mktemp('package-source')
    for path in common.source_members(source):
        output = target / path.relative_to(source)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, output)
        output.chmod(path.stat().st_mode & 0o777)
    return target


@pytest.fixture
def source(frozen_source, tmp_path):
    target = tmp_path / 'source'
    shutil.copytree(frozen_source, target)
    return target


def add_member(source, name, content):
    target = source / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding='utf-8')
    manifest = source / common.MEMBERS_FILE
    value = json.loads(manifest.read_text())
    value['files'] = sorted(set(value['files']) | {name})
    manifest.write_text(json.dumps(value, indent=2) + '\n')


@pytest.mark.parametrize('name', ['LICENSE', 'NOTICE', 'COPYING', 'pyproject.toml', 'README.md', '.env.example'])
def test_controlled_text_classification(tmp_path, name):
    file = tmp_path / name
    file.write_text('允许的 UTF-8 文本\n')
    assert common.is_text(file)
    file.write_bytes(b'bad\x00bytes')
    with pytest.raises(ValueError, match='CONTENT_INVALID'):
        common.is_text(file)


def test_unknown_binary_is_not_text_even_if_decodable(tmp_path):
    file = tmp_path / 'unknown.blob'
    file.write_text('decodable is not a distribution decision')
    assert not common.is_text(file)


def test_interrupted_manifest_publication_is_not_complete(tmp_path):
    (tmp_path / 'build-incomplete.json').write_text('{"status":"BUILD_INCOMPLETE"}')
    (tmp_path / 'bundle-manifest.json').write_text('{"status":"BUILT_NOT_HOST_INSTALLED"')
    with pytest.raises(ValueError, match='PACKAGE_BUILD_NOT_COMPLETE'):
        common.package_files(tmp_path)


@pytest.mark.parametrize('builder', BUILDERS)
def test_default_build_navigation_and_reproducibility(source, tmp_path, builder):
    # Disk pollution is outside the explicit source member set.
    for name in ('runtime/.pytest_cache/README.md', 'runtime/__pycache__/hidden.pyc',
                 'runtime/.env', 'docs/undeclared.md', 'scripts/backup.py.bak'):
        p = source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('must not be copied')
    outputs = [tmp_path / 'first', tmp_path / 'second']
    for output in outputs:
        result = run(sys.executable, source / 'scripts' / builder, '--out', output, cwd=tmp_path)
        assert json.loads(result.stdout)['status'] in ('BUILT_NOT_INSTALLED', 'BUILT_NOT_HOST_INSTALLED')
        assert not (output / 'build-incomplete.json').exists()
        for name in ('runtime/.env', 'docs/undeclared.md', 'runtime/.pytest_cache/README.md'):
            assert not (output / name).exists()
        structure = json.loads(run(sys.executable, output / 'scripts/verify_library.py', 'structure', cwd=tmp_path).stdout)
        assert structure['status'] == 'PASSED'
        assert structure['skills'] == 52
    name = MANIFESTS[BUILDERS.index(builder)]
    first, second = [json.loads((out / name).read_text()) for out in outputs]
    assert first['files'] == second['files']
    film = 'workflows/raven-film-recap/douyin-film-recap/'
    for relative in ('docs/alignment-import.md', 'schemas/AlignmentResult.schema.json',
                     'src/douyin_film_recap/alignment.py', 'tests/test_alignment_import.py',
                     'src/douyin_film_recap/local_alignment.py', 'tests/test_local_alignment.py',
                     'docs/local-alignment.md'):
        for output in outputs:
            assert (output / film / relative).read_bytes() == (source / film / relative).read_bytes()
    cli = (outputs[0] / film / 'src/douyin_film_recap/cli.py').read_text()
    assert '@app.command("validate-alignment")' in cli
    assert '@app.command("convert-whisperx-alignment")' in cli
    assert '@app.command("run-local-alignment")' in cli
    directories = {row['target'] for row in first['directory_navigation'] if row['from'] == 'README.md'}
    assert directories == DIRECTORIES
    members = {row['path'] for row in first['files']}
    assert {'README.md', 'AGENTS.md', 'LICENSES.md', 'docs/local-setup.md',
            'workflows/raven-film-recap/douyin-film-recap/LICENSE',
            'workflows/raven-film-recap/douyin-film-recap/pyproject.toml'} <= members


@pytest.mark.parametrize('builder', BUILDERS)
@pytest.mark.parametrize('origin', ['README.md', 'docs/local-setup.md', 'skills/editing-skill-library/SKILL.md', 'manifest'])
def test_final_member_reference_scope(source, tmp_path, builder, origin):
    if origin == 'manifest':
        file = source / '.codex-plugin/plugin.json'
        value = json.loads(file.read_text())
        value['mcpServers'] = './missing.json'
        file.write_text(json.dumps(value))
    else:
        with (source / origin).open('a') as stream:
            stream.write('\n[missing](missing.md)\n')
    output = tmp_path / 'broken'
    result = run(sys.executable, source / 'scripts' / builder, '--out', output, cwd=tmp_path, check=False)
    assert result.returncode != 0
    assert not any((output / name).exists() for name in MANIFESTS)


@pytest.mark.parametrize('builder', BUILDERS)
@pytest.mark.parametrize('bad', ['missing', 'escape', 'symlink', 'empty'])
def test_directory_negative_cases(source, tmp_path, builder, bad):
    if bad == 'missing':
        target = 'missing/'
    elif bad == 'escape':
        (tmp_path / 'outside').mkdir()
        target = '../outside/'
    elif bad == 'empty':
        (source / 'empty').mkdir()
        target = 'empty/'
    else:
        (source / 'linked').symlink_to(source / 'runtime', target_is_directory=True)
        target = 'linked/'
    with (source / 'README.md').open('a') as stream:
        stream.write('\n[bad directory](' + target + ')\n')
    output = tmp_path / 'broken'
    result = run(sys.executable, source / 'scripts' / builder, '--out', output, cwd=tmp_path, check=False)
    assert result.returncode != 0
    assert not any((output / name).exists() for name in MANIFESTS)


@pytest.mark.parametrize('builder', BUILDERS)
def test_new_text_dependency_requires_explicit_member(source, tmp_path, builder):
    (source / 'docs/unlisted.md').write_text('new documentation')
    with (source / 'README.md').open('a') as stream:
        stream.write('\n[new](docs/unlisted.md)\n')
    output = tmp_path / 'broken'
    assert run(sys.executable, source / 'scripts' / builder, '--out', output, cwd=tmp_path, check=False).returncode != 0
    add_member(source, 'docs/unlisted.md', 'new documentation')
    run(sys.executable, source / 'scripts' / builder, '--out', tmp_path / 'fixed', cwd=tmp_path)


def test_restricted_markdown_rejects_unsupported_reference_forms():
    assert common.markdown_targets('`[example](absent.md)`\n```md\n[x](x.md)\n```') == []
    for value in ('[ref][target]\n[target]: missing.md', '<img src="missing.png">'):
        with pytest.raises(ValueError, match='UNSUPPORTED_MARKDOWN'):
            common.markdown_targets(value)


def test_historical_resource_declaration_is_not_rebound(source, tmp_path):
    historical = source / 'contracts/portable-resource-edges.current.json'
    original = historical.read_bytes()
    result = run(sys.executable, source / 'scripts/build_portable_bundle.py', '--resources', historical,
                 '--out', tmp_path / 'historical', cwd=tmp_path, check=False)
    assert result.returncode != 0
    assert 'PACKAGE_TARGET_MISSING' in result.stderr or 'RESOURCE_TARGET_MISSING_OR_UNSAFE' in result.stderr
    assert historical.read_bytes() == original
    assert not (tmp_path / 'historical/bundle-manifest.json').exists()


@pytest.mark.parametrize('builder', BUILDERS)
def test_unknown_core_binary_rejected(source, tmp_path, builder):
    add_member(source, 'docs/unknown.bin', 'UTF-8 alone is not a text classification')
    output = tmp_path / 'unknown'
    result = run(sys.executable, source / 'scripts' / builder, '--out', output, cwd=tmp_path, check=False)
    assert result.returncode != 0
    assert 'CORE_BINARY_REQUIRES_RESOURCE_DECLARATION' in result.stderr
    assert not any((output / name).exists() for name in MANIFESTS)


def test_portable_resource_is_explicit_and_plugin_fails_closed(source, tmp_path):
    add_member(source, 'docs/view.html', '<html><img src="picture.bin"></html>')
    picture = source / 'docs/picture.bin'
    picture.write_bytes(b'\x00explicit synthetic resource\xff')
    with (source / 'README.md').open('a') as stream:
        stream.write('\n[view](docs/view.html)\n')
    for builder in BUILDERS:
        result = run(sys.executable, source / 'scripts' / builder, '--out', tmp_path / builder,
                     cwd=tmp_path, check=False)
        assert result.returncode != 0
        assert 'RESOURCE_DECLARATION_REQUIRED' in result.stderr
    declaration = {'schema': 'portable-resource-edges/1', 'sources': [{
        'path': 'docs/view.html', 'sha256': common.digest(source / 'docs/view.html'),
        'edges': [{'reference': 'picture.bin', 'decision': 'bundle',
                   'target': {'path': 'docs/picture.bin', 'sha256': common.digest(picture)}}]}]}
    resource_file = tmp_path / 'resources.json'
    resource_file.write_text(json.dumps(declaration))
    output = tmp_path / 'declared'
    run(sys.executable, source / 'scripts/build_portable_bundle.py', '--out', output,
        '--resources', resource_file, cwd=tmp_path)
    assert (output / 'docs/picture.bin').read_bytes() == picture.read_bytes()
    assert json.loads(run(sys.executable, output / 'scripts/verify_library.py', 'structure',
                          cwd=tmp_path).stdout)['status'] == 'PASSED'


def test_text_license_cannot_be_externalized(source, tmp_path):
    origin = source / 'workflows/raven-film-recap/douyin-film-recap/README.md'
    target = source / 'workflows/raven-film-recap/douyin-film-recap/LICENSE'
    policy = {'schema': 'portable-distribution-policy/1', 'external_links': [{
        'from': {'path': str(origin.relative_to(source)), 'sha256': common.digest(origin)},
        'target': {'path': str(target.relative_to(source)), 'sha256': common.digest(target)},
        'reason': 'test illegal text externalization'}]}
    policy_file = tmp_path / 'policy.json'
    policy_file.write_text(json.dumps(policy))
    result = run(sys.executable, source / 'scripts/build_portable_bundle.py', '--out', tmp_path / 'bad',
                 '--policy', policy_file, cwd=tmp_path, check=False)
    assert result.returncode != 0
    assert 'TEXT_LINK_CANNOT_BE_EXTERNALIZED' in result.stderr


def test_explicit_external_binary_stays_outside_package(source, tmp_path):
    origin, target = source / 'README.md', source / 'docs/external.bin'
    target.write_bytes(b'\x00external synthetic bytes')
    with origin.open('a') as stream:
        stream.write('\n[external](docs/external.bin)\n')
    policy = {'schema': 'portable-distribution-policy/1', 'external_links': [{
        'from': {'path': 'README.md', 'sha256': common.digest(origin)},
        'target': {'path': 'docs/external.bin', 'sha256': common.digest(target)},
        'reason': 'synthetic explicitly external fixture'}]}
    policy_file = tmp_path / 'external-policy.json'
    policy_file.write_text(json.dumps(policy))
    output = tmp_path / 'external'
    run(sys.executable, source / 'scripts/build_portable_bundle.py', '--out', output,
        '--policy', policy_file, cwd=tmp_path)
    assert not (output / 'docs/external.bin').exists()
    assert json.loads(run(sys.executable, output / 'scripts/verify_library.py', 'structure',
                          cwd=tmp_path).stdout)['status'] == 'PASSED'


@pytest.mark.parametrize('builder', BUILDERS)
def test_output_structure_failure_prevents_success(source, tmp_path, builder):
    # All files/links still exist. The copied structure checker must detect this.
    entry = source / 'atomic/media-inspect/SKILL.md'
    entry.write_text(entry.read_text().replace('name: media-inspect', 'name: wrong-name'))
    output = tmp_path / 'invalid-structure'
    result = run(sys.executable, source / 'scripts' / builder, '--out', output, cwd=tmp_path, check=False)
    assert result.returncode != 0
    assert 'PACKAGE_STRUCTURE_CHECK_FAILED' in result.stderr
    assert (output / 'build-incomplete.json').is_file()
    assert not any((output / name).exists() for name in MANIFESTS)


@pytest.mark.parametrize('builder', BUILDERS)
def test_copy_drift_has_no_success_manifest(source, tmp_path, monkeypatch, builder):
    spec = importlib.util.spec_from_file_location('builder_under_test', source / 'scripts' / builder)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    original_copy = module._common.copy_members

    def drifting_copy(root, destination, rows):
        original_copy(root, destination, rows)
        (root / 'README.md').write_text('changed after copying')

    monkeypatch.setattr(module._common, 'copy_members', drifting_copy)
    output = tmp_path / 'drifted'
    with pytest.raises(ValueError, match='DRIFT'):
        module.build(output)
    assert (output / 'build-incomplete.json').is_file()
    assert not any((output / name).exists() for name in MANIFESTS)


@pytest.mark.parametrize('builder', BUILDERS)
def test_relocated_output_doctor_stdio_and_real_render(source, tmp_path, builder):
    ffmpeg = os.environ.get('EDITING_FFMPEG') or shutil.which('ffmpeg')
    ffprobe = os.environ.get('EDITING_FFPROBE') or shutil.which('ffprobe')
    assert ffmpeg and ffprobe, 'Packaging media acceptance requires real FFmpeg/ffprobe'
    output = tmp_path / 'package'
    run(sys.executable, source / 'scripts' / builder, '--out', output, cwd=tmp_path)
    relocated = tmp_path / '中文 空格' / 'relocated package'
    relocated.parent.mkdir()
    output.rename(relocated)
    # Remove the source fixture entirely. Any implicit fallback must now fail.
    shutil.rmtree(source)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('PYTHON', 'EDITING_')) and k not in {'DEEPSEEK_API_KEY'}}
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    work_root = tmp_path / 'new work'
    work_root.mkdir()
    env['EDITING_SKILL_WORK_ROOT'] = str(work_root)
    doctor = json.loads(run(sys.executable, '-I', relocated / 'scripts/install_doctor.py',
                            '--root', relocated, '--ffmpeg', ffmpeg, '--ffprobe', ffprobe,
                            cwd=tmp_path, env=env).stdout)
    assert doctor['status'] != 'BUNDLE_DIAGNOSTIC_IDENTITY_FAILED'
    assert Path(doctor['diagnostic_source']['path']).is_relative_to(relocated)
    media = tmp_path / 'red.mp4'
    run(ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi', '-i', 'color=red:s=64x64:r=25:d=0.4',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', media, cwd=tmp_path)
    identity = hashlib.sha256(media.read_bytes()).hexdigest()
    request = {'operation': 'timeline-render', 'plan': {'schema': 'execution-plan/1',
               'fps': '25', 'width': 64, 'height': 64, 'fit': 'contain',
               'sources': {'red': {'path': str(media), 'sha256': identity}},
               'clips': [{'id': 'clip-1', 'source_id': 'red', 'start': 0, 'end': 0.4, 'gain_db': 0}]}}
    messages = [
        {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {'protocolVersion': '2025-03-26'}},
        {'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'},
        {'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {'name': 'list_skills', 'arguments': {}}},
        {'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {'name': 'run_operation',
         'arguments': {'request': request, 'work_dir': str(work_root / 'render'),
                       'ffmpeg': ffmpeg, 'ffprobe': ffprobe}}},
    ]
    result = subprocess.run([sys.executable, '-I', str(relocated / 'scripts/mcp_server.py')],
                            cwd=tmp_path, env=env, text=True,
                            input=''.join(json.dumps(row) + '\n' for row in messages),
                            capture_output=True, timeout=120)
    assert result.returncode == 0, result.stderr
    responses = [json.loads(line) for line in result.stdout.splitlines()]
    assert responses[0]['result']['protocolVersion'] == '2025-03-26'
    assert len(responses[1]['result']['tools']) == 3
    assert len(json.loads(responses[2]['result']['content'][0]['text'])['entries']) == 52
    assert not responses[3]['result'].get('isError'), responses[3]
    result = json.loads(responses[3]['result']['content'][0]['text'])
    assert result['status'] == 'SUCCEEDED', result
    assert hashlib.sha256(media.read_bytes()).hexdigest() == identity
    receipt = json.loads((work_root / 'render/receipt.json').read_text())
    assert receipt['status'] == 'SUCCEEDED'
    assert receipt['runtime_sha256'] == common.digest(relocated / 'runtime/editing_runtime.py')
    for name, digest in receipt['runtime_files'].items():
        assert common.digest(relocated / 'runtime' / name) == digest
    frame = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-i',
                            str(work_root / 'render/preview.mp4'), '-frames:v', '1',
                            '-f', 'rawvideo', '-pix_fmt', 'rgb24', 'pipe:1'],
                           capture_output=True, check=True, timeout=30).stdout
    assert len(frame) == 64 * 64 * 3
    assert frame[0] > 200 and frame[1] < 30 and frame[2] < 30
    # Tampering with the migrated package is caught by its own structure command.
    (relocated / 'docs/local-setup.md').unlink()
    assert run(sys.executable, '-I', relocated / 'scripts/verify_library.py', 'structure',
               cwd=tmp_path, env=env, check=False).returncode != 0
