import json
import sys
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from douyin_film_recap import send_guard as guard
from douyin_film_recap.providers import OpenAICompatibleClient, ProviderError
from douyin_film_recap.tts import synthesize_edge_tts
from douyin_film_recap.pipeline import FilmRecapPipeline
from douyin_film_recap.workspace import read

SCOPE = {"binding": "synthetic full identity", "stage": "story", "stage_inputs": "stable"}


@pytest.fixture
def provider(app_config, monkeypatch):
    monkeypatch.setenv("FILM_RECAP_BASE_URL", "https://synthetic.invalid/v1")
    monkeypatch.setenv("FILM_RECAP_API_KEY", "test-key-must-not-be-recorded")
    return OpenAICompatibleClient(app_config.models)


def transport(monkeypatch, root, results):
    sent = []
    class FakeClient:
        def __init__(self, **kwargs):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def post(self, endpoint, **kwargs):
            # Receipt exists with UNKNOWN before the transport can observe/send.
            assert any(read(p)["status"] == "UNKNOWN" for p in (root / ".remote-intents").glob("*.json"))
            sent.append({"endpoint": endpoint, "payload": json.loads(json.dumps(kwargs["json"]))})
            response = results[len(sent) - 1]
            if isinstance(response, Exception):
                raise response
            return response
    monkeypatch.setattr("douyin_film_recap.providers.httpx.Client", FakeClient)
    return sent


def response(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


def test_api_key_is_not_authorization_and_direct_provider_is_guarded(tmp_path, provider, monkeypatch):
    sent = transport(monkeypatch, tmp_path, [response("okay")])
    with pytest.raises(guard.SendBlocked, match="AUTHORIZATION"):
        provider.chat(system="s", prompt="p")
    with guard.send_session(tmp_path, SCOPE):
        with pytest.raises(guard.SendBlocked, match="AUTHORIZATION"):
            provider.chat(system="s", prompt="p")
    assert sent == [] and not (tmp_path / ".remote-intents").exists()


def test_reply_persisted_and_replays_without_new_send(tmp_path, provider, monkeypatch):
    sent = transport(monkeypatch, tmp_path, [response("observed reply")])
    with guard.send_session(tmp_path, SCOPE, authorized=True, max_requests=1):
        assert provider.chat(system="s", prompt="p") == "observed reply"
    receipt = next((tmp_path / ".remote-intents").glob("*.json"))
    assert read(receipt)["status"] == "SUCCEEDED"
    assert "test-key-must-not-be-recorded" not in receipt.read_text()
    with guard.send_session(tmp_path, SCOPE):
        assert provider.chat(system="s", prompt="p") == "observed reply"
    assert len(sent) == 1


def test_unknown_submission_never_automatically_retries(tmp_path, provider, monkeypatch):
    sent = transport(monkeypatch, tmp_path, [httpx.ReadTimeout("service may have accepted"), response("later")])
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        with pytest.raises(httpx.ReadTimeout):
            provider.chat(system="s", prompt="p")
    receipt = next((tmp_path / ".remote-intents").glob("*.json"))
    assert read(receipt)["status"] == "UNKNOWN"
    for authorized in (False, True):
        with guard.send_session(tmp_path, SCOPE, authorized=authorized):
            with pytest.raises(guard.SendBlocked, match="OUTCOME_UNKNOWN"):
                provider.chat(system="s", prompt="p")
    assert len(sent) == 1
    guard.reconcile(tmp_path, receipt.stem, "synthetic provider operator confirmed zero submissions")
    with guard.send_session(tmp_path, SCOPE):
        with pytest.raises(guard.SendBlocked, match="AUTHORIZATION"):
            provider.chat(system="s", prompt="p")
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        assert provider.chat(system="s", prompt="p") == "later"
    assert len(sent) == 2


def test_intent_payload_change_does_not_hide_unknown_send(tmp_path, provider, monkeypatch):
    sent = transport(monkeypatch, tmp_path, [httpx.ConnectError("disconnected")])
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        with pytest.raises(httpx.ConnectError):
            provider.chat(system="s", prompt="old", intent_key="stable-role")
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        with pytest.raises(guard.SendBlocked, match="PAYLOAD_CHANGED"):
            provider.chat(system="s", prompt="new", intent_key="stable-role")
    assert len(sent) == 1


def test_invalid_structured_reply_saved_before_separate_repair_and_cap(tmp_path, provider, monkeypatch):
    class Result(BaseModel):
        number: int
    sent = transport(monkeypatch, tmp_path, [response('{"number":"bad"}'), response('{"number":2}')])
    with guard.send_session(tmp_path, SCOPE, authorized=True, max_requests=1):
        with pytest.raises(guard.SendBlocked, match="LIMIT_REACHED"):
            provider.chat_json(system="s", prompt="p", model_type=Result)
    assert len(sent) == 1
    assert "bad" in read(next((tmp_path / ".remote-intents").glob("*.json")))["result"]["text"]
    with guard.send_session(tmp_path, SCOPE, authorized=True, max_requests=1):
        assert provider.chat_json(system="s", prompt="p", model_type=Result).number == 2
    with guard.send_session(tmp_path, SCOPE):
        assert provider.chat_json(system="s", prompt="p", model_type=Result).number == 2
    assert len(sent) == 2 and len(list((tmp_path / ".remote-intents").glob("*.json"))) == 2


def test_only_observed_format_rejection_can_issue_new_fallback(tmp_path, provider, monkeypatch):
    sent = transport(monkeypatch, tmp_path, [httpx.Response(400, text="format unsupported"), response("okay")])
    with guard.send_session(tmp_path, SCOPE, authorized=True, max_requests=2):
        assert provider.chat(system="s", prompt="p", response_format={"type": "json_object"}) == "okay"
    assert "response_format" in sent[0]["payload"] and "response_format" not in sent[1]["payload"]
    assert len(list((tmp_path / ".remote-intents").glob("*.json"))) == 2


def test_http_failure_and_bad_json_replay_without_retry(tmp_path, provider, monkeypatch):
    sent = transport(monkeypatch, tmp_path, [httpx.Response(500, text="rejected")])
    for authorized in (True, False):
        with guard.send_session(tmp_path, SCOPE, authorized=authorized):
            with pytest.raises(ProviderError, match="HTTP 500"):
                provider.chat(system="s", prompt="p")
    assert len(sent) == 1


def test_remote_tts_entry_authorization_reply_replay_and_unknown(tmp_path, app_config, monkeypatch):
    sends = []
    class Communicate:
        def __init__(self, **kwargs):
            self.payload = kwargs
        async def stream(self):
            sends.append(self.payload)
            yield {"type": "audio", "data": b"synthetic-audio-bytes"}
            yield {"type": "WordBoundary", "text": "test", "offset": 0, "duration": 10000000}
    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=Communicate))
    with pytest.raises(guard.SendBlocked, match="AUTHORIZATION"):
        synthesize_edge_tts(text="test", output_path=tmp_path / "blocked.mp3", config=app_config)
    assert not sends and not (tmp_path / "blocked.mp3").exists()
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        result = synthesize_edge_tts(text="test", output_path=tmp_path / "first.mp3", config=app_config)
    with guard.send_session(tmp_path, SCOPE):
        replay = synthesize_edge_tts(text="test", output_path=tmp_path / "replay.mp3", config=app_config)
    assert replay == result and len(sends) == 1
    assert (tmp_path / "first.mp3").read_bytes() == (tmp_path / "replay.mp3").read_bytes()


def test_pipeline_run_guard_and_global_cap_cover_actual_provider(tmp_path, provider, app_config, monkeypatch):
    source = tmp_path / "source.mp4"; source.write_bytes(b"synthetic input")
    p = FilmRecapPipeline(input_path=source, work_dir=tmp_path / "task", config=app_config)
    p.client = provider
    sent = transport(monkeypatch, p.task_root, [response("ingest response"), response("transcript response")])
    monkeypatch.setattr(p, "_stage_inputs", lambda stage: stage)
    monkeypatch.setattr(p, "_required_artifacts", lambda stage, artifact: [artifact])
    def stage(name):
        def run():
            text = p.client.chat(system="s", prompt=name)
            out = p.work_dir / f"{name}.json"; out.write_text(json.dumps({"reply": text}))
            return out
        return run
    monkeypatch.setattr(p, "_stage_ingest", stage("ingest"))
    monkeypatch.setattr(p, "_stage_transcript", stage("transcript"))
    with pytest.raises(guard.SendBlocked, match="AUTHORIZATION"):
        p.run(until="transcript")
    assert not sent
    with pytest.raises(guard.SendBlocked, match="LIMIT_REACHED"):
        p.run(until="transcript", allow_remote=True, max_remote_requests=1)
    assert len(sent) == 1 and p.state.stages["ingest"].status == "passed"
    p.run(until="transcript", allow_remote=True, max_remote_requests=1)
    assert len(sent) == 2
    p.run(until="transcript")
    assert len(sent) == 2


def test_existing_authorization_reused_but_endpoint_config_change_rejected(tmp_path, provider, app_config, monkeypatch):
    source = tmp_path / "source.mp4"; source.write_bytes(b"synthetic")
    p = FilmRecapPipeline(input_path=source, work_dir=tmp_path / "task", config=app_config)
    p.client = provider
    sent = transport(monkeypatch, p.task_root, [response("ingest"), response("transcript")])
    monkeypatch.setattr(p, "_stage_inputs", lambda stage: stage)
    monkeypatch.setattr(p, "_required_artifacts", lambda stage, artifact: [artifact])
    failed = {"first": True}
    def ingest():
        p.client.chat(system="s", prompt="ingest", intent_key="ingest:fixture")
        path = p.work_dir / "ingest.json"; path.write_text('{}'); return path
    def transcript():
        if failed["first"]:
            failed["first"] = False
            raise ValueError("local validation failed before any remote send")
        p.client.chat(system="s", prompt="transcript", intent_key="transcript:fixture")
        path = p.work_dir / "transcript.json"; path.write_text('{}'); return path
    monkeypatch.setattr(p, "_stage_ingest", ingest)
    monkeypatch.setattr(p, "_stage_transcript", transcript)
    with pytest.raises(ValueError, match="local validation"):
        p.run(until="transcript", allow_remote=True, max_remote_requests=2)
    p.run(until="transcript")  # Prior authorization covers the untouched request.
    assert len(sent) == 2
    assert read(p.work_dir / ".receipts/recompute-plan.json")["existing_authorization_reused"] is True
    monkeypatch.setenv("FILM_RECAP_BASE_URL", "https://other.synthetic.invalid/v1")
    with pytest.raises(ValueError, match="BINDING_CHANGED"):
        p.run(until="ingest")
    monkeypatch.setenv("FILM_RECAP_BASE_URL", "https://synthetic.invalid/v1")
    p.config.models.llm_model = "unauthorized-model"
    with pytest.raises(ValueError, match="BINDING_CHANGED"):
        p.run(until="ingest")


def test_actual_send_policy_rejects_out_of_scope_model(tmp_path, provider, monkeypatch):
    sent = transport(monkeypatch, tmp_path, [response("should never send")])
    policy = {"endpoint": provider.base_url, "models": ["allowed-only"], "edge_tts": {}}
    with guard.send_session(tmp_path, {**SCOPE, "remote_policy": policy}, authorized=True):
        with pytest.raises(guard.SendBlocked, match="OUTSIDE_AUTHORIZED_SCOPE"):
            provider.chat(system="s", prompt="p", intent_key="role")
    assert sent == []


def test_constructor_binds_frozen_config_during_external_mutation(tmp_path, app_config, monkeypatch):
    from douyin_film_recap import pipeline as module
    from douyin_film_recap.utils import fingerprint_json
    source = tmp_path / "source.mp4"; source.write_bytes(b"synthetic")
    monkeypatch.delenv("FILM_RECAP_BASE_URL", raising=False)
    expected_config = app_config.fingerprint()
    discover = module.discover_videos
    def changing_discover(path):
        app_config.models.llm_model = "changed by caller during discovery"
        return discover(path)
    monkeypatch.setattr(module, "discover_videos", changing_discover)
    p = FilmRecapPipeline(input_path=source, work_dir=tmp_path / "task", config=app_config)
    assert p.config.models.llm_model == "test-llm"
    assert p.binding["config_fingerprint"] == fingerprint_json({"config": expected_config,
        "pipeline_revision": module.PIPELINE_REVISION, "context_fingerprint": None, "remote_endpoint": None})
