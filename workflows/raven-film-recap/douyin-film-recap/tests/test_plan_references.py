"""Structural/engineering regressions; no real-film or semantic acceptance."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from douyin_film_recap.config import load_config
from douyin_film_recap.models import Character, RecapPlan, TimeSpan
from douyin_film_recap.narrative_contracts import diagnose_plan_references
from douyin_film_recap.planning import build_plan
from douyin_film_recap.qc import preflight_qc
from douyin_film_recap.retrieval import (
    benchmark_supporting_spans,
    build_retrieval_requests,
    rerank_visual_pool,
)
from douyin_film_recap.utils import fingerprint_json
from test_narrative_contracts import FakeClient, _artifacts, _config, _plan, _storyboard


def test_build_plan_reports_all_missing_refs_with_beat_field_and_id():
    config = _config(format={"duration_mode": "highlight"})
    manifest, transcript, story, highlights = _artifacts(config)
    plan = _plan()
    plan.beats[0].event_ids = ["event_typo"]
    plan.beats[1].character_focus = ["character_typo"]
    plan.beats[2].preferred_highlights = ["highlight_typo"]
    client = FakeClient(plan)
    with pytest.raises(ValueError, match="Plan reference check failed") as error:
        build_plan(manifest, transcript, story, highlights, config, client)
    for index, field, ref in [(0, "event_ids", "event_typo"),
                              (1, "character_focus", "character_typo"),
                              (2, "preferred_highlights", "highlight_typo")]:
        assert f"beats[{index}].{field} (beat 'b{index}')" in str(error.value)
        assert ref in str(error.value)
    assert "supplied" in str(error.value)  # Absence is scoped to the provided registry.
    assert len(client.calls) == 1  # No extra paid replan for reference diagnostics.


def test_missing_refs_and_unknown_story_evidence_are_distinct():
    _, _, story, highlights = _artifacts(_config())
    plan = _plan()
    plan.beats[0].event_ids = []
    plan.beats[1].character_focus = ["c1"]  # An existing temporary identity.
    plan.beats[2].event_ids = ["absent"]
    diagnostics = diagnose_plan_references(plan, story, highlights)
    unknown = [item for item in diagnostics if item["status"] == "unknown"]
    assert {item["rule_id"] for item in unknown} >= {
        "BEAT_EVENT_MAPPING_UNKNOWN", "BEAT_CHARACTER_IDENTITY_UNKNOWN",
    }
    assert all(not item["blocking"] and not item["deterministic"] for item in unknown)
    missing = [item for item in diagnostics if item["blocking"]]
    assert len(missing) == 1
    assert missing[0]["path"] == "beats[2].event_ids"
    assert missing[0]["references"] == ["absent"]


def test_same_name_aliases_and_temporary_identity_are_never_auto_merged():
    _, _, story, highlights = _artifacts(_config())
    story.character_registry.characters = [
        Character(character_id="c_left", display_name="小王", aliases=["阿王"], temporary_name=False),
        Character(character_id="c_right", display_name="小王", aliases=["阿王"], temporary_name=False),
        Character(character_id="temporary_1", display_name="小王", aliases=["阿王"]),
    ]
    plan = _plan()
    plan.beats[0].character_focus = ["c_left", "c_right", "temporary_1"]
    before = story.model_dump(mode="json")
    diagnostics = diagnose_plan_references(plan, story, highlights)
    assert not any(item["blocking"] for item in diagnostics)
    request = build_retrieval_requests(plan, story)[0]
    assert request.canonical_character_ids == ("c_left", "c_right")
    assert any(item["references"] == ["temporary_1"] for item in request.reference_diagnostics)
    assert story.model_dump(mode="json") == before
    # Neither a shared display name nor an alias becomes a canonical ID.
    for name in ["小王", "阿王"]:
        plan.beats[0].character_focus = [name]
        diagnostic = next(item for item in diagnose_plan_references(plan, story, highlights)
                          if item["rule_id"] == "BEAT_UNKNOWN_CHARACTER")
        assert diagnostic["references"] == [name]


def test_duplicate_ids_stay_ambiguous_and_do_not_grant_retrieval_permission():
    _, _, story, highlights = _artifacts(_config())
    story.character_registry.characters[0].temporary_name = False
    story.character_registry.characters.append(story.character_registry.characters[0].model_copy(deep=True))
    story.story_graph.events.append(story.story_graph.events[1].model_copy(deep=True))
    plan = _plan()
    plan.beats[0].character_focus = ["c1"]
    diagnostics = diagnose_plan_references(plan, story, highlights)
    assert not any(item["blocking"] for item in diagnostics)
    assert {item["rule_id"] for item in diagnostics} >= {
        "BEAT_AMBIGUOUS_EVENT_ID", "BEAT_AMBIGUOUS_CHARACTER_ID",
    }
    request = build_retrieval_requests(plan, story)[0]
    assert request.canonical_character_ids == ()
    assert request.allowed_knowledge_event_ids == ()
    assert request.preferred_spans == ()


def test_legacy_plan_retrieval_reports_missing_refs_without_granting_knowledge():
    _, _, story, _ = _artifacts(_config())
    plan = _plan()
    plan.beats[0].event_ids = ["invented_future"]
    plan.beats[0].character_focus = ["no_person"]
    request = build_retrieval_requests(plan, story)[0]
    assert request.event_ids == ("invented_future",)  # Keep the user's declared reference.
    assert request.allowed_knowledge_event_ids == ()
    assert request.canonical_character_ids == ()
    result = rerank_visual_pool([], r0_pool=[], requests=[request])
    persisted = json.loads(json.dumps(result.provenance))
    assert {item["rule_id"] for item in persisted["requests"][0]["reference_diagnostics"]} == {
        "BEAT_UNKNOWN_EVENT", "BEAT_UNKNOWN_CHARACTER",
    }
    assert persisted["coverage"]["b0"]["status"] == "unknown"


def test_declared_focus_and_highlight_links_are_uncertain_not_contradictions():
    config = _config(format={"duration_mode": "highlight"})
    manifest, transcript, story, highlights = _artifacts(config)
    plan = _plan()
    plan.beats[0].character_focus = ["c1"]
    plan.beats[0].preferred_highlights = ["h_twist"]  # Different event, possible context.
    highlights.candidates[0].selected = False
    built = build_plan(manifest, transcript, story, highlights, config, FakeClient(plan))
    assert built.beats[0].character_focus == ["c1"]
    assert built.beats[0].preferred_highlights == ["h_twist"]
    assert any("BEAT_CHARACTER_EVENT_LINK_UNKNOWN" in risk for risk in built.risks)
    assert any("BEAT_HIGHLIGHT_EVENT_LINK_UNKNOWN" in risk for risk in built.risks)
    assert any("BEAT_HIGHLIGHT_NOT_SELECTED" in risk for risk in built.risks)
    assert all("status=unknown" in risk for risk in built.risks)
    assert built.hook_highlight_id == "h_open"  # No new spoiler permission or hook fallback.


def test_event_with_no_source_spans_stays_unknown():
    _, _, story, highlights = _artifacts(_config())
    story.story_graph.events[1].source_spans = []
    diagnostics = diagnose_plan_references(_plan(), story, highlights)
    assert len(diagnostics) == 3
    assert all(item["rule_id"] == "BEAT_EVENT_MAPPING_UNKNOWN" for item in diagnostics)
    assert all(not item["blocking"] for item in diagnostics)


def test_existing_intent_fields_pass_through_and_bind_ids_after_analysis():
    config = _config(format={"duration_mode": "highlight", "content_unit": "relationship"},
                     project={"editorial_brief": {
                         "narrative_question": "甲乙的信任怎样改变", "preserve": ["沉默中的关系变化"],
                         "stance": "围绕信任与代价", "spoiler_policy": "preserve",
                     }})
    manifest, transcript, story, highlights = _artifacts(config)
    plan = _plan()
    plan.beats[0].character_focus = ["c1"]
    client = FakeClient(plan)
    result = build_plan(manifest, transcript, story, highlights, config, client)
    assert result.editorial_brief == config.project.editorial_brief.model_dump(mode="json")
    assert result.content_unit == "relationship"
    assert result.pov == plan.pov and result.main_spine == plan.main_spine
    payload = json.loads(client.calls[0]["prompt"].split("\n\n", 1)[1])
    assert payload["story"]["characters"][0]["character_id"] == "c1"
    assert payload["editorial_brief"]["narrative_question"] == "甲乙的信任怎样改变"


def test_diagnostics_do_not_change_old_artifacts_config_or_fingerprints():
    config = _config()
    manifest, _, story, highlights = _artifacts(config)
    plan = RecapPlan.model_validate(_plan().model_dump(mode="json"))
    artifacts = [config, manifest, story, highlights, plan]
    before = [item.model_dump(mode="json") for item in artifacts]
    plan_hash = fingerprint_json(before[-1])
    diagnose_plan_references(plan, story, highlights)
    assert [item.model_dump(mode="json") for item in artifacts] == before
    assert fingerprint_json(plan.model_dump(mode="json")) == plan_hash
    # Captured from unchanged main at 4d11a11; no new default config field.
    assert config.fingerprint() == "2f4791a7570451404f64eb8fa4861eca4e512ec027d5707269374d1725f66192"
    example = Path(__file__).resolve().parents[1] / "config.example.yaml"
    assert load_config(example).fingerprint() == "16475a39fefe8f6d79b8ceb82d0b2476157da68fdb905b77cfb62d74a8073256"


def test_qc_checks_hand_edited_character_reference_with_existing_gate_severity():
    config = _config()
    manifest, transcript, story, highlights = _artifacts(config)
    plan = _plan()
    plan.beats[0].character_focus = ["absent"]
    board = _storyboard(manifest, {"source_id": "s1", "start": 20, "end": 24})
    report = preflight_qc(manifest=manifest, transcript=transcript, story=story,
                          highlights=highlights, plan=plan, storyboard=board, config=config)
    finding = next(item for item in report.findings if item.rule_id == "BEAT_UNKNOWN_CHARACTER")
    assert finding.blocking and finding.deterministic and finding.severity == "critical"
    assert finding.evidence["beat_id"] == "b0"
    assert finding.evidence["path"] == "beats[0].character_focus"
    assert finding.evidence["unknown"] == ["absent"]


def test_one_episode_hit_never_certifies_cross_episode_support():
    _, _, story, _ = _artifacts(_config())
    story.story_graph.events[1].source_spans = [
        TimeSpan(source_id="episode_1", start=0, end=2),
        TimeSpan(source_id="episode_2", start=0, end=2),
    ]
    plan = _plan(beats=1)
    requests = build_retrieval_requests(plan, story)
    assert set(requests[0].allowed_source_ids) == {"episode_1", "episode_2"}
    units = [{"unit_id": f"u{i}", "source_id": f"episode_{i}", "start": 0, "end": 2,
              "visible_facts": ["藏起证据"], "evidence_type": "scene_analysis"} for i in [1, 2]]
    result = rerank_visual_pool(units, r0_pool=units[:1], requests=requests,
                                ordinary_limit=1, exploration_fraction=0)
    assert result.provenance["coverage"]["b0"]["status"] == "candidate_evidence"
    report = benchmark_supporting_spans(units[:1], result, {"b0": [["u1", "u2"]]})
    metrics = report["per_beat"]["b0"]
    assert metrics["r1_candidates_recalled"] is True
    assert metrics["r1_writer_pool_recalled"] is False
    assert metrics["render_consumed_support"] is None
