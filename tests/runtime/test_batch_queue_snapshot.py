"""Concurrent status observations with real SQLite in both journal modes."""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_batch_manifest_binding import batch, invoke, queue_state
import batch_ops


def journal(folder, mode):
    with sqlite3.connect(folder / 'queue.sqlite') as db:
        assert db.execute('PRAGMA journal_mode=' + mode).fetchone()[0] == mode.lower()


def start_attempt(folder):
    # The same two writes as the worker, committed by a separate connection.
    # timeout=0 ensures status does not leave a read lock blocking this commit.
    with sqlite3.connect(folder / 'queue.sqlite', timeout=0) as writer:
        writer.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',
                       ('one', 1, 'RUNNING', str(folder / 'jobs/one/attempt-0001'), None))
        writer.execute("UPDATE jobs SET status='RUNNING',attempt=1 WHERE id='one'")


@pytest.mark.parametrize('mode', ['DELETE', 'WAL'])
def test_status_concurrent_commit_after_queue_capture_is_consistent(batch, monkeypatch, mode):
    folder = batch[0]
    journal(folder, mode)
    original = batch_ops.database
    commits = []

    class Captured:
        def __init__(self, rows):
            self.rows = rows
        def __iter__(self):
            return iter(self.rows)
        def fetchall(self):
            return self.rows
        def close(self):
            pass

    class Reader:
        def __init__(self, db):
            self.db = db
        def execute(self, sql, *args):
            cursor = self.db.execute(sql, *args)
            if not commits and ('UNION ALL' in sql or sql == 'SELECT * FROM jobs ORDER BY ordinal'):
                rows = cursor.fetchall()
                cursor.close()
                start_attempt(folder)
                commits.append(True)
                return Captured(rows)
            return cursor
        def close(self):
            self.db.close()

    monkeypatch.setattr(batch_ops, 'database', lambda p: Reader(original(p)))
    result = invoke(batch, 'status')
    assert commits == [True]
    assert result['jobs'][0]['status'] == 'PENDING'
    assert result['jobs'][0]['attempt'] == 0
    assert result['attempts'] == []
    assert result['artifact_integrity'] == 'NOT_RECHECKED_STATUS_ONLY'
    assert queue_state(folder)[1][0][2:4] == ('RUNNING', 1)


@pytest.mark.parametrize('mode', ['DELETE', 'WAL'])
def test_status_concurrent_work_lookup_cannot_mix_or_lock_queue(batch, monkeypatch, mode):
    folder = batch[0]
    journal(folder, mode)
    original_database, original_work = batch_ops.database, batch_ops.work_state
    closed = []
    commits = []

    class Reader:
        def __init__(self, db):
            self.db = db
        def execute(self, *args):
            return self.db.execute(*args)
        def close(self):
            self.db.close()
            closed.append(True)

    def work_state(store):
        assert closed == [True], 'Status must release its queue connection before Work inspection'
        start_attempt(folder)
        commits.append(True)
        return original_work(store)

    monkeypatch.setattr(batch_ops, 'database', lambda p: Reader(original_database(p)))
    monkeypatch.setattr(batch_ops, 'work_state', work_state)
    result = invoke(batch, 'status')
    assert commits == [True]
    assert result['jobs'][0]['status'] == 'PENDING'
    assert result['attempts'] == []
    assert result['jobs'][0]['current_version_matches'] is True
    assert queue_state(folder)[1][0][2:4] == ('RUNNING', 1)


def test_exclusive_writer_keeps_existing_nonblocking_status_failure(batch):
    folder = batch[0]
    journal(folder, 'DELETE')
    writer = sqlite3.connect(folder / 'queue.sqlite', timeout=0)
    try:
        writer.execute('BEGIN EXCLUSIVE')
        with pytest.raises(sqlite3.OperationalError, match='locked'):
            invoke(batch, 'status')
    finally:
        writer.rollback()
        writer.close()


@pytest.mark.parametrize('duplicate', [False, True])
def test_manifest_metadata_not_dropped_or_overwritten(batch, duplicate):
    folder = batch[0]
    with sqlite3.connect(folder / 'queue.sqlite') as db:
        if duplicate:
            # Simulate a corrupted schema without its required primary key.
            db.execute('CREATE TABLE replacement AS SELECT * FROM metadata')
            db.execute('INSERT INTO replacement SELECT * FROM metadata')
            db.execute('DROP TABLE metadata')
            db.execute('ALTER TABLE replacement RENAME TO metadata')
        else:
            db.execute('DELETE FROM metadata')
    before = queue_state(folder)
    with pytest.raises(ValueError, match='BATCH_MANIFEST_DATABASE_MISMATCH'):
        invoke(batch, 'status')
    assert queue_state(folder) == before


def test_queue_capture_keeps_all_attempts_visible(batch):
    folder = batch[0]
    with sqlite3.connect(folder / 'queue.sqlite') as db:
        db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)',
                   ('unindexed', 1, 'RUNNING', '/unindexed/attempt', None))
    db = batch_ops.database(folder)
    try:
        captured = batch_ops.queue_snapshot(db)
    finally:
        db.close()
    # A cache must not silently hide records via a join to the jobs table.
    assert captured['attempts'] == [{'job_id': 'unindexed', 'number': 1,
        'status': 'RUNNING', 'path': '/unindexed/attempt', 'error': None}]
