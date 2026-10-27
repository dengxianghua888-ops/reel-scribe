"""Offline G1-G4 intent contracts; synthetic bytes are not media acceptance."""
import copy
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
import editing_runtime
import generation_dispatch
import work_ops


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


class SyntheticMediaTools:
    """Declared fixture metadata for Work CAS only; no probe/encode claim."""
    def probe(self, path):
        return {'duration': 1, 'streams': [{'codec_type': 'video', 'index': 0}]}

    def selected_video_clock(self, path, media, start, end):
        return {'stream_index': 0, 'stream_selector': 'v:0', 'time_base': '1/25',
                'observed_intervals': [['0', '1']], 'playback_intervals': [['0', '1']],
                'max_observed_frame_duration': '1/25', 'observation_window': ['0', '1'],
                'observation': 'Synthetic fixture declaration; not decoded media'}


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

    def ready(self, key, *, payload=None):
        task = self.create(key, payload=payload)
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

    def verified(self, key, *, payload=None):
        task = self.ready(key, payload=payload)
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

    def work_fixture(self):
        """Real Work SQLite/CAS with declared synthetic clock metadata, no rendered media."""
        tools = SyntheticMediaTools()
        base_asset = self.root / 'work-base.bin'
        base_asset.write_bytes(b'Declared synthetic Work input; not decoded media.\n')
        document = {'schema': 'work-document/1', 'plan': {
            'schema': 'execution-plan/1', 'fps': '25', 'width': 64, 'height': 64,
            'fit': 'contain', 'sources': {'source': {'path': str(base_asset), 'sha256': digest(base_asset)}},
            'clips': [{'id': 'clip', 'source_id': 'source', 'start': 0, 'end': 1, 'gain_db': 0}]},
            'captions': {}, 'caption_style': None, 'audio_tracks': {}, 'style_bindings': {},
            'notes': {'manual-note': 'Keep this current Work note.'}, 'visual_layers': {}}
        store = self.root / 'current-work.sqlite3'
        operations = []

        def call(action, **kwargs):
            output = self.root / ('work-op-' + str(len(operations)))
            output.mkdir()
            operations.append(output)
            return work_ops.work_version({'operation': 'work-version', 'action': action,
                'store': str(store), **kwargs}, output, tools)

        def head():
            db = work_ops.connect(store)
            try:
                return work_ops.load(db), db.execute('SELECT COUNT(*) FROM revisions').fetchone()[0]
            finally:
                db.close()

        state = call('init', work_id='current-work', document=document,
                     author='agent', message='Synthetic Work CAS fixture')
        return {'tools': tools, 'document': document, 'store': store,
                'call': call, 'head': head, 'state': state}

    @staticmethod
    def work_token(state):
        return {key: state[key] for key in ('work_id', 'version', 'document_sha256')}

    @staticmethod
    def scope(*, notes=(), sources=(), clips=()):
        return {'clip_ids': list(clips), 'source_ids': list(sources), 'caption_ids': [],
                'audio_ids': [], 'style_keys': [], 'note_keys': list(notes), 'output_fields': [],
                'caption_style': False, 'freeze_positions': ['clip'], 'freeze_duration': True}

    def work_candidate(self, fixture, document, name, scope):
        output = self.root / name
        output.mkdir()
        work_ops.timeline_revise({'operation': 'timeline-revise',
            'base_version': fixture['state']['version'], 'document': fixture['document'],
            'expected_document_sha256': fixture['state']['document_sha256'],
            'candidate': document, 'scope': scope}, output, fixture['tools'])
        return output / 'candidate.json'

    def reuse_fixture(self):
        task = self.verified('reuse-source')
        origin_candidate = self.candidate('reuse-source')
        self.accept(task, origin_candidate, 'reuse-source')
        origin_review = self.root / 'reuse-source-review.json'
        target = self.work_fixture()
        document = copy.deepcopy(target['document'])
        document['plan']['sources']['source'] = {'path': str(self.adapter.output),
                                                 'sha256': task['result_sha256']}
        document['notes']['reuse-origin'] = {'task_id': task['task_id'],
                                             'receipt_sha256': task['result_receipt_sha256']}
        candidate = self.work_candidate(target, document, 'reuse-target-candidate',
            self.scope(sources=['source'], clips=['clip'], notes=['reuse-origin']))
        proof_body = {'schema': 'generation-reuse-review/1', 'task_id': task['task_id'],
            'result_sha256': task['result_sha256'], 'result_receipt_sha256': task['result_receipt_sha256'],
            'origin_candidate_sha256': digest(origin_candidate), 'origin_review_sha256': digest(origin_review),
            'target_work': self.work_token(target['state']), 'candidate_sha256': digest(candidate),
            'decision': 'ACCEPT', 'rationale': 'Synthetic current-use review for this target Work only.'}
        proof = write_json(self.root / 'reuse-review.json', proof_body)
        reuse = {key: proof_body[key] for key in ('result_sha256', 'result_receipt_sha256',
            'origin_candidate_sha256', 'origin_review_sha256')}
        reuse.update(intent='reuse-verified-result', review_path=str(proof), review_sha256=digest(proof))
        return {'task': task, 'origin_candidate': origin_candidate, 'origin_review': origin_review,
                'target': target, 'candidate': candidate, 'proof': proof,
                'proof_body': proof_body, 'reuse': reuse}

    def ledger(self):
        with sqlite3.connect(self.store.path) as db:
            return {name: db.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall()
                    for name in ('budgets', 'tasks', 'task_events', 'candidate_reviews', 'output_attempts')}

    def reuse_gate(self, fixture, *, reuse=None, current_work=None):
        return self.store.adoption_gate(fixture['task']['task_id'],
            current_work or self.work_token(fixture['target']['state']),
            fixture['candidate'], fixture['proof_body']['candidate_sha256'],
            reuse=fixture['reuse'] if reuse is None else reuse)

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
        submits_before_reuse = len(self.adapter.submits)
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
        current_candidate = write_json(self.root / 'current-work-candidate.json', {
            'schema': 'work-candidate/1', 'base_version': current_work['version'],
            'base_document_sha256': current_work['document_sha256'],
            'document': {'source': {'path': str(self.adapter.output), 'sha256': task['result_sha256']}}})
        current_review = self.review(task, current_candidate, 'current-work')
        self.store.record_review(task['task_id'], current_candidate, digest(current_candidate),
                                  current_review, digest(current_review))
        # Even a fresh candidate/review bound to another current Work cannot use the old task gate.
        # This is an explicit contract gap, not a successful cross-Work adoption.
        with self.assertRaisesRegex(Conflict, 'WORK_HEAD_CHANGED'):
            self.store.adoption_gate(task['task_id'], current_work,
                                      current_candidate, digest(current_candidate))
        incomplete_work = dict(self.work)
        incomplete_work.pop('version')
        with self.assertRaisesRegex(GenerationError, 'CURRENT_WORK_BINDING_INVALID'):
            self.store.adoption_gate(task['task_id'], incomplete_work, candidate, digest(candidate))
        for field in ('provider_response_path', 'result_receipt_path'):
            with self.subTest(missing_origin=field):
                original = Path(task[field])
                displaced = original.with_name(original.name + '.temporarily-missing')
                original.rename(displaced)
                try:
                    with self.assertRaisesRegex(Conflict, 'OUTPUT_IDENTITY_CHAIN_HASH_CHANGED'):
                        self.store.adoption_gate(task['task_id'], self.work, candidate, digest(candidate))
                finally:
                    displaced.rename(original)
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
        self.assertEqual(len(self.adapter.submits) - submits_before_reuse, 0)

    def test_g3_explicit_recreation_has_new_identity_even_if_bytes_are_equal(self):
        for label, seed in (('no-seed', None), ('fixed-seed', 8128)):
            with self.subTest(seed=seed):
                payload = {'prompt': 'synthetic prompt'}
                if seed is not None:
                    payload['seed'] = seed
                before = len(self.adapter.submits)
                first_key, second_key = label + '-one', label + '-two'
                first = self.verified(first_key, payload=payload)
                first_candidate = self.candidate(first_key)
                first_gate = self.accept(first, first_candidate, first_key)
                # Explicit new creation intent after the first verified output, not recovery.
                second = self.ready(second_key, payload=payload)
                self.assertNotEqual(first['task_id'], second['task_id'])
                self.assertNotEqual(first['provider_task_id'], second['provider_task_id'])
                self.assertNotEqual(first['provider_output_id'], second['provider_output_id'])
                self.assertEqual(self.adapter.submits[before][1], payload)
                self.assertEqual(self.adapter.submits[before + 1][1], payload)
                with self.assertRaisesRegex(Conflict, 'RESULT_RECEIPT_ATTEMPT_MISMATCH'):
                    self.store.record_result(second['task_id'], first['result_receipt_path'],
                                              first['result_receipt_sha256'])
                receipt = self.receipt(second, second_key + '-download')
                second = self.store.record_result(second['task_id'], receipt, digest(receipt))
                second_candidate = self.candidate(second_key)
                self.assertEqual(first['result_sha256'], second['result_sha256'])
                self.assertEqual(first_candidate.read_bytes(), second_candidate.read_bytes())
                old_review = self.root / (first_key + '-review.json')
                with self.assertRaisesRegex(GenerationError, 'REVIEW_RECORD_INVALID'):
                    self.store.record_review(second['task_id'], second_candidate, digest(second_candidate),
                                              old_review, digest(old_review))
                with self.assertRaisesRegex(NotReady, 'EXPLICIT_ACCEPTED_REVIEW_REQUIRED'):
                    self.store.adoption_gate(second['task_id'], self.work,
                                              second_candidate, digest(second_candidate))
                second_gate = self.accept(second, second_candidate, second_key)
                self.assertEqual(first_gate['candidate_sha256'], second_gate['candidate_sha256'])
                self.assertNotEqual(first_gate['task_id'], second_gate['task_id'])
                self.assertNotEqual(first_gate['result_receipt_sha256'], second_gate['result_receipt_sha256'])
                self.assertEqual(len(self.adapter.submits) - before, 2)

    def test_g1_unknown_and_not_found_hold_original_key_without_automatic_recreation(self):
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

    def test_g4_changed_result_receipt_candidate_review_and_work_head_are_conflicts(self):
        fixture = self.work_fixture()
        self.work = self.work_token(fixture['state'])
        task = self.verified('guard')
        candidate = self.candidate('guard')
        candidate_sha = digest(candidate)
        self.accept(task, candidate, 'guard')

        def ledger():
            with sqlite3.connect(self.store.path) as db:
                return {name: db.execute('SELECT * FROM ' + name + ' ORDER BY rowid').fetchall()
                        for name in ('budgets', 'tasks', 'task_events', 'candidate_reviews', 'output_attempts')}

        for path, error in [(self.adapter.output, 'OUTPUT_IDENTITY_CHAIN_HASH_CHANGED'),
                (Path(task['result_receipt_path']), 'OUTPUT_IDENTITY_CHAIN_HASH_CHANGED'),
                (candidate, 'CANDIDATE_HASH_MISMATCH'),
                (self.root / 'guard-review.json', 'ACCEPTED_REVIEW_HASH_CHANGED')]:
            with self.subTest(changed=path.name):
                original = path.read_bytes()
                before = ledger(), fixture['head']()
                path.write_bytes(original + b' ')
                try:
                    with self.assertRaisesRegex(Conflict, error):
                        self.store.adoption_gate(task['task_id'], self.work, candidate, candidate_sha)
                finally:
                    path.write_bytes(original)
                self.assertEqual((ledger(), fixture['head']()), before)
        changed = copy.deepcopy(fixture['document'])
        changed['notes']['later-edit'] = 'A later legitimate Work edit.'
        later = self.work_candidate(fixture, changed, 'later-work-candidate',
                                    self.scope(notes=['later-edit']))
        current = fixture['call']('commit', expected_version=fixture['state']['version'],
            candidate={'path': str(later), 'sha256': digest(later)},
            message='Later current Work revision', author='agent')
        self.assertEqual(current['sequence'], 2)
        before = ledger(), fixture['head']()
        with self.assertRaisesRegex(Conflict, 'WORK_HEAD_CHANGED'):
            self.store.adoption_gate(task['task_id'], self.work_token(current), candidate, candidate_sha)
        with self.assertRaisesRegex(editing_runtime.ContractError, 'WORK_VERSION_CONFLICT'):
            fixture['call']('commit', expected_version=fixture['state']['version'],
                candidate={'path': str(later), 'sha256': digest(later)},
                message='Stale candidate must not move the head', author='agent')
        self.assertEqual((ledger(), fixture['head']()), before)
        self.assertEqual(len(self.adapter.submits), 1)

    def test_g2_explicit_reuse_preserves_origin_and_uses_current_work_cas(self):
        fixture = self.reuse_fixture()
        original = self.ledger()
        original_files = {path: Path(path).read_bytes() for path in (
            fixture['task']['provider_response_path'], fixture['task']['result_receipt_path'],
            str(fixture['origin_review']))}
        before_head = fixture['target']['head']()
        submissions = len(self.adapter.submits)
        gate = self.reuse_gate(fixture)
        self.assertEqual(gate['status'], 'READY_FOR_WORK_VERSION_CAS_ONLY')
        self.assertFalse(gate['publishable'])
        self.assertEqual(gate['expected_work'], self.work_token(fixture['target']['state']))
        for _ in range(3):
            self.store = GenerationStore(self.store.path)
            self.assertEqual(self.reuse_gate(fixture), gate)
        after = self.ledger()
        for table in original:
            if table != 'task_events':
                self.assertEqual(after[table], original[table])
        checks = [event for event in self.store.events(fixture['task']['task_id'])
                  if event['action'] == 'reuse_gate_checked']
        self.assertEqual(len(checks), 1)
        self.assertEqual(len(after['task_events']), len(original['task_events']) + 1)
        self.assertEqual(fixture['target']['head'](), before_head)
        for path, data in original_files.items():
            self.assertEqual(Path(path).read_bytes(), data)
        self.assertEqual(len(self.adapter.submits), submissions)
        adopted = fixture['target']['call']('commit', expected_version=gate['expected_work']['version'],
            candidate={'path': str(fixture['candidate']), 'sha256': digest(fixture['candidate'])},
            author='agent', message='Explicit fixed-SHA reuse in the target Work')
        actual = fixture['target']['call']('read')
        self.assertEqual(adopted['version'], actual['version'])
        self.assertEqual(actual['document']['plan']['sources']['source']['sha256'], fixture['task']['result_sha256'])
        self.assertEqual(actual['document']['notes']['manual-note'], 'Keep this current Work note.')
        before = self.ledger(), fixture['target']['head']()
        with self.assertRaisesRegex(Conflict, 'CANDIDATE_BASE_CONFLICT'):
            self.reuse_gate(fixture, current_work=self.work_token(actual))
        with self.assertRaisesRegex(editing_runtime.ContractError, 'WORK_VERSION_CONFLICT'):
            fixture['target']['call']('commit', expected_version=gate['expected_work']['version'],
                candidate={'path': str(fixture['candidate']), 'sha256': digest(fixture['candidate'])},
                author='agent', message='Stale reuse must not move the head')
        self.assertEqual((self.ledger(), fixture['target']['head']()), before)
        self.assertEqual(len(self.adapter.submits), submissions)

    def test_g2_explicit_reuse_rejects_null_unknown_fields_and_wrong_pins_without_writes(self):
        fixture = self.reuse_fixture()
        cases = [(None, 'REUSE_INTENT_INVALID'),
                 ({**fixture['reuse'], 'extra': True}, 'REUSE_INTENT_INVALID'),
                 ({**fixture['reuse'], 'review_path': '/invalid' + chr(0) + '/review.json'},
                  'REUSE_INTENT_INVALID'),
                 ({**fixture['reuse'], 'result_sha256': 'f' * 64}, 'REUSE_RESULT_PIN_MISMATCH'),
                 ({**fixture['reuse'], 'result_receipt_sha256': 'f' * 64}, 'REUSE_RESULT_PIN_MISMATCH'),
                 ({**fixture['reuse'], 'origin_review_sha256': 'f' * 64}, 'ORIGIN_ACCEPTED_REVIEW_REQUIRED')]
        for reuse, error in cases:
            with self.subTest(reuse=reuse):
                before = self.ledger(), fixture['target']['head']()
                with self.assertRaisesRegex(GenerationError, error):
                    self.store.adoption_gate(fixture['task']['task_id'],
                        self.work_token(fixture['target']['state']), fixture['candidate'],
                        digest(fixture['candidate']), reuse=reuse)
                self.assertEqual((self.ledger(), fixture['target']['head']()), before)
        request = {'operation': 'generation-task', 'action': 'adoption-gate', 'store': str(self.store.path),
            'task_id': fixture['task']['task_id'], 'current_work': self.work_token(fixture['target']['state']),
            'candidate_path': str(fixture['candidate']), 'candidate_sha256': digest(fixture['candidate']),
            'reuse': None}
        before = self.ledger(), fixture['target']['head']()
        with self.assertRaisesRegex(GenerationError, 'REUSE_INTENT_INVALID'):
            generation_dispatch.execute(request)
        self.assertEqual((self.ledger(), fixture['target']['head']()), before)

    def test_g2_reuse_audit_binds_proof_bytes_and_ignores_safe_locator_changes(self):
        fixture = self.reuse_fixture()
        first = self.reuse_gate(fixture)
        copied_candidate = self.root / 'relocated-candidate.json'
        copied_candidate.write_bytes(fixture['candidate'].read_bytes())
        copied_proof = self.root / 'relocated-review.json'
        copied_proof.write_bytes(fixture['proof'].read_bytes())
        moved = {**fixture, 'candidate': copied_candidate,
                 'reuse': {**fixture['reuse'], 'review_path': str(copied_proof)}}
        self.assertEqual(self.reuse_gate(moved), first)
        checks = lambda: [e for e in self.store.events(fixture['task']['task_id'])
                          if e['action'] == 'reuse_gate_checked']
        self.assertEqual(len(checks()), 1)
        replacement = {**fixture['proof_body'], 'rationale': 'A different explicit current-use review.'}
        write_json(copied_proof, replacement)
        moved['reuse']['review_sha256'] = digest(copied_proof)
        second = self.reuse_gate(moved)
        self.assertNotEqual(first['reuse_audit_key'], second['reuse_audit_key'])
        self.assertEqual(len(checks()), 2)
        before = self.ledger(), fixture['target']['head']()
        copied_proof.write_bytes(fixture['proof'].read_bytes())
        with self.assertRaisesRegex(Conflict, 'REUSE_REVIEW_HASH_CHANGED'):
            self.reuse_gate(moved)
        self.assertEqual((self.ledger(), fixture['target']['head']()), before)
        self.assertEqual(len(self.adapter.submits), 1)

    def test_g2_reuse_existing_audit_never_bypasses_changed_or_missing_evidence(self):
        fixture = self.reuse_fixture()
        self.reuse_gate(fixture)
        target = self.work_token(fixture['target']['state'])
        invalid_targets = [{**target, 'work_id': True}, {**target, 'version': 'bad'},
            {**target, 'document_sha256': 123}, {**target, 'extra': 'not allowed'},
            {key: value for key, value in target.items() if key != 'version'}]
        for invalid in invalid_targets:
            with self.subTest(invalid_target=invalid):
                before = self.ledger(), fixture['target']['head']()
                with self.assertRaisesRegex(GenerationError, 'REUSE_INTENT_INVALID'):
                    self.reuse_gate(fixture, current_work=invalid)
                self.assertEqual((self.ledger(), fixture['target']['head']()), before)
        evidence = [(self.adapter.output, 'OUTPUT_IDENTITY_CHAIN_HASH_CHANGED'),
            (Path(fixture['task']['provider_response_path']), 'OUTPUT_IDENTITY_CHAIN_HASH_CHANGED'),
            (Path(fixture['task']['result_receipt_path']), 'OUTPUT_IDENTITY_CHAIN_HASH_CHANGED'),
            (fixture['origin_review'], 'ORIGIN_REVIEW_HASH_CHANGED'),
            (fixture['proof'], 'REUSE_REVIEW_HASH_CHANGED'),
            (fixture['candidate'], 'CANDIDATE_HASH_MISMATCH')]
        for path, error in evidence:
            for missing in (False, True):
                with self.subTest(evidence=path.name, missing=missing):
                    original = path.read_bytes()
                    before = self.ledger(), fixture['target']['head']()
                    if missing:
                        path.unlink()  # Only this temporary fixture file; restored below.
                    else:
                        path.write_bytes(original + b' ')
                    try:
                        with self.assertRaisesRegex(Conflict, error):
                            self.reuse_gate(fixture)
                    finally:
                        path.write_bytes(original)
                    self.assertEqual((self.ledger(), fixture['target']['head']()), before)
        proof_bytes = fixture['proof'].read_bytes()
        for changes, error in [({'schema': 'generation-candidate-review/1'}, 'REUSE_REVIEW_INVALID'),
                ({'rationale': ''}, 'REUSE_REVIEW_INVALID'),
                ({'decision': 'REJECT'}, 'EXPLICIT_REUSE_ACCEPTED_REVIEW_REQUIRED'),
                ({'candidate_sha256': 'f' * 64}, 'REUSE_REVIEW_BINDING_MISMATCH'),
                ({'target_work': {**target, 'work_id': 'different-work'}}, 'REUSE_REVIEW_BINDING_MISMATCH'),
                ({'result_sha256': 'f' * 64}, 'REUSE_REVIEW_BINDING_MISMATCH')]:
            with self.subTest(proof_change=changes):
                before = self.ledger(), fixture['target']['head']()
                write_json(fixture['proof'], {**fixture['proof_body'], **changes})
                revised = {**fixture['reuse'], 'review_sha256': digest(fixture['proof'])}
                try:
                    with self.assertRaisesRegex(GenerationError, error):
                        self.reuse_gate(fixture, reuse=revised)
                finally:
                    fixture['proof'].write_bytes(proof_bytes)
                self.assertEqual((self.ledger(), fixture['target']['head']()), before)
        # A candidate can have valid bytes yet no longer match this Work base or source pin.
        original_candidate = fixture['candidate'].read_bytes()
        for change, error in [('base', 'CANDIDATE_BASE_CONFLICT'),
                              ('source', 'CANDIDATE_DOES_NOT_REFERENCE_VERIFIED_RESULT')]:
            with self.subTest(candidate_change=change):
                body = json.loads(original_candidate)
                if change == 'base':
                    body['base_version'] = 'f' * 64
                else:
                    body['document']['plan']['sources'] = fixture['target']['document']['plan']['sources']
                    body['document']['notes'].pop('reuse-origin')
                before = self.ledger(), fixture['target']['head']()
                write_json(fixture['candidate'], body)
                changed_proof = {**fixture['proof_body'], 'candidate_sha256': digest(fixture['candidate'])}
                write_json(fixture['proof'], changed_proof)
                revised = {**fixture['reuse'], 'review_sha256': digest(fixture['proof'])}
                changed_fixture = {**fixture, 'proof_body': changed_proof}
                try:
                    with self.assertRaisesRegex(Conflict, error):
                        self.reuse_gate(changed_fixture, reuse=revised)
                finally:
                    fixture['candidate'].write_bytes(original_candidate)
                    fixture['proof'].write_bytes(proof_bytes)
                self.assertEqual((self.ledger(), fixture['target']['head']()), before)
        self.assertEqual(len(self.adapter.submits), 1)

    def test_g2_reuse_rechecks_proof_candidate_and_origin_review_at_audit_boundary(self):
        fixture = self.reuse_fixture()
        self.reuse_gate(fixture)
        verify = GenerationStore._verify_result_chain
        for path, error in [(fixture['proof'], 'REUSE_REVIEW_HASH_CHANGED'),
                (fixture['candidate'], 'CANDIDATE_HASH_MISMATCH'),
                (fixture['origin_review'], 'ORIGIN_REVIEW_HASH_CHANGED')]:
            with self.subTest(changed_during_final_check=path.name):
                original = path.read_bytes()
                calls = []

                def mutate_after_chain(task, db):
                    verify(task, db)
                    calls.append(True)
                    if len(calls) == 2:
                        path.write_bytes(original + b' ')

                before = self.ledger(), fixture['target']['head']()
                try:
                    with patch.object(GenerationStore, '_verify_result_chain', side_effect=mutate_after_chain):
                        with self.assertRaisesRegex(Conflict, error):
                            self.reuse_gate(fixture)
                finally:
                    path.write_bytes(original)
                self.assertEqual(len(calls), 2)
                self.assertEqual((self.ledger(), fixture['target']['head']()), before)
        self.assertEqual(len(self.adapter.submits), 1)


if __name__ == '__main__':
    unittest.main()
