"""Bind settlement amounts to the exact UTF-8 bytes checked by their SHA.

All three ledgers use real temporary SQLite files and synthetic clients. The
controlled I/O interleaving replaces real evidence bytes after their first read;
it does not replace hashing, JSON parsing, accounting, or database operations.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from deepseek_text import DeepSeekCallStore, DeepSeekError
from generation_tasks import (Conflict, GenerationError, GenerationStore,
                              ProviderCapabilities, ProviderObservation, SubmissionAck)
from model_text_generic import ModelTextError, TextCallStore, TextProfile


class SyntheticGeneration:
    provider_id = 'offline'

    def __init__(self):
        self.submits = 0

    def capabilities(self):
        return ProviderCapabilities('USD', False, True)

    def submit(self, payload, **kwargs):
        self.submits += 1
        return SubmissionAck('task/' + payload['name'], 'RUNNING')

    def query(self, **kwargs):
        return ProviderObservation('FAILED', provider_task_id=kwargs['provider_task_id'])


class SyntheticText:
    provider_id = 'deepseek'
    base_url = 'https://api.deepseek.com'

    def __init__(self, profile=None):
        self.profile = profile
        self.submits = 0

    def send(self, body):
        self.submits += 1
        return {'synthetic': 'no network or real fees'}


class BillingEvidenceBytesTests(unittest.TestCase):
    kinds = ('generation', 'generic-text', 'legacy-text')

    def fixture(self, root, kind, count=1):
        path = root / 'ledger.sqlite'
        limit = 2**63 - 1
        identities = []
        if kind == 'generation':
            store = GenerationStore(path)
            store.create_budget('b', 'USD', limit)
            client = SyntheticGeneration()
        elif kind == 'generic-text':
            store = TextCallStore(path)
            store.budget_create('b', 'USD', limit)
            profile = TextProfile.from_dict({'profile_id': 'offline', 'provider_id': 'offline',
                'endpoint': 'https://offline.invalid', 'model': 'offline',
                'credential_env': 'OFFLINE_API_KEY', 'allow_custom_endpoint': True})
            client = SyntheticText(profile)
        else:
            store = DeepSeekCallStore(path)
            store.create_budget('b', 'USD', limit)
            client = SyntheticText()
        for index in range(count):
            name = 'call-' + str(index)
            if kind == 'generation':
                task = store.create_task(idempotency_key=name, provider_id='offline', model='offline',
                    kind='video', payload={'name': name}, budget_key='b', max_cost_micros=10,
                    work_binding={'work_id': 'offline', 'version': 'a' * 64,
                                  'document_sha256': 'b' * 64})
                identifier = task['task_id']
                store.submit_once(identifier, client)
                store.poll(identifier, client)
                identity = {'schema': 'generation-billing-evidence/1', 'task_id': identifier,
                    'intent_sha256': task['intent_sha256'], 'provider_id': 'offline', 'model': 'offline'}
            else:
                body = {'messages': [{'role': 'user', 'content': 'synthetic'}], 'max_tokens': 1}
                if kind == 'generic-text':
                    task = store.prepare(name, body, profile, 'b', 10)
                    identity = {'schema': 'model-text-billing-evidence/1',
                        'profile_sha256': task['profile_sha256'], 'provider_id': 'offline',
                        'endpoint': profile.endpoint, 'model': 'offline'}
                else:
                    task = store.prepare(name, dict(body, model='offline'), 'b', 10)
                    identity = {'schema': 'deepseek-billing-evidence/1', 'provider_id': 'deepseek',
                        'endpoint': client.base_url, 'model': 'offline'}
                identifier = task['call_id']
                store.send_once(identifier, client)
                identity.update(call_id=identifier, body_sha256=task['body_sha256'])
            identity.update(currency='USD', source_ref='synthetic 核验记录')
            identities.append((identifier, identity))
        return store, path, client, identities

    @staticmethod
    def evidence(root, identity, amount, name='bill.json'):
        path = root / name
        path.write_bytes(json.dumps(dict(identity, actual_cost_micros=amount),
                                   ensure_ascii=False).encode('utf-8'))
        return path, hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def snapshot(path):
        with sqlite3.connect(path) as db:
            tables = [row[0] for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            return {table: db.execute('SELECT * FROM ' + table + ' ORDER BY rowid').fetchall()
                    for table in tables}

    @staticmethod
    def spent_reserved(path, kind):
        with sqlite3.connect(path) as db:
            table = 'budget' if kind == 'legacy-text' else 'budgets'
            return db.execute('SELECT spent_micros,reserved_micros FROM ' + table).fetchone()

    def test_replacement_after_initial_read_rejects_without_accounting_writes(self):
        for kind in self.kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                store, database, client, items = self.fixture(root, kind)
                identifier, identity = items[0]
                evidence, pinned = self.evidence(root, identity, 9)
                replacement = json.dumps(dict(identity, actual_cost_micros=0),
                                         ensure_ascii=False).encode('utf-8')
                original_open = Path.open
                reads = []
                before = self.snapshot(database)

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
                        if value and not reads:
                            reads.append(value)
                            evidence.write_bytes(replacement)
                        return value

                    def __getattr__(self, name):
                        return getattr(self.stream, name)

                def controlled_open(path, *args, **kwargs):
                    stream = original_open(path, *args, **kwargs)
                    mode = args[0] if args else kwargs.get('mode', 'r')
                    return ReplaceAfterRead(stream) if path == evidence and mode == 'rb' else stream

                with patch.object(Path, 'open', controlled_open):
                    with self.assertRaisesRegex((Conflict, ModelTextError, DeepSeekError),
                                                'BILLING_EVIDENCE_HASH_MISMATCH'):
                        store.settle_cost(identifier, 'first', str(evidence), pinned)
                self.assertEqual(len(reads), 1)
                self.assertNotEqual(hashlib.sha256(evidence.read_bytes()).hexdigest(), pinned)
                self.assertEqual(self.snapshot(database), before)
                self.assertEqual(client.submits, 1)
                # A separately pinned, valid observation can reconcile the same
                # call after reopening. The unknown send is never repeated.
                evidence, corrected = self.evidence(root, identity, 9)
                reopened = type(store)(database)
                result = reopened.settle_cost(identifier, 'first', str(evidence), corrected)
                self.assertEqual(result['actual_cost_micros'], 9)
                self.assertEqual(self.spent_reserved(database, kind), (9, 0))
                self.assertEqual(client.submits, 1)

    def test_initial_hash_mismatch_preserves_every_ledger_table(self):
        for kind in self.kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                store, database, client, items = self.fixture(root, kind)
                identifier, identity = items[0]
                evidence, _ = self.evidence(root, identity, 9)
                before = self.snapshot(database)
                with self.assertRaisesRegex((Conflict, ModelTextError, DeepSeekError),
                                            'BILLING_EVIDENCE_HASH_MISMATCH'):
                    store.settle_cost(identifier, 'first', str(evidence), '0' * 64)
                self.assertEqual(self.snapshot(database), before)
                self.assertEqual(client.submits, 1)

    def test_valid_utf8_replay_correction_and_prior_evidence_binding(self):
        for kind in self.kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                store, database, client, items = self.fixture(root, kind)
                identifier, identity = items[0]
                evidence, pinned = self.evidence(root, identity, 9)
                self.assertFalse(store.settle_cost(identifier, 'first', str(evidence), pinned)['idempotent'])
                before = self.snapshot(database)
                self.assertTrue(store.settle_cost(identifier, 'first', str(evidence), pinned)['idempotent'])
                self.assertEqual(before, self.snapshot(database))
                correction, corrected = self.evidence(root, identity, 2, 'corrected.json')
                result = store.settle_cost(identifier, 'correction', str(correction), corrected)
                self.assertTrue(result['correction'])
                self.assertEqual(self.spent_reserved(database, kind), (2, 0))
                # Modifying an older evidence file must still block a new event.
                evidence.write_text('{}', encoding='utf-8')
                before = self.snapshot(database)
                with self.assertRaisesRegex((Conflict, ModelTextError, DeepSeekError),
                                            'PRIOR_BILLING_EVIDENCE_CHANGED'):
                    store.settle_cost(identifier, 'later', str(correction), corrected)
                self.assertEqual(before, self.snapshot(database))
                self.assertEqual(client.submits, 1)

    def test_overflow_still_rolls_back_and_valid_zero_can_finish(self):
        for kind in self.kinds:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as raw:
                root = Path(raw)
                store, database, client, items = self.fixture(root, kind, count=2)
                first, first_identity = items[0]
                last, last_identity = items[1]
                evidence, pinned = self.evidence(root, first_identity, 2**63 - 1)
                store.settle_cost(first, 'first', str(evidence), pinned)
                other, other_sha = self.evidence(root, last_identity, 1, 'other.json')
                before = self.snapshot(database)
                with self.assertRaisesRegex((GenerationError, ModelTextError, DeepSeekError),
                                            'BUDGET_ACCOUNTING_OVERFLOW'):
                    store.settle_cost(last, 'other', str(other), other_sha)
                self.assertEqual(before, self.snapshot(database))
                other, other_sha = self.evidence(root, last_identity, 0, 'other.json')
                store.settle_cost(last, 'other', str(other), other_sha)
                self.assertEqual(self.spent_reserved(database, kind), (2**63 - 1, 0))
                self.assertEqual(client.submits, 2)


if __name__ == '__main__':
    unittest.main()
