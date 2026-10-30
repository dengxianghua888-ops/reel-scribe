"""Byte-only readback race fixtures; no NLE, media interpretation or adoption."""
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from douyin_film_recap import otio_exchange as x
from douyin_film_recap import otio_readback as r
import test_otio_readback as readback_tests


class ReadbackSnapshotIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = readback_tests.SavedReadbackTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.capture(captions=self.fixture.captions)
        self.snapshot = self.fixture.root / "snapshot"
        self.before = {p: p.read_bytes() for p in (self.fixture.work / "09_storyboard.json",
            self.fixture.work / "state.json", self.fixture.host)}

    def unchanged_authority(self):
        self.assertEqual(self.before, {p: p.read_bytes() for p in self.before})

    def replace_saved_branch(self):
        path = self.snapshot / "saved.otio"
        document = json.loads(path.read_bytes())
        clip = next(t for t in document["tracks"]["children"] if t["kind"] == "Video")["children"][0]
        clip["source_range"]["start_time"]["value"] += 30
        path.write_bytes(x.canonical(document))
        manifest_path = self.snapshot / "snapshot-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        manifest["saved_file_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        manifest_path.write_bytes(x.canonical(manifest))
        seal_path = self.snapshot / "checksums.json"
        seal = json.loads(seal_path.read_bytes())
        for name in ("saved.otio", "snapshot-manifest.json"):
            data = (self.snapshot / name).read_bytes()
            seal["files"][name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}
        seal_path.write_bytes(x.canonical(seal))
        r.verify_saved_snapshot(self.snapshot)  # Replacement itself is a coherent archive.

    def test_self_consistent_snapshot_replacement_cannot_report_previous_identity(self):
        original_parse = r.parse_snapshot

        def replace_then_parse(*args, **kwargs):
            self.replace_saved_branch()
            return original_parse(*args, **kwargs)

        with patch.object(r, "parse_snapshot", side_effect=replace_then_parse):
            with self.assertRaises(x.ExchangeError):
                self.fixture.propose()
        self.unchanged_authority()
        self.assertTrue((self.snapshot / "saved.otio").exists())

    def test_saved_document_hash_check_and_consumption_cannot_split(self):
        target = self.snapshot / "saved.otio"
        read_stable = x.read_stable
        changed = []

        def change_before_read(path):
            if Path(path) == target and not changed:
                changed.append(True)
                document = json.loads(target.read_bytes())
                document["name"] = "Changed after archive verification"
                target.write_bytes(x.canonical(document))
            return read_stable(path)

        with patch.object(x, "read_stable", side_effect=change_before_read):
            with self.assertRaises(x.ExchangeError):
                self.fixture.propose()
        self.assertTrue(changed)
        self.unchanged_authority()

    def test_caption_document_hash_check_and_consumption_cannot_split(self):
        target = self.snapshot / "captions.saved.json"
        read_stable = x.read_stable
        changed = []

        def change_before_read(path):
            if Path(path) == target and not changed:
                changed.append(True)
                target.write_bytes(x.canonical({"captions": [dict(self.fixture.captions[0],
                    text="Unsealed caption text")]}))
            return read_stable(path)

        with patch.object(x, "read_stable", side_effect=change_before_read):
            with self.assertRaises(x.ExchangeError):
                self.fixture.propose()
        self.assertTrue(changed)
        self.unchanged_authority()

    def test_export_storyboard_hash_check_and_consumption_cannot_split(self):
        target = self.fixture.package / "storyboard.snapshot.json"
        read_stable = x.read_stable
        changed = []

        def change_before_read(path):
            if Path(path) == target and not changed:
                changed.append(True)
                document = json.loads(target.read_bytes())
                document["project_name"] = "Unsealed original Storyboard"
                target.write_bytes(x.canonical(document))
            return read_stable(path)

        with patch.object(x, "read_stable", side_effect=change_before_read):
            with self.assertRaises(x.ExchangeError):
                self.fixture.propose()
        self.assertTrue(changed)
        self.unchanged_authority()

    def test_snapshot_change_after_comparison_cannot_return_verified_claim(self):
        observe = r.observe_saved_origin

        def change_at_last_observation(manifest):
            result = observe(manifest)
            (self.snapshot / "saved.otio").write_bytes(b'{"changed":"after comparison"}')
            return result

        with patch.object(r, "observe_saved_origin", side_effect=change_at_last_observation):
            with self.assertRaises(x.ExchangeError):
                self.fixture.propose()
        self.unchanged_authority()

    def test_manifest_hash_check_and_parse_cannot_split(self):
        target = self.snapshot / "snapshot-manifest.json"
        sha = r.workspace.sha
        changed = []

        def change_after_hash(path):
            result = sha(path)
            if Path(path) == target and not changed:
                changed.append(True)
                manifest = json.loads(target.read_bytes())
                manifest["saved_file_sha256"] = "0" * 64
                target.write_bytes(x.canonical(manifest) + b"\n")
            return result

        with patch.object(r.workspace, "sha", side_effect=change_after_hash):
            with self.assertRaises(x.ExchangeError):
                r.verify_saved_snapshot(self.snapshot)
        self.assertTrue(changed)
        self.unchanged_authority()

    def reseal_files(self):
        path = self.snapshot / "checksums.json"
        seal = json.loads(path.read_bytes())
        seal["files"] = {p.relative_to(self.snapshot).as_posix(): {
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
            for p in self.snapshot.rglob("*") if p.is_file() and p != path}
        path.write_bytes(x.canonical(seal))

    def test_resource_manifest_identity_must_match_sealed_media_bytes(self):
        manifest = json.loads((self.snapshot / "snapshot-manifest.json").read_bytes())
        resource = next(iter(manifest["resources"].values()))
        (self.snapshot / resource["snapshot_path"]).write_bytes(b"Changed inert media bytes")
        self.reseal_files()
        with self.assertRaises(x.ExchangeError):
            self.fixture.propose()
        self.unchanged_authority()

    def test_caption_and_opaque_companion_identities_must_match_sealed_bytes(self):
        for companion in (False, True):
            with self.subTest(companion=companion):
                # Restore a coherent fixture for each independent negative case.
                if companion:
                    target = self.snapshot / "companions" / "opaque.txt"
                    target.parent.mkdir()
                    target.write_bytes(b"Original opaque evidence")
                    manifest_path = self.snapshot / "snapshot-manifest.json"
                    manifest = json.loads(manifest_path.read_bytes())
                    manifest["companions"]["opaque"] = {"snapshot_path": "companions/opaque.txt",
                        "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
                    manifest_path.write_bytes(x.canonical(manifest))
                else:
                    target = self.snapshot / "captions.saved.json"
                original = target.read_bytes()
                self.reseal_files()
                r.verify_saved_snapshot(self.snapshot)
                target.write_bytes(b"Changed sealed bytes, unchanged manifest identity")
                self.reseal_files()
                with self.assertRaises(x.ExchangeError):
                    r.verify_saved_snapshot(self.snapshot)
                target.write_bytes(original)
                self.reseal_files()
                self.unchanged_authority()

    def test_unchanged_snapshot_remains_read_only_and_same_proposal_contract(self):
        archived = {p: p.read_bytes() for p in self.snapshot.rglob("*") if p.is_file()}
        proposal = self.fixture.propose()
        self.assertEqual(proposal["status"], "NO_CHANGES")
        self.assertEqual(proposal["claims"]["saved_snapshot_bytes"], "VERIFIED")
        self.assertEqual(proposal["saved_file_sha256"], hashlib.sha256(
            (self.snapshot / "saved.otio").read_bytes()).hexdigest())
        self.assertFalse(proposal["adoption_performed"])
        self.assertFalse(proposal["active_host_write"])
        self.assertEqual(archived, {p: p.read_bytes() for p in archived})
        self.unchanged_authority()
