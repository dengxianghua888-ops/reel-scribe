"""Offline byte/currency boundaries; no real provider, media or adoption claim."""
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import generation_tasks as generation
import test_generation_intents as fixtures


class GenerationObservationBytes(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.GenerationIntentContracts()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.store = self.fixture.store

    def accepted(self):
        task = self.fixture.verified('byte-review')
        candidate = self.fixture.candidate('byte-review')
        review = self.fixture.review(task, candidate, 'byte-review')
        self.store.record_review(task['task_id'], candidate, fixtures.digest(candidate),
                                 review, fixtures.digest(review))
        return task, candidate, review

    def swap_after_read(self, target, replacement):
        """Real on-disk change after one byte snapshot; hashing must bind the snapshot."""
        read = Path.read_bytes
        changed = []

        def observe(path):
            data = read(path)
            if path == target and not changed:
                changed.append(True)
                target.write_bytes(replacement)
            return data

        return patch.object(Path, 'read_bytes', observe)

    def test_record_review_never_records_changed_decision_under_original_hash(self):
        task = self.fixture.verified('review-swap')
        candidate = self.fixture.candidate('review-swap')
        review = self.fixture.review(task, candidate, 'review-swap')
        original = review.read_bytes()
        rejecting = dict(json.loads(original), decision='REJECT')
        review.write_text(json.dumps(rejecting), encoding='utf-8')
        rejected_sha = fixtures.digest(review)
        before = self.fixture.ledger()
        with self.swap_after_read(review, original):
            with self.assertRaisesRegex(generation.Conflict, 'CANDIDATE_OR_REVIEW_HASH_MISMATCH'):
                self.store.record_review(task['task_id'], candidate, fixtures.digest(candidate),
                                         review, rejected_sha)
        self.assertEqual(before, self.fixture.ledger())

    def test_record_review_rechecks_candidate_before_write_and_idempotent_return(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                task = self.fixture.verified('candidate-' + str(existing))
                candidate = self.fixture.candidate('candidate-' + str(existing))
                review = self.fixture.review(task, candidate, 'candidate-' + str(existing))
                candidate_sha, review_sha = fixtures.digest(candidate), fixtures.digest(review)
                if existing:
                    self.store.record_review(task['task_id'], candidate, candidate_sha, review, review_sha)
                before = self.fixture.ledger()
                verify = self.store._verify_result_chain

                def change_after_validation(*args):
                    verify(*args)
                    candidate.write_bytes(b'Changed while result chain was checked.\n')

                with patch.object(self.store, '_verify_result_chain', change_after_validation):
                    with self.assertRaisesRegex(generation.Conflict, 'CANDIDATE_OR_REVIEW_HASH_MISMATCH'):
                        self.store.record_review(task['task_id'], candidate, candidate_sha, review, review_sha)
                self.assertEqual(before, self.fixture.ledger())

    def test_default_gate_checks_actual_review_decision_even_for_legacy_row(self):
        task, candidate, review = self.accepted()
        body = json.loads(review.read_bytes())
        body['decision'] = 'REJECT'
        review.write_text(json.dumps(body), encoding='utf-8')
        # Simulate a row created by the previous split-read bug. No automatic repair.
        with sqlite3.connect(self.store.path) as db:
            db.execute('UPDATE candidate_reviews SET review_sha256=?', (fixtures.digest(review),))
        before = self.fixture.ledger()
        with self.assertRaisesRegex(generation.Conflict, 'ACCEPTED_REVIEW_OUTPUT_IDENTITY_CHANGED'):
            self.store.adoption_gate(task['task_id'], self.fixture.work, candidate, fixtures.digest(candidate))
        self.assertEqual(before, self.fixture.ledger())

    def test_default_gate_rechecks_candidate_and_review_after_snapshot(self):
        for target_kind, expected_error in (('candidate', 'CANDIDATE_HASH_MISMATCH'),
                                             ('review', 'ACCEPTED_REVIEW_HASH_CHANGED')):
            with self.subTest(target=target_kind):
                task, candidate, review = self.accepted()
                original = {p: p.read_bytes() for p in (candidate, review)}
                before = self.fixture.ledger()
                target = candidate if target_kind == 'candidate' else review
                with self.swap_after_read(target, b'{"changed":true}'):
                    with self.assertRaisesRegex(generation.Conflict, expected_error):
                        self.store.adoption_gate(task['task_id'], self.fixture.work,
                                                 candidate, hashlib.sha256(original[candidate]).hexdigest())
                self.assertEqual(before, self.fixture.ledger())
                for path, data in original.items():
                    path.write_bytes(data)

    def test_receipt_snapshot_change_does_not_create_verified_result(self):
        task = self.fixture.ready('receipt-swap')
        receipt = self.fixture.receipt(task, 'receipt-swap-download')
        before = self.fixture.ledger()
        receipt_sha = fixtures.digest(receipt)
        with self.swap_after_read(receipt, b'{"changed":true}'):
            with self.assertRaisesRegex(generation.Conflict, 'RESULT_HASH_CHANGED'):
                self.store.record_result(task['task_id'], receipt, receipt_sha)
        self.assertEqual(before, self.fixture.ledger())

    def test_valid_utf8_review_remains_idempotent_and_gate_is_read_only(self):
        task, candidate, review = self.accepted()
        before = self.fixture.ledger()
        self.store.record_review(task['task_id'], candidate, fixtures.digest(candidate),
                                 review, fixtures.digest(review))
        result = self.store.adoption_gate(task['task_id'], self.fixture.work,
                                          candidate, fixtures.digest(candidate))
        self.assertEqual(result['status'], 'READY_FOR_WORK_VERSION_CAS_ONLY')
        self.assertFalse(result['publishable'])
        self.assertEqual(before, self.fixture.ledger())
        self.assertEqual(len(self.fixture.adapter.submits), 1)


class GenerationCurrencyBoundary(unittest.TestCase):
    def test_currency_drift_rejects_poll_and_cancel_without_provider_or_ledger_change(self):
        for action in ('poll', 'cancel'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as directory:
                store = generation.GenerationStore(Path(directory) / 'tasks.sqlite')
                store.create_budget('b', 'USD', 100)
                task = store.create_task(idempotency_key='currency', provider_id='fixture',
                    model='offline', kind='video', payload={'prompt': 'synthetic'}, budget_key='b',
                    max_cost_micros=50, work_binding={'work_id': 'w', 'version': 'a' * 64,
                                                     'document_sha256': 'b' * 64})

                class Adapter:
                    provider_id = 'fixture'
                    currency = 'USD'
                    submits = queries = cancels = 0

                    def capabilities(self):
                        return generation.ProviderCapabilities(self.currency, False, True, cancel_supported=True)

                    def submit(self, *args, **kwargs):
                        self.submits += 1
                        return generation.SubmissionAck('job', 'RUNNING')

                    def query(self, **kwargs):
                        self.queries += 1
                        return generation.ProviderObservation('SUCCEEDED', provider_task_id='job',
                                                               result_available=False, actual_cost_micros=25)

                    def cancel(self, **kwargs):
                        self.cancels += 1

                adapter = Adapter()
                store.submit_once(task['task_id'], adapter)
                adapter.currency = 'CNY'
                before = (store.get(task['task_id']), store.budget('b'), store.events(task['task_id']))
                operation = store.poll if action == 'poll' else store.request_cancel
                with self.assertRaisesRegex(generation.Conflict, 'PROVIDER_CURRENCY_MISMATCH'):
                    operation(task['task_id'], adapter)
                self.assertEqual(before, (store.get(task['task_id']), store.budget('b'), store.events(task['task_id'])))
                self.assertEqual((adapter.submits, adapter.queries, adapter.cancels), (1, 0, 0))
                adapter.currency = 'USD'
                reopened = generation.GenerationStore(store.path)
                operation = reopened.poll if action == 'poll' else reopened.request_cancel
                operation(task['task_id'], adapter)
                self.assertEqual(adapter.submits, 1)
                self.assertEqual(adapter.queries if action == 'poll' else adapter.cancels, 1)

    def test_invalid_currency_is_a_controlled_capability_error(self):
        with tempfile.TemporaryDirectory() as directory:
            store = generation.GenerationStore(Path(directory) / 'tasks.sqlite')
            store.create_budget('b', 'USD', 100)
            task = store.create_task(idempotency_key='bad-currency', provider_id='fixture', model='offline',
                kind='video', payload={'prompt': 'synthetic'}, budget_key='b', max_cost_micros=1,
                work_binding={'work_id': 'w', 'version': 'a' * 64, 'document_sha256': 'b' * 64})
            class Adapter:
                provider_id = 'fixture'
                def capabilities(self):
                    return generation.ProviderCapabilities(None, False, True)
            with self.assertRaisesRegex(generation.GenerationError, 'PROVIDER_CAPABILITIES_INVALID'):
                store.submit_once(task['task_id'], Adapter())
            self.assertEqual(store.get(task['task_id'])['state'], 'CREATED')
            self.assertEqual(store.budget('b')['reserved_micros'], 0)


class TextPrepareByteSnapshot(unittest.TestCase):
    def test_both_prepare_entries_freeze_only_the_sha_verified_body_bytes(self):
        import deepseek_dispatch
        import model_text_dispatch
        from model_text_generic import ProfileRegistry
        for legacy in (False, True):
            with self.subTest(legacy=legacy), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                database, body_path = root / 'text.sqlite', root / 'body.json'
                body = {'messages': [{'role': 'user', 'content': 'approved body'}], 'max_tokens': 32}
                if legacy:
                    body['model'] = 'deepseek-chat'
                body_a = json.dumps(body, ensure_ascii=False).encode('utf-8')
                body_b = body_a.replace(b'approved body', b'unapproved body')
                body_path.write_bytes(body_a)
                operation = 'model-text-deepseek' if legacy else 'model-text'
                dispatch = deepseek_dispatch.execute if legacy else model_text_dispatch.execute
                dispatch({'operation': operation, 'action': 'budget-create', 'store': str(database),
                          'budget_key': 'offline', 'currency': 'USD', 'limit_micros': 100})
                args = {'operation': operation, 'action': 'prepare', 'store': str(database),
                    'intent_key': 'approved-intent', 'body_path': str(body_path),
                    'body_sha256': hashlib.sha256(body_a).hexdigest(),
                    'budget_key': 'offline', 'reservation_micros': 10}
                if not legacy:
                    profile = ProfileRegistry().get('deepseek-default')
                    args.update(profile_id=profile.profile_id, profile_sha256=profile.profile_sha256)
                original_open = Path.open
                snapshots = []

                def replace_after_open(path, mode='r', *a, **kw):
                    if path == body_path and mode == 'rb' and not snapshots:
                        snapshots.append(True)
                        body_path.write_bytes(body_b)
                        return io.BytesIO(body_a)
                    return original_open(path, mode, *a, **kw)

                with patch.object(Path, 'open', replace_after_open):
                    result = dispatch(args)
                with sqlite3.connect(database) as db:
                    frozen = json.loads(db.execute('SELECT body_json FROM calls').fetchone()[0])
                    table = 'budget' if legacy else 'budgets'
                    self.assertEqual(db.execute('SELECT reserved_micros FROM ' + table).fetchone()[0], 0)
                self.assertEqual(frozen['messages'][0]['content'], 'approved body')
                self.assertEqual(result['state'], 'PREPARED')
                self.assertEqual(dispatch({'operation': operation, 'action': 'read', 'store': str(database),
                                           'call_id': result['call_id']})['attempt_count'], 0)
                self.assertEqual(body_path.read_bytes(), body_b)
                self.assertEqual(len(snapshots), 1)


if __name__ == '__main__':
    unittest.main()
