"""Offline adapter-contract tests: no network, provider, or real spend."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "runtime"))
from generation_tasks import GenerationStore, ProviderCapabilities, SubmissionAck, ProviderObservation


class TaskIdOnlyAdapter:
    provider_id = "fixture"

    def __init__(self, task_id):
        self.task_id = task_id
        self.submits = 0
        self.queries = []

    def capabilities(self):
        return ProviderCapabilities("USD", True, False, query_by_task_id=True)

    def submit(self, payload, *, idempotency_key, max_cost_micros):
        self.submits += 1
        return SubmissionAck(self.task_id, "QUEUED")

    def query(self, *, idempotency_key, provider_task_id):
        self.queries.append(provider_task_id)
        return ProviderObservation("RUNNING", provider_task_id=self.task_id)


def create(store):
    store.create_budget("b", "USD", 100)
    return store.create_task(idempotency_key="one", provider_id="fixture", model="model",
                             kind="video", payload={"prompt": "synthetic"}, budget_key="b",
                             max_cost_micros=50, work_binding={"work_id": "work",
                             "version": "a" * 64, "document_sha256": "b" * 64})


@pytest.mark.parametrize("provider_id", ["operations/task-123", "projects/p/locations/r/operations/t",
                                         "x" * 129, "x" * 512, "simple-task"])
def test_ack_preserves_external_id_for_task_id_only_recovery(tmp_path, provider_id):
    store = GenerationStore(tmp_path / "tasks.sqlite")
    task = create(store)
    adapter = TaskIdOnlyAdapter(provider_id)
    result = store.submit_once(task["task_id"], adapter)
    assert result["state"] == "QUEUED"
    assert result["provider_task_id"] == provider_id
    assert result["reserved_micros"] == 50
    reopened = GenerationStore(tmp_path / "tasks.sqlite")
    assert reopened.poll(task["task_id"], adapter)["state"] == "RUNNING"
    assert adapter.queries == [provider_id]
    reopened.submit_once(task["task_id"], adapter)
    assert adapter.submits == 1


@pytest.mark.parametrize("provider_id", ["", "bad\nname", "bad\x00name", "bad\x7fname", "x" * 513, 123])
def test_invalid_ack_remains_uncertain_without_resubmission(tmp_path, provider_id):
    store = GenerationStore(tmp_path / "tasks.sqlite")
    task = create(store)
    adapter = TaskIdOnlyAdapter(provider_id)
    result = store.submit_once(task["task_id"], adapter)
    assert result["state"] == "SUBMISSION_UNKNOWN"
    assert result["provider_task_id"] is None
    assert result["reserved_micros"] == 50
    assert store.poll(task["task_id"], adapter)["recovery"] == "QUERY_UNAVAILABLE_HOLD_NO_RESUBMIT"
    store.submit_once(task["task_id"], adapter)
    assert adapter.submits == 1
    assert adapter.queries == []
