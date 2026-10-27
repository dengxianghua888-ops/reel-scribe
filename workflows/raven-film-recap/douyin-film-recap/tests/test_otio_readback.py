from copy import deepcopy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from douyin_film_recap import otio_exchange as x
from douyin_film_recap import otio_readback as r
from test_otio_exchange_contract import fixture


class SavedReadbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work, self.story, self.facts, self.profile = fixture(self.root)
        for source in self.story["sources"]:
            source["identity_schema"] = "sha256-full/2"
        for i, segment in enumerate(self.story["segments"]):
            segment["visuals"][0]["clip_instance_id"] = f"occurrence-{i}"
        self.save_story()
        (self.work / "00_source_manifest.json").write_bytes(x.canonical({
            "schema_version": 2, "sources": self.story["sources"]}))
        self.captions = [{"caption_id": "cap-1", "start": 1, "end": 3, "text": "跨切点字幕"}]
        self.package = self.root / "package"
        x.export_otio_package(self.work, self.package, profile=self.profile,
                              media_facts=self.facts, captions=self.captions)
        self.otio = json.loads((self.package / "timeline.otio").read_bytes())
        self.host = self.root / "host-saved.otio"

    def tearDown(self):
        self.temp.cleanup()

    def save_story(self):
        (self.work / "09_storyboard.json").write_bytes(x.canonical(self.story))

    def capture(self, *, captions=None, media_root=None):
        self.host.write_bytes(x.canonical(self.otio))
        cap = None
        if captions is not None:
            cap = self.root / "host-captions.json"
            cap.write_bytes(x.canonical({"captions": captions}))
        r.capture_saved_snapshot(self.host, self.root / "snapshot", export_package=self.package,
            media_root=media_root or self.package, caption_document=cap)

    def propose(self, **kwargs):
        return r.propose_saved_readback(self.package, self.work, self.root / "snapshot", **kwargs)

    def video(self, i=0):
        return next(t for t in self.otio["tracks"]["children"] if t["kind"] == "Video")["children"][i]

    def test_unchanged_has_no_changes_and_never_writes_authority_or_host(self):
        self.capture()
        before = {p: p.read_bytes() for p in (self.work / "09_storyboard.json", self.host,
                                             self.work / "state.json")}
        proposal = self.propose()
        self.assertEqual(proposal["status"], "NO_CHANGES")
        self.assertFalse(proposal["adoption_performed"])
        self.assertFalse(proposal["active_host_write"])
        self.assertEqual(proposal["changes"], [])
        for path, raw in before.items():
            self.assertEqual(path.read_bytes(), raw)

    def test_added_video_tail_gap_is_measured_and_blocked(self):
        track = next(t for t in self.otio["tracks"]["children"] if t["kind"] == "Video")
        track["children"].append({"OTIO_SCHEMA": "Gap.1", "name": "tail", "metadata": {},
            "source_range": x._range(0, 3, 30), "effects": [], "markers": [], "enabled": True})
        self.capture()
        proposal = self.propose()
        self.assertEqual(proposal["status"], "CONFLICT")
        self.assertFalse(proposal["proposed_changes"])
        delta = next(row for row in proposal["changes"] if row["field"] == "track_end")
        self.assertEqual(delta["base"], x.rational(6))
        self.assertEqual(delta["host"], x.rational(9))
        self.assertIn("HOST_TRAILING_GAP_REQUIRES_EXPLICIT_MAPPING",
                      {p["code"] for p in proposal["conflicts"]})

    def test_short_audio_tail_gap_is_detected_without_changing_timeline_max(self):
        track = next(t for t in self.otio["tracks"]["children"] if t["name"] == "narration")
        track["children"].append({"OTIO_SCHEMA": "Gap.1", "name": "tail", "metadata": {},
            "source_range": x._range(0, 1, 48000), "effects": [], "markers": [], "enabled": True})
        self.capture()
        paths = [self.work / "09_storyboard.json", self.work / "state.json", self.host,
                 self.root / "snapshot" / "saved.otio"]
        before = {path: path.read_bytes() for path in paths}
        proposal = self.propose()
        self.assertEqual(proposal["status"], "CONFLICT")
        delta = next(row for row in proposal["changes"] if row["field"] == "track_end")
        self.assertEqual(delta["base"], x.rational(4))
        self.assertEqual(delta["host"], x.rational(5))  # Video remains 6 seconds.
        self.assertFalse(proposal["proposed_changes"])
        self.assertEqual(before, {path: path.read_bytes() for path in paths})

    def test_changed_and_removed_tail_gap_do_not_erase_endpoint_evidence(self):
        # The export has no trailing gaps. An edited saved document can have one;
        # successive snapshots must report against the export, not the last read.
        track = next(t for t in self.otio["tracks"]["children"] if t["kind"] == "Video")
        track["children"].append({"OTIO_SCHEMA": "Gap.1", "name": "tail", "metadata": {},
            "source_range": x._range(0, 3, 30), "effects": [], "markers": [], "enabled": True})
        binding = json.loads((self.package / "export-binding.json").read_bytes())
        base = json.loads((self.package / "projection.json").read_bytes())
        for index, duration in enumerate((3, 1, 0)):
            if duration:
                track["children"][-1]["source_range"] = x._range(0, duration, 30)
            else:
                track["children"].pop()
            self.host.write_bytes(x.canonical(self.otio))
            snapshot = self.root / f"snapshot-{index}"
            r.capture_saved_snapshot(self.host, snapshot, export_package=self.package,
                                     media_root=self.package)
            parsed = r.parse_snapshot(snapshot, base, binding)
            tid = track["metadata"]["recap"]["track_id"]
            self.assertEqual(parsed["track_ends"][tid], x.rational(6 + duration))
            proposal = r.propose_saved_readback(self.package, self.work, snapshot)
            self.assertEqual(proposal["status"], "CONFLICT" if duration else "NO_CHANGES")
            self.assertFalse(proposal["proposed_changes"])

    def test_capture_rejects_traversal_before_mutating_frozen_package(self):
        self.host.write_bytes(x.canonical(self.otio))
        before = {p.relative_to(self.package): p.read_bytes() for p in self.package.rglob("*") if p.is_file()}
        (self.root / "other").mkdir()
        candidates = [self.root / "other" / ".." / "package" / "inside-snapshot",
                      self.root / "absent" / ".." / "package" / "inside-snapshot",
                      self.root / "other" / "..", self.package / ".." / "package" / "media" / "snapshot"]
        for destination in candidates:
            with self.subTest(destination=destination), self.assertRaisesRegex(x.ExchangeError, "PATH_TRAVERSAL"):
                r.capture_saved_snapshot(self.host, destination, export_package=self.package,
                                         media_root=self.package)
            x.verify_package(self.package)
        self.assertFalse((self.root / "absent").exists())
        self.assertEqual(before, {p.relative_to(self.package): p.read_bytes()
                                 for p in self.package.rglob("*") if p.is_file()})

    def test_capture_rejects_aliased_package_and_symlink_paths(self):
        self.host.write_bytes(x.canonical(self.otio))
        (self.root / "other").mkdir()
        with self.assertRaisesRegex(x.ExchangeError, "PATH_TRAVERSAL"):
            r.capture_saved_snapshot(self.host, self.package / "inside",
                export_package=self.root / "other" / ".." / "package", media_root=self.package)
        alias = self.root / "alias"
        alias.symlink_to(self.package, target_is_directory=True)
        with self.assertRaisesRegex(x.ExchangeError, "SYMLINK_REJECTED"):
            r.capture_saved_snapshot(self.host, alias / "inside", export_package=self.package,
                                     media_root=self.package)
        with self.assertRaisesRegex(x.ExchangeError, "CANNOT_MODIFY_EXPORT_PACKAGE"):
            r.capture_saved_snapshot(self.host, self.package / "media" / "inside",
                                     export_package=self.package, media_root=self.package)
        x.verify_package(self.package)
        self.assertFalse((self.package / "inside").exists())

    def test_confirmed_occurrence_trim_generates_preconditioned_proposal(self):
        self.video()["source_range"]["start_time"]["value"] += 1
        self.capture()
        proposal = self.propose()
        self.assertEqual(proposal["status"], "READY_FOR_REVIEW")
        changes = proposal["proposed_changes"]
        self.assertEqual(len(changes), 1)
        self.assertEqual(changes[0]["entity_id"], "occurrence-0")
        self.assertEqual(changes[0]["field"], "source_start")
        self.assertEqual(changes[0]["current_value_sha256"], x.digest({"numerator": 1, "denominator": 1}))
        self.assertTrue(proposal["current_revision_base"])

    def test_repeated_source_lost_id_is_blocked_without_guessing(self):
        del self.video(2)["metadata"]["recap"]["instance_id"]
        self.capture()
        proposal = self.propose()
        self.assertEqual(proposal["status"], "CONFLICT")
        self.assertFalse(proposal["proposed_changes"])
        self.assertIn("INSTANCE_ID_MISSING_UNKNOWN_OR_DUPLICATE", {p["code"] for p in proposal["conflicts"]})

    def test_same_field_concurrent_edit_conflict(self):
        self.video()["source_range"]["start_time"]["value"] += 2
        self.capture()
        visual = self.story["segments"][0]["visuals"][0]
        visual["start"], visual["end"] = 2, 4
        self.save_story()
        proposal = self.propose()
        self.assertEqual(proposal["status"], "CONFLICT")
        self.assertIn("SAME_FIELD_CHANGED_BOTH", {p["code"] for p in proposal["conflicts"]})

    def test_different_timing_fields_still_check_dependencies(self):
        self.video()["source_range"]["duration"]["value"] -= 30
        self.capture()
        visual = self.story["segments"][0]["visuals"][0]
        visual["start"], visual["end"] = 2, 4
        self.save_story()
        proposal = self.propose()
        self.assertIn("CROSS_FIELD_TIMING_DEPENDENCY", {p["code"] for p in proposal["conflicts"]})
        self.assertFalse(any(p["entity_id"] == "occurrence-0" for p in proposal["proposed_changes"]))

    def test_current_notes_preserved_without_false_conflict(self):
        self.video()["source_range"]["start_time"]["value"] += 1
        self.capture()
        self.story["segments"][0]["notes"] = "manual notes remain"
        self.save_story()
        proposal = self.propose()
        self.assertEqual(proposal["status"], "READY_FOR_REVIEW")
        self.assertEqual(json.loads((self.work / "09_storyboard.json").read_bytes())["segments"][0]["notes"],
                         "manual notes remain")

    def test_semantic_and_protection_changes_block_trim(self):
        self.video()["source_range"]["start_time"]["value"] += 1
        self.capture()
        self.story["segments"][0].update(text="different narration meaning", protected=True)
        self.save_story()
        proposal = self.propose()
        codes = {p["code"] for p in proposal["conflicts"]}
        self.assertIn("CURRENT_SEMANTIC_ANCHOR_CHANGED", codes)
        self.assertIn("PROTECTED_STORYBOARD_ENTITY", codes)

    def test_unknown_host_effects_survive_and_block_temporal_adoption(self):
        effect = {"OTIO_SCHEMA": "VendorPrivateEffect.9", "keyframes": [{"at": 5, "value": 1}]}
        self.video()["effects"].append(effect)
        self.video()["source_range"]["start_time"]["value"] += 1
        self.capture()
        raw = (self.root / "snapshot/saved.otio").read_bytes()
        proposal = self.propose()
        self.assertEqual(proposal["opaque"]["occurrence-0"]["clip"]["effects"], [effect])
        self.assertIn("UNKNOWN_TEMPORAL_DEPENDENCY", {p["code"] for p in proposal["conflicts"]})
        self.assertEqual((self.root / "snapshot/saved.otio").read_bytes(), raw)

    def test_same_sha_relative_relocation_is_allowed_but_replacement_is_not(self):
        new_media = self.root / "moved-media"
        new_media.mkdir()
        for ref in r._references(self.otio):
            original = self.package / ref["target_url"]
            dest = new_media / original.name
            dest.write_bytes(original.read_bytes())
            ref["target_url"] = original.name
        self.capture(media_root=new_media)
        self.assertEqual(self.propose()["status"], "NO_CHANGES")

    def test_source_identity_bytes_replacement_is_blocked(self):
        new_media = self.root / "moved-media"
        new_media.mkdir()
        for ref in r._references(self.otio):
            original = self.package / ref["target_url"]
            dest = new_media / original.name
            dest.write_bytes(b"different source bytes")
            ref["target_url"] = original.name
        self.capture(media_root=new_media)
        proposal = self.propose()
        self.assertEqual(proposal["status"], "CONFLICT")
        self.assertIn("SOURCE_ID_BYTES_DRIFTED", {p["code"] for p in proposal["conflicts"]})

    def test_missing_and_old_absolute_media_refs_are_not_relinked(self):
        before = {path: path.read_bytes() for path in (
            self.work / "09_storyboard.json", self.work / "state.json")}
        for scenario in ("missing", "old-absolute"):
            with self.subTest(scenario=scenario):
                document = deepcopy(self.otio)
                for reference in r._references(document):
                    original = self.package / reference["target_url"]
                    self.assertTrue(original.is_file())
                    reference["target_url"] = (str(original) if scenario == "old-absolute"
                        else "missing/" + original.name)
                raw = x.canonical(document)
                self.host.write_bytes(raw)
                snapshot = self.root / scenario
                r.capture_saved_snapshot(self.host, snapshot, export_package=self.package,
                                         media_root=self.package)
                manifest = r.verify_saved_snapshot(snapshot)
                self.assertEqual(manifest["resources"], {})
                self.assertTrue(manifest["findings"])
                self.assertEqual((snapshot / "saved.otio").read_bytes(), raw)
                proposal = r.propose_saved_readback(self.package, self.work, snapshot)
                self.assertEqual(proposal["status"], "CONFLICT")
                self.assertIn("UNRESOLVED_OR_UNSAFE_MEDIA_REFERENCE",
                              {p["code"] for p in proposal["conflicts"]})
                self.assertFalse(proposal["proposed_changes"])
                self.assertFalse(proposal["adoption_performed"])
                self.assertFalse(proposal["active_host_write"])
                self.assertFalse(proposal["host_cas"])
                self.assertEqual(self.host.read_bytes(), raw)
                self.assertEqual(before, {path: path.read_bytes() for path in before})
                x.verify_package(self.package)

    def test_symlinked_media_directory_cannot_supply_snapshot_resources(self):
        media_root = self.root / "media-root"
        media_root.mkdir()
        (media_root / "linked").symlink_to(self.package / "media", target_is_directory=True)
        for reference in r._references(self.otio):
            reference["target_url"] = "linked/" + Path(reference["target_url"]).name
        raw = x.canonical(self.otio)
        self.capture(media_root=media_root)
        snapshot = self.root / "snapshot"
        manifest = r.verify_saved_snapshot(snapshot)
        self.assertEqual(manifest["resources"], {})
        self.assertTrue(manifest["findings"])
        self.assertTrue(all(row["detail"]["reason"] == "SYMLINK_REJECTED"
                            for row in manifest["findings"]))
        self.assertFalse((snapshot / "resources").exists())
        self.assertEqual((snapshot / "saved.otio").read_bytes(), raw)
        proposal = self.propose()
        self.assertEqual(proposal["status"], "CONFLICT")
        self.assertFalse(proposal["proposed_changes"])
        self.assertFalse(proposal["adoption_performed"])
        x.verify_package(self.package)

    def test_saved_origin_diverges_after_capture(self):
        self.capture()
        self.host.write_bytes(self.host.read_bytes() + b"\n")
        proposal = self.propose()
        self.assertEqual(proposal["status"], "DIVERGED")
        self.assertEqual(proposal["live_origin"]["state"], "DIVERGED")
        self.assertFalse(proposal["proposed_changes"])
        r.verify_saved_snapshot(self.root / "snapshot")

    def test_caption_changes_need_stable_ids_and_current_binding(self):
        changed = deepcopy(self.captions)
        changed[0]["text"] = "改过的字幕"
        self.capture(captions=changed)
        proposal = self.propose()
        self.assertEqual(proposal["status"], "READY_FOR_REVIEW")
        self.assertEqual(proposal["proposed_changes"][0]["field"], "text")
        self.story["segments"][0]["notes"] = "changed"
        self.save_story()
        proposal = self.propose()
        self.assertIn("CURRENT_CAPTION_BINDING_REQUIRED", {p["code"] for p in proposal["conflicts"]})

    def test_clip2_schema_upgrade_and_unknown_recap_preservation(self):
        for track in self.otio["tracks"]["children"]:
            for clip in track["children"]:
                if clip["OTIO_SCHEMA"] == "Clip.1":
                    clip["OTIO_SCHEMA"] = "Clip.2"
                    clip["media_references"] = {"DEFAULT_MEDIA": clip.pop("media_reference")}
                    clip["active_media_reference_key"] = "DEFAULT_MEDIA"
        self.video()["metadata"]["recap"]["unknown_future_field"] = {"timing": 3}
        self.capture()
        proposal = self.propose()
        self.assertEqual(proposal["status"], "NEEDS_REVIEW")
        self.assertIn("metadata", proposal["opaque"]["occurrence-0"]["clip"])

    def test_snapshot_tampering_and_proposal_no_overwrite(self):
        self.capture()
        proposal = self.propose()
        target = self.root / "proposal.json"
        r.write_readback_proposal(proposal, target)
        with self.assertRaisesRegex(x.ExchangeError, "TARGET_EXISTS"):
            r.write_readback_proposal(proposal, target)
        (self.root / "snapshot/saved.otio").write_bytes(b"{}")
        with self.assertRaisesRegex(x.ExchangeError, "HASH_MISMATCH"):
            self.propose()

    def test_caption_protection_and_unknown_timing_dependencies(self):
        base = {"tracks": [], "captions": [{"caption_id": "cap", "start": 0, "end": 1,
            "text": "original", "protected": True}], "opaque": {}}
        host = {"entities": {}, "problems": [], "opaque": {}, "captions": {
            "cap": {"caption_id": "cap", "start": 0, "end": 2, "text": "changed", "protected": True}}}
        board = {"segments": [], "protected": True}
        result = r.three_way_compare(base, deepcopy(base), host,
            base_storyboard=board, current_storyboard=board)
        self.assertFalse(result["proposed_changes"])
        codes = {p["code"] for p in result["conflicts"]}
        self.assertIn("PROTECTED_CAPTION_OR_DOCUMENT", codes)
        self.assertIn("UNKNOWN_CAPTION_TEMPORAL_DEPENDENCY", codes)

    def test_snapshot_cannot_mutate_frozen_base_package(self):
        self.host.write_bytes(x.canonical(self.otio))
        with self.assertRaisesRegex(x.ExchangeError, "CANNOT_MODIFY_EXPORT"):
            r.capture_saved_snapshot(self.host, self.package / "snapshot", export_package=self.package)
        x.verify_package(self.package)

    def test_standalone_readback_cli_produces_new_report(self):
        self.host.write_bytes(x.canonical(self.otio))
        output = io.StringIO()
        with redirect_stdout(output):
            status = r.main(["capture", "--export-package", str(self.package),
                "--saved-otio", str(self.host), "--media-root", str(self.package),
                "--snapshot-dir", str(self.root / "snapshot")])
        self.assertEqual(status, 0)
        with redirect_stdout(io.StringIO()):
            status = r.main(["propose", "--export-package", str(self.package),
                "--work-dir", str(self.work), "--snapshot-dir", str(self.root / "snapshot"),
                "--output", str(self.root / "report.json")])
        self.assertEqual(status, 0)
        self.assertEqual(json.loads((self.root / "report.json").read_bytes())["status"], "NO_CHANGES")

    def test_malformed_host_metadata_is_opaque_conflict(self):
        self.video()["metadata"] = ["malformed"]
        self.capture()
        proposal = self.propose()
        self.assertEqual(proposal["status"], "CONFLICT")
        self.assertFalse(proposal["proposed_changes"])
        self.assertIn("HOST_STRUCTURE_UNSUPPORTED", {p["code"] for p in proposal["conflicts"]})

    def test_unknown_source_extension_blocks_affected_timing_proposal(self):
        self.video()["source_range"]["start_time"]["value"] += 1
        self.capture()
        self.story["sources"][0]["vendor_unknown"] = {"keyframe_time": 7}
        self.save_story()
        proposal = self.propose()
        self.assertIn("UNKNOWN_TEMPORAL_DEPENDENCY", {p["code"] for p in proposal["conflicts"]})
        self.assertFalse(any(p["entity_id"] == "occurrence-0" for p in proposal["proposed_changes"]))

    def test_changed_narration_bytes_not_hidden_by_unchanged_path(self):
        self.video(1)["source_range"]["start_time"]["value"] += 1
        self.capture()
        Path(self.story["segments"][1]["audio_file"]).write_bytes(b"new narration bytes at same path")
        proposal = self.propose()
        self.assertIn("CURRENT_SOURCE_BINDING_CHANGED", {p["code"] for p in proposal["conflicts"]})
        self.assertFalse(proposal["proposed_changes"])


if __name__ == "__main__":
    unittest.main()
