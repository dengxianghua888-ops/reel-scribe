"""Persistent, conservative lifecycle for externally billed generation tasks.

This module contains no provider implementation and makes no network call by itself.
An uncertain submit is deliberately never retried. Query is used only when a provider
documents a usable lookup; no lookup leaves the task frozen, not resubmitted.
"""
import hashlib
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, Optional, Protocol
from uuid import uuid4


SCHEMA_VERSION = 4
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ACTIVE = frozenset(("SUBMISSION_UNKNOWN", "QUEUED", "RUNNING", "OUTPUT_UNKNOWN"))


class GenerationError(ValueError):
    pass


class Conflict(GenerationError):
    pass


class NotReady(GenerationError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def _sha_file(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _word(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", value):
        raise GenerationError(label + "_INVALID")
    return value


def _external_id(value, label):
    if (not isinstance(value, str) or not value or len(value) > 512 or
            any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise GenerationError(label + "_INVALID")
    return value


def _hash(value, label):
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise GenerationError(label + "_INVALID")
    return value


def _money(value, label, positive=False):
    if type(value) is not int or value < (1 if positive else 0) or value > 2**63 - 1:
        raise GenerationError(label + "_INVALID")
    return value


@dataclass(frozen=True)
class ProviderCapabilities:
    currency: str  # ISO 4217 units used by all *_micros values.
    # False means max_cost_micros is a local reservation, not a spending ceiling.
    hard_cost_cap: bool
    # A lost submit ack is recoverable only with a same-key lookup.
    query_by_idempotency_key: bool
    query_by_task_id: bool = False
    cancel_supported: bool = False


@dataclass(frozen=True)
class SubmissionAck:
    provider_task_id: str
    state: str  # QUEUED or RUNNING; success must be observed by query.


@dataclass(frozen=True)
class ProviderObservation:
    state: str  # UNKNOWN, NOT_FOUND, QUEUED, RUNNING, SUCCEEDED, FAILED, CANCELLED
    provider_task_id: Optional[str] = None
    actual_cost_micros: Optional[int] = None  # None means cost unknown; reserve stays held.
    result_available: Optional[bool] = None  # False + SUCCEEDED means completed-empty.
    response_path: Optional[str] = None  # Immutable local copy of raw service response.
    response_sha256: Optional[str] = None
    output_id: Optional[str] = None  # Provider output or asset identity, not a URL guess.
    output_checksum_sha256: Optional[str] = None  # Provider-attested digest, if supplied.
    detail: str = ""


class ProviderAdapter(Protocol):
    provider_id: str

    def capabilities(self) -> ProviderCapabilities:
        ...

    def submit(self, payload: Dict[str, Any], *, idempotency_key: str,
               max_cost_micros: int) -> SubmissionAck:
        ...

    def query(self, *, idempotency_key: str,
              provider_task_id: Optional[str]) -> ProviderObservation:
        ...

    def cancel(self, *, idempotency_key: str,
               provider_task_id: Optional[str]) -> None:
        ...


class GenerationStore:
    """One SQLite file may serve several tasks; paid calls occur outside transactions."""

    def __init__(self, database_path):
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)
        with self._connection() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, SCHEMA_VERSION):
                raise GenerationError("GENERATION_SCHEMA_UNSUPPORTED")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS budgets(
                    budget_key TEXT PRIMARY KEY, currency TEXT NOT NULL,
                    limit_micros INTEGER NOT NULL, reserved_micros INTEGER NOT NULL DEFAULT 0,
                    spent_micros INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS tasks(
                    task_id TEXT PRIMARY KEY, idempotency_key TEXT NOT NULL UNIQUE,
                    intent_sha256 TEXT NOT NULL, provider_id TEXT NOT NULL, model TEXT NOT NULL,
                    kind TEXT NOT NULL, payload_json TEXT NOT NULL, budget_key TEXT NOT NULL,
                    max_cost_micros INTEGER NOT NULL, work_id TEXT NOT NULL,
                    work_version TEXT NOT NULL, work_document_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL, submit_attempts INTEGER NOT NULL DEFAULT 0,
                    hard_cost_cap INTEGER,
                    provider_task_id TEXT, cancel_requested INTEGER NOT NULL DEFAULT 0,
                    cancel_call_started INTEGER NOT NULL DEFAULT 0,
                    reserved_micros INTEGER NOT NULL DEFAULT 0, actual_cost_micros INTEGER,
                    provider_response_path TEXT, provider_response_sha256 TEXT,
                    provider_output_id TEXT, provider_output_checksum_sha256 TEXT,
                    result_receipt_path TEXT, result_receipt_sha256 TEXT,
                    result_hash_source TEXT,
                    result_path TEXT, result_sha256 TEXT, last_error TEXT,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    FOREIGN KEY(budget_key) REFERENCES budgets(budget_key));
                CREATE TABLE IF NOT EXISTS task_events(
                    event_id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL,
                    at TEXT NOT NULL, action TEXT NOT NULL, old_state TEXT,
                    new_state TEXT NOT NULL, detail_json TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id));
                CREATE TABLE IF NOT EXISTS candidate_reviews(
                    task_id TEXT NOT NULL, candidate_sha256 TEXT NOT NULL,
                    decision TEXT NOT NULL, review_path TEXT NOT NULL,
                    review_sha256 TEXT NOT NULL, result_sha256 TEXT NOT NULL,
                    recorded_at TEXT NOT NULL,
                    PRIMARY KEY(task_id,candidate_sha256),
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id));
                CREATE TABLE IF NOT EXISTS billing_events(
                    event_key TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    evidence_path TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
                    currency TEXT NOT NULL, actual_cost_micros INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id));
                CREATE TABLE IF NOT EXISTS output_attempts(
                    attempt_key TEXT PRIMARY KEY, task_id TEXT NOT NULL,
                    provider_output_id TEXT NOT NULL, source_kind TEXT NOT NULL,
                    source_ref TEXT NOT NULL, state TEXT NOT NULL,
                    error_code TEXT, receipt_sha256 TEXT, result_sha256 TEXT,
                    started_at TEXT NOT NULL, completed_at TEXT,
                    FOREIGN KEY(task_id) REFERENCES tasks(task_id));
            """)
            if version == 1:
                # v1 admitted only hard-capped providers; retain that frozen fact.
                db.execute("ALTER TABLE tasks ADD COLUMN hard_cost_cap INTEGER")
                db.execute("UPDATE tasks SET hard_cost_cap=1 WHERE submit_attempts>0")
            if version in (1, 2, 3):
                for definition in (
                    "provider_response_path TEXT", "provider_response_sha256 TEXT",
                    "provider_output_id TEXT", "provider_output_checksum_sha256 TEXT",
                    "result_receipt_path TEXT", "result_receipt_sha256 TEXT",
                    "result_hash_source TEXT"):
                    db.execute("ALTER TABLE tasks ADD COLUMN " + definition)
            db.execute("PRAGMA user_version=4")

    @contextmanager
    def _connection(self):
        db = None
        try:
            db = sqlite3.connect(str(self.path), timeout=5)
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            try:
                yield db
                db.commit()
            except BaseException:
                db.rollback()
                raise
        except sqlite3.Error as exc:
            raise GenerationError("GENERATION_STORE_ERROR: " + str(exc)) from exc
        finally:
            if db is not None:
                db.close()

    @contextmanager
    def _write(self):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def _event(db, task_id, action, old, new, detail=None):
        db.execute("INSERT INTO task_events(task_id,at,action,old_state,new_state,detail_json) VALUES(?,?,?,?,?,?)",
                   (task_id, _now(), action, old, new, _canonical(detail or {})))

    @staticmethod
    def _task(db, task_id):
        row = db.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise GenerationError("TASK_NOT_FOUND")
        return row

    @staticmethod
    def _public(row):
        # Do not echo prompt/payload in ordinary status reads.
        value = dict(row)
        value.pop("payload_json", None)
        value["cost_status"] = "UNKNOWN" if value["actual_cost_micros"] is None else "REPORTED"
        value["cost_limit_kind"] = ("UNDECIDED" if value["hard_cost_cap"] is None else
                                    "PROVIDER_HARD_CAP" if value["hard_cost_cap"] else
                                    "LOCAL_RESERVATION_ONLY")
        return value

    @staticmethod
    def _verify_result_chain(task, db=None):
        if not all(task[key] for key in ("provider_task_id","provider_response_path",
                "provider_response_sha256","provider_output_id","result_receipt_path",
                "result_receipt_sha256","result_path","result_sha256")):
            raise Conflict("OUTPUT_IDENTITY_CHAIN_INCOMPLETE")
        for path_key, hash_key in (("provider_response_path","provider_response_sha256"),
                                   ("result_receipt_path","result_receipt_sha256"),
                                   ("result_path","result_sha256")):
            path=Path(task[path_key])
            if not path.is_file() or _sha_file(path) != task[hash_key]:
                raise Conflict("OUTPUT_IDENTITY_CHAIN_HASH_CHANGED")
        receipt=json.loads(Path(task["result_receipt_path"]).read_text(encoding="utf-8"))
        if (not isinstance(receipt,dict) or receipt.get("schema") != "generation-output-receipt/1"
                or receipt.get("task_id") != task["task_id"]
                or receipt.get("provider_id") != task["provider_id"]
                or receipt.get("provider_task_id") != task["provider_task_id"]
                or receipt.get("provider_output_id") != task["provider_output_id"]
                or receipt.get("provider_response_sha256") != task["provider_response_sha256"]
                or receipt.get("provider_output_checksum_sha256") != task["provider_output_checksum_sha256"]
                or not isinstance(receipt.get("result_path"),str)
                or str(Path(receipt["result_path"]).resolve(strict=True)) != task["result_path"]
                or receipt.get("result_sha256") != task["result_sha256"]):
            raise Conflict("OUTPUT_IDENTITY_CHAIN_RECEIPT_CHANGED")
        service_digest=task["provider_output_checksum_sha256"]
        if (service_digest and (task["result_sha256"] != service_digest or
                                task["result_hash_source"] != "PROVIDER_SHA256")) or (
                not service_digest and task["result_hash_source"] != "LOCAL_FIRST_BASELINE"):
            raise Conflict("OUTPUT_CHECKSUM_BASIS_CHANGED")
        if db is not None:
            attempt=db.execute("SELECT * FROM output_attempts WHERE attempt_key=?",
                               (receipt.get("attempt_key"),)).fetchone()
            if (not attempt or attempt["task_id"] != task["task_id"] or
                    attempt["provider_output_id"] != task["provider_output_id"] or
                    attempt["source_kind"] != receipt.get("source_kind") or
                    attempt["source_ref"] != receipt.get("source_ref") or
                    attempt["state"] != "COMPLETE" or
                    attempt["receipt_sha256"] != task["result_receipt_sha256"] or
                    attempt["result_sha256"] != task["result_sha256"]):
                raise Conflict("OUTPUT_IDENTITY_CHAIN_ATTEMPT_CHANGED")

    def get(self, task_id):
        with self._connection() as db:
            return self._public(self._task(db, task_id))

    def events(self, task_id):
        with self._connection() as db:
            self._task(db, task_id)
            return [dict(x) for x in db.execute(
                "SELECT * FROM task_events WHERE task_id=? ORDER BY event_id", (task_id,))]

    def create_budget(self, budget_key, currency, limit_micros):
        _word(budget_key, "BUDGET_KEY")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            raise GenerationError("CURRENCY_INVALID")
        _money(limit_micros, "BUDGET_LIMIT", positive=True)
        with self._write() as db:
            row = db.execute("SELECT * FROM budgets WHERE budget_key=?", (budget_key,)).fetchone()
            if row:
                if row["currency"] != currency or row["limit_micros"] != limit_micros:
                    raise Conflict("BUDGET_DEFINITION_CONFLICT")
            else:
                db.execute("INSERT INTO budgets(budget_key,currency,limit_micros) VALUES(?,?,?)",
                           (budget_key, currency, limit_micros))
        return self.budget(budget_key)

    def budget(self, budget_key):
        with self._connection() as db:
            row = db.execute("SELECT * FROM budgets WHERE budget_key=?", (budget_key,)).fetchone()
            if row is None:
                raise GenerationError("BUDGET_NOT_FOUND")
            return dict(row)

    def create_task(self, *, idempotency_key, provider_id, model, kind, payload,
                    budget_key, max_cost_micros, work_binding):
        for label, value in (("IDEMPOTENCY_KEY", idempotency_key), ("PROVIDER", provider_id),
                             ("KIND", kind), ("BUDGET_KEY", budget_key)):
            _word(value, label)
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,127}", model):
            raise GenerationError("MODEL_INVALID")
        _money(max_cost_micros, "MAX_COST", positive=True)
        if not isinstance(payload, dict) or not payload:
            raise GenerationError("PAYLOAD_OBJECT_REQUIRED")
        if not isinstance(work_binding, dict) or set(work_binding) != {"work_id", "version", "document_sha256"}:
            raise GenerationError("WORK_BINDING_INVALID")
        _word(work_binding["work_id"], "WORK_ID")
        _hash(work_binding["version"], "WORK_VERSION")
        _hash(work_binding["document_sha256"], "WORK_DOCUMENT_SHA256")
        serialized = _canonical(payload)
        intent = _sha_bytes(_canonical({"provider_id": provider_id, "model": model,
                  "kind": kind, "payload": payload, "budget_key": budget_key,
                  "max_cost_micros": max_cost_micros,
                  "work_binding": work_binding}).encode("utf-8"))
        with self._write() as db:
            existing = db.execute("SELECT * FROM tasks WHERE idempotency_key=?", (idempotency_key,)).fetchone()
            if existing:
                if existing["intent_sha256"] != intent:
                    raise Conflict("IDEMPOTENCY_KEY_REUSED_WITH_DIFFERENT_INTENT")
                return self._public(existing)
            if db.execute("SELECT 1 FROM budgets WHERE budget_key=?", (budget_key,)).fetchone() is None:
                raise GenerationError("BUDGET_NOT_FOUND")
            task_id, at = str(uuid4()), _now()
            db.execute("""INSERT INTO tasks(task_id,idempotency_key,intent_sha256,provider_id,model,kind,
                       payload_json,budget_key,max_cost_micros,work_id,work_version,work_document_sha256,
                       state,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                       (task_id,idempotency_key,intent,provider_id,model,kind,serialized,budget_key,
                        max_cost_micros,work_binding["work_id"],work_binding["version"],
                        work_binding["document_sha256"],"CREATED",at,at))
            self._event(db, task_id, "create", None, "CREATED", {"intent_sha256": intent})
            return self._public(self._task(db, task_id))

    @staticmethod
    def _adapter(task, adapter):
        if adapter.provider_id != task["provider_id"]:
            raise Conflict("PROVIDER_MISMATCH")
        caps = adapter.capabilities()
        if (not isinstance(caps, ProviderCapabilities) or not re.fullmatch(r"[A-Z]{3}", caps.currency)
                or any(type(value) is not bool for value in
                       (caps.hard_cost_cap,caps.query_by_idempotency_key,
                        caps.query_by_task_id,caps.cancel_supported))):
            raise GenerationError("PROVIDER_CAPABILITIES_INVALID")
        if task["hard_cost_cap"] is not None and bool(task["hard_cost_cap"]) != caps.hard_cost_cap:
            raise Conflict("PROVIDER_COST_CAPABILITY_CHANGED")
        return caps

    def submit_once(self, task_id, adapter):
        """At most one external submit invocation per task, including after a crash."""
        with self._write() as db:
            task = self._task(db, task_id)
            if task["state"] != "CREATED":
                return self._public(task)
            caps = self._adapter(task, adapter)
            budget = db.execute("SELECT * FROM budgets WHERE budget_key=?", (task["budget_key"],)).fetchone()
            if budget["currency"] != caps.currency:
                raise Conflict("PROVIDER_CURRENCY_MISMATCH")
            remaining = budget["limit_micros"] - budget["spent_micros"] - budget["reserved_micros"]
            if task["max_cost_micros"] > remaining:
                raise NotReady("BUDGET_EXHAUSTED")
            db.execute("UPDATE budgets SET reserved_micros=reserved_micros+? WHERE budget_key=?",
                       (task["max_cost_micros"], task["budget_key"]))
            db.execute("""UPDATE tasks SET state='SUBMISSION_UNKNOWN',submit_attempts=1,
                       hard_cost_cap=?,reserved_micros=max_cost_micros,updated_at=? WHERE task_id=?""",
                       (int(caps.hard_cost_cap),_now(),task_id))
            self._event(db, task_id, "submit_boundary", "CREATED", "SUBMISSION_UNKNOWN",
                        {"reason": "persist before provider call; never automatic resubmit",
                         "provider_hard_cost_cap":caps.hard_cost_cap,
                         "cost_limit_kind":"PROVIDER_HARD_CAP" if caps.hard_cost_cap else "LOCAL_RESERVATION_ONLY"})
            payload = json.loads(task["payload_json"])
            key, maximum = task["idempotency_key"], task["max_cost_micros"]
        try:
            ack = adapter.submit(payload, idempotency_key=key, max_cost_micros=maximum)
            if not isinstance(ack, SubmissionAck) or not ack.provider_task_id or ack.state not in ("QUEUED", "RUNNING"):
                raise GenerationError("PROVIDER_ACK_INVALID")
            _external_id(ack.provider_task_id,"PROVIDER_TASK_ID")
        except Exception as exc:
            # The call may have reached the provider. Keep reservation and unknown state.
            with self._write() as db:
                db.execute("UPDATE tasks SET last_error=?,updated_at=? WHERE task_id=?",
                           (type(exc).__name__, _now(), task_id))
                self._event(db, task_id, "submit_uncertain", "SUBMISSION_UNKNOWN", "SUBMISSION_UNKNOWN",
                            {"error_type": type(exc).__name__})
            return self.get(task_id)
        with self._write() as db:
            task = self._task(db, task_id)
            if task["provider_task_id"] and task["provider_task_id"] != ack.provider_task_id:
                raise Conflict("PROVIDER_TASK_ID_CONFLICT")
            if task["state"] == "SUBMISSION_UNKNOWN":
                db.execute("UPDATE tasks SET provider_task_id=?,state=?,last_error=NULL,updated_at=? WHERE task_id=?",
                           (ack.provider_task_id,ack.state,_now(),task_id))
                self._event(db,task_id,"submit_ack","SUBMISSION_UNKNOWN",ack.state,
                            {"provider_task_id":ack.provider_task_id})
        return self.get(task_id)

    def poll(self, task_id, adapter):
        with self._connection() as db:
            task = self._task(db, task_id)
            caps = self._adapter(task, adapter)
            if task["state"] not in ACTIVE:
                return self._public(task)
            key, provider_task_id = task["idempotency_key"], task["provider_task_id"]
            if not caps.query_by_idempotency_key and not (caps.query_by_task_id and provider_task_id):
                return dict(self._public(task), recovery="QUERY_UNAVAILABLE_HOLD_NO_RESUBMIT")
        try:
            observation = adapter.query(idempotency_key=key, provider_task_id=provider_task_id)
            if not isinstance(observation, ProviderObservation):
                raise GenerationError("PROVIDER_OBSERVATION_INVALID")
        except Exception as exc:
            with self._write() as db:
                db.execute("UPDATE tasks SET last_error=?,updated_at=? WHERE task_id=?",
                           (type(exc).__name__,_now(),task_id))
                current = self._task(db,task_id)
                self._event(db,task_id,"query_uncertain",current["state"],current["state"],
                            {"error_type":type(exc).__name__})
            return self.get(task_id)
        if observation.state not in ("UNKNOWN","NOT_FOUND","QUEUED","RUNNING","SUCCEEDED","FAILED","CANCELLED"):
            raise GenerationError("PROVIDER_STATE_INVALID")
        if observation.provider_task_id is not None:
            _external_id(observation.provider_task_id,"PROVIDER_TASK_ID")
        if observation.output_id is not None:
            _external_id(observation.output_id,"PROVIDER_OUTPUT_ID")
        if observation.output_checksum_sha256 is not None:
            _hash(observation.output_checksum_sha256,"PROVIDER_OUTPUT_CHECKSUM_SHA256")
        if (observation.response_path is None) != (observation.response_sha256 is None):
            raise GenerationError("PROVIDER_RESPONSE_PATH_HASH_PAIR_REQUIRED")
        response_path = None
        if observation.response_path is not None:
            _hash(observation.response_sha256,"PROVIDER_RESPONSE_SHA256")
            response_path = Path(observation.response_path).resolve(strict=True)
            if not response_path.is_file() or _sha_file(response_path) != observation.response_sha256:
                raise Conflict("PROVIDER_RESPONSE_HASH_MISMATCH")
        with self._write() as db:
            task = self._task(db,task_id)
            if task["state"] not in ACTIVE:
                return self._public(task)
            if task["provider_task_id"] and observation.provider_task_id and task["provider_task_id"] != observation.provider_task_id:
                db.execute("UPDATE tasks SET last_error=?,updated_at=? WHERE task_id=?",
                           ("PROVIDER_TASK_ID_CONFLICT",_now(),task_id))
                self._event(db,task_id,"query_identity_conflict",task["state"],task["state"])
                return self._public(self._task(db,task_id))
            old = task["state"]
            pid = observation.provider_task_id or task["provider_task_id"]
            if observation.state in ("UNKNOWN","NOT_FOUND"):
                # NOT_FOUND is not proof a delayed paid submission cannot still appear.
                db.execute("UPDATE tasks SET provider_task_id=?,last_error=?,updated_at=? WHERE task_id=?",
                           (pid,"PROVIDER_"+observation.state,_now(),task_id))
                self._event(db,task_id,"query_unresolved",old,old,{"observed":observation.state})
            elif observation.state in ("QUEUED","RUNNING"):
                if not pid:
                    raise GenerationError("PROVIDER_TASK_ID_REQUIRED")
                db.execute("UPDATE tasks SET state=?,provider_task_id=?,last_error=NULL,updated_at=? WHERE task_id=?",
                           (observation.state,pid,_now(),task_id))
                self._event(db,task_id,"query_progress",old,observation.state)
            else:
                if not pid:
                    raise GenerationError("PROVIDER_TASK_ID_REQUIRED")
                if observation.state == "SUCCEEDED" and (
                        observation.result_available is None or
                        observation.result_available is True and
                        (not observation.output_id or response_path is None)):
                    db.execute("""UPDATE tasks SET state='OUTPUT_UNKNOWN',provider_task_id=?,
                               provider_response_path=?,provider_response_sha256=?,
                               last_error=?,updated_at=? WHERE task_id=?""",
                               (pid,str(response_path) if response_path else None,
                                observation.response_sha256,
                                "RESULT_AVAILABILITY_UNKNOWN" if observation.result_available is None else
                                "OUTPUT_IDENTITY_OR_RESPONSE_MISSING",_now(),task_id))
                    self._event(db,task_id,"query_output_unknown",old,"OUTPUT_UNKNOWN")
                    return self._public(self._task(db,task_id))
                if observation.state == "SUCCEEDED" and observation.result_available is True:
                    if task["provider_output_id"] and task["provider_output_id"] != observation.output_id:
                        raise Conflict("PROVIDER_OUTPUT_ID_CHANGED")
                    if _sha_file(response_path) != observation.response_sha256:
                        raise Conflict("PROVIDER_RESPONSE_HASH_CHANGED")
                reserve = task["reserved_micros"]
                actual = (None if observation.actual_cost_micros is None else
                          _money(observation.actual_cost_micros,"ACTUAL_COST"))
                new = ("COST_VIOLATION" if actual is not None and actual > reserve and caps.hard_cost_cap else
                       "COMPLETED_EMPTY" if observation.state == "SUCCEEDED" and observation.result_available is False else
                       "AWAITING_RESULT" if observation.state == "SUCCEEDED" else observation.state)
                if actual is not None:
                    budget = db.execute("SELECT spent_micros FROM budgets WHERE budget_key=?",
                                        (task["budget_key"],)).fetchone()
                    if not 0 <= budget["spent_micros"] + actual <= 2**63 - 1:
                        raise GenerationError("BUDGET_ACCOUNTING_OVERFLOW")
                    db.execute("UPDATE budgets SET reserved_micros=reserved_micros-?,spent_micros=spent_micros+? WHERE budget_key=?",
                               (reserve,actual,task["budget_key"]))
                db.execute("""UPDATE tasks SET state=?,provider_task_id=?,reserved_micros=?,
                           actual_cost_micros=?,provider_response_path=?,provider_response_sha256=?,
                           provider_output_id=?,provider_output_checksum_sha256=?,last_error=?,updated_at=?
                           WHERE task_id=?""",
                           (new,pid,0 if actual is not None else reserve,actual,
                            str(response_path) if response_path else None,observation.response_sha256,
                            observation.output_id if observation.state == "SUCCEEDED" and observation.result_available else None,
                            observation.output_checksum_sha256 if observation.state == "SUCCEEDED" and observation.result_available else None,
                            "PROVIDER_EXCEEDED_HARD_COST_CAP" if new == "COST_VIOLATION" else
                            "LOCAL_RESERVATION_EXCEEDED" if actual is not None and actual > reserve else
                            "ACTUAL_COST_UNKNOWN" if actual is None else None,
                            _now(),task_id))
                self._event(db,task_id,"query_terminal",old,new,
                            {"provider_state":observation.state,"actual_cost_micros":actual,
                             "cost_status":"UNKNOWN" if actual is None else "REPORTED"})
            return self._public(self._task(db,task_id))

    def request_cancel(self, task_id, adapter):
        with self._write() as db:
            task = self._task(db,task_id)
            if task["state"] == "CREATED":
                db.execute("UPDATE tasks SET state='CANCELLED',cancel_requested=1,updated_at=? WHERE task_id=?",
                           (_now(),task_id))
                self._event(db,task_id,"cancel_before_submit","CREATED","CANCELLED")
                return self._public(self._task(db,task_id))
            if task["state"] in ACTIVE:
                caps = self._adapter(task,adapter)
                if task["cancel_call_started"]:
                    return self._public(task)
                if not caps.cancel_supported:
                    db.execute("UPDATE tasks SET cancel_requested=1,updated_at=? WHERE task_id=?",
                               (_now(),task_id))
                    self._event(db,task_id,"cancel_unavailable_hold",task["state"],task["state"])
                    return dict(self._public(self._task(db,task_id)),
                                recovery="CANCEL_UNAVAILABLE_QUERY_OR_MANUAL_RECONCILIATION")
                db.execute("""UPDATE tasks SET cancel_requested=1,cancel_call_started=1,updated_at=?
                           WHERE task_id=?""",(_now(),task_id))
                self._event(db,task_id,"cancel_boundary",task["state"],task["state"],
                            {"reason":"request persisted before provider cancel; query for outcome"})
                key,pid=task["idempotency_key"],task["provider_task_id"]
            else:
                if not task["cancel_requested"]:
                    db.execute("UPDATE tasks SET cancel_requested=1,updated_at=? WHERE task_id=?",
                               (_now(),task_id))
                    self._event(db,task_id,"abandon_result",task["state"],task["state"])
                return self._public(self._task(db,task_id))
        try:
            adapter.cancel(idempotency_key=key,provider_task_id=pid)
        except Exception as exc:
            with self._write() as db:
                db.execute("UPDATE tasks SET last_error=?,updated_at=? WHERE task_id=?",
                           (type(exc).__name__,_now(),task_id))
        return self.get(task_id)

    def billing_events(self, task_id):
        with self._connection() as db:
            self._task(db,task_id)
            return [dict(row) for row in db.execute(
                "SELECT * FROM billing_events WHERE task_id=? ORDER BY rowid",(task_id,))]

    def output_attempts(self, task_id):
        with self._connection() as db:
            self._task(db,task_id)
            return [dict(row) for row in db.execute(
                "SELECT * FROM output_attempts WHERE task_id=? ORDER BY rowid",(task_id,))]

    def begin_output_attempt(self, task_id, attempt_key, source_kind, source_ref):
        _word(attempt_key,"OUTPUT_ATTEMPT_KEY")
        if source_kind not in ("provider-download","explicit-import"):
            raise GenerationError("OUTPUT_SOURCE_KIND_INVALID")
        if not isinstance(source_ref,str) or not source_ref.strip():
            raise GenerationError("OUTPUT_SOURCE_REF_REQUIRED")
        with self._write() as db:
            task=self._task(db,task_id)
            if (task["state"] not in ("AWAITING_RESULT","VERIFIED") or task["cancel_requested"]
                    or not task["provider_output_id"] or not task["provider_response_sha256"]):
                raise NotReady("RECORDED_OUTPUT_REQUIRED")
            if (not task["provider_response_path"] or
                    _sha_file(task["provider_response_path"]) != task["provider_response_sha256"]):
                raise Conflict("PROVIDER_RESPONSE_HASH_CHANGED")
            existing=db.execute("SELECT * FROM output_attempts WHERE attempt_key=?",(attempt_key,)).fetchone()
            if existing:
                if (existing["task_id"],existing["provider_output_id"],existing["source_kind"],existing["source_ref"]) != (
                        task_id,task["provider_output_id"],source_kind,source_ref):
                    raise Conflict("OUTPUT_ATTEMPT_KEY_CONFLICT")
                return dict(existing)
            db.execute("""INSERT INTO output_attempts(attempt_key,task_id,provider_output_id,
                       source_kind,source_ref,state,started_at) VALUES(?,?,?,?,?,'STARTED',?)""",
                       (attempt_key,task_id,task["provider_output_id"],source_kind,source_ref,_now()))
            self._event(db,task_id,"output_attempt_begin",task["state"],task["state"],
                        {"attempt_key":attempt_key,"provider_output_id":task["provider_output_id"]})
            return dict(db.execute("SELECT * FROM output_attempts WHERE attempt_key=?",(attempt_key,)).fetchone())

    def fail_output_attempt(self, task_id, attempt_key, error_code):
        _word(attempt_key,"OUTPUT_ATTEMPT_KEY")
        _word(error_code,"OUTPUT_ERROR_CODE")
        with self._write() as db:
            task=self._task(db,task_id)
            attempt=db.execute("SELECT * FROM output_attempts WHERE attempt_key=?",(attempt_key,)).fetchone()
            if not attempt or attempt["task_id"] != task_id:
                raise GenerationError("OUTPUT_ATTEMPT_NOT_FOUND")
            if attempt["state"] == "FAILED" and attempt["error_code"] == error_code:
                return dict(attempt)
            if attempt["state"] != "STARTED":
                raise Conflict("OUTPUT_ATTEMPT_ALREADY_TERMINAL")
            db.execute("UPDATE output_attempts SET state='FAILED',error_code=?,completed_at=? WHERE attempt_key=?",
                       (error_code,_now(),attempt_key))
            self._event(db,task_id,"output_attempt_fail",task["state"],task["state"],
                        {"attempt_key":attempt_key,"error_code":error_code})
            return dict(db.execute("SELECT * FROM output_attempts WHERE attempt_key=?",(attempt_key,)).fetchone())

    def settle_cost(self, task_id, event_key, evidence_path, evidence_sha256):
        """Reconcile a terminal task with supplied billing evidence; no provider call."""
        _word(event_key,"BILLING_EVENT_KEY")
        _hash(evidence_sha256,"BILLING_EVIDENCE_SHA256")
        path=Path(evidence_path).resolve(strict=True)
        if not path.is_file() or _sha_file(path) != evidence_sha256:
            raise Conflict("BILLING_EVIDENCE_HASH_MISMATCH")
        evidence=json.loads(path.read_text(encoding="utf-8"))
        with self._write() as db:
            task=self._task(db,task_id)
            if task["submit_attempts"] != 1 or task["state"] in ACTIVE or task["state"] == "CREATED":
                raise NotReady("TERMINAL_SUBMITTED_TASK_REQUIRED")
            budget=db.execute("SELECT * FROM budgets WHERE budget_key=?",(task["budget_key"],)).fetchone()
            amount=evidence.get("actual_cost_micros") if isinstance(evidence,dict) else None
            if (not isinstance(evidence,dict) or evidence.get("schema") != "generation-billing-evidence/1"
                    or evidence.get("task_id") != task_id
                    or evidence.get("intent_sha256") != task["intent_sha256"]
                    or evidence.get("provider_id") != task["provider_id"]
                    or evidence.get("model") != task["model"]
                    or evidence.get("currency") != budget["currency"]
                    or not isinstance(evidence.get("source_ref"),str) or not evidence["source_ref"].strip()
                    or type(amount) is not int or not 0 <= amount <= 2**63 - 1):
                raise GenerationError("BILLING_EVIDENCE_INVALID")
            existing=db.execute("SELECT * FROM billing_events WHERE event_key=?",(event_key,)).fetchone()
            if existing:
                if (existing["task_id"],existing["evidence_sha256"],existing["actual_cost_micros"]) != (
                        task_id,evidence_sha256,amount):
                    raise Conflict("BILLING_EVENT_KEY_CONFLICT")
                return {"task_id":task_id,"event_key":event_key,"actual_cost_micros":amount,
                        "idempotent":True}
            for prior in db.execute("SELECT evidence_path,evidence_sha256 FROM billing_events WHERE task_id=?",
                                    (task_id,)):
                if not Path(prior["evidence_path"]).is_file() or _sha_file(prior["evidence_path"]) != prior["evidence_sha256"]:
                    raise Conflict("PRIOR_BILLING_EVIDENCE_CHANGED")
            previous=db.execute("SELECT actual_cost_micros FROM billing_events WHERE task_id=? ORDER BY rowid DESC LIMIT 1",
                                (task_id,)).fetchone()
            baseline=(previous["actual_cost_micros"] if previous else
                      task["actual_cost_micros"] if task["actual_cost_micros"] is not None else 0)
            delta=amount-baseline
            release=task["reserved_micros"] if previous is None else 0
            if budget["spent_micros"]+delta < 0 or budget["spent_micros"]+delta > 2**63-1:
                raise GenerationError("BUDGET_ACCOUNTING_OVERFLOW")
            db.execute("UPDATE budgets SET reserved_micros=reserved_micros-?,spent_micros=spent_micros+? WHERE budget_key=?",
                       (release,delta,task["budget_key"]))
            violation=bool(task["hard_cost_cap"] and amount>task["max_cost_micros"])
            local_overage=bool(not task["hard_cost_cap"] and amount>task["max_cost_micros"])
            db.execute("UPDATE tasks SET reserved_micros=0,actual_cost_micros=?,last_error=?,updated_at=? WHERE task_id=?",
                       (amount,"PROVIDER_EXCEEDED_HARD_COST_CAP" if violation else
                        "LOCAL_RESERVATION_EXCEEDED" if local_overage else None,_now(),task_id))
            db.execute("""INSERT INTO billing_events(event_key,task_id,evidence_path,evidence_sha256,
                       currency,actual_cost_micros,recorded_at) VALUES(?,?,?,?,?,?,?)""",
                       (event_key,task_id,str(path),evidence_sha256,budget["currency"],amount,_now()))
            self._event(db,task_id,"billing_reconcile",task["state"],task["state"],
                        {"event_key":event_key,"evidence_sha256":evidence_sha256,
                         "actual_cost_micros":amount,"correction":previous is not None,
                         "hard_cap_violation":violation})
            return {"task_id":task_id,"event_key":event_key,"actual_cost_micros":amount,
                    "idempotent":False,"correction":previous is not None,
                    "hard_cap_violation":violation,"local_reservation_exceeded":local_overage}

    def record_result(self, task_id, receipt_path, receipt_sha256):
        """Import one recorded provider output; failed downloads may retry this step."""
        _hash(receipt_sha256,"RESULT_RECEIPT_SHA256")
        receipt_file=Path(receipt_path).resolve(strict=True)
        if not receipt_file.is_file() or _sha_file(receipt_file) != receipt_sha256:
            raise Conflict("RESULT_RECEIPT_HASH_MISMATCH")
        receipt=json.loads(receipt_file.read_text(encoding="utf-8"))
        if not isinstance(receipt,dict) or receipt.get("schema") != "generation-output-receipt/1":
            raise GenerationError("RESULT_RECEIPT_INVALID")
        _hash(receipt.get("result_sha256"),"RESULT_SHA256")
        if not isinstance(receipt.get("result_path"),str) or not receipt["result_path"]:
            raise GenerationError("RESULT_PATH_INVALID")
        result_file=Path(receipt.get("result_path","")).resolve(strict=True)
        if not result_file.is_file() or _sha_file(result_file) != receipt["result_sha256"]:
            raise Conflict("RESULT_HASH_MISMATCH")
        if (receipt.get("source_kind") not in ("provider-download","explicit-import") or
                not isinstance(receipt.get("source_ref"),str) or not receipt["source_ref"].strip()):
            raise GenerationError("RESULT_SOURCE_INVALID")
        _word(receipt.get("attempt_key"),"OUTPUT_ATTEMPT_KEY")
        with self._write() as db:
            task=self._task(db,task_id)
            attempt=db.execute("SELECT * FROM output_attempts WHERE attempt_key=?",
                               (receipt["attempt_key"],)).fetchone()
            if (not attempt or attempt["task_id"] != task_id or
                    attempt["provider_output_id"] != task["provider_output_id"] or
                    attempt["source_kind"] != receipt["source_kind"] or
                    attempt["source_ref"] != receipt["source_ref"]):
                raise Conflict("RESULT_RECEIPT_ATTEMPT_MISMATCH")
            if (task["state"] == "VERIFIED" and task["result_receipt_path"] == str(receipt_file)
                    and task["result_receipt_sha256"] == receipt_sha256):
                self._verify_result_chain(task,db)
                return self._public(task)
            if (task["state"] == "VERIFIED" and task["result_path"] == str(result_file)
                    and task["result_sha256"] == receipt["result_sha256"]):
                self._verify_result_chain(task,db)
                if attempt["state"] != "STARTED":
                    raise Conflict("OUTPUT_ATTEMPT_ALREADY_TERMINAL")
                db.execute("""UPDATE output_attempts SET state='COMPLETE',receipt_sha256=?,
                           result_sha256=?,completed_at=? WHERE attempt_key=?""",
                           (receipt_sha256,receipt["result_sha256"],_now(),receipt["attempt_key"]))
                self._event(db,task_id,"output_attempt_recovered",task["state"],task["state"],
                            {"attempt_key":receipt["attempt_key"],"receipt_sha256":receipt_sha256})
                return self._public(task)
            if task["state"] not in ("AWAITING_RESULT","VERIFIED") or task["cancel_requested"]:
                raise NotReady("RESULT_NOT_ADOPTABLE_IN_TASK_STATE")
            if (not task["provider_output_id"] or not task["provider_response_sha256"] or
                    not task["provider_response_path"] or not task["provider_task_id"]):
                raise Conflict("PROVIDER_OUTPUT_IDENTITY_REQUIRED")
            if attempt["state"] != "STARTED":
                raise Conflict("OUTPUT_ATTEMPT_ALREADY_TERMINAL")
            if (receipt.get("task_id") != task_id or
                    receipt.get("provider_id") != task["provider_id"] or
                    receipt.get("provider_task_id") != task["provider_task_id"] or
                    receipt.get("provider_output_id") != task["provider_output_id"] or
                    receipt.get("provider_response_sha256") != task["provider_response_sha256"] or
                    receipt.get("provider_output_checksum_sha256") != task["provider_output_checksum_sha256"] or
                    str(Path(receipt.get("result_path", "")).resolve(strict=True)) != str(result_file)):
                raise Conflict("RESULT_RECEIPT_OUTPUT_IDENTITY_MISMATCH")
            if _sha_file(task["provider_response_path"]) != task["provider_response_sha256"]:
                raise Conflict("PROVIDER_RESPONSE_HASH_CHANGED")
            if _sha_file(receipt_file) != receipt_sha256 or _sha_file(result_file) != receipt["result_sha256"]:
                raise Conflict("RESULT_HASH_CHANGED")
            service_digest=task["provider_output_checksum_sha256"]
            if service_digest and receipt["result_sha256"] != service_digest:
                raise Conflict("PROVIDER_OUTPUT_CHECKSUM_MISMATCH")
            if task["result_sha256"] and receipt["result_sha256"] != task["result_sha256"]:
                raise Conflict("FIRST_RESULT_BASELINE_MISMATCH")
            hash_source="PROVIDER_SHA256" if service_digest else "LOCAL_FIRST_BASELINE"
            old=task["state"]
            db.execute("""UPDATE tasks SET state='VERIFIED',result_path=?,result_sha256=?,
                       result_receipt_path=?,result_receipt_sha256=?,result_hash_source=?,updated_at=?
                       WHERE task_id=?""",
                       (str(result_file),receipt["result_sha256"],str(receipt_file),receipt_sha256,
                        hash_source,_now(),task_id))
            db.execute("""UPDATE output_attempts SET state='COMPLETE',receipt_sha256=?,
                       result_sha256=?,completed_at=? WHERE attempt_key=?""",
                       (receipt_sha256,receipt["result_sha256"],_now(),receipt["attempt_key"]))
            self._event(db,task_id,"record_result",old,"VERIFIED",
                        {"attempt_key":receipt["attempt_key"],
                         "provider_output_id":task["provider_output_id"],
                         "provider_response_sha256":task["provider_response_sha256"],
                         "receipt_sha256":receipt_sha256,"result_sha256":receipt["result_sha256"],
                         "hash_source":hash_source})
            return self._public(self._task(db,task_id))

    def record_review(self, task_id, candidate_path, candidate_sha256, review_path, review_sha256):
        """Record an explicit complex-layer accept/reject decision, not a model success."""
        _hash(candidate_sha256,"CANDIDATE_SHA256")
        _hash(review_sha256,"REVIEW_SHA256")
        candidate_file=Path(candidate_path).resolve(strict=True)
        review_file=Path(review_path).resolve(strict=True)
        if _sha_file(candidate_file) != candidate_sha256 or _sha_file(review_file) != review_sha256:
            raise Conflict("CANDIDATE_OR_REVIEW_HASH_MISMATCH")
        review=json.loads(review_file.read_text())
        if (not isinstance(review,dict) or review.get("schema") != "generation-candidate-review/1"
                or review.get("task_id") != task_id or review.get("candidate_sha256") != candidate_sha256
                or not isinstance(review.get("result_receipt_sha256"),str)
                or not isinstance(review.get("provider_output_id"),str)
                or review.get("decision") not in ("ACCEPT","REJECT")
                or not isinstance(review.get("rationale"),str) or not review["rationale"].strip()):
            raise GenerationError("REVIEW_RECORD_INVALID")
        with self._write() as db:
            task=self._task(db,task_id)
            if task["state"] != "VERIFIED" or task["cancel_requested"]:
                raise NotReady("TASK_RESULT_NOT_REVIEWABLE")
            self._verify_result_chain(task,db)
            if (review.get("result_sha256") != task["result_sha256"] or
                    review.get("result_receipt_sha256") != task["result_receipt_sha256"] or
                    review.get("provider_output_id") != task["provider_output_id"]):
                raise Conflict("REVIEW_RESULT_MISMATCH")
            existing=db.execute("SELECT * FROM candidate_reviews WHERE task_id=? AND candidate_sha256=?",
                                (task_id,candidate_sha256)).fetchone()
            if existing:
                if existing["review_path"] != str(review_file) or existing["review_sha256"] != review_sha256:
                    raise Conflict("CANDIDATE_REVIEW_ALREADY_RECORDED")
                return dict(existing)
            db.execute("""INSERT INTO candidate_reviews(task_id,candidate_sha256,decision,review_path,
                       review_sha256,result_sha256,recorded_at) VALUES(?,?,?,?,?,?,?)""",
                       (task_id,candidate_sha256,review["decision"],str(review_file),review_sha256,
                        task["result_sha256"],_now()))
            self._event(db,task_id,"candidate_review",task["state"],task["state"],
                        {"decision":review["decision"],"candidate_sha256":candidate_sha256})
            return dict(db.execute("SELECT * FROM candidate_reviews WHERE task_id=? AND candidate_sha256=?",
                                   (task_id,candidate_sha256)).fetchone())

    def adoption_gate(self, task_id, current_work, candidate_path, candidate_sha256):
        """Validate a Work candidate; does not commit or claim user acceptance."""
        _hash(candidate_sha256,"CANDIDATE_SHA256")
        candidate_file=Path(candidate_path).resolve(strict=True)
        if _sha_file(candidate_file) != candidate_sha256:
            raise Conflict("CANDIDATE_HASH_MISMATCH")
        candidate=json.loads(candidate_file.read_text())
        if not isinstance(current_work,dict) or set(current_work)!={"work_id","version","document_sha256"}:
            raise GenerationError("CURRENT_WORK_BINDING_INVALID")
        with self._connection() as db:
            task=self._task(db,task_id)
            if task["state"] != "VERIFIED" or task["cancel_requested"]:
                raise NotReady("TASK_RESULT_NOT_ADOPTABLE")
            if task["hard_cost_cap"] and task["actual_cost_micros"] is not None and task["actual_cost_micros"]>task["max_cost_micros"]:
                raise NotReady("PROVIDER_HARD_COST_CAP_VIOLATION")
            expected={"work_id":task["work_id"],"version":task["work_version"],
                      "document_sha256":task["work_document_sha256"]}
            if current_work != expected:
                raise Conflict("WORK_HEAD_CHANGED")
            self._verify_result_chain(task,db)
            if candidate.get("schema") != "work-candidate/1" or candidate.get("base_version") != task["work_version"] or candidate.get("base_document_sha256") != task["work_document_sha256"]:
                raise Conflict("CANDIDATE_BASE_CONFLICT")
            def refs(value):
                if isinstance(value,dict):
                    if value.get("path") == task["result_path"] and value.get("sha256") == task["result_sha256"]:
                        return True
                    return any(refs(x) for x in value.values())
                if isinstance(value,list):
                    return any(refs(x) for x in value)
                return False
            if not refs(candidate.get("document")):
                raise Conflict("CANDIDATE_DOES_NOT_REFERENCE_VERIFIED_RESULT")
            review=db.execute("SELECT * FROM candidate_reviews WHERE task_id=? AND candidate_sha256=?",
                              (task_id,candidate_sha256)).fetchone()
            if review is None or review["decision"] != "ACCEPT":
                raise NotReady("EXPLICIT_ACCEPTED_REVIEW_REQUIRED")
            if _sha_file(review["review_path"]) != review["review_sha256"] or review["result_sha256"] != task["result_sha256"]:
                raise Conflict("ACCEPTED_REVIEW_HASH_CHANGED")
            review_content=json.loads(Path(review["review_path"]).read_text(encoding="utf-8"))
            if (review_content.get("result_receipt_sha256") != task["result_receipt_sha256"] or
                    review_content.get("provider_output_id") != task["provider_output_id"]):
                raise Conflict("ACCEPTED_REVIEW_OUTPUT_IDENTITY_CHANGED")
            return {"schema":"generation-adoption-gate/1","task_id":task_id,
                    "intent_sha256":task["intent_sha256"],"result_sha256":task["result_sha256"],
                    "provider_task_id":task["provider_task_id"],
                    "provider_output_id":task["provider_output_id"],
                    "provider_response_sha256":task["provider_response_sha256"],
                    "result_receipt_sha256":task["result_receipt_sha256"],
                    "result_hash_source":task["result_hash_source"],
                    "candidate_sha256":candidate_sha256,"review_sha256":review["review_sha256"],
                    "expected_work":expected,
                    "status":"READY_FOR_WORK_VERSION_CAS_ONLY","publishable":False,
                    "note":"Caller must recheck this gate and use work-version commit CAS; no media or human review is implied."}
