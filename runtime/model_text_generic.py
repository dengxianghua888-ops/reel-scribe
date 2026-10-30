"""Durable OpenAI-compatible text/function calls from host-owned provider profiles.

No network on import. A call is persisted as UNKNOWN before one HTTP attempt.
No unknown call can be retried by this interface. Media generation is out of scope.
"""
import hashlib
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
import re
import sqlite3
from urllib import error, request
from urllib.parse import urlsplit
from uuid import uuid4


DEFAULT_ENDPOINT = "https://api.deepseek.com"
PROFILE_CONFIG_ENV = "EDITING_TEXT_PROVIDER_PROFILES_PATH"


class ModelTextError(ValueError):
    pass


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def validate_endpoint(value):
    if not isinstance(value, str):
        raise ModelTextError("PROFILE_ENDPOINT_INVALID")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or
            parsed.password or parsed.query or parsed.fragment or
            not re.fullmatch(r"(?:/[A-Za-z0-9._~-]+)*/*", parsed.path)):
        raise ModelTextError("PROFILE_ENDPOINT_INVALID")
    return value.rstrip("/")


@dataclass(frozen=True)
class TextProfile:
    profile_id: str
    provider_id: str
    endpoint: str
    model: str
    credential_env: str
    allow_custom_endpoint: bool
    profile_sha256: str

    @classmethod
    def from_dict(cls, value):
        expected = {"profile_id", "provider_id", "endpoint", "model",
                    "credential_env", "allow_custom_endpoint"}
        if not isinstance(value, dict) or set(value) != expected:
            raise ModelTextError("PROFILE_FIELDS_INVALID")
        for key in ("profile_id", "provider_id", "model"):
            if not isinstance(value[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./:@-]{0,127}", value[key]):
                raise ModelTextError("PROFILE_ID_OR_MODEL_INVALID")
        endpoint = validate_endpoint(value["endpoint"])
        credential_env = value["credential_env"]
        if not isinstance(credential_env, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{2,63}_(?:API_KEY|TOKEN)", credential_env):
            raise ModelTextError("CREDENTIAL_ENV_NAME_INVALID")
        if type(value["allow_custom_endpoint"]) is not bool:
            raise ModelTextError("CUSTOM_ENDPOINT_FLAG_INVALID")
        if endpoint != DEFAULT_ENDPOINT and not value["allow_custom_endpoint"]:
            raise ModelTextError("CUSTOM_ENDPOINT_EXPLICIT_OPT_IN_REQUIRED")
        if endpoint != DEFAULT_ENDPOINT and credential_env == "DEEPSEEK_API_KEY":
            raise ModelTextError("DEEPSEEK_KEY_CUSTOM_ENDPOINT_FORBIDDEN")
        if credential_env == "DEEPSEEK_API_KEY" and value["provider_id"] != "deepseek":
            raise ModelTextError("DEEPSEEK_KEY_PROVIDER_MISMATCH")
        frozen = dict(value, endpoint=endpoint)
        return cls(**frozen, profile_sha256=digest(frozen))


class ProfileRegistry:
    """Only the host chooses the optional profile file path through environment."""
    def __init__(self, profile_file=None):
        default = TextProfile.from_dict({"profile_id":"deepseek-default",
            "provider_id":"deepseek","endpoint":DEFAULT_ENDPOINT,
            "model":"deepseek-flash","credential_env":"DEEPSEEK_API_KEY",
            "allow_custom_endpoint":False})
        self.profiles = {default.profile_id: default}
        path = profile_file if profile_file is not None else os.environ.get(PROFILE_CONFIG_ENV)
        if path is None:
            return
        file = Path(path)
        if not file.is_absolute() or not file.is_file():
            raise ModelTextError("ABSOLUTE_HOST_PROFILE_FILE_REQUIRED")
        config = json.loads(file.read_text(encoding="utf-8"))
        if not isinstance(config, dict) or set(config) != {"schema", "profiles"} or config["schema"] != "model-text-profiles/1" or not isinstance(config["profiles"], list):
            raise ModelTextError("PROFILE_CONFIG_INVALID")
        for item in config["profiles"]:
            profile = TextProfile.from_dict(item)
            if profile.profile_id in self.profiles:
                raise ModelTextError("PROFILE_ID_DUPLICATE")
            self.profiles[profile.profile_id] = profile

    def get(self, profile_id, expected_sha256=None):
        profile = self.profiles.get(profile_id)
        if profile is None:
            raise ModelTextError("PROFILE_NOT_CONFIGURED")
        if expected_sha256 is not None and profile.profile_sha256 != expected_sha256:
            raise ModelTextError("PROFILE_CONFIG_HASH_CHANGED")
        return profile

    def public(self):
        return [{"profile_id":p.profile_id,"provider_id":p.provider_id,
                 "endpoint":p.endpoint,"model":p.model,"profile_sha256":p.profile_sha256}
                for p in self.profiles.values()]


def validate_body(body, profile):
    allowed = {"messages", "max_tokens", "tools", "tool_choice", "temperature",
               "top_p", "response_format"}
    if profile.provider_id == "deepseek":
        allowed |= {"thinking", "reasoning_effort"}
    if not isinstance(body, dict) or set(body) - allowed:
        raise ModelTextError("MODEL_BODY_FIELDS_INVALID")
    if not isinstance(body.get("messages"), list) or not body["messages"]:
        raise ModelTextError("MESSAGES_REQUIRED")
    if type(body.get("max_tokens")) is not int or body["max_tokens"] <= 0:
        raise ModelTextError("MAX_TOKENS_REQUIRED")
    if "tools" in body and (not isinstance(body["tools"], list) or any(
            not isinstance(tool, dict) or tool.get("type") != "function" for tool in body["tools"])):
        raise ModelTextError("ONLY_FUNCTION_TOOLS_SUPPORTED")
    if "thinking" in body and body["thinking"] not in ({"type":"enabled"},{"type":"disabled"}):
        raise ModelTextError("THINKING_INVALID")
    if "reasoning_effort" in body and body["reasoning_effort"] not in ("low","high","max"):
        raise ModelTextError("REASONING_EFFORT_INVALID")
    return dict(body, model=profile.model, stream=False)


class OpenAICompatibleTextClient:
    def __init__(self, profile, timeout_seconds=120):
        if not isinstance(profile, TextProfile):
            raise ModelTextError("PROFILE_REQUIRED")
        key = os.environ.get(profile.credential_env)
        if not key:
            raise ModelTextError("PROFILE_CREDENTIAL_UNAVAILABLE")
        if not isinstance(timeout_seconds, (int,float)) or timeout_seconds <= 0:
            raise ModelTextError("TIMEOUT_INVALID")
        self.profile = profile
        self.provider_id = profile.provider_id
        self.base_url = profile.endpoint
        self._key = key
        self.timeout_seconds = timeout_seconds
        self._opener = request.build_opener(_NoRedirect())

    def send(self, body):
        if not isinstance(body,dict) or body.get("model") != self.profile.model or body.get("stream") is not False:
            raise ModelTextError("FROZEN_MODEL_BODY_MISMATCH")
        payload = validate_body({k:v for k,v in body.items() if k not in ("model","stream")},self.profile)
        req = request.Request(self.base_url + "/chat/completions",
            data=canonical(payload).encode("utf-8"), method="POST",
            headers={"Authorization":"Bearer " + self._key,
                     "Content-Type":"application/json"})
        try:
            with self._opener.open(req, timeout=self.timeout_seconds) as response:
                raw = response.read(32*1024*1024+1)
        except error.HTTPError as exc:
            raise ModelTextError("HTTP_STATUS_" + str(exc.code)) from None
        except (error.URLError, TimeoutError, OSError) as exc:
            raise ModelTextError("OUTCOME_UNKNOWN_" + type(exc).__name__) from None
        if len(raw) > 32*1024*1024:
            raise ModelTextError("RESPONSE_TOO_LARGE_OUTCOME_UNKNOWN")
        try:
            value = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ModelTextError("RESPONSE_INVALID_OUTCOME_UNKNOWN") from None
        if (not isinstance(value, dict) or not isinstance(value.get("choices"), list)
                or not value["choices"] or not isinstance(value["choices"][0], dict)
                or not isinstance(value["choices"][0].get("message"), dict)):
            raise ModelTextError("RESPONSE_SHAPE_UNKNOWN")
        choice=value["choices"][0]
        return {"id":value.get("id"),"model":value.get("model"),
                "finish_reason":choice.get("finish_reason"),"message":choice["message"],
                "usage":value.get("usage"),"response_sha256":hashlib.sha256(raw).hexdigest()}


class TextCallStore:
    def __init__(self, database_path):
        self.path=Path(database_path).resolve()
        self.path.parent.mkdir(parents=True,exist_ok=True)
        if not self.path.exists():
            self.path.touch(mode=0o600)
        with self._db() as db:
            version=db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0,1):
                raise ModelTextError("MODEL_TEXT_SCHEMA_UNSUPPORTED")
            if version == 0 and db.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='calls'").fetchone():
                raise ModelTextError("UNVERSIONED_MODEL_TEXT_LEDGER_UNSAFE")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS budgets(
                    budget_key TEXT PRIMARY KEY,currency TEXT NOT NULL,
                    limit_micros INTEGER NOT NULL,reserved_micros INTEGER NOT NULL DEFAULT 0,
                    spent_micros INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS calls(
                    call_id TEXT PRIMARY KEY,intent_key TEXT NOT NULL UNIQUE,
                    profile_id TEXT NOT NULL,profile_sha256 TEXT NOT NULL,
                    provider_id TEXT NOT NULL,endpoint TEXT NOT NULL,model TEXT NOT NULL,
                    body_json TEXT NOT NULL,body_sha256 TEXT NOT NULL,
                    budget_key TEXT NOT NULL,reservation_micros INTEGER NOT NULL,
                    state TEXT NOT NULL,attempt_count INTEGER NOT NULL DEFAULT 0,
                    result_json TEXT,error_type TEXT,
                    FOREIGN KEY(budget_key) REFERENCES budgets(budget_key));
                CREATE TABLE IF NOT EXISTS billing_events(
                    event_key TEXT PRIMARY KEY,call_id TEXT NOT NULL,
                    evidence_path TEXT NOT NULL,evidence_sha256 TEXT NOT NULL,
                    actual_cost_micros INTEGER NOT NULL,recorded_at TEXT NOT NULL,
                    FOREIGN KEY(call_id) REFERENCES calls(call_id));
            """)
            db.execute("PRAGMA user_version=1")

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
            raise ModelTextError("MODEL_TEXT_STORE_ERROR: " + str(exc)) from exc
        finally:
            if db is not None:
                db.close()

    def budget_create(self,key,currency,limit_micros):
        if (not isinstance(key,str) or not key or not isinstance(currency,str)
                or not re.fullmatch(r"[A-Z]{3}",currency) or type(limit_micros) is not int
                or not 0 < limit_micros <= 2**63-1):
            raise ModelTextError("BUDGET_INVALID")
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing=db.execute("SELECT * FROM budgets WHERE budget_key=?",(key,)).fetchone()
            if existing and (existing["currency"],existing["limit_micros"]) != (currency,limit_micros):
                raise ModelTextError("BUDGET_CONFLICT")
            if existing is None:
                db.execute("INSERT INTO budgets(budget_key,currency,limit_micros) VALUES(?,?,?)",
                           (key,currency,limit_micros))
        return {"budget_key":key,"status":"CREATED_OR_MATCHED","hard_provider_cap":False}

    def prepare(self,intent_key,body,profile,budget_key,reservation_micros):
        if not isinstance(profile,TextProfile):
            raise ModelTextError("PROFILE_REQUIRED")
        frozen_body=validate_body(body,profile)
        if (not isinstance(intent_key,str) or not intent_key or
                type(reservation_micros) is not int or not 0 < reservation_micros <= 2**63-1):
            raise ModelTextError("INTENT_OR_RESERVATION_INVALID")
        body_hash=digest({"profile_sha256":profile.profile_sha256,"body":frozen_body})
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing=db.execute("SELECT * FROM calls WHERE intent_key=?",(intent_key,)).fetchone()
            if existing:
                if (existing["profile_sha256"],existing["body_sha256"],existing["budget_key"],
                    existing["reservation_micros"]) != (profile.profile_sha256,body_hash,budget_key,reservation_micros):
                    raise ModelTextError("INTENT_KEY_CONFLICT")
                return self.read(existing["call_id"])
            if not db.execute("SELECT 1 FROM budgets WHERE budget_key=?",(budget_key,)).fetchone():
                raise ModelTextError("BUDGET_NOT_FOUND")
            call_id=str(uuid4())
            db.execute("""INSERT INTO calls(call_id,intent_key,profile_id,profile_sha256,
                       provider_id,endpoint,model,body_json,body_sha256,budget_key,
                       reservation_micros,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,'PREPARED')""",
                       (call_id,intent_key,profile.profile_id,profile.profile_sha256,
                        profile.provider_id,profile.endpoint,profile.model,canonical(frozen_body),
                        body_hash,budget_key,reservation_micros))
        return self.read(call_id)

    def read(self,call_id):
        with self._db() as db:
            row=db.execute("SELECT * FROM calls WHERE call_id=?",(call_id,)).fetchone()
            if row is None:
                raise ModelTextError("CALL_NOT_FOUND")
            return {key:row[key] for key in ("call_id","intent_key","profile_id","profile_sha256",
                    "provider_id","endpoint","model","body_sha256","budget_key",
                    "reservation_micros","state","attempt_count","error_type")}

    def result(self,call_id):
        with self._db() as db:
            row=db.execute("SELECT state,result_json FROM calls WHERE call_id=?",(call_id,)).fetchone()
            if row is None or row["state"] != "COMPLETE":
                raise ModelTextError("RESULT_NOT_AVAILABLE")
            return json.loads(row["result_json"])

    def send_once(self,call_id,client):
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM calls WHERE call_id=?",(call_id,)).fetchone()
            if row is None:
                raise ModelTextError("CALL_NOT_FOUND")
            if row["state"] != "PREPARED":
                return self.read(call_id)
            profile=getattr(client,"profile",None)
            if (not isinstance(profile,TextProfile) or profile.profile_sha256 != row["profile_sha256"]
                    or profile.profile_id != row["profile_id"] or profile.provider_id != row["provider_id"]
                    or profile.endpoint != row["endpoint"] or profile.model != row["model"]):
                raise ModelTextError("FROZEN_PROFILE_MISMATCH")
            budget=db.execute("SELECT * FROM budgets WHERE budget_key=?",(row["budget_key"],)).fetchone()
            if row["reservation_micros"] > budget["limit_micros"]-budget["reserved_micros"]-budget["spent_micros"]:
                raise ModelTextError("BUDGET_EXHAUSTED")
            db.execute("UPDATE budgets SET reserved_micros=reserved_micros+? WHERE budget_key=?",
                       (row["reservation_micros"],row["budget_key"]))
            db.execute("UPDATE calls SET state='UNKNOWN_SUBMISSION',attempt_count=1 WHERE call_id=?",(call_id,))
            body=json.loads(row["body_json"])
        try:
            output=client.send(body)
        except Exception as exc:
            with self._db() as db:
                db.execute("UPDATE calls SET error_type=? WHERE call_id=?",(type(exc).__name__,call_id))
            return self.read(call_id)
        with self._db() as db:
            db.execute("UPDATE calls SET state='COMPLETE',result_json=?,error_type=NULL WHERE call_id=? AND state='UNKNOWN_SUBMISSION'",
                       (canonical(output),call_id))
        return self.read(call_id)

    def settle_cost(self,call_id,event_key,evidence_path,evidence_sha256):
        if not isinstance(event_key,str) or not event_key:
            raise ModelTextError("BILLING_EVENT_KEY_REQUIRED")
        path=Path(evidence_path).resolve(strict=True)
        if not path.is_file():
            raise ModelTextError("BILLING_EVIDENCE_HASH_MISMATCH")
        evidence_bytes=path.read_bytes()
        if hashlib.sha256(evidence_bytes).hexdigest()!=evidence_sha256:
            raise ModelTextError("BILLING_EVIDENCE_HASH_MISMATCH")
        evidence=json.loads(evidence_bytes.decode("utf-8"))
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            row=db.execute("SELECT * FROM calls WHERE call_id=?",(call_id,)).fetchone()
            if row is None or row["state"] == "PREPARED":
                raise ModelTextError("CALL_NOT_SENT")
            budget=db.execute("SELECT * FROM budgets WHERE budget_key=?",(row["budget_key"],)).fetchone()
            amount=evidence.get("actual_cost_micros") if isinstance(evidence,dict) else None
            if (not isinstance(evidence,dict) or evidence.get("schema")!="model-text-billing-evidence/1"
                    or evidence.get("call_id")!=call_id or evidence.get("body_sha256")!=row["body_sha256"]
                    or evidence.get("profile_sha256")!=row["profile_sha256"]
                    or evidence.get("provider_id")!=row["provider_id"]
                    or evidence.get("endpoint")!=row["endpoint"] or evidence.get("model")!=row["model"]
                    or evidence.get("currency")!=budget["currency"]
                    or not isinstance(evidence.get("source_ref"),str) or not evidence["source_ref"].strip()
                    or type(amount) is not int or not 0<=amount<=2**63-1):
                raise ModelTextError("BILLING_EVIDENCE_INVALID")
            old=db.execute("SELECT * FROM billing_events WHERE event_key=?",(event_key,)).fetchone()
            if old and (old["call_id"],old["evidence_sha256"],old["actual_cost_micros"]) != (call_id,evidence_sha256,amount):
                raise ModelTextError("BILLING_EVENT_KEY_CONFLICT")
            for prior in db.execute("SELECT evidence_path,evidence_sha256 FROM billing_events WHERE call_id=?",(call_id,)):
                previous_file=Path(prior["evidence_path"])
                if not previous_file.is_file() or hashlib.sha256(previous_file.read_bytes()).hexdigest()!=prior["evidence_sha256"]:
                    raise ModelTextError("PRIOR_BILLING_EVIDENCE_CHANGED")
            if old:
                if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=evidence_sha256:
                    raise ModelTextError("BILLING_EVIDENCE_HASH_MISMATCH")
                return {"call_id":call_id,"event_key":event_key,"idempotent":True,"actual_cost_micros":amount}
            previous=db.execute("SELECT actual_cost_micros FROM billing_events WHERE call_id=? ORDER BY rowid DESC LIMIT 1",(call_id,)).fetchone()
            delta=amount-(previous["actual_cost_micros"] if previous else 0)
            if not 0<=budget["spent_micros"]+delta<=2**63-1:
                raise ModelTextError("BUDGET_ACCOUNTING_OVERFLOW")
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=evidence_sha256:
                raise ModelTextError("BILLING_EVIDENCE_HASH_MISMATCH")
            db.execute("UPDATE budgets SET reserved_micros=reserved_micros-?,spent_micros=spent_micros+? WHERE budget_key=?",
                       (row["reservation_micros"] if previous is None else 0,delta,row["budget_key"]))
            db.execute("INSERT INTO billing_events(event_key,call_id,evidence_path,evidence_sha256,actual_cost_micros,recorded_at) VALUES(?,?,?,?,?,datetime('now'))",
                       (event_key,call_id,str(path),evidence_sha256,amount))
            return {"call_id":call_id,"event_key":event_key,"idempotent":False,
                    "correction":previous is not None,"actual_cost_micros":amount}
