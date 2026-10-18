"""Offline TTS API/preparation regressions; never contact a provider."""
import asyncio
import json
import sys
from types import SimpleNamespace

import pytest

from douyin_film_recap.send_guard import SendBlocked, send_session
from douyin_film_recap.tts import _edge_tts_stream, prepare_edge_tts


PARAMS = dict(text="测试", voice="zh-CN-XiaoxiaoNeural", rate="+0%", pitch="+0Hz", volume="+0%")


def run_tts(root, filename="audio.mp3", **overrides):
    return asyncio.run(_edge_tts_stream(output_path=root / filename, intent_key="audio:1",
                                       **{**PARAMS, **overrides}))


def receipts(root):
    return [json.loads(p.read_text()) for p in (root / ".remote-intents").glob("*.json")]


class WorkingCommunicate:
    def __init__(self, **kwargs):
        pass

    async def stream(self):
        yield {"type": "audio", "data": b"offline-test"}
        yield {"type": "WordBoundary", "text": "测试", "offset": 0, "duration": 10000000}


@pytest.mark.parametrize("failure", ["missing", "legacy", "invalid"])
def test_local_failure_does_not_reserve_and_can_retry(tmp_path, monkeypatch, failure):
    class LegacyCommunicate:
        def __init__(self, text, voice, *, rate, pitch, volume):
            pytest.fail("legacy constructor must not be invoked")

    class InvalidCommunicate:
        def __init__(self, **kwargs):
            raise ValueError("invalid voice/rate")

    module = None if failure == "missing" else SimpleNamespace(
        Communicate=LegacyCommunicate if failure == "legacy" else InvalidCommunicate)
    monkeypatch.setitem(sys.modules, "edge_tts", module)
    with send_session(tmp_path, {}, authorized=True, max_requests=1) as session:
        with pytest.raises((RuntimeError, ValueError)):
            run_tts(tmp_path)
        assert session.sent == 0
        assert receipts(tmp_path) == []
        monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=WorkingCommunicate))
        assert run_tts(tmp_path)[0]["duration"] == 1
        assert session.sent == 1
    assert receipts(tmp_path)[0]["status"] == "SUCCEEDED"


def test_unknown_transport_never_becomes_retryable(tmp_path, monkeypatch):
    calls = []

    class FailingCommunicate(WorkingCommunicate):
        async def stream(self):
            calls.append("entered transport")
            raise TimeoutError("acceptance unknown")
            yield  # async generator, without real network I/O

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=FailingCommunicate))
    with send_session(tmp_path, {}, authorized=True):
        with pytest.raises(TimeoutError):
            run_tts(tmp_path)
    before = receipts(tmp_path)
    assert before[0]["status"] == "UNKNOWN"
    monkeypatch.setitem(sys.modules, "edge_tts", None)
    with send_session(tmp_path, {}, authorized=True):
        with pytest.raises(SendBlocked, match="SEND_OUTCOME_UNKNOWN"):
            run_tts(tmp_path)
    assert receipts(tmp_path) == before
    assert len(calls) == 1


def test_cached_success_replays_without_installed_tts(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=WorkingCommunicate))
    with send_session(tmp_path, {}, authorized=True):
        expected = run_tts(tmp_path)
    monkeypatch.setitem(sys.modules, "edge_tts", None)
    with send_session(tmp_path, {}, authorized=False) as session:
        assert run_tts(tmp_path, "replay.mp3") == expected
        assert session.sent == 0
    assert (tmp_path / "replay.mp3").read_bytes() == b"offline-test"


def test_installed_edge_tts_constructor_offline(monkeypatch):
    """CI runs this against the actual minimum and newest supported releases."""
    edge_tts = pytest.importorskip("edge_tts")

    def forbidden(*args, **kwargs):
        pytest.fail("offline compatibility check must not enter transport")

    monkeypatch.setattr(edge_tts.Communicate, "stream", forbidden)
    instance = prepare_edge_tts(**PARAMS)
    assert instance.tts_config.boundary == "WordBoundary"
    with pytest.raises(ValueError):
        prepare_edge_tts(**{**PARAMS, "rate": "invalid"})


@pytest.mark.parametrize("compatible", [True, False])
def test_doctor_validates_capability_offline(tmp_path, app_config, monkeypatch, compatible):
    from douyin_film_recap import doctor

    class LegacyCommunicate:
        def __init__(self, text, voice):
            pass

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(
        Communicate=WorkingCommunicate if compatible else LegacyCommunicate))
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)
    monkeypatch.setattr(doctor.OpenAICompatibleClient, "healthcheck", lambda _: (True, "offline"))
    checks = doctor.run_doctor(app_config, tmp_path / "config.yaml")
    tts = next(check for check in checks if check.name == "TTS")
    assert tts.status == ("PASS" if compatible else "FAIL")
    assert tts.critical is (not compatible)


def test_unauthorized_request_does_not_prepare(tmp_path, monkeypatch):
    class UnexpectedCommunicate:
        def __init__(self, **kwargs):
            pytest.fail("authorization must be checked before preparation")

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=UnexpectedCommunicate))
    with send_session(tmp_path, {}, authorized=False):
        with pytest.raises(SendBlocked, match="REMOTE_AUTHORIZATION_REQUIRED"):
            run_tts(tmp_path)
    assert receipts(tmp_path) == []


def test_declared_extras_exclude_incompatible_legacy():
    import tomllib
    from pathlib import Path
    from packaging.requirements import Requirement

    project = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())
    for extra in ("tts", "all"):
        dependency = next(Requirement(value) for value in project["project"]["optional-dependencies"][extra]
                          if value.startswith("edge-tts"))
        assert "6.1.12" not in dependency.specifier
        assert "7.2.0" in dependency.specifier
        assert "7.3.1" in dependency.specifier
        assert "8.0.0" not in dependency.specifier
