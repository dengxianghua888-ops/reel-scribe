"""Offline G1-G4 intent contracts; synthetic bytes are not media acceptance."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from generation_tasks import (Conflict, GenerationError, GenerationStore, NotReady,
                              ProviderCapabilities, ProviderObservation, SubmissionAck)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False) + '\n', encoding='utf-8')
    return path


class SyntheticAdapter:
    provider_id = 'synthetic'

    def __init__(self, root, *, lost_ack=False, lookup=True):
        self.root = root
        self.lost_ack = lost_ack
        self.lookup = lookup
        self.observed = 'SUCCEEDED'
        self.submits = []
        self.queries = []
        self.output = root / 'synthetic-result.bin'
        self.output.write_bytes(b'Synthetic contract bytes, not a generated media file.\n')

    def capabilities(self):
        return ProviderCapabilities('USD', False, self.lookup)

    def submit(self, payload, *, idempotency_key, max_cost_micros):
        self.submits.append((idempotency_key, dict(payload), max_cost_micros))
        if self.lost_ack:
            raise TimeoutError('Synthetic ACK lost after possible submission')
        return SubmissionAck('jobs/' + idempotency_key, 'RUNNING')

    def query(self, *, idempotency_key, provider_task_id):
        self.queries.append((idempotency_key, provider_task_id))
        if self.observed in ('UNKNOWN', 'NOT_FOUND'):
            return ProviderObservation(self.observed)
        response = self.root / (idempotency_key + '-response.json')
        write_json(response, {'job': 'jobs/' + idempotency_key,
                              'output': 'outputs/' + idempotency_key, 'status': 'SUCCEEDED'})
        return ProviderObservation('SUCCEEDED', provider_task_id='jobs/' + idempotency_key,
            actual_cost_micros=0, result_available=True, response_path=str(response),
            response_sha256=digest(response), output_id='outputs/' + idempotency_key,
            output_checksum_sha256=digest(self.output))


class GenerationIntentContracts(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='generation-intents-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.store = GenerationStore(self.root / 'tasks.sqlite3')
        self.store.create_budget('offline', 'USD', 1000)
        self.work = {'work_id': 'original-work', 'version': 'a' * 64,
                     'document_sha256': 'b' * 64}
        self.adapter = SyntheticAdapter(self.root)

    def create(self, key, *, payload=None):
        return self.store.create_task(idempotency_key=key, provider_id='synthetic',
            model='offline-model', kind='video', payload=payload or {'prompt': 'synthetic prompt'},
            budget_key='offline', max_cost_micros=50, work_binding=self.work)

    def ready(self, key):
        task = self.create(key)
        self.store.submit_once(task['task_id'], self.adapter)
        return self.store.poll(task['task_id'], self.adapter)

    def receipt(self, task, attempt_key, *, changes=None):
        source_ref = 'synthetic-output:' + task['provider_output_id']
        self.store.begin_output_attempt(task['task_id'], attempt_key, 'explicit-import', source_ref)
        body = {'schema': 'generation-output-receipt/1', 'task_id': task['task_id'],
            'provider_id': task['provider_id'], 'provider_task_id': task['provider_task_id'],
            'provider_output_id': task['provider_output_id'],
            'provider_response_sha256': task['provider_response_sha256'],
            'provider_output_checksum_sha256': task['provider_output_checksum_sha256'],
            'attempt_key': attempt_key, 'source_kind': 'explicit-import', 'source_ref': source_ref,
            'result_path': str(self.adapter.output), 'result_sha256': digest(self.adapter.output)}
        body.update(changes or {})
        return write_json(self.root / (attempt_key + '-receipt.json'), body)

    def verified(self, key):
        task = self.ready(key)
        receipt = self.receipt(task, key + '-download')
        return self.store.record_result(task['task_id'], receipt, digest(receipt))

    def candidate(self, name):
        # Only the generation gate is under test. No Work media validation or CAS is claimed.
        return write_json(self.root / (name + '-candidate.json'), {'schema': 'work-candidate/1',
            'base_version': self.work['version'], 'base_document_sha256': self.work['document_sha256'],
            'document': {'source': {'path': str(self.adapter.output),
                                    'sha256': digest(self.adapter.output)}}})

    def review(self, task, candidate, name):
        return write_json(self.root / (name + '-review.json'), {
            'schema': 'generation-candidate-review/1', 'task_id': task['task_id'],
            'candidate_sha256': digest(candidate), 'result_sha256': task['result_sha256'],
            'result_receipt_sha256': task['result_receipt_sha256'],
            'provider_output_id': task['provider_output_id'], 'decision': 'ACCEPT',
            'rationale': 'Synthetic contract assertion only; no aesthetic or human acceptance.'})

    def accept(self, task, candidate, name):
        review = self.review(task, candidate, name)
        self.store.record_review(task['task_id'], candidate, digest(candidate), review, digest(review))
        return self.store.adoption_gate(task['task_id'], self.work, candidate, digest(candidate))

    def test_g1_resume_same_task_and_failed_transfer_without_another_submit(self):
        task = self.create('resume')
        self.store.submit_once(task['task_id'], self.adapter)
        self.store = GenerationStore(self.store.path)
        self.assertEqual(self.create('resume')['task_id'], task['task_id'])
        self.store.submit_once(task['task_id'], self.adapter)
        with self.assertRaisesRegex(Conflict, 'IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_INTENT'):
            self.create('resume', payload={'prompt': 'changed prompt is not a resume'})
        task = self.store.poll(task['task_id'], self.adapter)
        self.store.begin_output_attempt(task['task_id'], 'failed-transfer', 'provider-download',
                                        'synthetic-output:' + task['provider_output_id'])
        self.store.fail_output_attempt(task['task_id'], 'failed-transfer', 'SYNTHETIC_DOWNLOAD_FAILED')
        receipt = self.receipt(task, 'recovered-transfer')
        verified = self.store.record_result(task['task_id'], receipt, digest(receipt))
        reopened = GenerationStore(self.store.path)
        self.assertEqual(reopened.get(task['task_id']), verified)
        self.assertEqual(reopened.record_result(task['task_id'], receipt, digest(receipt)), verified)
        self.assertEqual([a['state'] for a in reopened.output_attempts(task['task_id'])],
                         ['FAILED', 'COMPLETE'])
        self.assertEqual(verified['provider_task_id'], 'jobs/resume')
        self.assertEqual(verified['provider_output_id'], 'outputs/resume')
        self.assertEqual(len(self.adapter.submits), 1)
        self.assertEqual(self.store.budget('offline')['reserved_micros'], 0)

    def test_g2_pin_verified_sha_preserve_origin_and_reject_receipt_identity_laundering(self):
        task = self.verified('original')
        candidate = self.candidate('original')
        gate = self.accept(task, candidate, 'original')
        original_receipt_bytes = Path(task['result_receipt_path']).read_bytes()
        self.assertEqual(digest(self.adapter.output), task['result_sha256'])
        self.assertEqual(gate['status'], 'READY_FOR_WORK_VERSION_CAS_ONLY')
        self.assertFalse(gate['publishable'])
        current_work = {'work_id': 'current-work', 'version': 'c' * 64,
                        'document_sha256': 'd' * 64}
        with self.assertRaisesRegex(Conflict, 'WORK_HEAD_CHANGED'):
            self.store.adoption_gate(task['task_id'], current_work, candidate, digest(candidate))
        for field, wrong in [('task_id', 'different-task'), ('provider_id', 'different-provider'),
                ('provider_task_id', 'jobs/different-task'),
                ('provider_output_id', 'outputs/different-output'),
                ('provider_response_sha256', 'e' * 64),
                ('provider_output_checksum_sha256', 'f' * 64)]:
            with self.subTest(field=field):
                receipt = self.receipt(task, 'retry-' + field, changes={field: wrong})
                before = (self.store.get(task['task_id']), self.store.events(task['task_id']),
                          self.store.output_attempts(task['task_id']))
                with self.assertRaisesRegex(Conflict, 'RESULT_RECEIPT_OUTPUT_IDENTITY_MISMATCH'):
                    self.store.record_result(task['task_id'], receipt, digest(receipt))
                self.assertEqual(before, (self.store.get(task['task_id']),
                    self.store.events(task['task_id']), self.store.output_attempts(task['task_id'])))
        # A new receipt can change while the earlier canonical chain is being checked.
        receipt = self.receipt(task, 'concurrent-retry')
        receipt_sha = digest(receipt)
        receipt_bytes = receipt.read_bytes()
        before = (self.store.get(task['task_id']), self.store.events(task['task_id']),
                  self.store.output_attempts(task['task_id']))
        verify_chain = GenerationStore._verify_result_chain

        def change_new_receipt(verified_task, db):
            verify_chain(verified_task, db)
            receipt.write_bytes(receipt_bytes + b' ')

        with patch.object(GenerationStore, '_verify_result_chain', side_effect=change_new_receipt):
            with self.assertRaisesRegex(Conflict, 'RESULT_HASH_CHANGED'):
                self.store.record_result(task['task_id'], receipt, receipt_sha)
        self.assertEqual(before, (self.store.get(task['task_id']), self.store.events(task['task_id']),
                                  self.store.output_attempts(task['task_id'])))
        # Genuine re-import of the same output is still valid and leaves the original chain authoritative.
        receipt = self.receipt(task, 'honest-retry')
        self.assertEqual(self.store.record_result(task['task_id'], receipt, digest(receipt)), task)
        self.assertEqual(Path(task['result_receipt_path']).read_bytes(), original_receipt_bytes)
        original_bytes = self.adapter.output.read_bytes()
        self.adapter.output.write_bytes(b'Different bytes at the same existing result path.\n')
        before = (self.store.get(task['task_id']), self.store.events(task['task_id']),
                  self.store.output_attempts(task['task_id']))
        with self.assertRaisesRegex(Conflict, 'RESULT_HASH_MISMATCH'):
            self.store.record_result(task['task_id'], task['result_receipt_path'],
                                      task['result_receipt_sha256'])
        self.assertEqual(before, (self.store.get(task['task_id']), self.store.events(task['task_id']),
                                  self.store.output_attempts(task['task_id'])))
        self.adapter.output.write_bytes(original_bytes)
        self.assertEqual(len(self.adapter.submits), 1)

    def test_g3_explicit_recreation_has_new_identity_even_if_bytes_are_equal(self):
        first = self.verified('take-one')
        first_candidate = self.candidate('take-one')
        first_gate = self.accept(first, first_candidate, 'take-one')
        second = self.ready('take-two')  # Explicit new creation intent, not unknown-submit recovery.
        self.assertNotEqual(first['task_id'], second['task_id'])
        self.assertNotEqual(first['provider_task_id'], second['provider_task_id'])
        self.assertNotEqual(first['provider_output_id'], second['provider_output_id'])
        self.assertEqual(self.adapter.submits[0][1], self.adapter.submits[1][1])
        with self.assertRaisesRegex(Conflict, 'RESULT_RECEIPT_ATTEMPT_MISMATCH'):
            self.store.record_result(second['task_id'], first['result_receipt_path'],
                                      first['result_receipt_sha256'])
        receipt = self.receipt(second, 'take-two-download')
        second = self.store.record_result(second['task_id'], receipt, digest(receipt))
        second_candidate = self.candidate('take-two')
        self.assertEqual(first['result_sha256'], second['result_sha256'])
        self.assertEqual(first_candidate.read_bytes(), second_candidate.read_bytes())
        old_review = self.root / 'take-one-review.json'
        with self.assertRaisesRegex(GenerationError, 'REVIEW_RECORD_INVALID'):
            self.store.record_review(second['task_id'], second_candidate, digest(second_candidate),
                                      old_review, digest(old_review))
        with self.assertRaisesRegex(NotReady, 'EXPLICIT_ACCEPTED_REVIEW_REQUIRED'):
            self.store.adoption_gate(second['task_id'], self.work, second_candidate, digest(second_candidate))
        second_gate = self.accept(second, second_candidate, 'take-two')
        self.assertEqual(first_gate['candidate_sha256'], second_gate['candidate_sha256'])
        self.assertNotEqual(first_gate['task_id'], second_gate['task_id'])
        self.assertNotEqual(first_gate['result_receipt_sha256'], second_gate['result_receipt_sha256'])
        self.assertEqual(len(self.adapter.submits), 2)

    def test_g4_unknown_and_not_found_hold_original_key_without_automatic_recreation(self):
        for lookup in (True, False):
            with self.subTest(lookup=lookup):
                folder = self.root / ('lookup-' + str(lookup))
                folder.mkdir()
                self.store = GenerationStore(folder / 'tasks.sqlite3')
                self.store.create_budget('offline', 'USD', 1000)
                adapter = SyntheticAdapter(folder, lost_ack=True, lookup=lookup)
                task = self.create('unknown')
                self.assertEqual(self.store.submit_once(task['task_id'], adapter)['state'],
                                 'SUBMISSION_UNKNOWN')
                for observed in ('UNKNOWN', 'NOT_FOUND'):
                    adapter.observed = observed
                    self.store = GenerationStore(self.store.path)
                    self.assertEqual(self.create('unknown')['task_id'], task['task_id'])
                    self.store.submit_once(task['task_id'], adapter)
                    status = self.store.poll(task['task_id'], adapter)
                    self.assertEqual(status['state'], 'SUBMISSION_UNKNOWN')
                    self.assertEqual(status['reserved_micros'], 50)
                    if not lookup:
                        self.assertEqual(status['recovery'], 'QUERY_UNAVAILABLE_HOLD_NO_RESUBMIT')
                with sqlite3.connect(self.store.path) as db:
                    self.assertEqual(db.execute('SELECT idempotency_key FROM tasks').fetchall(),
                                     [('unknown',)])
                self.assertEqual([call[0] for call in adapter.submits], ['unknown'])
                self.assertEqual(len(adapter.queries), 2 if lookup else 0)
                self.assertEqual(sum(e['action'] == 'submit_boundary'
                                     for e in self.store.events(task['task_id'])), 1)


if __name__ == '__main__':
    unittest.main()
