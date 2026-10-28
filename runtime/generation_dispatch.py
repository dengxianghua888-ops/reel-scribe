"""Strict operation adapter for editing_runtime.execute integration.

The production host must inject real provider adapters explicitly. No adapter is
bundled here, so submit/query/cancel cannot accidentally reach a paid service.
"""
from pathlib import Path

from generation_tasks import GenerationError, GenerationStore


FIELDS = {
    "budget-create": {"budget_key", "currency", "limit_micros"},
    "task-create": {"idempotency_key", "provider_id", "model", "kind", "payload",
                    "budget_key", "max_cost_micros", "work_binding"},
    "task-read": {"task_id"},
    "task-events": {"task_id"},
    "billing-events": {"task_id"},
    "billing-record": {"task_id", "event_key", "evidence_path", "evidence_sha256"},
    "output-attempts": {"task_id"},
    "output-attempt-begin": {"task_id", "attempt_key", "source_kind", "source_ref"},
    "output-attempt-fail": {"task_id", "attempt_key", "error_code"},
    "submit": {"task_id"},
    "poll": {"task_id"},
    "cancel": {"task_id"},
    "result-record": {"task_id", "receipt_path", "receipt_sha256"},
    "review-record": {"task_id", "candidate_path", "candidate_sha256",
                      "review_path", "review_sha256"},
    "adoption-gate": {"task_id", "current_work", "candidate_path", "candidate_sha256"},
}


def execute(request, directory=None, tools=None, adapter_registry=None):
    if not isinstance(request, dict) or request.get("operation") != "generation-task":
        raise GenerationError("GENERATION_OPERATION_REQUIRED")
    action = request.get("action")
    if action not in FIELDS:
        raise GenerationError("GENERATION_ACTION_UNSUPPORTED")
    expected = {"operation", "action", "store"} | FIELDS[action]
    optional = {"reuse"} if action == "adoption-gate" else set()
    if not expected <= set(request) or not set(request) <= expected | optional:
        raise GenerationError("GENERATION_REQUEST_FIELDS_INVALID")
    store_path = Path(request["store"])
    if not store_path.is_absolute():
        raise GenerationError("ABSOLUTE_GENERATION_STORE_REQUIRED")
    store = GenerationStore(store_path)
    fields = {key: request[key] for key in FIELDS[action]}
    if "reuse" in request:
        fields["reuse"] = request["reuse"]
    if action == "budget-create":
        return store.create_budget(**fields)
    if action == "task-create":
        return store.create_task(**fields)
    if action == "task-read":
        return store.get(**fields)
    if action == "task-events":
        return {"task_id": fields["task_id"], "events": store.events(**fields)}
    if action == "billing-events":
        return {"task_id": fields["task_id"], "billing_events": store.billing_events(**fields)}
    if action == "billing-record":
        return store.settle_cost(**fields)
    if action == "output-attempts":
        return {"task_id": fields["task_id"], "output_attempts": store.output_attempts(**fields)}
    if action == "output-attempt-begin":
        return store.begin_output_attempt(**fields)
    if action == "output-attempt-fail":
        return store.fail_output_attempt(**fields)
    if action in ("submit", "poll", "cancel"):
        task = store.get(fields["task_id"])
        adapters = adapter_registry or {}
        adapter = adapters.get(task["provider_id"])
        if adapter is None:
            raise GenerationError("PROVIDER_ADAPTER_NOT_CONFIGURED")
        return {"submit": store.submit_once, "poll": store.poll,
                "cancel": store.request_cancel}[action](fields["task_id"], adapter)
    if action == "result-record":
        return store.record_result(fields["task_id"], fields["receipt_path"], fields["receipt_sha256"])
    if action == "review-record":
        return store.record_review(fields["task_id"], fields["candidate_path"],
                                   fields["candidate_sha256"], fields["review_path"], fields["review_sha256"])
    if action == "adoption-gate":
        return store.adoption_gate(**fields)
    raise AssertionError(action)
