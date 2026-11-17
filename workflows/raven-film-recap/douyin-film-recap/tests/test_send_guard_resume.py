"""Exercise resume and concurrent calls through the real local send boundary."""
from __future__ import annotations

import json
import sys
from threading import Barrier, Lock
from types import SimpleNamespace

import httpx
import pytest

from douyin_film_recap import send_guard as guard
from douyin_film_recap.analysis import analyze_scenes
from douyin_film_recap.models import (
    HighlightDocument, RecapPlan, RhythmProfile, SceneIndex, SceneUnit,
    StoryBundle, Storyboard, StoryboardSegment,
)
from douyin_film_recap.providers import OpenAICompatibleClient
from douyin_film_recap.pipeline import FilmRecapPipeline
from douyin_film_recap.qc import _semantic_qc
from douyin_film_recap.tts import synthesize_storyboard
from douyin_film_recap.utils import write_json
from douyin_film_recap.workspace import read, work_lock


SCOPE = {"binding": "synthetic-full-content-identity", "stage": "tts", "stage_inputs": "fixed"}


@pytest.fixture
def provider(app_config, monkeypatch):
    monkeypatch.setenv("FILM_RECAP_BASE_URL", "https://synthetic.invalid/v1")
    monkeypatch.setenv("FILM_RECAP_API_KEY", "synthetic-test-key")
    return OpenAICompatibleClient(app_config.models)


def _storyboard():
    return Storyboard(
        project_name="synthetic-resume", sources=[], plan_fingerprint="synthetic-plan",
        target_duration_sec=2,
        segments=[
            StoryboardSegment(
                segment_id=f"segment-{index}", beat_id="beat-1", mode="voiceover",
                title="synthetic", text=text, audio_owner="narration",
                planned_duration_sec=1, notes="",
                visuals=[{"source_id": "synthetic-source", "start": 0, "end": 1}],
            )
            for index, text in enumerate(("甲", "甲" * 100), start=1)
        ],
    )


def test_tts_cache_skip_cannot_renumber_unknown_chat_and_resend(
    tmp_path, app_config, provider, monkeypatch,
):
    sends = {"edge_tts": 0, "chat": 0}

    class Communicate:
        def __init__(self, **kwargs):
            pass

        async def stream(self):
            sends["edge_tts"] += 1
            yield {"type": "audio", "data": b"synthetic-audio"}

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, *args, **kwargs):
            sends["chat"] += 1
            raise httpx.ReadTimeout("synthetic: provider acceptance cannot be determined")

    monkeypatch.setitem(sys.modules, "edge_tts", SimpleNamespace(Communicate=Communicate))
    monkeypatch.setattr("douyin_film_recap.providers.httpx.Client", FakeClient)
    monkeypatch.setattr("douyin_film_recap.tts.media_duration", lambda _: 1.0)

    # First segment commits a local TTS cache; shortening the second segment is UNKNOWN.
    with work_lock(tmp_path), guard.send_session(tmp_path, SCOPE, authorized=True):
        with pytest.raises(httpx.ReadTimeout):
            synthesize_storyboard(_storyboard(), app_config, provider, tmp_path)
    original = {
        path.name: path.read_bytes() for path in (tmp_path / ".remote-intents").glob("*.json")
    }
    audio_files = list((tmp_path / "audio").rglob("*.mp3"))
    assert len(audio_files) == 1
    cached_audio = audio_files[0].read_bytes()

    # On restart segment one skips all sends. Existing authorization must not let
    # segment two become a new logical request merely because its ordinal changes.
    for authorized in (True, False):
        with work_lock(tmp_path), guard.send_session(tmp_path, SCOPE, authorized=authorized):
            with pytest.raises(guard.SendBlocked, match="OUTCOME_UNKNOWN"):
                synthesize_storyboard(_storyboard(), app_config, provider, tmp_path)

    assert sends == {"edge_tts": 1, "chat": 1}
    assert list((tmp_path / "audio").rglob("*.mp3")) == audio_files
    assert audio_files[0].read_bytes() == cached_audio
    assert {
        path.name: path.read_bytes() for path in (tmp_path / ".remote-intents").glob("*.json")
    } == original
    records = [json.loads(raw) for raw in original.values()]
    assert {(record["kind"], record["status"]) for record in records} == {
        ("edge_tts", "SUCCEEDED"), ("chat", "UNKNOWN"),
    }
    assert {record["logical_key"] for record in records} == {
        "tts:segment-1:audio:initial", "tts:segment-2:shorten:pre-fit:format-0",
    }


def _scenes(count):
    return SceneIndex(
        units=[SceneUnit(unit_id=f"unit-{i}", source_id="synthetic", start=i, end=i + 1)
               for i in range(count)],
        source_fingerprints={"synthetic": "full-content-sha"}, detector="synthetic",
    )


def _scene_transport(monkeypatch, simultaneous):
    calls = []
    lock = Lock()
    barrier = Barrier(simultaneous)

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, endpoint, **kwargs):
            with lock:
                calls.append({"session": guard._session.get(), "endpoint": endpoint})
            # Force overlapping workers; absence of Context propagation would fail
            # at guarded_send before any transport can enter this barrier.
            barrier.wait(timeout=5)
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"items":[]}'}}],
            })

    monkeypatch.setattr("douyin_film_recap.providers.httpx.Client", FakeClient)
    return calls


def test_analysis_workers_share_session_and_stable_keys_replay(
    tmp_path, app_config, provider, monkeypatch,
):
    app_config.scene.contact_sheet_units = 1
    app_config.scene.max_scene_analysis_workers = 3
    calls = _scene_transport(monkeypatch, simultaneous=3)
    scenes = _scenes(3)
    scope = {**SCOPE, "stage": "scene_analysis"}
    with work_lock(tmp_path), guard.send_session(
        tmp_path, scope, authorized=True, max_requests=3,
    ) as session:
        result = analyze_scenes(scenes, app_config, provider)
    assert [item.unit_id for item in result.items] == ["unit-0", "unit-1", "unit-2"]
    assert len(calls) == 3 and all(call["session"] is session for call in calls)
    assert session.sent == 3
    assert {read(path)["logical_key"] for path in (tmp_path / ".remote-intents").glob("*.json")} == {
        f"scene-analysis:batch:{index:04d}:schema-json:format-0" for index in range(3)
    }
    with work_lock(tmp_path), guard.send_session(tmp_path, scope) as replay:
        repeated = analyze_scenes(scenes, app_config, provider)
    assert repeated.items == result.items
    assert len(calls) == 3 and replay.sent == 0


def test_analysis_workers_cannot_exceed_shared_request_limit(
    tmp_path, app_config, provider, monkeypatch,
):
    app_config.scene.contact_sheet_units = 1
    app_config.scene.max_scene_analysis_workers = 8
    calls = _scene_transport(monkeypatch, simultaneous=2)
    with work_lock(tmp_path), guard.send_session(
        tmp_path, {**SCOPE, "stage": "scene_analysis"}, authorized=True, max_requests=2,
    ) as session:
        with pytest.raises(guard.SendBlocked, match="LIMIT_REACHED"):
            analyze_scenes(_scenes(8), app_config, provider)
    assert len(calls) == session.sent == 2
    assert all(call["session"] is session for call in calls)
    receipts = list((tmp_path / ".remote-intents").glob("*.json"))
    assert len(receipts) == 2
    assert all(read(path)["status"] == "SUCCEEDED" for path in receipts)


@pytest.mark.parametrize("unknown", [False, True])
def test_semantic_qc_ignores_rendered_fields_for_reply_or_unknown_replay(
    tmp_path, app_config, provider, monkeypatch, unknown,
):
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, endpoint, **kwargs):
            calls.append(kwargs["json"])
            if unknown:
                raise httpx.ReadTimeout("synthetic unknown semantic request")
            return httpx.Response(200, json={
                "choices": [{"message": {"content": '{"findings":[]}'}}],
            })

    monkeypatch.setattr("douyin_film_recap.providers.httpx.Client", FakeClient)
    board = _storyboard()
    story = StoryBundle.model_validate({
        "character_registry": {"characters": []},
        "story_graph": {"main_plot": "synthetic", "events": []},
        "knowledge_timeline": {"states": []},
    })
    highlights = HighlightDocument(
        genre_profile="synthetic", candidates=[], weights={}, source_fingerprints={},
    )
    plan = RecapPlan(
        viewer_promise="synthetic", pov="synthetic", main_spine="synthetic",
        hook_strategy="synthetic", hook_highlight_id="synthetic", target_duration_sec=2,
        duration_mode="highlight", original_ratio_target=0, ending_strategy="synthetic",
        reveal_strategy="synthetic", beats=[], rhythm=RhythmProfile(),
    )
    kwargs = {"story": story, "highlights": highlights, "plan": plan, "storyboard": board,
              "config": app_config, "client": provider}
    scope = {**SCOPE, "stage": "pre_qc"}
    with guard.send_session(tmp_path, scope, authorized=True):
        if unknown:
            with pytest.raises(httpx.ReadTimeout):
                _semantic_qc(**kwargs)
        else:
            assert _semantic_qc(**kwargs) == []

    receipt = next((tmp_path / ".remote-intents").glob("*.json"))
    original_receipt = receipt.read_bytes()
    board.output = {"final_video": str(tmp_path / "synthetic-render.mp4")}
    for segment in board.segments:
        segment.status = "rendered"
        segment.rendered_file = str(tmp_path / f"{segment.segment_id}.mp4")
        segment.rendered_duration_sec = 1.0
    rendered_board = board.model_dump(mode="json")
    with guard.send_session(tmp_path, scope):
        if unknown:
            with pytest.raises(guard.SendBlocked, match="OUTCOME_UNKNOWN"):
                _semantic_qc(**kwargs)
        else:
            assert _semantic_qc(**kwargs) == []
    assert len(calls) == 1
    assert receipt.read_bytes() == original_receipt
    assert board.model_dump(mode="json") == rendered_board  # Prompt shaping is not a write.


def test_pipeline_prepares_cues_before_scope_so_unknown_qc_cannot_resend(
    tmp_path, app_config, provider, monkeypatch,
):
    source = tmp_path / "synthetic-source.mp4"
    source.write_bytes(b"synthetic-media-identity-only")
    pipeline = FilmRecapPipeline(input_path=source, work_dir=tmp_path / "task", config=app_config)
    pipeline.client = provider
    board = _storyboard()
    board.segments[0].mode = "original"
    board.segments[0].audio_owner = "original_dialogue"
    write_json(pipeline.paths["storyboard"], board)
    for dependency in ("manifest", "transcript", "characters", "story", "knowledge", "highlights", "plan"):
        write_json(pipeline.paths[dependency], {"synthetic": dependency})
    before_preparation = pipeline._stage_inputs("pre_qc")
    monkeypatch.setattr(pipeline.store, "selected_stages", lambda until: ["pre_qc"])
    preparations = []

    def normalize_cues(storyboard):
        preparations.append(storyboard.segments[0].original_cues_verified)
        # Represents deterministic transcript-derived changes to a hand-edited
        # storyboard. It changes a substantive field included in stage_inputs.
        storyboard.segments[0].original_cues_verified = True

    monkeypatch.setattr(pipeline, "_attach_original_cues", normalize_cues)
    sends = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, endpoint, **kwargs):
            sends.append(kwargs["json"])
            raise httpx.ReadTimeout("synthetic unknown pre-QC request")

    monkeypatch.setattr("douyin_film_recap.providers.httpx.Client", FakeClient)

    def semantic_handler():
        current = pipeline._storyboard()
        assert current.segments[0].original_cues_verified
        pipeline.client.chat(
            system="synthetic semantic review", prompt=current.model_dump_json(),
            intent_key="pre-qc:semantic",
        )
        raise AssertionError("The synthetic transport always times out")

    monkeypatch.setattr(pipeline, "_stage_pre_qc", semantic_handler)
    with pytest.raises(httpx.ReadTimeout):
        pipeline.run(until="pre_qc", allow_remote=True, max_remote_requests=2)
    receipt = next((pipeline.task_root / ".remote-intents").glob("*.json"))
    original = receipt.read_bytes()
    record = read(receipt)
    assert record["scope"]["stage_inputs"] != before_preparation
    assert record["scope"]["stage_inputs"] == pipeline._stage_inputs("pre_qc")
    assert record["status"] == "UNKNOWN"

    # Reuse the recorded authorization. Normalization is idempotent and the same
    # UNKNOWN remains blocking, even though two requests were originally allowed.
    with pytest.raises(guard.SendBlocked, match="OUTCOME_UNKNOWN"):
        pipeline.run(until="pre_qc")
    assert preparations == [False, True]
    assert len(sends) == 1
    assert receipt.read_bytes() == original
    assert len(list((pipeline.task_root / ".remote-intents").glob("*.json"))) == 1
    assert pipeline.state.stages["pre_qc"].status == "failed"
