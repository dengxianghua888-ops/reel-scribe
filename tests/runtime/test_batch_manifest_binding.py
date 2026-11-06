"""Real SQLite, synthetic Work metadata; no provider or media quality claims."""
import json
import sqlite3
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_generation_intents as fixtures
import batch_ops


@pytest.fixture
def batch(tmp_path):
    contracts = fixtures.GenerationIntentContracts()
    contracts.setUp()
    try:
        work = contracts.work_fixture()
        work['tools'].doctor = lambda: {'synthetic': {'sha256': 'a' * 64}}
        folder = tmp_path / 'batch'
        output = tmp_path / 'prepare'
        output.mkdir()
        result = batch_ops.batch_render({
            'operation': 'work-batch-render', 'action': 'prepare',
            'batch_dir': str(folder), 'batch_id': 'approved',
            'jobs': [{'id': 'one', 'store': str(work['store']),
                      'expected_version': work['state']['version']}]}, output, work['tools'])
        yield folder, result['manifest_sha256'], work, tmp_path
    finally:
        contracts.doCleanups()


def request(batch, action):
    folder, digest, _, _ = batch
    result = {'operation': 'work-batch-render', 'action': action,
              'batch_dir': str(folder), 'manifest_sha256': digest}
    if action == 'run':
        result.update(job_ids=['one'], retry_failed=False)
    return result


def invoke(batch, action):
    _, _, work, root = batch
    output = root / action
    output.mkdir()
    return batch_ops.batch_render(request(batch, action), output, work['tools'])


def queue_state(folder):
    with sqlite3.connect(folder / 'queue.sqlite') as db:
        return [db.execute('SELECT * FROM ' + table + ' ORDER BY 1').fetchall()
                for table in ['metadata', 'jobs', 'attempts']]


@pytest.mark.parametrize('action', ['status', 'run'])
def test_reject_manifest_bytes_different_from_approved_hash(batch, monkeypatch, action):
    folder, _, work, _ = batch
    manifest = folder / 'manifest.json'
    approved = manifest.read_bytes()
    replacement = json.loads(approved)
    replacement['batch_id'] = 'unapproved'
    replacement['jobs'][0]['store'] = '/unapproved/work.sqlite'
    changed = json.dumps(replacement).encode()
    before = queue_state(folder)
    parent = work['head']()
    read_bytes, read_text = Path.read_bytes, Path.read_text

    def swapped_bytes(path):
        if path != manifest:
            return read_bytes(path)
        # Model A -> B -> A between the path checksum and JSON consumption.
        path.write_bytes(changed)
        try:
            return read_bytes(path)
        finally:
            path.write_bytes(approved)

    def swapped_text(path, *args, **kwargs):
        if path != manifest:
            return read_text(path, *args, **kwargs)
        return swapped_bytes(path).decode('utf-8')

    monkeypatch.setattr(Path, 'read_bytes', swapped_bytes)
    monkeypatch.setattr(Path, 'read_text', swapped_text)
    with pytest.raises(ValueError, match='BATCH_MANIFEST_CHANGED'):
        invoke(batch, action)
    assert queue_state(folder) == before
    assert work['head']() == parent
    assert not (folder / 'jobs').exists()


@pytest.mark.parametrize('action', ['status', 'run'])
def test_reject_persistently_changed_manifest_without_queue_writes(batch, action):
    folder, _, _, _ = batch
    before = queue_state(folder)
    manifest = folder / 'manifest.json'
    manifest.write_bytes(manifest.read_bytes() + b' ')
    with pytest.raises(ValueError, match='BATCH_MANIFEST_CHANGED'):
        invoke(batch, action)
    assert queue_state(folder) == before


def test_recheck_manifest_after_worker_lock_before_queue_mutation(batch, monkeypatch):
    folder, _, _, _ = batch
    before = queue_state(folder)
    exclusive = batch_ops.exclusive

    @contextmanager
    def changed_at_lock(path):
        with exclusive(path):
            manifest = folder / 'manifest.json'
            manifest.write_bytes(manifest.read_bytes() + b' ')
            yield

    monkeypatch.setattr(batch_ops, 'exclusive', changed_at_lock)
    def unexpected_render(*args, **kwargs):
        raise AssertionError('Render started after the manifest changed')
    monkeypatch.setattr(fixtures.editing_runtime, 'run', unexpected_render)
    with pytest.raises(ValueError, match='BATCH_MANIFEST_CHANGED'):
        invoke(batch, 'run')
    assert queue_state(folder) == before
    assert not (folder / 'jobs').exists()


def test_unchanged_manifest_status_retains_contract(batch):
    folder, digest, _, _ = batch
    before = queue_state(folder)
    result = invoke(batch, 'status')
    assert result['batch_id'] == 'approved'
    assert result['jobs'][0]['status'] == 'PENDING'
    assert result['artifact_integrity'] == 'NOT_RECHECKED_STATUS_ONLY'
    assert fixtures.digest(folder / 'manifest.json') == digest
    assert queue_state(folder) == before
