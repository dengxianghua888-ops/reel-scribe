import unittest
from test_boundary_contract import boundary_fixture
from douyin_film_recap.boundary import candidate_revision, proposal_hash
from douyin_film_recap.boundary_apply import prepare_boundary_revision, BoundaryApplyError, HIGHLIGHTS, PLAN, BOARD, SIDECAR
from douyin_film_recap.config import AppConfig
from douyin_film_recap.models import (
    HighlightDocument, RecapPlan, RecapBeat, RhythmProfile, StoryBundle, StoryGraph,
    CharacterRegistry, KnowledgeTimeline, KnowledgeState, StoryEvent,
    Storyboard, StoryboardSegment, VisualReference, TranscriptDocument, TranscriptSegment,
)
from douyin_film_recap.planning import _normalize_storyboard
from douyin_film_recap.utils import fingerprint_json
from douyin_film_recap.visual_evidence import validate_storyboard_visual_evidence, VisualEvidenceError


def apply_fixture():
    p, kw = boundary_fixture()
    candidate = kw.pop("candidate")
    kw.pop("knowledge_snapshot_hash")
    candidate.confidence = .95
    candidate.event_ids = ["e1"]
    candidate.quote = "开始"
    candidate.boundary.action_complete = False
    kw["highlights"] = HighlightDocument(genre_profile="action", candidates=[candidate],
        source_fingerprints={"s1": "a"*64}, weights={"story_significance": 1})
    kw["story"] = StoryBundle(character_registry=CharacterRegistry(characters=[]),
        story_graph=StoryGraph(main_plot="fixture", events=[StoryEvent(event_id="e1", story_order=1,
            reveal_order=1, event="action", source_spans=[{"source_id":"s1","start":10,"end":22}], confidence=.9)]),
        knowledge_timeline=KnowledgeTimeline(states=[KnowledgeState(event_id="e1", reveal_sensitivity="low")]))
    kw["plan"] = RecapPlan(viewer_promise="fixture", pov="fixture", main_spine="fixture",
        hook_strategy="action", hook_highlight_id="h1", target_duration_sec=26,
        duration_mode="highlight", original_ratio_target=.3, ending_strategy="fixture", reveal_strategy="preserve",
        beats=[RecapBeat(beat_id="b1", function="action", change="result", audience_question_in="why",
            audience_question_out="how", narration_job="context", target_duration_sec=26, target_original_sec=6,
            preferred_highlights=["h1"], event_ids=["e1"])], rhythm=RhythmProfile())
    kw["storyboard"] = Storyboard(project_name="fixture", sources=kw["manifest"].sources,
        plan_fingerprint="old-plan", target_duration_sec=26, segments=[
        StoryboardSegment(segment_id="o1", beat_id="b1", mode="original", title="action", text="开始",
            text_raw="开始", visuals=[VisualReference(source_id="s1", start=10, end=16,
                highlight_id="h1", unit_id="highlight:h1")], audio_owner="action_sound",
            planned_duration_sec=6, notes="preserve source", highlight_id="h1"),
        StoryboardSegment(segment_id="v1", beat_id="b1", mode="voiceover", title="context", text="narration",
            visuals=[VisualReference(source_id="s1", start=0, end=10, unit_id="u0"),
                     VisualReference(source_id="s1", start=22, end=32, unit_id="u1")], audio_owner="narration",
            planned_duration_sec=20, notes="manual context")])
    kw["transcript"] = TranscriptDocument(provider="fixture", source_fingerprints={"s1":"a"*64},
        segments=[TranscriptSegment(source_id="s1", start=11, end=13, text="开始"),
                  TranscriptSegment(source_id="s1", start=19, end=21, text="结束")])
    kw["config"] = AppConfig(models={"llm_model":"fixture","vlm_model":"fixture"})
    hashes = {HIGHLIGHTS:"1"*64, PLAN:"2"*64, BOARD:"3"*64}
    kw["current_artifact_hashes"] = hashes
    p.base_artifact_hashes = dict(hashes)
    p.candidate_revision = candidate_revision(candidate)
    p.original_highlight_hash = fingerprint_json(candidate.model_dump(mode="json"))
    p.knowledge_snapshot_hash = fingerprint_json(kw["story"].knowledge_timeline.model_dump(mode="json"))
    p.event_ids = ["e1"]
    p.contained_reveal_ids = ["e1"]
    p.proposal_content_hash = proposal_hash(p)
    p.editorial_decision = "approved"
    p.approved_proposal_hash = p.proposal_content_hash
    return p, kw


class BoundaryApplyTests(unittest.TestCase):
    def test_consistent_07_08_09_and_quote_no_clamp(self):
        p, kw = apply_fixture()
        old = {key: obj.model_dump(mode="json") for key,obj in kw.items() if hasattr(obj,"model_dump")}
        result = prepare_boundary_revision(p, **kw)
        self.assertEqual(set(result.artifacts), {HIGHLIGHTS, PLAN, BOARD, SIDECAR})
        h = result.artifacts[HIGHLIGHTS]["candidates"][0]
        plan, board = result.artifacts[PLAN], result.artifacts[BOARD]
        self.assertEqual((h["start"], h["end"], h["quote"]), (10,22,"开始 结束"))
        self.assertFalse(h["boundary"]["action_complete"])  # advisory did not become hard bool
        self.assertEqual(plan["beats"][0]["target_original_sec"], 12)
        self.assertEqual(board["segments"][0]["planned_duration_sec"],12)
        self.assertEqual(board["segments"][0]["audio_owner"],"action_sound")
        self.assertEqual(board["segments"][0]["visuals"][0]["evidence_revision"], h["evidence_revision"])
        self.assertEqual(board["segments"][1],old["storyboard"]["segments"][1])
        for key, obj in kw.items():
            if key in old:
                self.assertEqual(obj.model_dump(mode="json"),old[key])
        parsed = Storyboard.model_validate(board)
        updated = HighlightDocument.model_validate(result.artifacts[HIGHLIGHTS])
        _normalize_storyboard(parsed, kw["manifest"], updated, kw["config"])
        self.assertEqual(parsed.segments[0].visuals[0].end,22)
        self.assertEqual(parsed.segments[0].visuals[0].evidence_revision,h["evidence_revision"])

    def test_old_board_does_not_drift_to_new_highlight(self):
        p, kw = apply_fixture()
        result = prepare_boundary_revision(p, **kw)
        updated = HighlightDocument.model_validate(result.artifacts[HIGHLIGHTS])
        with self.assertRaisesRegex(VisualEvidenceError,"Stale"):
            validate_storyboard_visual_evidence(kw["storyboard"], kw["manifest"], updated,
                                               kw["scene_index"], kw["scene_analysis"])

    def test_vo_highlight_subspan_only_rebinds(self):
        p, kw = apply_fixture()
        visual = kw["storyboard"].segments[1].visuals[0]
        visual.start, visual.end = 11,15
        kw["config"].format.original_ratio_range = (.1,.9)
        visual.unit_id, visual.highlight_id = "highlight:h1","h1"
        result = prepare_boundary_revision(p, **kw)
        v = result.artifacts[BOARD]["segments"][1]["visuals"][0]
        self.assertEqual((v["start"],v["end"]),(11,15))
        self.assertIn("evidence_revision",v)

    def test_reveal_position_uses_audio_clock_not_planned_budget(self):
        p, kw = apply_fixture()
        board = kw["storyboard"]
        board.segments.reverse()
        board.segments[0].planned_duration_sec = 20
        board.segments[0].audio_duration_sec = 5
        p.allowed_output_position_constraints = {"min_output_seconds": 8}
        p.proposal_content_hash = proposal_hash(p)
        p.approved_proposal_hash = p.proposal_content_hash
        with self.assertRaisesRegex(BoundaryApplyError,"OUTPUT_REVEAL_POSITION"):
            prepare_boundary_revision(p, **kw)

    def test_stale_hash_rejected_without_mutation(self):
        p, kw = apply_fixture()
        kw["current_artifact_hashes"][BOARD]="changed"
        with self.assertRaisesRegex(BoundaryApplyError,"STALE"):
            prepare_boundary_revision(p, **kw)
        self.assertEqual(kw["storyboard"].segments[0].visuals[0].end,16)

    def test_manual_original_subrange_not_overwritten(self):
        p, kw = apply_fixture()
        kw["storyboard"].segments[0].visuals[0].start=11
        with self.assertRaisesRegex(BoundaryApplyError,"MANUAL_ORIGINAL"):
            prepare_boundary_revision(p, **kw)

    def test_required_audio_not_downgraded(self):
        p, kw = apply_fixture()
        h=kw["highlights"].candidates[0]
        h.must_hear_original=True
        p.candidate_revision=candidate_revision(h)
        p.original_highlight_hash=fingerprint_json(h.model_dump(mode="json"))
        p.proposal_content_hash=proposal_hash(p)
        p.approved_proposal_hash=p.proposal_content_hash
        with self.assertRaisesRegex(BoundaryApplyError,"AUDIO_PRESERVATION"):
            prepare_boundary_revision(p, **kw)

    def test_added_reveal_requires_reconciliation(self):
        p, kw = apply_fixture()
        kw["story"].story_graph.events.append(StoryEvent(event_id="killer",story_order=2,reveal_order=2,
            event="killer exposed",source_spans=[{"source_id":"s1","start":21,"end":22}]))
        with self.assertRaisesRegex(BoundaryApplyError,"EVENT_RANGE"):
            prepare_boundary_revision(p, **kw)

    def test_partial_dialogue_no_fake_sentence(self):
        p,kw=apply_fixture()
        kw["transcript"].segments[0].start=9
        with self.assertRaisesRegex(BoundaryApplyError,"PARTIAL_DIALOGUE"):
            prepare_boundary_revision(p,**kw)

    def test_full_adoption_uses_existing_generation_and_keeps_old_bytes(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from douyin_film_recap.pipeline import FilmRecapPipeline
        from douyin_film_recap.revision import freeze_revision
        from douyin_film_recap.boundary_apply import apply_boundary_proposal
        from douyin_film_recap.utils import write_json, content_fingerprint
        from douyin_film_recap import workspace as w
        p, kw = apply_fixture()
        with TemporaryDirectory() as folder:
            source_path=Path(folder)/"source.mp4"
            source_path.write_bytes(b"synthetic full identity only; no media decoding")
            pipeline=FilmRecapPipeline(input_path=source_path,work_dir=Path(folder)/"work",config=kw["config"])
            work=pipeline.work_dir
            source=kw["manifest"].sources[0]
            source.path=str(source_path)
            source.fingerprint=content_fingerprint(source_path)
            kw["storyboard"].sources=[source.model_copy(deep=True)]
            for key in ("highlights","transcript","scene_index"):
                kw[key].source_fingerprints={"s1":source.fingerprint}
            p.source_sha256=source.fingerprint
            for ref in p.ordered_evidence_units:
                ref.source_sha256=source.fingerprint
            artifacts={"00_source_manifest.json":kw["manifest"],"01_transcript.json":kw["transcript"],
                "02_scene_index.json":kw["scene_index"],"03_scene_analysis.json":kw["scene_analysis"],
                "04_character_registry.json":kw["story"].character_registry,
                "05_story_graph.json":kw["story"].story_graph,"06_knowledge_timeline.json":kw["story"].knowledge_timeline,
                HIGHLIGHTS:kw["highlights"],PLAN:kw["plan"],BOARD:kw["storyboard"]}
            for name,value in artifacts.items():
                write_json(work/name,value)
            base=freeze_revision(work)
            p.base_artifact_hashes=base["artifact_hashes"]
            p.proposal_content_hash=proposal_hash(p)
            p.approved_proposal_hash=p.proposal_content_hash
            original=(work/BOARD).read_bytes()
            result=apply_boundary_proposal(work,proposal=p,base=base,config=kw["config"],timebases=kw["timebases"])
            active=Path(result["active_dir"])
            self.assertEqual(result["status"],"ADOPTED")
            self.assertNotEqual(active,work)
            self.assertEqual((work/BOARD).read_bytes(),original)
            self.assertEqual(w.read(active/BOARD)["segments"][0]["visuals"][0]["end"],22)
            self.assertEqual(w.read(active/"state.json")["stages"]["pre_qc"]["status"],"pending")
            self.assertTrue((active/SIDECAR).is_file())
            with self.assertRaisesRegex(Exception,"BASE_CONFLICT|STALE_BASE"):
                apply_boundary_proposal(work,proposal=p,base=base,config=kw["config"],timebases=kw["timebases"])

    def test_collect_timebase_uses_pts_and_rejects_missing_clock(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch
        from douyin_film_recap.boundary_apply import collect_boundary_timebases
        from douyin_film_recap.utils import content_fingerprint
        _,kw=apply_fixture()
        with TemporaryDirectory() as folder:
            path=Path(folder)/"source.mp4"
            path.write_bytes(b"synthetic identity")
            source=kw["manifest"].sources[0]
            source.path=str(path)
            source.fingerprint=content_fingerprint(path)
            data={"streams":[{"codec_type":"video","time_base":"1/90000","start_pts":900000,"start_time":"10.000000"}]}
            with patch("douyin_film_recap.media.ffprobe_json",return_value=data):
                mapping=collect_boundary_timebases(kw["manifest"])["s1"]
            self.assertEqual(mapping.origin_pts,900000)
            self.assertEqual(mapping.origin_seconds,0)
            data["streams"][0].pop("start_pts")
            with patch("douyin_film_recap.media.ffprobe_json",return_value=data):
                with self.assertRaisesRegex(BoundaryApplyError,"MAPPING_UNKNOWN"):
                    collect_boundary_timebases(kw["manifest"])

    def test_source_range_normalization_rejects_no_silent_clamp(self):
        p,kw=apply_fixture()
        kw["storyboard"].segments[0].visuals[0].end=65
        with self.assertRaisesRegex(ValueError,"invalid source range"):
            _normalize_storyboard(kw["storyboard"],kw["manifest"],kw["highlights"],kw["config"])


if __name__ == "__main__":
    unittest.main()
