"""Durable, one-attempt DeepSeek Chat Completions text/function caller.

This is a general model interface, not a generation-task ProviderAdapter. DeepSeek
does not document the hard monetary cap or idempotency lookup required there.
No request is made on import. Tool calls are returned as data, never executed.
"""
import hashlib
import json
import os
from contextlib import contextmanager
from pathlib import Path
import sqlite3
from urllib import error, request
from urllib.parse import urlsplit
from uuid import uuid4


API_BASE = "https://api.deepseek.com"


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class DeepSeekError(ValueError):
    pass


class OutcomeUnknown(DeepSeekError):
    pass


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _validate_body(body):
    if not isinstance(body, dict) or set(body) - {"model", "messages", "max_tokens", "tools", "tool_choice", "thinking", "reasoning_effort", "temperature", "top_p", "response_format"}:
        raise DeepSeekError("REQUEST_FIELDS_UNSUPPORTED")
    if not isinstance(body.get("model"), str) or not body["model"].strip():
        raise DeepSeekError("MODEL_REQUIRED")
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise DeepSeekError("MESSAGES_REQUIRED")
    if type(body.get("max_tokens")) is not int or not 1 <= body["max_tokens"] <= 393216:
        raise DeepSeekError("MAX_TOKENS_REQUIRED")
    if "tools" in body and (not isinstance(body["tools"], list) or
                            any(not isinstance(t, dict) or t.get("type") != "function" for t in body["tools"])):
        raise DeepSeekError("ONLY_FUNCTION_TOOLS_SUPPORTED")
    if "thinking" in body and body["thinking"] not in ({"type": "enabled"}, {"type": "disabled"}):
        raise DeepSeekError("THINKING_INVALID")
    if "reasoning_effort" in body and body["reasoning_effort"] not in ("low", "high", "max"):
        raise DeepSeekError("REASONING_EFFORT_INVALID")
    # Unknown input fields are rejected instead of relying on silent provider ignores.
    return dict(body, stream=False)


class DeepSeekTextClient:
    provider_id = "deepseek"

    def __init__(self, api_key=None, base_url=API_BASE, timeout_seconds=120,
                 allow_custom_endpoint=False):
        if not isinstance(base_url, str):
            raise DeepSeekError("HTTPS_BASE_URL_REQUIRED")
        parsed = urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
                parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
            raise DeepSeekError("HTTPS_BASE_URL_REQUIRED")
        normalized = base_url.rstrip("/")
        if normalized != API_BASE:
            if allow_custom_endpoint is not True:
                raise DeepSeekError("CUSTOM_ENDPOINT_EXPLICIT_OPT_IN_REQUIRED")
            if not isinstance(api_key, str) or not api_key:
                raise DeepSeekError("CUSTOM_ENDPOINT_EXPLICIT_KEY_REQUIRED")
            self.api_key = api_key
        else:
            self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise DeepSeekError("DEEPSEEK_API_KEY_REQUIRED")
        self.base_url = normalized
        if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
            raise DeepSeekError("TIMEOUT_INVALID")
        self.timeout_seconds = timeout_seconds

    def send(self, body):
        """One HTTP attempt. Caller must persist UNKNOWN before invoking this."""
        payload = _validate_body(body)
        req = request.Request(
            self.base_url + "/chat/completions", data=_json(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + self.api_key,
                     "Content-Type": "application/json"}, method="POST")
        try:
            with request.build_opener(_NoRedirect()).open(req, timeout=self.timeout_seconds) as response:
                data = response.read(32 * 1024 * 1024 + 1)
        except error.HTTPError as exc:
            # No response body is surfaced: it may echo prompts or credentials.
            raise DeepSeekError("HTTP_STATUS_" + str(exc.code)) from None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise OutcomeUnknown(type(exc).__name__) from None
        if len(data) > 32 * 1024 * 1024:
            raise OutcomeUnknown("RESPONSE_TOO_LARGE")
        try:
            parsed = json.loads(data)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OutcomeUnknown("RESPONSE_INVALID_JSON") from None
        if (not isinstance(parsed, dict) or not isinstance(parsed.get("choices"), list)
                or not parsed["choices"] or not isinstance(parsed["choices"][0], dict)
                or not isinstance(parsed["choices"][0].get("message"), dict)):
            raise OutcomeUnknown("RESPONSE_INVALID_SHAPE")
        choice = parsed["choices"][0]
        # Preserve tool-call arguments as untrusted data; executing tools is the host's job.
        return {"id": parsed.get("id"), "model": parsed.get("model"),
                "finish_reason": choice.get("finish_reason"),
                "message": choice["message"], "usage": parsed.get("usage"),
                "response_sha256": hashlib.sha256(data).hexdigest()}


class DeepSeekCallStore:
    """Local one-shot ledger. Reservation is accounting, not a server-side cost cap.

    All reservations remain held until an independently verified billing procedure
    settles them. Even a 4xx/5xx is treated as unresolved for budget purposes.
    """
    def __init__(self, database_path):
        self.path = Path(database_path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)
        with self._db() as db:
            version = db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 2):
                raise DeepSeekError("TEXT_LEDGER_SCHEMA_UNSUPPORTED")
            if version == 0 and db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calls'").fetchone():
                raise DeepSeekError("TEXT_LEDGER_LEGACY_ENDPOINT_UNFROZEN")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS budget(
                    budget_key TEXT PRIMARY KEY, currency TEXT NOT NULL,
                    limit_micros INTEGER NOT NULL, reserved_micros INTEGER NOT NULL DEFAULT 0,
                    spent_micros INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS calls(
                    call_id TEXT PRIMARY KEY, intent_key TEXT NOT NULL UNIQUE,
                    provider_id TEXT NOT NULL, endpoint TEXT NOT NULL, model TEXT NOT NULL,
                    body_json TEXT NOT NULL, body_sha256 TEXT NOT NULL,
                    budget_key TEXT NOT NULL, reservation_micros INTEGER NOT NULL,
                    state TEXT NOT NULL, attempt_count INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT, error_type TEXT,
                    FOREIGN KEY(budget_key) REFERENCES budget(budget_key));
                CREATE TABLE IF NOT EXISTS billing_events(
                    event_key TEXT PRIMARY KEY, call_id TEXT NOT NULL,
                    evidence_path TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
                    currency TEXT NOT NULL, actual_cost_micros INTEGER NOT NULL,
                    recorded_at TEXT NOT NULL,
                    FOREIGN KEY(call_id) REFERENCES calls(call_id));
            """)
            db.execute("PRAGMA user_version=2")

    @contextmanager
    def _db(self):
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
            raise DeepSeekError("DEEPSEEK_STORE_ERROR: " + str(exc)) from exc
        finally:
            if db is not None:
                db.close()

    def create_budget(self, key, currency, limit_micros):
        if (not isinstance(key, str) or not key or not isinstance(currency, str)
                or len(currency) != 3 or not currency.isupper() or type(limit_micros) is not int
                or not 0 < limit_micros <= 2**63 - 1):
            raise DeepSeekError("BUDGET_INVALID")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM budget WHERE budget_key=?", (key,)).fetchone()
            if row and (row["currency"] != currency or row["limit_micros"] != limit_micros):
                raise DeepSeekError("BUDGET_CONFLICT")
            if row is None:
                db.execute("INSERT INTO budget(budget_key,currency,limit_micros) VALUES(?,?,?)",
                           (key, currency, limit_micros))

    def prepare(self, intent_key, body, budget_key, reservation_micros,
                endpoint=API_BASE, provider_id="deepseek"):
        safe_body = _validate_body(body)
        safe_body.pop("stream")
        if provider_id != "deepseek" or not isinstance(endpoint, str) or not endpoint.startswith("https://"):
            raise DeepSeekError("PROVIDER_OR_ENDPOINT_INVALID")
        endpoint = endpoint.rstrip("/")
        if (not isinstance(intent_key, str) or not intent_key or
                type(reservation_micros) is not int or
                not 0 < reservation_micros <= 2**63 - 1):
            raise DeepSeekError("INTENT_OR_RESERVATION_INVALID")
        body_hash = _digest({"provider_id":provider_id,"endpoint":endpoint,"body":safe_body})
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM calls WHERE intent_key=?", (intent_key,)).fetchone()
            if row:
                if (row["body_sha256"], row["budget_key"], row["reservation_micros"],
                    row["endpoint"], row["provider_id"], row["model"]) != (
                        body_hash, budget_key, reservation_micros, endpoint, provider_id, safe_body["model"]):
                    raise DeepSeekError("INTENT_KEY_CONFLICT")
                return self.read(row["call_id"])
            if not db.execute("SELECT 1 FROM budget WHERE budget_key=?", (budget_key,)).fetchone():
                raise DeepSeekError("BUDGET_NOT_FOUND")
            call_id = str(uuid4())
            db.execute("""INSERT INTO calls(call_id,intent_key,provider_id,endpoint,model,body_json,
                       body_sha256,budget_key,reservation_micros,state) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                       (call_id, intent_key, provider_id, endpoint, safe_body["model"],
                        _json(safe_body), body_hash, budget_key, reservation_micros, "PREPARED"))
            return {"call_id": call_id, "state": "PREPARED", "body_sha256": body_hash}

    def read(self, call_id):
        with self._db() as db:
            row = db.execute("SELECT * FROM calls WHERE call_id=?", (call_id,)).fetchone()
            if not row:
                raise DeepSeekError("CALL_NOT_FOUND")
            # Prompt and result content are omitted from status reads.
            return {key: row[key] for key in ("call_id", "intent_key", "provider_id",
                    "endpoint", "model", "body_sha256", "budget_key", "reservation_micros",
                    "state", "attempt_count", "error_type")}

    def result(self, call_id):
        with self._db() as db:
            row = db.execute("SELECT state,result_json FROM calls WHERE call_id=?", (call_id,)).fetchone()
            if not row or row["state"] != "COMPLETE":
                raise DeepSeekError("RESULT_NOT_AVAILABLE")
            return json.loads(row["result_json"])

    def send_once(self, call_id, client):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM calls WHERE call_id=?", (call_id,)).fetchone()
            if not row:
                raise DeepSeekError("CALL_NOT_FOUND")
            if row["state"] != "PREPARED":
                return self.read(call_id)
            if (getattr(client, "provider_id", None) != row["provider_id"] or
                    getattr(client, "base_url", None) != row["endpoint"] or
                    not callable(getattr(client, "send", None))):
                raise DeepSeekError("FROZEN_ENDPOINT_MISMATCH")
            budget = db.execute("SELECT * FROM budget WHERE budget_key=?",
                                (row["budget_key"],)).fetchone()
            if row["reservation_micros"] > budget["limit_micros"] - budget["reserved_micros"] - budget["spent_micros"]:
                raise DeepSeekError("BUDGET_EXHAUSTED")
            db.execute("UPDATE budget SET reserved_micros=reserved_micros+? WHERE budget_key=?",
                       (row["reservation_micros"], row["budget_key"]))
            db.execute("UPDATE calls SET state='UNKNOWN_SUBMISSION',attempt_count=1 WHERE call_id=?",
                       (call_id,))
            body = json.loads(row["body_json"])
        try:
            result = client.send(body)
        except Exception as exc:
            with self._db() as db:
                db.execute("UPDATE calls SET error_type=? WHERE call_id=?",
                           (type(exc).__name__, call_id))
            return self.read(call_id)
        with self._db() as db:
            db.execute("UPDATE calls SET state='COMPLETE',result_json=?,error_type=NULL WHERE call_id=? AND state='UNKNOWN_SUBMISSION'",
                       (_json(result), call_id))
        return self.read(call_id)

    def settle_cost(self, call_id, event_key, evidence_path, evidence_sha256):
        """Record human-verified bill or correction; never reopens the HTTP call."""
        if not isinstance(event_key, str) or not event_key:
            raise DeepSeekError("BILLING_EVENT_KEY_REQUIRED")
        path = Path(evidence_path).resolve(strict=True)
        if not path.is_file():
            raise DeepSeekError("BILLING_EVIDENCE_HASH_MISMATCH")
        evidence_bytes = path.read_bytes()
        if hashlib.sha256(evidence_bytes).hexdigest() != evidence_sha256:
            raise DeepSeekError("BILLING_EVIDENCE_HASH_MISMATCH")
        evidence = json.loads(evidence_bytes.decode("utf-8"))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM calls WHERE call_id=?", (call_id,)).fetchone()
            if not row or row["state"] == "PREPARED":
                raise DeepSeekError("CALL_NOT_SENT")
            budget = db.execute("SELECT * FROM budget WHERE budget_key=?", (row["budget_key"],)).fetchone()
            amount = evidence.get("actual_cost_micros") if isinstance(evidence, dict) else None
            if (not isinstance(evidence, dict) or evidence.get("schema") != "deepseek-billing-evidence/1"
                    or evidence.get("call_id") != call_id or evidence.get("body_sha256") != row["body_sha256"]
                    or evidence.get("provider_id") != row["provider_id"]
                    or evidence.get("endpoint") != row["endpoint"] or evidence.get("model") != row["model"]
                    or evidence.get("currency") != budget["currency"]
                    or not isinstance(evidence.get("source_ref"), str) or not evidence["source_ref"].strip()
                    or type(amount) is not int or not 0 <= amount <= 2**63 - 1):
                raise DeepSeekError("BILLING_EVIDENCE_INVALID")
            existing = db.execute("SELECT * FROM billing_events WHERE event_key=?", (event_key,)).fetchone()
            if existing:
                if (existing["call_id"], existing["evidence_sha256"], existing["actual_cost_micros"]) != (
                        call_id, evidence_sha256, amount):
                    raise DeepSeekError("BILLING_EVENT_KEY_CONFLICT")
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != evidence_sha256:
                    raise DeepSeekError("BILLING_EVIDENCE_HASH_MISMATCH")
                return {"call_id":call_id,"event_key":event_key,"actual_cost_micros":amount,
                        "idempotent":True}
            for prior in db.execute("SELECT evidence_path,evidence_sha256 FROM billing_events WHERE call_id=?",
                                    (call_id,)):
                prior_file = Path(prior["evidence_path"])
                if (not prior_file.is_file() or
                        hashlib.sha256(prior_file.read_bytes()).hexdigest() != prior["evidence_sha256"]):
                    raise DeepSeekError("PRIOR_BILLING_EVIDENCE_CHANGED")
            previous = db.execute("SELECT actual_cost_micros FROM billing_events WHERE call_id=? ORDER BY rowid DESC LIMIT 1",
                                  (call_id,)).fetchone()
            delta = amount - (previous["actual_cost_micros"] if previous else 0)
            if budget["spent_micros"] + delta < 0 or budget["spent_micros"] + delta > 2**63 - 1:
                raise DeepSeekError("BUDGET_ACCOUNTING_OVERFLOW")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != evidence_sha256:
                raise DeepSeekError("BILLING_EVIDENCE_HASH_MISMATCH")
            db.execute("UPDATE budget SET reserved_micros=reserved_micros-?,spent_micros=spent_micros+? WHERE budget_key=?",
                       (row["reservation_micros"] if previous is None else 0, delta, row["budget_key"]))
            db.execute("INSERT INTO billing_events(event_key,call_id,evidence_path,evidence_sha256,currency,actual_cost_micros,recorded_at) VALUES(?,?,?,?,?,?,datetime('now'))",
                       (event_key,call_id,str(path),evidence_sha256,budget["currency"],amount))
            return {"call_id":call_id,"event_key":event_key,"actual_cost_micros":amount,
                    "idempotent":False,"correction":previous is not None}
