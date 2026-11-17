"""Synthetic FFmpeg integration and path/corruption safety; no film-quality claim."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from douyin_film_recap.config import AppConfig
from douyin_film_recap.models import SourceInfo, Storyboard, StoryboardSegment, VisualReference
from douyin_film_recap.render import render_storyboard
from douyin_film_recap.render_cache import CachePathError, SegmentCache, copy_new, verify_media
from douyin_film_recap.utils import content_fingerprint, run_command


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class IncrementalCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="film-cache-tests-")
        cls.root = Path(cls.temporary.name)
        cls.source = cls.root / "source.mp4"
        run_command(["ffmpeg", "-n", "-v", "error", "-f", "lavfi", "-i",
            "testsrc2=size=64x64:rate=30:duration=3", "-f", "lavfi", "-i",
            "sine=frequency=440:sample_rate=48000:duration=3", "-c:v", "libx264", "-c:a", "aac", "-shortest", cls.source])
        cls.voice = cls.root / "voice.wav"
        run_command(["ffmpeg", "-n", "-v", "error", "-f", "lavfi", "-i",
                     "sine=frequency=880:sample_rate=48000:duration=1", cls.voice])

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def setUp(self):
        self.work = Path(tempfile.mkdtemp(dir=self.root))
        self.config = AppConfig(models={"llm_model": "unused", "vlm_model": "unused"},
            render={"width": 64, "height": 64, "fps": 30, "layout": "fit_black", "preset": "ultrafast",
                    "subtitle_burn_in": False, "incremental_cache": True}, runtime={"max_parallel_ffmpeg": 1})
        source = SourceInfo(source_id="src", path=str(self.source), fingerprint=content_fingerprint(self.source),
            size_bytes=self.source.stat().st_size, filename="source.mp4", duration=3, width=64, height=64, fps=30)
        self.board = Storyboard(project_name="synthetic", sources=[source], plan_fingerprint="p", target_duration_sec=2,
            segments=[StoryboardSegment(segment_id=f"s{i}", beat_id="b", mode="original", title="",
                text="", visuals=[VisualReference(source_id="src", start=i, end=i + 1)], audio_owner="action_sound",
                planned_duration_sec=1, notes="") for i in range(2)])

    def receipt(self, board):
        return json.loads(Path(board.output["render_receipt"]).read_text())

    def decode(self, path, stream):
        args = ["ffmpeg", "-v", "error", "-i", str(path)]
        args += ["-map", "0:v:0", "-pix_fmt", "yuv420p", "-f", "rawvideo"] if stream == "video" else ["-map", "0:a:0", "-f", "s16le", "-acodec", "pcm_s16le"]
        return subprocess.run(args + ["-"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def test_cold_warm_and_full_oracle_equal_decoded_media(self):
        full_config = self.config.model_copy(deep=True)
        full_config.render.incremental_cache = False
        full = render_storyboard(self.board, full_config, self.work / "full")
        cold = render_storyboard(self.board, self.config, self.work / "cached")
        warm = render_storyboard(self.board, self.config, self.work / "cached")
        self.assertEqual([r["action"] for r in self.receipt(cold)["segments"]], ["executed", "executed"])
        self.assertEqual([r["action"] for r in self.receipt(warm)["segments"]], ["reused", "reused"])
        self.assertTrue(self.receipt(warm)["finalize_executed"])
        self.assertFalse(self.receipt(warm)["qc_inherited"])
        self.assertLess(self.receipt(warm)["ffmpeg_render_calls"], self.receipt(cold)["ffmpeg_render_calls"])
        self.assertEqual(full.output["realized_timeline"], cold.output["realized_timeline"])
        self.assertEqual(cold.output["realized_timeline"], warm.output["realized_timeline"])
        for stream in ("video", "audio"):
            self.assertEqual(self.decode(full.output["final_video"], stream), self.decode(cold.output["final_video"], stream))
            self.assertEqual(self.decode(cold.output["final_video"], stream), self.decode(warm.output["final_video"], stream))
        for a, b in zip(cold.segments, warm.segments):
            self.assertNotEqual(Path(a.rendered_file).stat().st_ino, Path(b.rendered_file).stat().st_ino)
        self.assertEqual(content_fingerprint(self.source), self.board.sources[0].fingerprint)

    def test_atomic_publication_crash_and_concurrent_writers(self):
        cold = render_storyboard(self.board, self.config, self.work)
        plan = json.loads(Path(cold.output["render_plan"]).read_text())
        node = next(n for n in plan["nodes"] if n["kind"] == "segment_av")
        artifact = Path(cold.segments[0].rendered_file)
        verified = verify_media(artifact, node["params"])
        cache = SegmentCache(self.work / "fault-cache")
        with patch("douyin_film_recap.render_cache.os.link", side_effect=OSError("synthetic interrupted publish")):
            with self.assertRaises(OSError):
                cache.publish(node, artifact, verified, attempt_id="fault")
        self.assertFalse(list(cache.root.rglob("*.json")))
        self.assertFalse(list(cache.root.rglob("*.pending")))
        self.assertTrue(artifact.exists())
        with ThreadPoolExecutor(max_workers=2) as executor:
            records = list(executor.map(lambda index: cache.publish(node, artifact, verified,
                attempt_id=str(index)), range(2)))
        self.assertEqual(len(set(records)), 2)
        output = self.work / "materialized.mp4"
        actual, _ = cache.materialize(node, output)
        self.assertEqual(actual["sha256"], verified["sha256"])
        self.assertNotEqual(output.stat().st_ino, artifact.stat().st_ino)
        for record in records:
            data = json.loads(record.read_text())
            self.assertEqual(data["completion_state"], "COMPLETE")

    def test_bad_manifest_and_symlink_artifact_never_followed(self):
        cold = render_storyboard(self.board, self.config, self.work)
        first = self.receipt(cold)["segments"][0]
        manifest = Path(first["cache_manifest"])
        data = json.loads(manifest.read_text())
        artifact = manifest.parent / data["artifact"]["relative_path"]
        artifact.unlink()
        artifact.symlink_to(self.source)
        second = self.receipt(cold)["segments"][1]
        other = Path(second["cache_manifest"])
        record = json.loads(other.read_text())
        record["artifact"]["relative_path"] = "../../source.mp4"
        other.write_text(json.dumps(record))
        warm = render_storyboard(self.board, self.config, self.work)
        self.assertEqual([r["action"] for r in self.receipt(warm)["segments"]], ["executed", "executed"])
        self.assertEqual(content_fingerprint(self.source), self.board.sources[0].fingerprint)

    def test_wrong_manifest_kind_and_conflicting_digest_are_rejected(self):
        cold = render_storyboard(self.board, self.config, self.work)
        for index, row in enumerate(self.receipt(cold)["segments"]):
            manifest = Path(row["cache_manifest"])
            record = json.loads(manifest.read_text())
            if index == 0:
                record["kind"] = "unknown-future-kind"
            else:
                record["nondeterministic_output_digest"] = "0" * 64
            manifest.write_text(json.dumps(record))
        warm = render_storyboard(self.board, self.config, self.work)
        self.assertEqual([r["action"] for r in self.receipt(warm)["segments"]], ["executed", "executed"])

    def test_rejected_contract_counts_both_decode_attempts(self):
        cold = render_storyboard(self.board, self.config, self.work)
        manifest = Path(self.receipt(cold)["segments"][0]["cache_manifest"])
        record = json.loads(manifest.read_text())
        record["media_contract"]["video_profile"] = "wrong"
        manifest.write_text(json.dumps(record))
        result = render_storyboard(self.board, self.config, self.work)
        self.assertEqual(self.receipt(result)["verification_decode_calls"], 3)
        self.assertEqual([r["action"] for r in self.receipt(result)["segments"]], ["executed", "reused"])

    def test_one_shot_change_only_executes_that_segment(self):
        cold = render_storyboard(self.board, self.config, self.work)
        self.board.segments[1].visuals[0].start = 2
        self.board.segments[1].visuals[0].end = 3
        changed = render_storyboard(self.board, self.config, self.work)
        rows = self.receipt(changed)["segments"]
        self.assertEqual([r["action"] for r in rows], ["reused", "executed"])
        self.assertEqual(rows[0]["sha256"], self.receipt(cold)["segments"][0]["sha256"])

    def test_corrupt_cache_is_rejected_and_rebuilt(self):
        cold = render_storyboard(self.board, self.config, self.work)
        row = self.receipt(cold)["segments"][0]
        manifest = Path(row["cache_manifest"])
        record = json.loads(manifest.read_text())
        artifact = manifest.parent / record["artifact"]["relative_path"]
        artifact.write_bytes(b"truncated")
        warm = render_storyboard(self.board, self.config, self.work)
        self.assertEqual([r["action"] for r in self.receipt(warm)["segments"]], ["executed", "reused"])
        self.assertEqual(Path(cold.output["final_video"]).stat().st_size > 0, True)

    def test_reorder_reuses_local_segments_and_repositions_edl(self):
        render_storyboard(self.board, self.config, self.work)
        self.board.segments.reverse()
        warm = render_storyboard(self.board, self.config, self.work)
        self.assertEqual([r["action"] for r in self.receipt(warm)["segments"]], ["reused", "reused"])
        edl = json.loads(Path(warm.output["edl"]).read_text())
        self.assertEqual(edl[0]["segment_id"], "s1")
        self.assertEqual(edl[0]["output_start"], 0)

    def test_verified_cache_survives_existing_generation_change(self):
        from douyin_film_recap import workspace as w
        w.atomic(self.work / "state.json", {"schema_version": 2, "project_name": "synthetic",
            "input_fingerprint": "same-source", "config_fingerprint": "old-config", "stages": {}})
        render_storyboard(self.board, self.config, self.work)
        w.atomic(self.work / "09_storyboard.json", self.board.model_dump(mode="json"))
        root, active, _ = w.prepare(self.work, {"input_paths": [str(self.source)],
            "input_fingerprint": "same-source", "config_fingerprint": "new-config"})
        self.assertNotEqual(active, root)
        warm = render_storyboard(self.board, self.config, active)
        self.assertEqual([r["action"] for r in self.receipt(warm)["segments"]], ["reused", "reused"])
        self.assertTrue(Path(self.receipt(warm)["segments"][0]["cache_manifest"]).is_relative_to(root / "render_cache"))
        self.assertTrue(Path(warm.output["final_video"]).is_relative_to(active))

    def test_notes_changes_cannot_inherit_review_path(self):
        cold = render_storyboard(self.board, self.config, self.work)
        changed = cold.model_copy(deep=True)
        changed.segments[0].notes = "new editorial evidence"
        warm = render_storyboard(changed, self.config, self.work)
        self.assertNotEqual(cold.output["review_file"], warm.output["review_file"])
        self.assertEqual([r["action"] for r in self.receipt(warm)["segments"]], ["reused", "reused"])

    def test_identical_voice_segments_singleflight_under_parallel_render(self):
        self.config.runtime.max_parallel_ffmpeg = 2
        for segment in self.board.segments:
            segment.mode, segment.audio_owner = "voiceover", "narration"
            segment.audio_file, segment.audio_duration_sec = str(self.voice), 1
            segment.visuals = [VisualReference(source_id="src", start=0, end=1)]
            segment.allow_reuse = True
        result = render_storyboard(self.board, self.config, self.work)
        self.assertEqual(sorted(r["action"] for r in self.receipt(result)["segments"]), ["executed", "reused"])
        self.assertEqual(self.receipt(result)["segments"][0]["sha256"], self.receipt(result)["segments"][1]["sha256"])

    def test_default_fractional_segments_use_measured_clock_without_nominal_rejection(self):
        from douyin_film_recap.qc import _checked_realized_timeline, post_render_qc
        from douyin_film_recap.render_contracts import rational
        template = self.board.segments[0]
        self.board.segments = []
        for i in range(3):
            segment = template.model_copy(deep=True)
            segment.segment_id = f"fractional-{i}"
            segment.visuals[0].start = i * 0.5
            segment.visuals[0].end = i * 0.5 + 0.35
            segment.planned_duration_sec = 0.35
            self.board.segments.append(segment)
        self.config.render.incremental_cache = False
        result = render_storyboard(self.board, self.config, self.work / "default")
        timeline = result.output["realized_timeline"]
        self.assertEqual(timeline[-1]["end_frame"], 33)
        self.assertEqual(float(rational(timeline[-1]["end"])), 1.1)
        self.assertAlmostEqual(result.output["nominal_quantization_delta_sec"], 0.05)
        edl = json.loads(Path(result.output["edl"]).read_text())
        self.assertAlmostEqual(edl[1]["output_start"], 11 / 30)
        self.assertEqual(_checked_realized_timeline(result, self.config), timeline)
        report = post_render_qc(storyboard=result, config=self.config)
        self.assertFalse(any(f.rule_id == "INVALID_REALIZED_TIMELINE" for f in report.findings))
        self.assertTrue(any(f.rule_id == "NOMINAL_FRAME_QUANTIZATION" and not f.blocking for f in report.findings))
        result.output["segment_clock_evidence"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "REALIZED_SEGMENT_MEDIA_CHANGED"):
            _checked_realized_timeline(result, self.config)
        self.config.render.incremental_cache = True
        with self.assertRaisesRegex(ValueError, "REALIZED_CUMULATIVE_DRIFT"):
            render_storyboard(self.board, self.config, self.work / "strict")

    def test_voice_and_original_segments_decode(self):
        segment = self.board.segments[1]
        segment.mode, segment.audio_owner = "voiceover", "narration"
        segment.text = "Synthetic narration"
        segment.audio_file, segment.audio_duration_sec = str(self.voice), 1
        cold = render_storyboard(self.board, self.config, self.work)
        warm = render_storyboard(self.board, self.config, self.work)
        self.assertEqual([r["action"] for r in self.receipt(warm)["segments"]], ["reused", "reused"])
        self.assertEqual(self.decode(cold.output["final_video"], "audio"), self.decode(warm.output["final_video"], "audio"))


class CachePathTests(unittest.TestCase):
    def test_symlink_parent_rejected_and_existing_output_preserved(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source"
            source.write_bytes(b"user media")
            link = root / "link"
            link.symlink_to(root, target_is_directory=True)
            with self.assertRaises(CachePathError):
                SegmentCache(link / "cache")
            with self.assertRaises(FileExistsError):
                copy_new(source, source)
            self.assertEqual(source.read_bytes(), b"user media")

    def test_copy_is_independent_and_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source, output = root / "source", root / "copy"
            source.write_bytes(b"input")
            copy_new(source, output)
            self.assertNotEqual(source.stat().st_ino, output.stat().st_ino)
            output.write_bytes(b"changed")
            self.assertEqual(source.read_bytes(), b"input")
            with self.assertRaises(ValueError):
                copy_new(source, root / "bad", {"sha256": "0" * 64, "size": 5})
            self.assertFalse((root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
