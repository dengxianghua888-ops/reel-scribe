"""Work commits must consume the same UTF-8 candidate bytes as their pinned SHA.

Real temporary SQLite and the existing scope/CAS code run here. The reused
SyntheticMediaTools fixture declares clock metadata for plain bytes; it does not
decode media or certify a user project, provider output, or editor round trip.
"""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_generation_intents as fixtures


class WorkCandidateBytesTests(unittest.TestCase):
    def setUp(self):
        self.contracts = fixtures.GenerationIntentContracts()
        self.contracts.setUp()
        self.addCleanup(self.contracts.doCleanups)
        self.work = self.contracts.work_fixture()
        document = copy.deepcopy(self.work['document'])
        document['notes']['manual-note'] = 'Reviewed change A'
        self.candidate = self.contracts.work_candidate(self.work, document, 'reviewed-candidate',
            self.contracts.scope(notes=['manual-note']))
        self.pinned = fixtures.digest(self.candidate)
        self.other = json.loads(self.candidate.read_text())
        self.other['document']['notes']['manual-note'] = 'Unreviewed change B'

    def snapshot(self):
        with sqlite3.connect(self.work['store']) as db:
            return (db.execute('SELECT * FROM metadata ORDER BY key').fetchall(),
                    db.execute('SELECT * FROM revisions ORDER BY sequence').fetchall())

    def commit(self, expected=None):
        return self.work['call']('commit', expected_version=expected or self.work['state']['version'],
            candidate={'path': str(self.candidate), 'sha256': self.pinned},
            author='agent', message='Apply precisely the reviewed candidate')

    def test_same_scope_replacement_between_initial_hash_and_parse_is_rejected(self):
        before = self.snapshot()
        original_open = Path.open
        observed = []
        candidate = self.candidate
        replacement = json.dumps(self.other).encode('utf-8')

        class ReplaceAfterRead:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                self.stream.__enter__()
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def read(self, *args):
                value = self.stream.read(*args)
                if value and not observed:
                    observed.append(value)
                    candidate.write_bytes(replacement)
                return value

            def __getattr__(self, name):
                return getattr(self.stream, name)

        def controlled_open(path, *args, **kwargs):
            stream = original_open(path, *args, **kwargs)
            mode = args[0] if args else kwargs.get('mode', 'r')
            return ReplaceAfterRead(stream) if path == candidate and mode == 'rb' else stream

        with patch.object(Path, 'open', controlled_open):
            with self.assertRaisesRegex(ValueError, 'SOURCE_HASH_MISMATCH'):
                self.commit()
        self.assertEqual(len(observed), 1)
        self.assertNotEqual(fixtures.digest(candidate), self.pinned)
        self.assertEqual(self.snapshot(), before)

    def test_replacement_after_parsing_during_scope_validation_is_rejected(self):
        before = self.snapshot()
        original_diff = fixtures.work_ops.revision_diff
        observed = []

        def validate_then_replace(*args, **kwargs):
            result = original_diff(*args, **kwargs)
            self.candidate.write_text(json.dumps(self.other), encoding='utf-8')
            observed.append(True)
            return result

        with patch.object(fixtures.work_ops, 'revision_diff', validate_then_replace):
            with self.assertRaisesRegex(ValueError, 'SOURCE_HASH_MISMATCH'):
                self.commit()
        self.assertEqual(observed, [True])
        self.assertEqual(self.snapshot(), before)

    def test_normal_candidate_keeps_exact_pin_readback_and_stale_cas_rejection(self):
        result = self.commit()
        head, count = self.work['head']()
        self.assertEqual(count, 2)
        self.assertEqual(head['document']['notes']['manual-note'], 'Reviewed change A')
        self.assertEqual(head['version'], result['version'])
        with sqlite3.connect(self.work['store']) as db:
            extra = json.loads(db.execute('SELECT extra FROM revisions WHERE sequence=2').fetchone()[0])
        self.assertEqual(extra['candidate']['sha256'], self.pinned)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'WORK_VERSION_CONFLICT'):
            self.commit()
        self.assertEqual(self.snapshot(), before)

    def test_valid_byte_pin_does_not_relax_the_existing_scope(self):
        self.other['document']['notes']['outside-scope'] = 'This field was never authorized'
        self.candidate.write_text(json.dumps(self.other), encoding='utf-8')
        self.pinned = fixtures.digest(self.candidate)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'OUTSIDE_SCOPE: notes'):
            self.commit()
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
