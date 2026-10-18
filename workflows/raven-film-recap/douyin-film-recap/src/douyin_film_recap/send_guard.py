"""Durable local send intents, scoped authorization and conservative replay.

This records local observations, not a provider-side exactly-once guarantee.
An interrupted send is UNKNOWN and requires human/provider reconciliation.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Callable, Any
from threading import Event, RLock

from .workspace import WorkspaceError, atomic, digest, member, now, preflight, read, work_lock


class SendBlocked(RuntimeError):
    pass


class SendCancelled(SendBlocked):
    """A local cancellation gate, not a statement about provider acceptance."""


_session: ContextVar = ContextVar("film_send_session", default=None)


class SendSession:
    def __init__(self, root: Path, scope: dict, *, authorized=False, max_requests=None, grant=None):
        if max_requests is not None and max_requests < 0:
            raise ValueError("max_requests must be non-negative")
        self.root = Path(root)
        self.scope = scope
        self.authorized = authorized
        self.max_requests = max_requests
        self.sent = 0
        self.ordinal = 0
        self._lock = RLock()
        self.grant = grant
        self._cancelled = Event()

    def cancel(self):
        self._cancelled.set()

    def check_cancelled(self):
        if self._cancelled.is_set():
            raise SendCancelled("REMOTE_SEND_CANCELLED: no new sends in this session")

    def _reserve(self, kind: str, payload: dict, intent_key=None, prepare=None):
        with self._lock:
            return self._reserve_locked(kind, payload, intent_key, prepare)

    def _reserve_locked(self, kind, payload, intent_key, prepare=None):
        self.check_cancelled()
        policy = self.scope.get("remote_policy")
        if policy:
            if kind == "chat":
                if (not policy.get("endpoint") or payload.get("endpoint") != f"{policy['endpoint']}/chat/completions"
                        or payload.get("body", {}).get("model") not in policy["models"]):
                    raise SendBlocked("REMOTE_ENDPOINT_OR_MODEL_OUTSIDE_AUTHORIZED_SCOPE")
            elif kind == "edge_tts":
                if any(payload.get(k) != v for k, v in policy["edge_tts"].items()):
                    raise SendBlocked("REMOTE_TTS_OUTSIDE_AUTHORIZED_SCOPE")
            else:
                raise SendBlocked("REMOTE_KIND_OUTSIDE_AUTHORIZED_SCOPE")
        self.ordinal += 1
        payload_hash = digest(payload)
        logical_key = intent_key or f"request:{payload_hash}"
        intent = digest({"schema": "film-send-intent/1", "scope": self.scope,
                         "kind": kind, "logical_key": logical_key})
        path = member(self.root, f".remote-intents/{intent}.json")
        if path.exists():
            previous = read(path)
            if previous.get("schema") != "film-send-intent/1":
                raise SendBlocked("UNSUPPORTED_SEND_INTENT_SCHEMA")
            if previous.get("payload_sha256") != payload_hash:
                raise SendBlocked("SEND_INTENT_PAYLOAD_CHANGED: inspect/reconcile the prior intent")
            if previous.get("status") == "SUCCEEDED":
                if previous.get("result_sha256") != digest(previous["result"]):
                    raise SendBlocked("SEND_RESULT_DRIFTED")
                return path, previous, True
            if previous.get("status") != "NOT_SUBMITTED_CONFIRMED":
                raise SendBlocked(f"SEND_OUTCOME_UNKNOWN: {intent}; automatic retry disabled")
        # An unkeyed caller cannot evade an interrupted send by changing its payload.
        if intent_key is None and (self.root / ".remote-intents").is_dir():
            for receipt in (self.root / ".remote-intents").glob("*.json"):
                prior = read(receipt)
                if prior.get("scope") == self.scope and prior.get("status") == "UNKNOWN":
                    raise SendBlocked("SEND_OUTCOME_UNKNOWN: unkeyed request requires reconciliation")
        if not self.authorized:
            raise SendBlocked("REMOTE_AUTHORIZATION_REQUIRED: cached results can replay; new sends need --allow-remote")
        if self.max_requests is not None and self.sent >= self.max_requests:
            raise SendBlocked("LOCAL_REQUEST_LIMIT_REACHED: this is not a provider billing cap")
        if self.grant:
            current = read(member(self.root, ".remote-authorization.json"))
            if current != self.grant:
                raise SendBlocked("REMOTE_AUTHORIZATION_REVOKED_OR_CHANGED")
            used = 0
            for receipt in (self.root / ".remote-intents").glob("*.json"):
                prior = read(member(self.root, str(receipt.relative_to(self.root))))
                used += sum(a.get("authorization_id") == self.grant["id"] for a in prior.get("send_attempts", []))
            if self.grant.get("max_requests") is not None and used >= self.grant["max_requests"]:
                raise SendBlocked("LOCAL_REQUEST_LIMIT_REACHED: persisted authorization exhausted")
        # Local-only preparation happens after replay/authorization checks but before
        # a durable send reservation. Never perform network I/O in this callback.
        if prepare is not None:
            prepare()
        attempts = previous.get("send_attempts", []) if path.exists() else []
        attempts = [*attempts, {"reserved_at": now(),
                               "authorization_id": self.grant["id"] if self.grant else None}]
        record = {"schema": "film-send-intent/1", "intent": intent, "scope": self.scope,
                  "kind": kind, "ordinal": self.ordinal, "payload_sha256": payload_hash,
                  "logical_key": logical_key,
                  "status": "UNKNOWN", "send_reserved_at": now(),
                  "authorization": {"explicit": True, "max_requests": self.max_requests}}
        record["send_attempts"] = attempts
        if path.exists():
            record["reconciliation"] = previous.get("reconciliation")
            record["prior_local_errors"] = [*previous.get("prior_local_errors", []),
                                           *([previous["local_error"]] if previous.get("local_error") else [])]
        atomic(path, record)  # Persist before entering the actual transport.
        self.sent += 1
        return path, record, False

    def _check_before_transport(self, path, record):
        try:
            self.check_cancelled()
        except SendCancelled:
            # We have not invoked the transport callback. Reservations still count
            # conservatively toward the local budget; no billing claim is made.
            record.update(status="NOT_SUBMITTED_CONFIRMED",
                          cancellation={"at": now(), "reason": "cancelled_before_transport"})
            atomic(path, record)
            raise

    @staticmethod
    def _finish(path, record, result):
        record.update(status="SUCCEEDED", result=result, result_sha256=digest(result),
                      received_at=now())
        atomic(path, record)  # Raw response precedes all JSON/model validation.
        return result

    @staticmethod
    def _fail(path, record, exc):
        record["local_error"] = {"type": type(exc).__name__, "message": str(exc)[:500]}
        atomic(path, record)

    def perform(self, kind: str, payload: dict, send: Callable[[], Any], intent_key=None):
        path, record, cached = self._reserve(kind, payload, intent_key)
        if cached:
            return record["result"]
        self._check_before_transport(path, record)
        try:
            result = send()
        except BaseException as exc:
            # Timeout/connection loss/kill cannot prove the service did not accept.
            self._fail(path, record, exc)
            raise
        return self._finish(path, record, result)

    async def perform_async(self, kind, payload, send, intent_key=None, prepare=None):
        path, record, cached = self._reserve(kind, payload, intent_key, prepare)
        if cached:
            return record["result"]
        self._check_before_transport(path, record)
        try:
            result = await send()
        except BaseException as exc:
            self._fail(path, record, exc)
            raise
        return self._finish(path, record, result)


@contextmanager
def send_session(root, scope, *, authorized=False, max_requests=None, grant=None):
    root, _ = preflight(root)
    with work_lock(root):
        session = SendSession(root, scope, authorized=authorized, max_requests=max_requests, grant=grant)
        token = _session.set(session)
        try:
            yield session
        except BaseException:
            session.cancel()
            raise
        finally:
            _session.reset(token)


def cancel_active_sends():
    current = _session.get()
    if current is not None:
        current.cancel()


def check_active_send():
    current = _session.get()
    if current is not None:
        current.check_cancelled()


def guarded_send(kind, payload, send, *, intent_key=None):
    current = _session.get()
    if current is None:
        raise SendBlocked("REMOTE_AUTHORIZATION_REQUIRED: no active scoped send session")
    return current.perform(kind, payload, send, intent_key)


async def guarded_async_send(kind, payload, send, *, intent_key=None, prepare=None):
    current = _session.get()
    if current is None:
        raise SendBlocked("REMOTE_AUTHORIZATION_REQUIRED: no active scoped send session")
    return await current.perform_async(kind, payload, send, intent_key, prepare)


def reconcile(root, intent, evidence):
    """Explicit operator assertion; does not itself verify the provider outcome."""
    if len(intent) != 64 or any(c not in "0123456789abcdef" for c in intent):
        raise WorkspaceError("SEND_INTENT_INVALID")
    if not evidence.strip():
        raise WorkspaceError("RECONCILIATION_EVIDENCE_REQUIRED")
    with work_lock(root):
        path = member(root, f".remote-intents/{intent}.json")
        record = read(path)
        if record.get("schema") != "film-send-intent/1" or record.get("status") != "UNKNOWN":
            raise WorkspaceError("ONLY_UNKNOWN_SEND_CAN_BE_RECONCILED")
        record.update(status="NOT_SUBMITTED_CONFIRMED",
                      reconciliation={"operator_evidence": evidence, "at": now(),
                                      "provider_verified_by_runtime": False})
        atomic(path, record)
        return record
