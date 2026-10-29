"""Strict runtime operation for host-configured OpenAI-compatible text providers.

The request names a profile and hash, never an endpoint, environment variable,
or credential value. MCP run_operation can route this operation unchanged.
"""
import hashlib
import json
from pathlib import Path

from model_text_generic import (ModelTextError, OpenAICompatibleTextClient,
                                ProfileRegistry, TextCallStore)
from text_model_interface import TextModelRegistry


FIELDS = {
    "profile-list": set(),
    "budget-create": {"store","budget_key","currency","limit_micros"},
    "prepare": {"store","intent_key","profile_id","profile_sha256","body_path",
                "body_sha256","budget_key","reservation_micros"},
    "read": {"store","call_id"},
    "result": {"store","call_id"},
    "send-once": {"store","call_id"},
    "settle-cost": {"store","call_id","event_key","evidence_path","evidence_sha256"},
}


def execute(request, directory=None, tools=None):
    if not isinstance(request,dict) or request.get("operation") != "model-text":
        raise ModelTextError("MODEL_TEXT_OPERATION_REQUIRED")
    action=request.get("action")
    if action not in FIELDS:
        raise ModelTextError("MODEL_TEXT_ACTION_UNSUPPORTED")
    optional={"timeout_seconds"} if action == "send-once" else set()
    expected={"operation","action"}|FIELDS[action]
    if not expected <= set(request) or set(request)-expected-optional:
        raise ModelTextError("MODEL_TEXT_REQUEST_FIELDS_INVALID")
    if action == "profile-list":
        return {"profiles":ProfileRegistry().public(),
                "note":"Host-configured profiles; credential values are not returned"}
    store_path=Path(request["store"])
    if not store_path.is_absolute():
        raise ModelTextError("ABSOLUTE_MODEL_LEDGER_REQUIRED")
    store=TextCallStore(store_path)
    if action == "budget-create":
        return store.budget_create(request["budget_key"],request["currency"],request["limit_micros"])
    if action == "read":
        return store.read(request["call_id"])
    if action == "result":
        return store.result(request["call_id"])
    if action == "settle-cost":
        return store.settle_cost(request["call_id"],request["event_key"],
                                 request["evidence_path"],request["evidence_sha256"])
    if action == "prepare":
        profile=ProfileRegistry().get(request["profile_id"],request["profile_sha256"])
        body_path=Path(request["body_path"])
        if not body_path.is_absolute() or not body_path.is_file():
            raise ModelTextError("ABSOLUTE_BODY_FILE_REQUIRED")
        body_bytes = body_path.read_bytes()
        if hashlib.sha256(body_bytes).hexdigest()!=request["body_sha256"]:
            raise ModelTextError("BODY_HASH_MISMATCH")
        body=json.loads(body_bytes.decode("utf-8"))
        return store.prepare(request["intent_key"],body,profile,request["budget_key"],
                             request["reservation_micros"])
    frozen=store.read(request["call_id"])
    if frozen["state"] != "PREPARED":
        return frozen
    profile=ProfileRegistry().get(frozen["profile_id"],frozen["profile_sha256"])
    client=OpenAICompatibleTextClient(profile,request.get("timeout_seconds",120))
    registry=TextModelRegistry()
    registry.register(client)
    return registry.send_once(store,request["call_id"])
