"""Offline recovery checks with real SQLite and synthetic clients; no credentials."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import deepseek_dispatch
from deepseek_text import DeepSeekCallStore, DeepSeekError
from generation_tasks import Conflict
from model_text_generic import ModelTextError
import test_billing_evidence_bytes as fixtures


class BillingReplayIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BillingEvidenceBytesTests()

    def test_replayed_correction_still_checks_older_canonical_evidence(self):
        for kind in self.fixture.kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                store, database, client, items = self.fixture.fixture(root, kind)
                identifier, identity = items[0]
                original, original_sha = self.fixture.evidence(root, identity, 9)
                store.settle_cost(identifier, 'first', str(original), original_sha)
                correction, correction_sha = self.fixture.evidence(root, identity, 7, 'correction.json')
                store.settle_cost(identifier, 'correction', str(correction), correction_sha)
                original_bytes = original.read_bytes()
                original.write_bytes(b'Changed canonical historical evidence.\n')
                before = self.fixture.snapshot(database)
                reopened = type(store)(database)
                with self.assertRaisesRegex((Conflict, ModelTextError, DeepSeekError),
                                            'PRIOR_BILLING_EVIDENCE_CHANGED'):
                    reopened.settle_cost(identifier, 'correction', str(correction), correction_sha)
                self.assertEqual(before, self.fixture.snapshot(database))
                self.assertEqual(self.fixture.spent_reserved(database, kind), (7, 0))
                original.write_bytes(original_bytes)
                self.assertTrue(reopened.settle_cost(identifier, 'correction', str(correction), correction_sha)['idempotent'])
                self.assertEqual(before, self.fixture.snapshot(database))
                self.assertEqual(client.submits, 1)

    def test_same_bytes_new_path_does_not_hide_a_missing_canonical_receipt(self):
        for kind in self.fixture.kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                store, database, client, items = self.fixture.fixture(root, kind)
                identifier, identity = items[0]
                original, pinned = self.fixture.evidence(root, identity, 9)
                store.settle_cost(identifier, 'first', str(original), pinned)
                copied = root / 'copied.json'
                copied.write_bytes(original.read_bytes())
                before = self.fixture.snapshot(database)
                # A same-byte retry path remains allowed while the original is intact.
                self.assertTrue(store.settle_cost(identifier, 'first', str(copied), pinned)['idempotent'])
                original.unlink()
                with self.assertRaisesRegex((Conflict, ModelTextError, DeepSeekError),
                                            'PRIOR_BILLING_EVIDENCE_CHANGED'):
                    store.settle_cost(identifier, 'first', str(copied), pinned)
                self.assertEqual(before, self.fixture.snapshot(database))
                self.assertEqual(client.submits, 1)

    def test_reused_key_conflict_keeps_precedence_and_accounting(self):
        for kind in self.fixture.kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                store, database, client, items = self.fixture.fixture(root, kind)
                identifier, identity = items[0]
                original, pinned = self.fixture.evidence(root, identity, 9)
                store.settle_cost(identifier, 'first', str(original), pinned)
                different, changed_sha = self.fixture.evidence(root, identity, 7, 'other.json')
                original.write_bytes(b'Changed historical evidence.\n')
                before = self.fixture.snapshot(database)
                with self.assertRaisesRegex((Conflict, ModelTextError, DeepSeekError),
                                            'BILLING_EVENT_KEY_CONFLICT'):
                    store.settle_cost(identifier, 'first', str(different), changed_sha)
                self.assertEqual(before, self.fixture.snapshot(database))


class LegacyTextRecoveryTests(unittest.TestCase):
    @staticmethod
    def prepare(root):
        store = DeepSeekCallStore(root / 'calls.sqlite')
        store.create_budget('offline', 'USD', 100)
        result = store.prepare('original', {'model': 'offline', 'messages': [
            {'role': 'user', 'content': 'synthetic body'}], 'max_tokens': 1}, 'offline', 10)
        return store, result['call_id']

    @staticmethod
    def request(store, identifier):
        return {'operation': 'model-text-deepseek', 'action': 'send-once',
                'store': str(store.path), 'call_id': identifier}

    def test_unknown_and_complete_return_without_constructing_a_client(self):
        for uncertain in (False, True):
            with self.subTest(uncertain=uncertain), tempfile.TemporaryDirectory() as raw:
                store, identifier = self.prepare(Path(raw))
                client = fixtures.SyntheticText()
                if uncertain:
                    def unknown(body):
                        client.submits += 1
                        raise TimeoutError('Synthetic lost response; no network')
                    client.send = unknown
                store.send_once(identifier, client)
                before = fixtures.BillingEvidenceBytesTests.snapshot(store.path)
                expected = store.read(identifier)
                with patch.object(deepseek_dispatch, 'DeepSeekTextClient',
                                  side_effect=AssertionError('Recovery must not construct a credential client')) as constructor:
                    self.assertEqual(deepseek_dispatch.execute(self.request(store, identifier)), expected)
                    constructor.assert_not_called()
                self.assertEqual(before, fixtures.BillingEvidenceBytesTests.snapshot(store.path))
                self.assertEqual(client.submits, 1)
                self.assertEqual(expected['state'], 'UNKNOWN_SUBMISSION' if uncertain else 'COMPLETE')

    def test_prepared_call_still_needs_explicit_credential_client(self):
        with tempfile.TemporaryDirectory() as raw:
            store, identifier = self.prepare(Path(raw))
            before = fixtures.BillingEvidenceBytesTests.snapshot(store.path)
            with patch.object(deepseek_dispatch, 'DeepSeekTextClient',
                              side_effect=DeepSeekError('DEEPSEEK_API_KEY_REQUIRED')) as constructor:
                with self.assertRaisesRegex(DeepSeekError, 'DEEPSEEK_API_KEY_REQUIRED'):
                    deepseek_dispatch.execute(self.request(store, identifier))
                constructor.assert_called_once()
            self.assertEqual(before, fixtures.BillingEvidenceBytesTests.snapshot(store.path))
            self.assertEqual(store.read(identifier)['attempt_count'], 0)

    def test_missing_call_returns_ledger_error_without_a_credential_client(self):
        with tempfile.TemporaryDirectory() as raw:
            store, _ = self.prepare(Path(raw))
            with patch.object(deepseek_dispatch, 'DeepSeekTextClient',
                              side_effect=AssertionError('Must look up original task first')) as constructor:
                with self.assertRaisesRegex(DeepSeekError, 'CALL_NOT_FOUND'):
                    deepseek_dispatch.execute(self.request(store, 'missing-call'))
                constructor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
