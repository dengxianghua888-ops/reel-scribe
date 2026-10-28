"""Long-source synthetic contracts, not real-film or model-quality evidence."""
import json
import unittest

from douyin_film_recap.config import AppConfig
from douyin_film_recap.models import (
    CharacterRegistry, HighlightCandidate, HighlightDocument, KnowledgeState, KnowledgeTimeline,
    RecapBeat, RecapPlan, RhythmProfile, SceneAnalysisDocument, SceneAnalysisItem,
    SceneIndex, SceneUnit, SourceInfo, SourceManifest, StoryBundle, StoryEvent, StoryGraph,
)
from douyin_film_recap.planning import _build_visual_pool, _build_visual_pool_r0
from douyin_film_recap.retrieval import (
    RetrievalResult, benchmark_supporting_spans, writer_input_bytes,
)
from douyin_film_recap.utils import fingerprint_json


BEAT = "late_action_then_reaction"
ACTION, REACTION = "u0180", "u0181"
SUPPORT = {ACTION, REACTION}
GOLD = {BEAT: [[ACTION, REACTION]]}


def long_source_inputs(*, ordinary_limit=12, missing_analysis=(), text_byte_budget=None):
    """A 120-minute metadata-only index with early lures and two late shots.

    No media is read or generated. The broad event span intentionally cannot
    locate the action by itself; the existing retriever must use observations.
    """
    source = SourceInfo(source_id="s1", path="/synthetic/long-source.mp4",
        fingerprint="a" * 64, filename="long-source.mp4", duration=7200,
        width=32, height=32, fps=30)
    manifest = SourceManifest(sources=[source], config_fingerprint="fixture")
    units = [SceneUnit(unit_id=f"u{i:04d}", source_id="s1", start=i*30, end=(i+1)*30,
                       shot_spans=[(i*30, (i+1)*30)]) for i in range(240)]
    index = SceneIndex(units=units, source_fingerprints={"s1": source.fingerprint},
                       detector="synthetic", detection_status="unknown")
    facts = {ACTION: "keeper releases brass seal then door unlocks",
             REACTION: "witness recoils at unlocked door after seal release"}
    analysis = SceneAnalysisDocument(provider="synthetic", model="none",
        unit_fingerprint=fingerprint_json([u.model_dump(mode="json") for u in units]),
        items=[SceneAnalysisItem(unit_id=u.unit_id, visible_facts=[facts.get(
            u.unit_id, "keeper brass door " * 24 if i < 120 else "empty corridor")])
            for i, u in enumerate(units) if u.unit_id not in missing_analysis])
    story = StoryBundle(character_registry=CharacterRegistry(characters=[]),
        story_graph=StoryGraph(main_plot="synthetic", events=[StoryEvent(event_id="e1",
            story_order=1, reveal_order=1,
            event="keeper releases brass seal then witness recoils at unlocked door",
            source_spans=[{"source_id": "s1", "start": 0, "end": 7200}])]),
        knowledge_timeline=KnowledgeTimeline(states=[KnowledgeState(event_id="e1")]))
    plan = RecapPlan(viewer_promise="synthetic", pov="witness", main_spine="synthetic",
        hook_strategy="synthetic", hook_highlight_id="", target_duration_sec=60,
        duration_mode="highlight", original_ratio_target=0, ending_strategy="synthetic",
        reveal_strategy="preserve", rhythm=RhythmProfile(), beats=[RecapBeat(
            beat_id=BEAT, function="cause and reaction", event_ids=["e1"],
            change="seal released then witness recoils", audience_question_in="why",
            audience_question_out="what next", narration_job="connect shots", target_duration_sec=60)])
    config = AppConfig(models={"llm_model": "synthetic", "vlm_model": "synthetic"}, format={
        "visual_pool_size": ordinary_limit, "visual_exploration_fraction": 0,
        "visual_pool_text_budget": text_byte_budget})
    highlights = HighlightDocument(genre_profile="synthetic", candidates=[],
        source_fingerprints={"s1": source.fingerprint}, weights={})
    return manifest, story, highlights, plan, config, index, analysis


def long_source_fixture(**kwargs):
    inputs = long_source_inputs(**kwargs)
    _, _, _, _, config, _, analysis = inputs
    baseline = _build_visual_pool(*inputs)
    config.format.visual_retrieval = "r1"
    provenance = {}
    pool = _build_visual_pool(*inputs, retrieval_report=provenance)
    return baseline, RetrievalResult(pool, provenance), {item.unit_id for item in analysis.items}


class RetrievalLayerTests(unittest.TestCase):
    def report(self, *, text_byte_budget=None, missing_analysis=(), planned=None, consumed=None):
        baseline, result, indexed = long_source_fixture(
            text_byte_budget=text_byte_budget, missing_analysis=missing_analysis)
        return benchmark_supporting_spans(baseline, result, GOLD, consumed,
            indexed_unit_ids=indexed, planned_unit_ids=planned)

    def test_l1_missing_late_reaction_is_analysis_index_omission(self):
        metric = self.report(missing_analysis={REACTION})["per_beat"][BEAT]
        self.assertFalse(metric["analyzed_index_support"])
        self.assertFalse(metric["r1_candidates_recalled"])
        self.assertEqual(metric["first_missing_layer"], "L1_ANALYSIS_INDEX")
        self.assertIsNone(metric["retrieval_gap"])

    def test_l2_indexed_conjunction_ranked_but_cannot_fit_one_unit_budget(self):
        metric = self.report(text_byte_budget=1100)["per_beat"][BEAT]
        self.assertTrue(metric["analyzed_index_support"])
        self.assertTrue(metric["r1_candidates_recalled"])
        self.assertFalse(metric["r1_writer_pool_recalled"])
        self.assertEqual(metric["first_missing_layer"], "L2_RETRIEVAL")
        self.assertEqual(metric["retrieval_gap"], "writer_pool_selection_or_budget")

    def test_unmeasured_index_does_not_blame_a_later_missing_layer(self):
        baseline, result, _ = long_source_fixture(text_byte_budget=1100)
        metric = benchmark_supporting_spans(baseline, result, GOLD,
            {BEAT: set()}, planned_unit_ids={BEAT: set()})["per_beat"][BEAT]
        self.assertEqual(metric["layers"]["L1_ANALYSIS_INDEX"], "UNKNOWN")
        self.assertEqual(metric["layers"]["L2_RETRIEVAL"], "MISSING")
        self.assertEqual(metric["first_missing_layer"], "UNKNOWN")
        self.assertIsNone(metric["retrieval_gap"])

    def test_knowledge_filter_is_separate_from_writer_budget_omission(self):
        inputs = long_source_inputs()
        inputs[1].story_graph.events.append(StoryEvent(event_id="future", story_order=2,
            reveal_order=2, event="future reveal", source_spans=[{
                "source_id": "s1", "start": 5430, "end": 5460}]))
        baseline = _build_visual_pool(*inputs)
        inputs[4].format.visual_retrieval = "r1"
        provenance = {}
        pool = _build_visual_pool(*inputs, retrieval_report=provenance)
        result = RetrievalResult(pool, provenance)
        metric = benchmark_supporting_spans(baseline, result, GOLD,
            indexed_unit_ids={item.unit_id for item in inputs[6].items})["per_beat"][BEAT]
        self.assertTrue(metric["analyzed_index_support"])
        self.assertFalse(metric["r1_candidates_recalled"])
        self.assertEqual(metric["first_missing_layer"], "L2_RETRIEVAL")
        self.assertEqual(metric["retrieval_gap"], "candidate_filter_or_ranking")
        self.assertIn({"unit_id": REACTION, "reason": "knowledge_constraint"},
                      provenance["exclusions"][BEAT])

    def test_l3_writer_pool_support_does_not_mean_planner_selected_reaction(self):
        metric = self.report(planned={BEAT: {ACTION}})["per_beat"][BEAT]
        self.assertTrue(metric["r1_writer_pool_recalled"])
        self.assertFalse(metric["planned_support"])
        self.assertEqual(metric["first_missing_layer"], "L3_PLANNING")

    def test_l4_complete_plan_does_not_mean_render_consumed_reaction(self):
        metric = self.report(planned={BEAT: SUPPORT}, consumed={BEAT: {ACTION}})["per_beat"][BEAT]
        self.assertTrue(metric["planned_support"])
        self.assertFalse(metric["render_consumed_support"])
        self.assertEqual(metric["first_missing_layer"], "L4_CONSUMPTION")

    def test_missing_trace_is_unknown_and_other_beat_cannot_supply_it(self):
        for consumed in (None, {"other_beat": SUPPORT}):
            with self.subTest(consumed=consumed):
                metric = self.report(planned={BEAT: SUPPORT}, consumed=consumed)["per_beat"][BEAT]
                self.assertIsNone(metric["render_consumed_support"])
                self.assertEqual(metric["layers"]["L4_CONSUMPTION"], "UNKNOWN")
                self.assertEqual(metric["first_missing_layer"], "UNKNOWN")
        metric = self.report(planned={"other_beat": SUPPORT})["per_beat"][BEAT]
        self.assertIsNone(metric["planned_support"])
        self.assertEqual(metric["first_missing_layer"], "UNKNOWN")

    def test_complete_chain_only_certifies_synthetic_conjunctive_support(self):
        report = self.report(planned={BEAT: SUPPORT}, consumed={BEAT: SUPPORT})
        metric = report["per_beat"][BEAT]
        self.assertTrue(all(state == "PRESENT" for state in metric["layers"].values()))
        self.assertEqual(metric["first_missing_layer"], "NONE")
        self.assertEqual(metric["render_consumption_scope"], "per_beat")
        self.assertEqual(report["quality_status"], "synthetic_gold_only")

    def test_empty_gold_and_legacy_calls_do_not_gain_unmeasured_layers(self):
        baseline, result, _ = long_source_fixture()
        empty = benchmark_supporting_spans(baseline, result, {})
        self.assertEqual(empty["quality_status"], "NOT_RUN")
        self.assertEqual(empty["per_beat"], {})
        legacy = benchmark_supporting_spans(baseline, result, GOLD, SUPPORT)["per_beat"][BEAT]
        self.assertTrue(legacy["render_consumed_support"])
        self.assertEqual(legacy["render_consumption_scope"], "global_unit_ids")
        self.assertIsNone(legacy["analyzed_index_support"])
        self.assertIsNone(legacy["planned_support"])
        self.assertEqual(legacy["first_missing_layer"], "UNKNOWN")
        scoped = benchmark_supporting_spans(baseline, result, GOLD, SUPPORT,
            indexed_unit_ids={f"u{i:04d}" for i in range(240)},
            planned_unit_ids={BEAT: SUPPORT})["per_beat"][BEAT]
        self.assertTrue(scoped["render_consumed_support"])
        self.assertEqual(scoped["layers"]["L4_CONSUMPTION"], "UNKNOWN")
        self.assertEqual(scoped["first_missing_layer"], "UNKNOWN")

    def test_long_lures_and_late_shots_share_actual_writer_byte_envelope(self):
        baseline, result, _ = long_source_fixture()
        self.assertTrue(all(row["unit_id"] not in SUPPORT for row in baseline))
        self.assertLessEqual(SUPPORT, {row["unit_id"] for row in result.pool})
        actual = lambda rows: len(json.dumps({"visual_pool": rows}, ensure_ascii=False, indent=2).encode())
        self.assertEqual(result.provenance["writer_bytes"], actual(result.pool))
        self.assertEqual(result.provenance["r0_writer_bytes"], actual(baseline))
        self.assertLessEqual(writer_input_bytes(result.pool), writer_input_bytes(baseline))
        self.assertLessEqual(result.provenance["ordinary_count"], 12)
        self.assertFalse(result.provenance["provider_token_budget_verified"])
        self.assertIsNone(result.provenance["writer_tokens"])
        self.assertFalse(result.provenance["same_total_compute_cost_verified"])

    def test_explicit_writer_byte_budget_caps_actual_r0_and_r1_paths(self):
        budget = 1100
        baseline, result, _ = long_source_fixture(text_byte_budget=budget)
        self.assertLessEqual(writer_input_bytes(baseline), budget)
        self.assertLessEqual(writer_input_bytes(result.pool), writer_input_bytes(baseline))
        self.assertEqual(result.provenance["r0_writer_bytes"], writer_input_bytes(baseline))

    def test_uncapped_r0_remains_identical_to_existing_selection(self):
        inputs = long_source_inputs()
        self.assertEqual(_build_visual_pool(*inputs), _build_visual_pool_r0(*inputs))

    def test_selected_highlights_alone_exceed_cap_in_both_real_paths(self):
        inputs = long_source_inputs(text_byte_budget=200)
        inputs[2].candidates.append(HighlightCandidate(highlight_id="h1", source_id="s1",
            start=5400, end=5430, types=["action"], story_function="synthetic", selected=True))
        for method in ("r0", "r1"):
            with self.subTest(method=method):
                inputs[4].format.visual_retrieval = method
                with self.assertRaisesRegex(ValueError, "highlights alone"):
                    _build_visual_pool(*inputs)


if __name__ == "__main__":
    unittest.main()
