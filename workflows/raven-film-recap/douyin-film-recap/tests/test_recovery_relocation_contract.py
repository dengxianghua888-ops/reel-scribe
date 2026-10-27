"""Byte-only cross-interface recovery: names do not replace member identity."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from douyin_film_recap import workspace as w

REPO = Path(__file__).resolve().parents[4]


class RecoveryRelocationContractTests(unittest.TestCase):
    def test_same_named_external_results_recover_as_distinct_hash_bound_members(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)

            def invoke(*arguments):
                result = subprocess.run([sys.executable, *map(str, arguments)],
                    capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                return json.loads(result.stdout)

            bundle = base / "recovery-B"
            built = invoke(REPO / "scripts/build_film_recovery_bundle.py", "--out", bundle)
            self.assertEqual(built["status"], "BUILT_BYTES_VERIFIED")
            source = base / "source.mp4"
            source.write_bytes(b"synthetic source identity only; not playable media")
            external = []
            for name, content in (("first", b"first result"), ("second", b"different result")):
                parent = base / name
                parent.mkdir()
                path = parent / "same-name.dat"
                path.write_bytes(content)
                external.append(path)
            originals = {path: path.read_bytes() for path in (source, *external)}
            old = base / "legacy"
            old.mkdir()
            w.atomic(old / "09_storyboard.json", {"hand_authored": "retain this snapshot",
                "sources": [{"path": str(source), "fingerprint": w.sha(source)}]})
            w.atomic(old / "state.json", {"schema_version": 1, "stages": {
                "ingest": {"status": "passed", "artifacts": {str(source): w.sha(source)}},
                "render": {"status": "passed", "artifacts": {
                    str(path): w.sha(path) for path in external}}}})
            hand = (old / "09_storyboard.json").read_bytes()
            _, active, manifest = w.prepare(old, {"input_paths": [str(source)],
                "input_fingerprint": w.sha(source), "config_fingerprint": "offline-contract"},
                allow_legacy=True, recovery_bundle=bundle,
                recovery_bundle_sha256=built["package_sha256"])
            rows = [row for row in manifest["files"] if Path(row["path"]).name == "same-name.dat"]
            self.assertEqual(len(rows), 2)
            self.assertEqual(len({row["path"] for row in rows}), 2)
            self.assertEqual(len({row["sha256"] for row in rows}), 2)
            self.assertEqual({row["original_path"] for row in rows}, {str(path) for path in external})
            self.assertIn(str(source), manifest["external_references_not_copied"])
            self.assertFalse(any(row["original_path"] == str(source) for row in manifest["files"]))
            stages = w.read(active / "state.json")["stages"]
            self.assertEqual(set(stages), {"ingest", "render"})
            self.assertTrue(all(row["status"] == "pending" for row in stages.values()))
            archive = Path(w.read(active / "state.json")["recovery_manifest"]).parent
            restored = base / "restored"
            recovered = invoke(bundle / "recover.py", "recover", "--archive", archive, "--out", restored)
            self.assertEqual(recovered["status"], "RECOVERED_BYTES_ONLY")
            self.assertFalse(recovered["production_authorized"])
            self.assertEqual({path.relative_to(restored).as_posix()
                              for path in restored.rglob("*") if path.is_file()},
                             {row["path"] for row in manifest["files"]})
            for row in manifest["files"]:
                self.assertEqual(w.sha(restored / row["path"]), row["sha256"])
            self.assertEqual({path: path.read_bytes() for path in originals}, originals)
            self.assertEqual((old / "09_storyboard.json").read_bytes(), hand)
            self.assertEqual((restored / "09_storyboard.json").read_bytes(), hand)
            self.assertEqual(w.read(restored / "09_storyboard.json")["sources"][0]["path"], str(source))
            with self.assertRaisesRegex(w.WorkspaceError, "LEGACY_MIGRATION_REQUIRED"):
                w.preflight(restored)


if __name__ == "__main__":
    unittest.main()
