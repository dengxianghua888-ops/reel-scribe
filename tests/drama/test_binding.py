"""Real SQLite and generated test-video integration; not artistic acceptance."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime'))
import drama_binding as binding
import editing_runtime as runtime
import work_ops

EXAMPLE = ROOT / 'workflows/raven-drama-production/examples/return-key'


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    return path


@pytest.fixture
def package(tmp_path):
    root = tmp_path / 'package'
    shutil.copytree(EXAMPLE, root)
    return root / 'PACKAGE-MANIFEST.json'


@pytest.fixture
def work(tmp_path):
    ffmpeg = os.environ.get('EDITING_FFMPEG') or shutil.which('ffmpeg')
    ffprobe = os.environ.get('EDITING_FFPROBE') or shutil.which('ffprobe')
    assert ffmpeg and ffprobe, 'Work integration needs media tools; no false skip/pass.'
    tools = runtime.Tools(ffmpeg, ffprobe)
    media = tmp_path / 'test-video.mp4'
    subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-n', '-f', 'lavfi',
                    '-i', 'color=c=red:s=64x64:r=25:d=0.4', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', str(media)], check=True)
    document = {'schema': 'work-document/1', 'plan': {
        'schema': 'execution-plan/1', 'fps': '25', 'width': 64, 'height': 64,
        'fit': 'contain', 'sources': {'source': {'path': str(media), 'sha256': runtime.sha256(media)}},
        'clips': [{'id': 'clip', 'source_id': 'source', 'start': 0, 'end': 0.4, 'gain_db': 0}]},
        'captions': {}, 'caption_style': None, 'audio_tracks': {}, 'style_bindings': {},
        'notes': {'manual_note': 'Must survive'}, 'visual_layers': {}}
    store = tmp_path / 'work.sqlite3'
    counter = 0

    def call(action, **kwargs):
        nonlocal counter
        counter += 1
        output = tmp_path / ('operation-' + str(counter))
        output.mkdir()
        return work_ops.work_version({'operation': 'work-version', 'action': action,
                                     'store': str(store), **kwargs}, output, tools)
    state = call('init', work_id='drama-fixture', document=document, author='agent', message='Test fixture')
    return {'store': store, 'document': document, 'call': call, 'state': state, 'tools': tools}


def scope():
    return {'clip_ids': [], 'source_ids': [], 'caption_ids': [], 'audio_ids': [],
            'style_keys': [], 'note_keys': ['drama_domain_ref'], 'output_fields': [],
            'caption_style': False, 'freeze_positions': ['clip'], 'freeze_duration': True}


def candidate(tmp_path, state, reference, name='candidate.json', doc=None, allowed=None):
    document = copy.deepcopy(doc or state['document'])
    document['notes']['drama_domain_ref'] = reference
    return write(tmp_path / name, {'schema': 'work-candidate/1', 'base_version': state['version'],
        'base_document_sha256': state['document_sha256'], 'document': document, 'scope': allowed or scope()})


def commit(work, path, state=None):
    return work['call']('commit', expected_version=(state or work['state'])['version'],
                        candidate={'path': str(path), 'sha256': runtime.sha256(path)},
                        author='agent', message='Attach domain fixture')


def prepared(work, package):
    return binding.prepare_attachment(package, work['store'], work['state']['version'])


def test_package_hashes_and_relocation(package, tmp_path):
    checked = binding.verify_package(package)
    assert checked['status'] == 'PASS' and checked['media_review'] == 'NOT_RUN'
    elsewhere = tmp_path / 'moved'
    shutil.copytree(package.parent, elsewhere)
    moved = binding.verify_package(elsewhere / package.name)
    assert moved['manifest']['sha256'] == checked['manifest']['sha256']
    assert moved['content'] == checked['content']


def test_prepare_commit_read_restore_preserves_media_and_authority(work, package, tmp_path):
    receipt = prepared(work, package)
    assert receipt['host_adoption'] == 'NOT_RUN'
    assert work['call']('read')['version'] == work['state']['version']
    path = candidate(tmp_path, work['state'], receipt['reference'])
    adopted = commit(work, path)
    assert adopted['document']['plan'] == work['document']['plan']
    assert adopted['document']['notes']['manual_note'] == 'Must survive'
    assert adopted['diff']['invalidated'] == ['content-review', 'drama-domain-review']
    read = work['call']('read')
    assert read['version'] == adopted['version']
    assert read['drama_attachment_validation']['status'] == 'PASS'
    assert read['drama_attachment_validation']['media_review'] == 'NOT_RUN'
    restored = work['call']('restore', expected_version=read['version'], target_sequence=1,
                           author='agent', message='Restore original fixture')
    assert restored['document'] == work['document']
    again = work['call']('restore', expected_version=restored['version'], target_sequence=2,
                        author='agent', message='Restore verified attachment')
    assert again['document'] == adopted['document']


def test_tamper_after_preparation_refuses_commit(work, package, tmp_path):
    receipt = prepared(work, package)
    path = candidate(tmp_path, work['state'], receipt['reference'])
    asset = Path(receipt['reference']['manifest']['path']).parent / 'drama-content.json'
    asset.write_bytes(asset.read_bytes() + b' ')
    with pytest.raises(runtime.ContractError, match='DRAMA_IDENTITY_CHANGED'):
        commit(work, path)
    assert work['call']('read')['version'] == work['state']['version']


def test_tamper_during_domain_check_caught_at_append_boundary(work, package, tmp_path, monkeypatch):
    receipt = prepared(work, package)
    path = candidate(tmp_path, work['state'], receipt['reference'])
    original = binding.validate_work_attachment

    def change_after_check(*args, **kwargs):
        report = original(*args, **kwargs)
        victim = Path(report['checked_files'][1]['path'])
        victim.write_bytes(victim.read_bytes() + b' ')
        return report
    monkeypatch.setattr(binding, 'validate_work_attachment', change_after_check)
    with pytest.raises(runtime.ContractError, match='DRAMA_IDENTITY_CHANGED'):
        commit(work, path)


def test_stale_candidate_and_refuse_relabeling_base(work, package, tmp_path):
    receipt = prepared(work, package)
    first = candidate(tmp_path, work['state'], receipt['reference'])
    adopted = commit(work, first)
    with pytest.raises(runtime.ContractError, match='WORK_VERSION_CONFLICT'):
        commit(work, first)
    ref = copy.deepcopy(receipt['reference'])
    different = tmp_path / 'same-bytes.json'
    different.write_bytes(Path(ref['manifest']['path']).read_bytes())
    ref['manifest']['path'] = str(different)
    next_candidate = candidate(tmp_path, adopted, ref, 'next.json')
    with pytest.raises(runtime.ContractError, match='DRAMA_BASE_WORK_VERSION_CONFLICT'):
        commit(work, next_candidate, adopted)


def test_unchanged_ref_does_not_require_old_base_to_equal_new_head(work, package, tmp_path):
    receipt = prepared(work, package)
    adopted = commit(work, candidate(tmp_path, work['state'], receipt['reference']))
    doc = copy.deepcopy(adopted['document'])
    doc['notes']['manual_note'] = 'New human note'
    allowed = scope(); allowed['note_keys'] = ['manual_note']
    path = candidate(tmp_path, adopted, receipt['reference'], 'note.json', doc, allowed)
    result = commit(work, path, adopted)
    assert result['document']['notes']['manual_note'] == 'New human note'
    assert result['diff']['invalidated'] == []


def test_scope_cannot_hide_actual_media_edit(work, package, tmp_path):
    receipt = prepared(work, package)
    doc = copy.deepcopy(work['document'])
    doc['plan']['clips'][0]['gain_db'] = -3
    path = candidate(tmp_path, work['state'], receipt['reference'], doc=doc)
    with pytest.raises(runtime.ContractError, match='FROZEN_CLIP_CONTENT_CHANGED'):
        commit(work, path)


def test_domain_ref_outside_scope_rejected(work, package, tmp_path):
    receipt = prepared(work, package)
    allowed = scope(); allowed['note_keys'] = []
    path = candidate(tmp_path, work['state'], receipt['reference'], allowed=allowed)
    with pytest.raises(runtime.ContractError, match='OUTSIDE_SCOPE: notes'):
        commit(work, path)


def test_read_reports_corrupt_attachment_and_restore_rejects(work, package, tmp_path):
    receipt = prepared(work, package)
    adopted = commit(work, candidate(tmp_path, work['state'], receipt['reference']))
    Path(receipt['reference']['manifest']['path']).write_text('{}')
    read = work['call']('read')
    assert read['version'] == adopted['version']
    assert read['drama_attachment_validation']['status'] == 'FAIL'
    with pytest.raises(runtime.ContractError, match='DRAMA_IDENTITY_CHANGED'):
        work['call']('restore', expected_version=read['version'], target_sequence=2,
                     author='agent', message='Cannot certify corrupted historical attachment')


@pytest.mark.parametrize('mutation', ['traversal', 'duplicate', 'self', 'symlink'])
def test_malformed_package_paths_rejected(package, mutation):
    manifest = json.loads(package.read_text())
    if mutation == 'traversal':
        manifest['members'][0]['path'] = '../outside'
    elif mutation == 'duplicate':
        manifest['members'].append(manifest['members'][0])
    elif mutation == 'self':
        manifest['members'][0]['path'] = package.name
    else:
        item = package.parent / manifest['members'][0]['path']
        other = item.with_suffix('.original')
        item.rename(other); item.symlink_to(other)
    write(package, manifest)
    with pytest.raises(binding.DramaBindingError):
        binding.verify_package(package)


def test_duplicate_json_keys_rejected():
    with pytest.raises(binding.DramaBindingError, match='DUPLICATE_JSON_KEY'):
        binding.json_bytes(b'{"schema":"a","schema":"b"}')


def test_changed_content_with_fresh_hash_still_requires_domain_validation(package):
    manifest = json.loads(package.read_text())
    content_path = package.parent / manifest['content_path']
    content = json.loads(content_path.read_text())
    content['shots'][0]['asset_refs'].append('MISSING-ASSET')
    write(content_path, content)
    item = next(x for x in manifest['members'] if x['path'] == manifest['content_path'])
    item.update(sha256=runtime.sha256(content_path), size_bytes=content_path.stat().st_size)
    write(package, manifest)
    with pytest.raises(binding.DramaBindingError, match='DRAMA_DOMAIN_NOT_PASS'):
        binding.verify_package(package)


def test_cli_emits_exclusive_versioned_receipt(package, tmp_path):
    output = tmp_path / 'result.json'
    command = [sys.executable, str(ROOT / 'scripts/drama_tools.py'), 'verify-package', str(package), '--output', str(output)]
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(output.read_text())['host_adoption'] == 'NOT_RUN'
    original = output.read_bytes()
    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode != 0 and output.read_bytes() == original


def refresh_member(package, content):
    manifest = json.loads(package.read_text())
    target = package.parent / manifest['content_path']
    write(target, content)
    item = next(x for x in manifest['members'] if x['path'] == manifest['content_path'])
    item.update(sha256=runtime.sha256(target), size_bytes=target.stat().st_size)
    write(package, manifest)


@pytest.mark.parametrize('location', ['shot', 'observed-basis'])
def test_all_supported_media_binding_sites_are_byte_checked(package, location):
    content = json.loads((package.parent / 'drama-content.json').read_text())
    fake = {'path': '/definitely-not-real-drama-media.mp4', 'sha256': '0' * 64, 'size_bytes': 0}
    if location == 'shot':
        content['shots'][0].update(actual_duration_sec=8, actual_binding=fake)
    else:
        content['background'][0]['basis'] = {'kind': 'observed', 'actual_binding': fake}
    refresh_member(package, content)
    with pytest.raises(binding.DramaBindingError, match='DRAMA_FILE_REQUIRED'):
        binding.verify_package(package)


def test_missing_style_document_closure_is_not_an_adoptable_package(package):
    manifest = json.loads(package.read_text())
    manifest['members'] = [x for x in manifest['members'] if x['path'] == 'drama-content.json']
    write(package, manifest)
    with pytest.raises(binding.DramaBindingError, match='DRAMA_DOCUMENT_NOT_IN_MANIFEST'):
        binding.verify_package(package)


def test_optional_null_event_basis_does_not_crash_binding(package):
    content = json.loads((package.parent / 'drama-content.json').read_text())
    content['events'][0]['basis'] = None
    refresh_member(package, content)
    assert binding.verify_package(package)['status'] == 'PASS'


def test_variant_inherits_checked_drama_without_mutating_parent(work, package, tmp_path):
    import batch_ops
    receipt = prepared(work, package)
    adopted = commit(work, candidate(tmp_path, work['state'], receipt['reference']))
    child_candidate = candidate(tmp_path, adopted, receipt['reference'], 'variant.json')
    output = tmp_path / 'variant-operation'
    output.mkdir()
    result = batch_ops.variant_create({
        'operation': 'work-variant-create', 'parent_store': str(work['store']),
        'expected_parent_version': adopted['version'], 'target_store': str(tmp_path / 'variant.sqlite3'),
        'variant_id': 'variant-test', 'candidate': {'path': str(child_candidate), 'sha256': runtime.sha256(child_candidate)},
        'message': 'Create separate test variant', 'author': 'agent'}, output, work['tools'])
    assert result['parent_current_at_finish'] is True
    assert result['variant']['document']['notes']['drama_domain_ref'] == receipt['reference']
    assert result['variant']['drama_attachment_validation']['status'] == 'PASS'
    assert work['call']('read')['document'] == adopted['document']


def test_fabricated_init_inheritance_cannot_bypass_parent_version(work, package, tmp_path):
    receipt = prepared(work, package)
    document = copy.deepcopy(work['document'])
    document['notes']['drama_domain_ref'] = receipt['reference']
    output = tmp_path / 'bad-inheritance'; output.mkdir()
    target = tmp_path / 'should-not-exist.sqlite3'
    with pytest.raises(runtime.ContractError, match='DRAMA_PARENT_VERSION_CONFLICT'):
        work_ops.work_version({'operation':'work-version', 'action':'init', 'store':str(target),
            'work_id':'bad-child', 'document':document, 'message':'Test', 'author':'agent',
            'drama_inheritance':{'store':str(work['store']), 'expected_version':'made-up-version'}},
            output, work['tools'])
    assert not target.exists()
