"""Local contracts only: fake transports and inert recovery bytes, no providers."""
import asyncio
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from douyin_film_recap import send_guard as guard
from douyin_film_recap import workspace


class SendAuthorizationRecheckTests(unittest.TestCase):
    def _grant(self, root):
        grant = {"schema": "film-remote-authorization/1", "id": "local-test", "max_requests": 3}
        workspace.atomic(root / ".remote-authorization.json", grant)
        return grant

    def _mutate(self, root, grant, mutation):
        path = root / ".remote-authorization.json"
        if mutation == "missing":
            path.unlink()
        elif mutation == "malformed":
            path.write_text("{not valid json", encoding="utf-8")
        else:
            workspace.atomic(path, {**grant, "id": "revoked"})

    def test_async_preparation_revocation_never_reserves_or_sends(self):
        for mutation in ("changed", "missing", "malformed"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                grant = self._grant(root)
                calls = []

                async def send():
                    calls.append("transport")
                    return {"synthetic": True}

                with guard.send_session(root, {}, authorized=True, grant=grant) as session:
                    with self.assertRaisesRegex(guard.SendBlocked, "AUTHORIZATION_REVOKED_OR_CHANGED"):
                        asyncio.run(session.perform_async("edge_tts", {}, send,
                            prepare=lambda: self._mutate(root, grant, mutation)))
                    self.assertEqual(session.sent, 0)
                self.assertEqual(calls, [])
                self.assertEqual(list((root / ".remote-intents").glob("*.json")), [])

    def test_actual_tts_preparation_revocation_never_enters_stream(self):
        from douyin_film_recap.tts import _edge_tts_stream

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grant = self._grant(root)
            calls = []

            class Communicate:
                def __init__(self, **kwargs):
                    calls.append("local-prepare")
                    workspace.atomic(root / ".remote-authorization.json", {**grant, "id": "revoked"})

                async def stream(self):
                    calls.append("transport")
                    yield {"type": "audio", "data": b"inert fake bytes"}

            with patch.dict(sys.modules, {"edge_tts": SimpleNamespace(Communicate=Communicate)}):
                with guard.send_session(root, {}, authorized=True, grant=grant) as session:
                    with self.assertRaisesRegex(guard.SendBlocked, "AUTHORIZATION_REVOKED_OR_CHANGED"):
                        asyncio.run(_edge_tts_stream(text="synthetic", output_path=root / "out.mp3",
                            voice="zh-CN-XiaoxiaoNeural", rate="+0%", pitch="+0Hz", volume="+0%"))
                    self.assertEqual(session.sent, 0)
            self.assertEqual(calls, ["local-prepare"])
            self.assertFalse((root / "out.mp3").exists())

    def test_revocation_after_reservation_is_known_unsent_for_both_paths(self):
        for asynchronous in (False, True):
            for mutation in ("changed", "missing", "malformed"):
                with self.subTest(asynchronous=asynchronous, mutation=mutation):
                    with tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        grant = self._grant(root)
                        calls = []
                        with guard.send_session(root, {}, authorized=True, grant=grant) as session:
                            original = session._reserve

                            def reserve(*args, **kwargs):
                                result = original(*args, **kwargs)
                                self._mutate(root, grant, mutation)
                                return result

                            with patch.object(session, "_reserve", side_effect=reserve):
                                with self.assertRaisesRegex(guard.SendBlocked, "AUTHORIZATION_REVOKED_OR_CHANGED"):
                                    if asynchronous:
                                        asyncio.run(session.perform_async("chat", {},
                                            lambda: calls.append("transport"), "reserved"))
                                    else:
                                        session.perform("chat", {}, lambda: calls.append("transport"), "reserved")
                            self.assertEqual(session.sent, 1)
                        self.assertEqual(calls, [])
                        records = [workspace.read(p) for p in (root / ".remote-intents").glob("*.json")]
                        self.assertEqual(len(records), 1)
                        self.assertEqual(records[0]["status"], "NOT_SUBMITTED_CONFIRMED")
                        self.assertEqual(records[0]["cancellation"]["reason"], "authorization_revoked_before_transport")
                        self.assertEqual(len(records[0]["send_attempts"]), 1)

    def test_revoked_grant_blocks_before_local_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grant = self._grant(root)
            self._mutate(root, grant, "changed")
            calls = []
            with guard.send_session(root, {}, authorized=True, grant=grant) as session:
                with self.assertRaisesRegex(guard.SendBlocked, "AUTHORIZATION_REVOKED_OR_CHANGED"):
                    asyncio.run(session.perform_async("chat", {}, lambda: calls.append("send"),
                        prepare=lambda: calls.append("prepare")))
                self.assertEqual(session.sent, 0)
            self.assertEqual(calls, [])

    def test_successful_replay_needs_no_live_grant_or_prepare(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grant = self._grant(root)
            with guard.send_session(root, {}, authorized=True, grant=grant) as session:
                self.assertEqual(session.perform("chat", {}, lambda: {"reply": "local"}), {"reply": "local"})
            records = {p: p.read_bytes() for p in (root / ".remote-intents").glob("*.json")}
            self._mutate(root, grant, "changed")
            with guard.send_session(root, {}, authorized=False, grant=grant) as session:
                value = asyncio.run(session.perform_async("chat", {}, lambda: self.fail("transport"),
                    prepare=lambda: self.fail("prepare")))
                self.assertEqual(value, {"reply": "local"})
                self.assertEqual(session.sent, 0)
            self.assertEqual({p: p.read_bytes() for p in records}, records)

    def test_unknown_transport_remains_unknown_and_cannot_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            grant = self._grant(root)
            calls = []

            def unknown():
                calls.append("transport")
                raise TimeoutError("synthetic acceptance unknown")

            with guard.send_session(root, {}, authorized=True, grant=grant) as session:
                with self.assertRaises(TimeoutError):
                    session.perform("chat", {}, unknown)
            records = {p: p.read_bytes() for p in (root / ".remote-intents").glob("*.json")}
            self._mutate(root, grant, "changed")
            with guard.send_session(root, {}, authorized=True, grant=grant) as session:
                with self.assertRaisesRegex(guard.SendBlocked, "SEND_OUTCOME_UNKNOWN"):
                    session.perform("chat", {}, unknown)
                self.assertEqual(session.sent, 0)
            self.assertEqual(calls, ["transport"])
            self.assertEqual({p: p.read_bytes() for p in records}, records)


class RecoveryManifestRecheckTests(unittest.TestCase):
    def _archive(self, root):
        archive = root / "archive"
        data = archive / "files" / "data.bin"
        data.parent.mkdir(parents=True)
        data.write_bytes(b"inert original recovery bytes")
        manifest = {"schema": workspace.RECOVERY_SCHEMA, "source_identity": {"input_fingerprint": "original"},
            "files": [{"path": "data.bin", "bytes": data.stat().st_size, "sha256": workspace.sha(data)}]}
        workspace.atomic(archive / "recovery-manifest.json", manifest)
        return archive, manifest

    def test_nominal_recovery_returns_exact_frozen_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self._archive(root)
            expected = workspace.sha(archive / "recovery-manifest.json")
            result = workspace.recover(archive, root / "restored")
            self.assertEqual(result["manifest_sha256"], expected)
            self.assertEqual(result["status"], "RECOVERED_BYTES_ONLY")
            self.assertFalse(result["production_authorized"])
            self.assertEqual((root / "restored/data.bin").read_bytes(), (archive / "files/data.bin").read_bytes())
            self.assertEqual(workspace.verify_archive(archive), manifest)

    def test_manifest_identity_drift_after_copy_rejects_and_preserves_partial_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self._archive(root)
            copied = workspace.checked_copy

            def copy_then_change(*args):
                copied(*args)
                workspace.atomic(archive / "recovery-manifest.json", {**manifest,
                    "source_identity": {"input_fingerprint": "changed while copying"}})

            with patch.object(workspace, "checked_copy", side_effect=copy_then_change):
                with self.assertRaisesRegex(workspace.WorkspaceError, "RECOVERY_MANIFEST_DRIFTED"):
                    workspace.recover(archive, root / "restored")
            self.assertTrue((root / "restored/data.bin").exists())
            self.assertEqual((root / "restored/data.bin").read_bytes(), (archive / "files/data.bin").read_bytes())
            self.assertEqual(workspace.read(archive / "recovery-manifest.json")["source_identity"],
                {"input_fingerprint": "changed while copying"})

    def test_valid_replacement_archive_cannot_certify_old_restored_members(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self._archive(root)
            original = (archive / "files/data.bin").read_bytes()
            copied = workspace.checked_copy

            def copy_then_replace(*args):
                copied(*args)
                old = archive / "files/data.bin"
                new = archive / "files/replacement.bin"
                old.rename(new)
                new.write_bytes(b"different inert recovery bytes")
                workspace.atomic(archive / "recovery-manifest.json", {**manifest, "files": [
                    {"path": "replacement.bin", "bytes": new.stat().st_size, "sha256": workspace.sha(new)}]})

            with patch.object(workspace, "checked_copy", side_effect=copy_then_replace):
                with self.assertRaisesRegex(workspace.WorkspaceError, "RECOVERY_MANIFEST_DRIFTED"):
                    workspace.recover(archive, root / "restored")
            self.assertEqual((root / "restored/data.bin").read_bytes(), original)
            self.assertFalse((root / "restored/replacement.bin").exists())
            self.assertEqual(workspace.verify_archive(archive)["files"][0]["path"], "replacement.bin")

    def test_verify_checks_manifest_again_after_member_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self._archive(root)
            original = workspace.sha

            def hash_then_change(path):
                value = original(path)
                if Path(path).name == "data.bin":
                    workspace.atomic(archive / "recovery-manifest.json", {**manifest, "note": "changed"})
                return value

            with patch.object(workspace, "sha", side_effect=hash_then_change):
                with self.assertRaisesRegex(workspace.WorkspaceError, "RECOVERY_MANIFEST_DRIFTED"):
                    workspace.verify_archive(archive)

    def test_manifest_drift_while_validating_restored_bytes_also_rejects(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self._archive(root)
            original = workspace.sha
            destination = root / "restored"

            def hash_then_change(path):
                value = original(path)
                if Path(path).is_relative_to(destination):
                    workspace.atomic(archive / "recovery-manifest.json", {**manifest, "note": "last read drift"})
                return value

            with patch.object(workspace, "sha", side_effect=hash_then_change):
                with self.assertRaisesRegex(workspace.WorkspaceError, "RECOVERY_MANIFEST_DRIFTED"):
                    workspace.recover(archive, destination)
            self.assertTrue((destination / "data.bin").exists())

    def test_supplied_manifest_pin_is_enforced_before_copies(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, manifest = self._archive(root)
            pin = workspace.sha(archive / "recovery-manifest.json")
            workspace.atomic(archive / "recovery-manifest.json", {**manifest, "note": "new"})
            with self.assertRaisesRegex(workspace.WorkspaceError, "RECOVERY_MANIFEST_DRIFTED"):
                workspace.verify_archive(archive, expected_manifest_sha256=pin)


if __name__ == "__main__":
    unittest.main()
