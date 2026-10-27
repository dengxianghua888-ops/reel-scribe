"""Plan-v0 L1-L4 are case groups, separate from the four diagnostic layers."""
from copy import deepcopy
import json
from pathlib import Path
import unittest

from douyin_film_recap.models import HighlightCandidate, StoryEvent
from douyin_film_recap.planning import _build_visual_pool, _build_visual_pool_r0
from douyin_film_recap.retrieval import (
    RetrievalResult, benchmark_supporting_spans, build_retrieval_requests,
    rerank_visual_pool, writer_input_bytes,
)
from douyin_film_recap.utils import fingerprint_json
from test_retrieval_layers import BEAT, GOLD, SUPPORT, long_source_inputs


CASE = json.loads((Path(__file__).parent / "fixtures/retrieval-plan-v0.json").read_text())


def compare_pools(inputs):
    """The same objects/configuration reach R0 and R1; only method changes."""
    inputs[4].format.visual_retrieval = "r0"
    baseline = _build_visual_pool(*inputs)
    inputs[4].format.visual_retrieval = "r1"
    provenance = {}
    pool = _build_visual_pool(*inputs, retrieval_report=provenance)
    return baseline, RetrievalResult(pool, provenance)


class RetrievalPlanCaseTests(unittest.TestCase):
    def test_plan_l1_gold_and_observation_summary_are_frozen(self):
        inputs = long_source_inputs()
        self.assertEqual(CASE["gold"], GOLD)
        self.assertEqual(CASE["beat_id"], BEAT)
        self.assertEqual(inputs[0].sources[0].duration, CASE["source_duration_sec"])
        self.assertEqual(len(inputs[5].units), CASE["unit_count"])
        units = {unit.unit_id: unit for unit in inputs[5].units}
        analysis = {item.unit_id: item for item in inputs[6].items}
        for row in CASE["gold_observations"]:
            self.assertEqual((units[row["unit_id"]].start, units[row["unit_id"]].end),
                             (row["start"], row["end"]))
            self.assertEqual(analysis[row["unit_id"]].visible_facts, row["visible_facts"])
        baseline, result = compare_pools(inputs)
        metric = benchmark_supporting_spans(baseline, result, GOLD, {BEAT: SUPPORT},
            indexed_unit_ids=set(analysis), planned_unit_ids={BEAT: SUPPORT})["per_beat"][BEAT]
        self.assertFalse(metric["r0_support_recalled"])
        self.assertTrue(metric["r1_candidates_recalled"])
        self.assertTrue(metric["r1_writer_pool_recalled"])
        self.assertTrue(metric["planned_support"])
        self.assertTrue(metric["render_consumed_support"])

    def test_plan_l2_high_scores_at_start_middle_end_do_not_replace_action_reaction(self):
        inputs = long_source_inputs()
        analysis = {item.unit_id: item for item in inputs[6].items}
        units = {unit.unit_id: unit for unit in inputs[5].units}
        lures = CASE["time_dispersed_lures"]
        for row in lures:
            self.assertEqual((units[row["unit_id"]].start, units[row["unit_id"]].end),
                             (row["start"], row["end"]))
            analysis[row["unit_id"]].visible_facts = row["visible_facts"]
        baseline, result = compare_pools(inputs)
        rankings = {row["unit_id"]: row for row in result.provenance["per_beat_rankings"][BEAT]}
        self.assertEqual(CASE["gold"], GOLD)  # the late decoy never becomes gold
        for row in lures:
            self.assertGreater(rankings[row["unit_id"]]["score"], 0)
            self.assertGreaterEqual(rankings[row["unit_id"]]["score"],
                                    max(rankings[unit_id]["score"] for unit_id in SUPPORT))
            self.assertNotIn(row["unit_id"], SUPPORT)
        late_c = lures[-1]["unit_id"]
        self.assertIn(late_c, result.provenance["pool_unit_ids"])
        for selected in ({row["unit_id"] for row in lures}, {late_c}):
            with self.subTest(selected=selected):
                metric = benchmark_supporting_spans(baseline, result, GOLD,
                    {BEAT: selected}, indexed_unit_ids=set(analysis),
                    planned_unit_ids={BEAT: selected})["per_beat"][BEAT]
                self.assertTrue(metric["r1_writer_pool_recalled"])
                self.assertFalse(metric["planned_support"])
                self.assertFalse(metric["render_consumed_support"])
                self.assertEqual(metric["first_missing_layer"], "L3_PLANNING")
        self.assertLessEqual(writer_input_bytes(result.pool), writer_input_bytes(baseline))

    def test_plan_l3_shared_inputs_limit_long_summary_and_future_knowledge(self):
        inputs = long_source_inputs()
        settings = CASE["budget_and_knowledge"]
        analysis = {item.unit_id: item for item in inputs[6].items}
        long_id, future_id = settings["long_unit_id"], settings["future_unit_id"]
        analysis[long_id].visible_facts = [settings["long_text_fragment"] * settings["long_text_repetitions"]]
        analysis[future_id].visible_facts = settings["future_visible_facts"]
        future = next(unit for unit in inputs[5].units if unit.unit_id == future_id)
        inputs[1].story_graph.events.append(StoryEvent(event_id=settings["future_event_id"],
            story_order=2, reveal_order=2, event="future identity revealed",
            source_spans=[{"source_id": "s1", "start": future.start, "end": future.end}]))
        foreign_id = settings["foreign_unit_id"]
        analysis[foreign_id].visible_facts = settings["foreign_visible_facts"]
        foreign = next(unit for unit in inputs[5].units if unit.unit_id == foreign_id)
        foreign.source_id = "s2"
        inputs[0].sources.append(inputs[0].sources[0].model_copy(update={
            "source_id": "s2", "fingerprint": "b" * 64, "filename": "other-source.mp4",
            "path": "/synthetic/other-source.mp4"}))
        inputs[5].source_fingerprints["s2"] = "b" * 64
        inputs[6].unit_fingerprint = fingerprint_json([
            unit.model_dump(mode="json") for unit in inputs[5].units])
        inputs[2].candidates.append(HighlightCandidate(
            highlight_id=settings["selected_highlight_id"], source_id="s1", start=5400, end=5430,
            types=["action"], story_function="synthetic retained highlight", selected=True))
        inputs[3].beats.append(inputs[3].beats[0].model_copy(update={
            "beat_id": "uncovered", "event_ids": [], "change": "unobserved silent gesture"}))
        frozen = [deepcopy(obj.model_dump(mode="json")) for obj in inputs]
        baseline, result = compare_pools(inputs)
        for index, obj in enumerate(inputs):
            current = obj.model_dump(mode="json")
            if index == 4:
                current["format"]["visual_retrieval"] = "r0"
            self.assertEqual(current, frozen[index])
        ordinary = [row for row in result.pool if row["evidence_type"] != "highlight"]
        self.assertEqual(result.provenance["requested_ordinary_limit"], settings["ordinary_limit"])
        self.assertLessEqual(len(ordinary), settings["ordinary_limit"])
        self.assertEqual(len(ordinary), len({row["unit_id"] for row in ordinary}))
        self.assertEqual(result.provenance["ordinary_count"], len(ordinary))
        self.assertEqual(result.provenance["highlight_append_count"], 1)
        self.assertEqual(result.provenance["deduplicated_pool_count"],
                         len({row["unit_id"] for row in result.pool}))
        self.assertEqual([row for row in result.pool if row["evidence_type"] == "highlight"],
                         [row for row in baseline if row["evidence_type"] == "highlight"])
        self.assertNotIn(long_id, result.provenance["pool_unit_ids"])
        self.assertTrue(any(row["unit_id"] == long_id and row["reason"] == "writer_budget"
                            for row in result.provenance["budget_exclusions"]))
        self.assertIn({"unit_id": future_id, "reason": "knowledge_constraint"},
                      result.provenance["exclusions"][BEAT])
        self.assertIn({"unit_id": foreign_id, "reason": "source_constraint"},
                      result.provenance["exclusions"][BEAT])
        self.assertEqual(result.provenance["coverage"]["uncovered"]["status"], "unknown")
        self.assertLessEqual(writer_input_bytes(result.pool), writer_input_bytes(baseline))
        self.assertEqual(result.provenance["writer_bytes"], writer_input_bytes(result.pool))
        self.assertEqual(result.provenance["r0_writer_bytes"], writer_input_bytes(baseline))
        self.assertFalse(result.provenance["provider_token_budget_verified"])

    def test_plan_l3_duplicate_candidates_reject_without_extra_capacity(self):
        inputs = long_source_inputs()
        inputs[5].units.append(inputs[5].units[0].model_copy(deep=True))
        for method in ("r0", "r1"):
            with self.subTest(method=method):
                inputs[4].format.visual_retrieval = method
                with self.assertRaisesRegex(ValueError, "Duplicate scene unit_id"):
                    _build_visual_pool(*inputs)
        inputs = long_source_inputs()
        baseline = _build_visual_pool(*inputs)
        expanded = inputs[4].model_copy(deep=True)
        expanded.format.visual_pool_size = len(inputs[5].units)
        ordinary = _build_visual_pool_r0(*inputs[:4], expanded, *inputs[5:])
        requests = build_retrieval_requests(inputs[3], inputs[1])
        with self.assertRaisesRegex(ValueError, "Duplicate retrieval unit"):
            rerank_visual_pool(ordinary + [deepcopy(ordinary[0])], r0_pool=baseline,
                requests=requests, ordinary_limit=CASE["budget_and_knowledge"]["ordinary_limit"])


if __name__ == "__main__":
    unittest.main()
