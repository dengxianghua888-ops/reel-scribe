"""An edit after snapshot parsing must never become the older render's base hash."""
import unittest
from unittest.mock import patch

import test_protected_revision as protected_fixture
from douyin_film_recap.models import QCReport, Storyboard
from douyin_film_recap.pipeline import FilmRecapPipeline
from douyin_film_recap import workspace as w


class RenderCurrentSnapshotTests(unittest.TestCase):
    def setUp(self):
        protected_fixture.ProtectedRevisionTests.setUp(self)
        self.current = FilmRecapPipeline.from_current(work_dir=self.work, config=self.config)
        self.late = w.read(self.current.paths["storyboard"])
        self.late["segments"][0]["notes"] = "late manual save during validation"

    def save_late(self, *args, **kwargs):
        w.atomic(self.current.paths["storyboard"], self.late)

    def fake_render(self, board, *args):
        output = {}
        for key, filename in [("final_video", "final.mp4"), ("preview_video", "preview.mp4"),
                              ("subtitle", "captions.srt"), ("edl", "edl.json")]:
            path = self.root / filename
            path.write_bytes(b"synthetic stage artifact")
            output[key] = str(path)
        board.output = output
        return board

    def test_render_validation_edit_does_not_replace_new_draft_with_old_snapshot(self):
        with patch.object(self.current, "_validate_visual_evidence", side_effect=self.save_late), \
             patch("douyin_film_recap.pipeline.render_storyboard", side_effect=self.fake_render) as renderer:
            with self.assertRaisesRegex(w.WorkspaceError, "RENDER_CURRENT_STORYBOARD_CHANGED"):
                self.current._stage_render()
        self.assertEqual(w.read(self.current.paths["storyboard"]), self.late)
        renderer.assert_not_called()

    def test_repair_validation_edit_does_not_replace_new_draft_with_old_snapshot(self):
        blocked = QCReport(stage="post_render", status="BLOCKED", findings=[])
        passed = QCReport(stage="post_render", status="PASSED", findings=[])
        with patch("douyin_film_recap.pipeline.post_render_qc", side_effect=[blocked, passed]), \
             patch.object(self.current, "_validate_visual_evidence", side_effect=self.save_late), \
             patch("douyin_film_recap.pipeline.render_storyboard", side_effect=self.fake_render) as renderer:
            with self.assertRaisesRegex(w.WorkspaceError, "RENDER_CURRENT_STORYBOARD_CHANGED"):
                self.current._stage_post_qc()
        self.assertEqual(w.read(self.current.paths["storyboard"]), self.late)
        renderer.assert_not_called()

    def test_pre_qc_cue_attachment_does_not_overwrite_late_manual_save(self):
        with patch.object(self.current, "_attach_original_cues", side_effect=self.save_late):
            with self.assertRaisesRegex(w.WorkspaceError, "RENDER_CURRENT_STORYBOARD_CHANGED"):
                self.current._prepare_stage("pre_qc")
        self.assertEqual(w.read(self.current.paths["storyboard"]), self.late)

    def test_pre_qc_validation_edit_stops_before_model_or_qc_work(self):
        with patch.object(self.current, "_validate_visual_evidence", side_effect=self.save_late), \
             patch("douyin_film_recap.pipeline.preflight_qc") as qc:
            with self.assertRaisesRegex(w.WorkspaceError, "RENDER_CURRENT_STORYBOARD_CHANGED"):
                self.current._stage_pre_qc()
        qc.assert_not_called()
        self.assertEqual(w.read(self.current.paths["storyboard"]), self.late)
        self.assertFalse(self.current.paths["pre_qc"].exists())

    def test_hash_is_bound_to_parsed_bytes_not_a_later_read(self):
        validate = Storyboard.model_validate
        def parse_then_save(value):
            self.save_late()
            return validate(value)
        with patch("douyin_film_recap.pipeline.Storyboard.model_validate", side_effect=parse_then_save), \
             patch("douyin_film_recap.pipeline.render_storyboard", side_effect=self.fake_render) as renderer:
            with self.assertRaisesRegex(w.WorkspaceError, "RENDER_CURRENT_STORYBOARD_CHANGED"):
                self.current._stage_render()
        self.assertEqual(w.read(self.current.paths["storyboard"]), self.late)
        renderer.assert_not_called()

    def test_normal_two_repairs_refresh_only_the_published_snapshot(self):
        blocked = QCReport(stage="post_render", status="BLOCKED", findings=[])
        passed = QCReport(stage="post_render", status="PASSED", findings=[])
        with patch("douyin_film_recap.pipeline.post_render_qc", side_effect=[blocked, blocked, passed]), \
             patch("douyin_film_recap.pipeline.render_storyboard", side_effect=self.fake_render) as renderer:
            result = self.current._stage_post_qc()
        self.assertEqual(renderer.call_count, 2)
        self.assertEqual(w.read(result)["status"], "PASSED")
        self.assertEqual(w.read(self.current.paths["storyboard"])["segments"][0]["notes"], "original note")

    def test_post_qc_edit_does_not_publish_stale_passed_report(self):
        def check(**kwargs):
            self.save_late()
            return QCReport(stage="post_render", status="PASSED", findings=[])
        with patch("douyin_film_recap.pipeline.post_render_qc", side_effect=check):
            with self.assertRaisesRegex(w.WorkspaceError, "RENDER_CURRENT_STORYBOARD_CHANGED"):
                self.current._stage_post_qc()
        self.assertEqual(w.read(self.current.paths["storyboard"]), self.late)
        self.assertFalse(self.current.paths["post_qc"].exists())


if __name__ == "__main__":
    unittest.main()
