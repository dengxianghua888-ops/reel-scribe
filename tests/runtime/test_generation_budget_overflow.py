"""Offline billing observations must preserve integer accounting atomically."""
import hashlib
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from generation_tasks import (GenerationError, GenerationStore, ProviderCapabilities,
                              ProviderObservation, SubmissionAck)


class BillingAdapter:
    provider_id = 'fixture'

    def __init__(self, hard_cap=False):
        self.hard_cap = hard_cap
        self.cost = 2**62
        self.submits = 0

    def capabilities(self):
        return ProviderCapabilities('USD', self.hard_cap, True)

    def submit(self, payload, **kwargs):
        self.submits += 1
        return SubmissionAck('task/' + payload['name'], 'RUNNING')

    def query(self, **kwargs):
        return ProviderObservation('FAILED', provider_task_id=kwargs['provider_task_id'],
                                   actual_cost_micros=self.cost)


class GenerationBudgetOverflowTests(unittest.TestCase):
    def make_running_tasks(self, directory, adapter):
        store = GenerationStore(Path(directory) / 'tasks.sqlite3')
        store.create_budget('shared', 'USD', 100)
        tasks = []
        # Both sends happen before either observed charge consumes the budget.
        for name in ('first', 'second'):
            task = store.create_task(idempotency_key=name, provider_id='fixture',
                model='model', kind='video', payload={'name': name}, budget_key='shared',
                max_cost_micros=1, work_binding={'work_id': 'work', 'version': 'a' * 64,
                                               'document_sha256': 'b' * 64})
            store.submit_once(task['task_id'], adapter)
            tasks.append(task['task_id'])
        return store, tasks

    def test_terminal_cost_overflow_rolls_back_without_releasing_reservation(self):
        for hard_cap in (False, True):
            with self.subTest(hard_cap=hard_cap), tempfile.TemporaryDirectory() as directory:
                adapter = BillingAdapter(hard_cap)
                store, tasks = self.make_running_tasks(directory, adapter)
                store.poll(tasks[0], adapter)
                before = (store.budget('shared'), store.get(tasks[1]), store.events(tasks[1]))
                with self.assertRaisesRegex(GenerationError, 'BUDGET_ACCOUNTING_OVERFLOW'):
                    store.poll(tasks[1], adapter)
                self.assertEqual(before, (store.budget('shared'), store.get(tasks[1]),
                                          store.events(tasks[1])))
                self.assertEqual(type(store.budget('shared')['spent_micros']), int)
                self.assertEqual(store.budget('shared')['reserved_micros'], 1)
                store.submit_once(tasks[1], adapter)
                self.assertEqual(adapter.submits, 2)

    def test_total_exactly_at_integer_limit_remains_an_integer(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = BillingAdapter()
            store, tasks = self.make_running_tasks(directory, adapter)
            store.poll(tasks[0], adapter)
            adapter.cost -= 1
            store.poll(tasks[1], adapter)
            budget = store.budget('shared')
            self.assertEqual(type(budget['spent_micros']), int)
            self.assertEqual(budget['spent_micros'], 2**63 - 1)
            self.assertEqual(budget['reserved_micros'], 0)

    def test_reopen_and_valid_observation_can_finish_without_resubmit(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = BillingAdapter()
            store, tasks = self.make_running_tasks(directory, adapter)
            store.poll(tasks[0], adapter)
            with self.assertRaisesRegex(GenerationError, 'BUDGET_ACCOUNTING_OVERFLOW'):
                store.poll(tasks[1], adapter)
            reopened = GenerationStore(store.path)
            self.assertEqual(reopened.get(tasks[1])['state'], 'RUNNING')
            adapter.cost = 1
            self.assertEqual(reopened.poll(tasks[1], adapter)['state'], 'FAILED')
            self.assertEqual(reopened.budget('shared')['spent_micros'], 2**62 + 1)
            self.assertEqual(reopened.budget('shared')['reserved_micros'], 0)
            self.assertEqual(adapter.submits, 2)

    def test_invalid_reported_cost_keeps_existing_state_and_reservation(self):
        for value in (-1, True, 1.5, '1', 2**63):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as directory:
                adapter = BillingAdapter()
                store, tasks = self.make_running_tasks(directory, adapter)
                adapter.cost = value
                before = (store.budget('shared'), store.get(tasks[0]), store.events(tasks[0]))
                with self.assertRaisesRegex(GenerationError, 'ACTUAL_COST_INVALID'):
                    store.poll(tasks[0], adapter)
                self.assertEqual(before, (store.budget('shared'), store.get(tasks[0]),
                                          store.events(tasks[0])))

    def test_unknown_cost_or_malformed_observation_never_releases_reservation(self):
        with tempfile.TemporaryDirectory() as directory:
            adapter = BillingAdapter()
            store, tasks = self.make_running_tasks(directory, adapter)
            adapter.cost = None
            result = store.poll(tasks[0], adapter)
            self.assertEqual(result['state'], 'FAILED')
            self.assertEqual(result['cost_status'], 'UNKNOWN')
            adapter.query = lambda **kwargs: {'state': 'FAILED', 'actual_cost_micros': 0}
            result = store.poll(tasks[1], adapter)
            self.assertEqual(result['state'], 'RUNNING')
            self.assertEqual(result['last_error'], 'GenerationError')
            self.assertEqual(store.budget('shared')['reserved_micros'], 2)
            self.assertEqual(store.budget('shared')['spent_micros'], 0)
            self.assertEqual(adapter.submits, 2)

    def test_invalid_result_availability_preserves_ledger_and_original_task_recovery(self):
        for state in ('RUNNING', 'SUCCEEDED', 'FAILED'):
            for value in ('false', 'true', 0, 1, 0.0, [], {}, b'false'):
                with self.subTest(state=state, value=value), tempfile.TemporaryDirectory() as directory:
                    adapter = BillingAdapter()
                    store, tasks = self.make_running_tasks(directory, adapter)
                    queries = []

                    def invalid_query(**kwargs):
                        queries.append(kwargs['provider_task_id'])
                        return ProviderObservation(state, provider_task_id=kwargs['provider_task_id'],
                            result_available=value, actual_cost_micros=1)

                    adapter.query = invalid_query
                    before = (store.budget('shared'), store.get(tasks[0]), store.events(tasks[0]))
                    with self.assertRaisesRegex(GenerationError, '^PROVIDER_RESULT_AVAILABILITY_INVALID$'):
                        store.poll(tasks[0], adapter)
                    self.assertEqual(before, (store.budget('shared'), store.get(tasks[0]),
                                              store.events(tasks[0])))

                    reopened = GenerationStore(store.path)

                    def valid_query(**kwargs):
                        queries.append(kwargs['provider_task_id'])
                        return ProviderObservation('SUCCEEDED',
                            provider_task_id=kwargs['provider_task_id'], result_available=False,
                            actual_cost_micros=1)

                    adapter.query = valid_query
                    self.assertEqual(reopened.poll(tasks[0], adapter)['state'], 'COMPLETED_EMPTY')
                    self.assertEqual(queries, ['task/first', 'task/first'])
                    self.assertEqual(reopened.budget('shared')['reserved_micros'], 1)
                    self.assertEqual(reopened.budget('shared')['spent_micros'], 1)
                    reopened.submit_once(tasks[0], adapter)
                    self.assertEqual(adapter.submits, 2)  # Only the two original fixture tasks.

    def test_boolean_and_unknown_output_observations_keep_existing_semantics(self):
        for available, complete, expected in ((None, False, 'OUTPUT_UNKNOWN'),
                (True, False, 'OUTPUT_UNKNOWN'), (False, False, 'COMPLETED_EMPTY'),
                (True, True, 'AWAITING_RESULT')):
            with self.subTest(available=available, complete=complete), tempfile.TemporaryDirectory() as directory:
                adapter = BillingAdapter()
                store, tasks = self.make_running_tasks(directory, adapter)
                response = Path(directory) / 'response.json'
                response.write_bytes(b'{"synthetic":true}')
                adapter.query = lambda **kwargs: ProviderObservation('SUCCEEDED',
                    provider_task_id=kwargs['provider_task_id'], result_available=available,
                    actual_cost_micros=1, output_id='output/one' if complete else None,
                    response_path=str(response) if complete else None,
                    response_sha256=hashlib.sha256(response.read_bytes()).hexdigest() if complete else None)
                self.assertEqual(store.poll(tasks[0], adapter)['state'], expected)
                unresolved = expected == 'OUTPUT_UNKNOWN'
                self.assertEqual(store.budget('shared')['reserved_micros'], 2 if unresolved else 1)
                self.assertEqual(store.budget('shared')['spent_micros'], 0 if unresolved else 1)


if __name__ == '__main__':
    unittest.main()
