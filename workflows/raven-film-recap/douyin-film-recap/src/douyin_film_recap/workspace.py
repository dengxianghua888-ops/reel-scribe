"""Versioned film workspaces and byte-preserving, read-only recovery.

Standard-library only so the recovery entry can run without model credentials.
Locks coordinate cooperating local writers; they do not isolate hostile processes.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

POINTER = ".film-workspace.json"
GENERATION = ".film-generation.json"
WORKSPACE_SCHEMA = "film-workspace/2"
RECOVERY_SCHEMA = "film-recovery/1"
MIGRATION_SCHEMA = "film-migration/1"
RECOVERY_LAUNCHER = ('from pathlib import Path\nimport sys\n'
    'sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))\n'
    'from douyin_film_recap.workspace import recovery_main\n'
    'raise SystemExit(recovery_main())\n')
KNOWN_NAMES = {"state.json", ".remote-authorization.json", "delivery_report.md", "review_evidence.json"}
OWNED_DIRS = (".receipts", ".remote-intents", "output", "scripts", "audio")
PATH_FIELDS = {"audio_file", "rendered_file", "final_video", "preview_video", "subtitle",
               "edl", "review_file", "contact_sheet_path", "render_plan", "render_receipt"}
_held_roots = ContextVar("film_held_roots", default=frozenset())


class WorkspaceError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def sha(path):
    path = Path(path)
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
        after = os.fstat(stream.fileno())
    current = path.stat()
    attrs = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(getattr(before, k) != getattr(after, k) or
           getattr(after, k) != getattr(current, k) for k in attrs):
        raise WorkspaceError("FILE_CHANGED_DURING_READ")
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _sync_directory(path):
    """Make already-fsynced member/rename directory entries durable on local POSIX FS."""
    fd = os.open(Path(path), os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sync_tree(directory):
    for path in sorted((p for p in Path(directory).rglob("*") if p.is_dir()),
                       key=lambda p: len(p.parts), reverse=True):
        _sync_directory(path)
    _sync_directory(directory)
    _sync_directory(Path(directory).parent)


def atomic(path, value):
    path = Path(path)
    if path.is_symlink():
        raise WorkspaceError("STATE_SYMLINK_REJECTED")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pending-", delete=False) as out:
        temporary = Path(out.name)
        out.write(canonical(value) + b"\n")
        out.flush()
        os.fsync(out.fileno())
    try:
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def member(root, relative):
    root = Path(root).resolve()
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts or str(rel) in ("", "."):
        raise WorkspaceError("MEMBER_PATH_UNSAFE")
    candidate = root / rel
    current = candidate
    while current != root:
        if current.is_symlink():
            raise WorkspaceError("MEMBER_SYMLINK_REJECTED")
        current = current.parent
    if not candidate.resolve().is_relative_to(root):
        raise WorkspaceError("MEMBER_ESCAPES_ROOT")
    return candidate


def _task_root(path):
    raw = Path(path).expanduser().absolute()
    if raw.is_symlink():
        raise WorkspaceError("WORKSPACE_SYMLINK_REJECTED")
    path = raw.resolve()
    marker = path / GENERATION
    if marker.exists():
        if marker.is_symlink():
            raise WorkspaceError("GENERATION_MARKER_UNSAFE")
        data = read(marker)
        if data.get("schema") != WORKSPACE_SCHEMA:
            raise WorkspaceError("UNSUPPORTED_WORKSPACE_SCHEMA")
        root = Path(data["task_root"])
        if not root.is_absolute() or path != member(root, data["relative"]):
            raise WorkspaceError("GENERATION_OWNER_MISMATCH")
        return root.resolve()
    return path


def preflight(path, *, allow_legacy=False):
    """Read before any mkdir/client construction; unknown versions never migrate."""
    root = _task_root(path)
    active = root
    if (root / POINTER).exists():
        if (root / POINTER).is_symlink():
            raise WorkspaceError("WORKSPACE_POINTER_UNSAFE")
        pointer = read(root / POINTER)
        if pointer.get("schema") != WORKSPACE_SCHEMA:
            raise WorkspaceError("UNSUPPORTED_WORKSPACE_SCHEMA")
        active = member(root, pointer["active"])
        if not active.is_dir():
            raise WorkspaceError("ACTIVE_GENERATION_MISSING")
        if _task_root(active) != root or not (active / GENERATION).is_file():
            raise WorkspaceError("GENERATION_OWNER_MISMATCH")
        archive = member(root, f".migrations/{pointer['migration_intent']}")
        if sha(archive / "recovery-manifest.json") != pointer["recovery_manifest_sha256"]:
            raise WorkspaceError("RECOVERY_MANIFEST_DRIFTED")
    state_path = active / "state.json"
    if state_path.exists():
        if state_path.is_symlink():
            raise WorkspaceError("STATE_SYMLINK_REJECTED")
        version = read(state_path).get("schema_version", 1)
        if type(version) is not int or version not in (1, 2):
            raise WorkspaceError("UNSUPPORTED_STATE_SCHEMA")
        if version == 1 and not allow_legacy:
            raise WorkspaceError("LEGACY_MIGRATION_REQUIRED")
    return root, active


@contextmanager
def work_lock(path):
    import fcntl
    root = Path(path)
    key = str(root.resolve())
    if key in _held_roots.get():
        yield
        return
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root / ".film-write.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise WorkspaceError("WORKSPACE_BUSY") from exc
        token = _held_roots.set(_held_roots.get() | {key})
        try:
            yield
        finally:
            _held_roots.reset(token)
    finally:
        os.close(fd)


def _refs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in PATH_FIELDS and isinstance(item, str) and item:
                yield item, key
            elif key == "frame_paths" and isinstance(item, list):
                for path in item:
                    if isinstance(path, str) and path:
                        yield path, key
            elif key == "artifacts" and isinstance(item, dict):
                for path in item:
                    yield path, key
            else:
                yield from _refs(item)
    elif isinstance(value, list):
        for item in value:
            yield from _refs(item)


def _inherited_debug_absences(active, state):
    """Read only absence facts already pinned by this generation's recovery archive.

    A copied scenes record still points to its original generation. Neither a
    matching receipt alone nor an arbitrary missing external file is inherited.
    """
    root = _task_root(active)
    if root == active.resolve():
        return {}
    _, current = preflight(root)
    if current != active.resolve():
        raise WorkspaceError("STALE_WORKSPACE_INSTANCE")
    pointer = read(root / POINTER)
    intent = pointer["migration_intent"]
    archive = member(root, f".migrations/{intent}")
    if (state.get("migration_intent") != intent
            or state.get("recovery_manifest") != str(archive / "recovery-manifest.json")):
        return {}
    manifest = verify_archive(archive)
    previous = Path(manifest["previous_active"])
    archived_state = read(member(archive / "files", "state.json"))
    recorded = {
        str((Path(name) if Path(name).is_absolute() else previous / name).resolve()): value
        for name, value in archived_state.get("stages", {}).get("scenes", {}).get("artifacts", {}).items()
    }
    inherited = {}
    for row in manifest.get("unavailable_optional_references", []):
        if not isinstance(row, dict) or row.get("reason") not in {
                "recorded_regenerable_debug_cleanup", "missing_regenerable_debug_after_delivery"}:
            continue
        path = Path(row.get("original_path", ""))
        if not path.is_absolute() or not path.is_relative_to(root):
            continue
        relative = path.relative_to(root)
        parts = relative.parts
        # Only this task's original debug roots or an owned generation's debug
        # roots qualify. A sibling workspace/ordinary external artifact cannot.
        if len(parts) >= 2 and parts[0] in {"frames", "contact_sheets"}:
            owner = root
        elif (len(parts) >= 4 and parts[0] == ".generations"
              and parts[2] in {"frames", "contact_sheets"}):
            owner = member(root, str(Path(*parts[:2])))
            if _task_root(owner) != root or not (owner / GENERATION).is_file():
                continue
        else:
            continue
        checked = member(root, str(relative))
        key = str(checked.resolve())
        if key in recorded:
            inherited[key] = {"sha256": recorded[key], "reason": row["reason"]}
    return inherited


def _debug_absence_reason(active, state, path, cleanup, inherited=None):
    """Only recorded, regenerable scene imagery may be absent after cleanup."""
    root = active.resolve()
    resolved = path.resolve()
    local_debug = any(resolved.is_relative_to(root / name) for name in ("frames", "contact_sheets"))
    recorded = {
        str((Path(name) if Path(name).is_absolute() else active / name).resolve()): sha256
        for name, sha256 in state.get("stages", {}).get("scenes", {}).get("artifacts", {}).items()
    }
    if str(resolved) not in recorded:
        return None
    expected = recorded[str(resolved)]
    historical = (inherited or {}).get(str(resolved))
    if not local_debug and (historical is None or historical["sha256"] != expected):
        return None
    if cleanup is not None:
        cleanup_files = cleanup.get("files") if isinstance(cleanup, dict) else None
        if (isinstance(cleanup, dict) and cleanup.get("schema") == "film-debug-cleanup/1"
                and isinstance(cleanup_files, list)
                and any(row.get("path") == str(resolved) and row.get("sha256") == expected
                        for row in cleanup_files if isinstance(row, dict))):
            return "recorded_regenerable_debug_cleanup"
        # An explicit but mismatched receipt cannot fall back to a legacy guess.
        return None
    if not local_debug:
        if historical["reason"] == "missing_regenerable_debug_after_delivery":
            return historical["reason"]
        return None  # Removing a recorded-cleanup receipt does not create legacy proof.
    # Older completed workspaces predate cleanup receipts. Preserve the missing
    # fact rather than claim the file was reviewed or that cleanup was observed.
    stages = state.get("stages", {})
    if all(stages.get(name, {}).get("status") == "passed"
           for name in ("scenes", "scene_analysis", "highlights", "delivery")):
        return "missing_regenerable_debug_after_delivery"
    return None


def inventory(active):
    active = Path(active)
    files = {p for p in active.iterdir() if p.is_file() and
             (p.name in KNOWN_NAMES or re.match(r"^\d{2}_.*\.json$", p.name))}
    for name in OWNED_DIRS:
        directory = active / name
        if directory.is_symlink():
            raise WorkspaceError("ARCHIVE_DIRECTORY_SYMLINK")
        if directory.is_dir():
            for p in directory.rglob("*"):
                if p.is_symlink():
                    raise WorkspaceError("ARCHIVE_MEMBER_SYMLINK")
                if p.is_file():
                    files.add(p)
    recorded = {}
    state = read(active / "state.json")
    external = set()
    unavailable = {}
    cleanup_path = member(active, ".receipts/debug-cleanup.json")
    cleanup = read(cleanup_path) if cleanup_path.is_file() else None
    inherited_debug = None

    def missing_optional(path, field=None, *, stage=None):
        nonlocal inherited_debug
        if path.exists():
            return False
        reason = None
        if stage == "scenes" or field in {"frame_paths", "contact_sheet_path"}:
            if inherited_debug is None and not path.resolve().is_relative_to(active.resolve()):
                inherited_debug = _inherited_debug_absences(active, state)
            reason = _debug_absence_reason(active, state, path, cleanup, inherited_debug)
        if reason is None and field == "review_file":
            reason = "optional_review_not_present"
        if reason is None:
            return False
        key = str(path.absolute())
        unavailable[key] = {"original_path": key, "reason": reason}
        return True
    for stage, record in state.get("stages", {}).items():
        references = dict(record.get("artifacts", {}))
        if record.get("artifact"):
            references.setdefault(record["artifact"], record.get("fingerprint"))
        for path, expected in references.items():
            ref = Path(path)
            if not ref.is_absolute():
                ref = active / ref
            if ref.absolute().is_relative_to(active.absolute()):
                member(active, str(ref.relative_to(active)))
            elif ref.is_symlink():
                raise WorkspaceError("ARCHIVE_MEMBER_SYMLINK")
            recorded[str(ref.resolve())] = expected
            if ref.is_absolute() and ref.resolve().is_relative_to(active.resolve()):
                if not ref.is_file():
                    if missing_optional(ref, stage=stage):
                        continue
                    raise WorkspaceError("REQUIRED_ARCHIVE_MEMBER_MISSING")
                files.add(ref)
            elif stage == "ingest":
                external.add(str(ref))  # Original sidecar/source references stay references.
            else:
                if not ref.is_file():
                    if missing_optional(ref, stage=stage):
                        continue
                    raise WorkspaceError("REQUIRED_EXTERNAL_ARTIFACT_MISSING")
                files.add(ref)  # Preserve explicitly referenced generated artifacts.
    # In-task references may include nested generated media; sources outside the task
    # stay references and are not silently copied into the migration archive.
    for file in list(files):
        if file.suffix != ".json" or file == active / "state.json":
            continue
        try:
            value = read(file)
        except (ValueError, UnicodeError):
            continue  # Preserve damaged/user-edited bytes without certifying the JSON.
        for path, field in _refs(value):
            candidate = Path(path)
            candidate = candidate if candidate.is_absolute() else active / candidate
            if candidate.absolute().is_relative_to(active.absolute()):
                member(active, str(candidate.relative_to(active)))
                if not candidate.is_file():
                    if missing_optional(candidate, field):
                        continue
                    raise WorkspaceError("REQUIRED_ARCHIVE_REFERENCE_MISSING")
                files.add(candidate)
            else:
                if candidate.is_symlink():
                    raise WorkspaceError("ARCHIVE_MEMBER_SYMLINK")
                if not candidate.is_file():
                    if missing_optional(candidate, field):
                        continue
                    raise WorkspaceError("REQUIRED_EXTERNAL_REFERENCE_MISSING")
                files.add(candidate)
    rows = []
    for file in sorted(files):
        if file.absolute().is_relative_to(active.absolute()):
            rel = str(file.relative_to(active))
            checked = member(active, rel)
        else:
            rel = f"external/{digest(str(file.absolute()))}/{file.name}"
            checked = file.absolute()
            if checked.is_symlink():
                raise WorkspaceError("ARCHIVE_MEMBER_SYMLINK")
        actual = sha(checked)
        rows.append({"original_path": str(checked), "path": rel, "bytes": checked.stat().st_size,
                     "observed_sha256": actual, "recorded_sha256": recorded.get(str(checked.resolve())),
                     "sha256": actual})
    return rows, sorted(external), [unavailable[key] for key in sorted(unavailable)]


def checked_copy(source, target, expected):
    if target.exists() or target.is_symlink():
        raise WorkspaceError("COPY_TARGET_EXISTS")
    target.parent.mkdir(parents=True, exist_ok=True)
    with Path(source).open("rb") as src, target.open("xb") as dst:
        for chunk in iter(lambda: src.read(1024 * 1024), b""):
            dst.write(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    if target.stat().st_size != expected["bytes"] or sha(target) != expected["sha256"]:
        raise WorkspaceError("COPY_IDENTITY_MISMATCH")
    if sha(source) != expected["sha256"]:
        raise WorkspaceError("COPY_SOURCE_CHANGED")


def verify_archive(directory, *, expected_manifest_sha256=None):
    directory = Path(directory)
    if directory.is_symlink() or (directory / "recovery-manifest.json").is_symlink():
        raise WorkspaceError("RECOVERY_MANIFEST_UNSAFE")
    manifest_path = directory / "recovery-manifest.json"
    raw = manifest_path.read_bytes()
    manifest_sha = hashlib.sha256(raw).hexdigest()
    if expected_manifest_sha256 is not None and manifest_sha != expected_manifest_sha256:
        raise WorkspaceError("RECOVERY_MANIFEST_DRIFTED")
    manifest = json.loads(raw.decode("utf-8"))
    if manifest.get("schema") != RECOVERY_SCHEMA:
        raise WorkspaceError("UNSUPPORTED_RECOVERY_SCHEMA")
    rows = manifest.get("files")
    if (not isinstance(rows, list) or any(not isinstance(r, dict)
            or not isinstance(r.get("path"), str) or type(r.get("bytes")) is not int or r["bytes"] < 0
            or not isinstance(r.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", r["sha256"])
            for r in rows) or len({r["path"] for r in rows}) != len(rows)):
        raise WorkspaceError("RECOVERY_MEMBERS_INVALID")
    if (directory / "files").is_symlink() or any(p.is_symlink() for p in (directory / "files").rglob("*")):
        raise WorkspaceError("RECOVERY_MEMBER_SYMLINK")
    for row in rows:
        p = member(directory / "files", row["path"])
        if not p.is_file() or p.stat().st_size != row["bytes"] or sha(p) != row["sha256"]:
            raise WorkspaceError("RECOVERY_MEMBER_MISMATCH")
    actual = {str(p.relative_to(directory / "files")) for p in (directory / "files").rglob("*") if p.is_file()}
    if actual != {r["path"] for r in rows}:
        raise WorkspaceError("RECOVERY_MEMBER_SET_MISMATCH")
    if sha(manifest_path) != manifest_sha:
        raise WorkspaceError("RECOVERY_MANIFEST_DRIFTED")
    return manifest


def verify_recovery_bundle(directory, expected_sha=None):
    directory = Path(directory)
    if not expected_sha or sha(directory / "recovery-package.json") != expected_sha:
        raise WorkspaceError("PINNED_RECOVERY_BUNDLE_SHA_REQUIRED")
    manifest = read(Path(directory) / "recovery-package.json")
    if (manifest.get("schema") != "film-recovery-package/1"
            or manifest.get("mode") != "READ_ONLY_RECOVERY" or manifest.get("supported_state_schemas") != [1, 2]):
        raise WorkspaceError("RECOVERY_BUNDLE_INVALID")
    for row in manifest["files"]:
        p = member(directory, row["path"])
        if not p.is_file() or sha(p) != row["sha256"]:
            raise WorkspaceError("RECOVERY_BUNDLE_DRIFTED")
    expected = {"recover.py", "src/douyin_film_recap/workspace.py", "src/douyin_film_recap/__init__.py"}
    if expected != {r["path"] for r in manifest["files"]} or len(manifest["files"]) != 3:
        raise WorkspaceError("RECOVERY_ENTRY_MISSING")
    actual = {str(p.relative_to(directory)) for p in directory.rglob("*") if p.is_file()}
    # Bytecode created by executing the recovery candidate is not source authority.
    actual = {p for p in actual if "__pycache__" not in Path(p).parts}
    if actual != expected | {"recovery-package.json"}:
        raise WorkspaceError("RECOVERY_BUNDLE_MEMBERS_CHANGED")
    if ((directory / "recover.py").read_text() != RECOVERY_LAUNCHER
            or (directory / "src/douyin_film_recap/__init__.py").read_text() != "# Read-only recovery package.\n"
            or sha(directory / "src/douyin_film_recap/workspace.py") != sha(__file__)):
        raise WorkspaceError("RECOVERY_SOURCE_NOT_THIS_TESTED_CANDIDATE")
    return sha(Path(directory) / "recovery-package.json")


def prepare(path, binding, *, allow_legacy=False, recovery_bundle=None,
            recovery_bundle_sha256=None, interrupt=None):
    root, _ = preflight(path, allow_legacy=allow_legacy)
    with work_lock(root):
        root, active = preflight(root, allow_legacy=allow_legacy)
        pointer_before = sha(root / POINTER) if (root / POINTER).exists() else None
        state_path = active / "state.json"
        if not state_path.exists():
            return root, active, None
        old = read(state_path)
        legacy = old.get("schema_version", 1) == 1
        if not legacy and old.get("input_fingerprint") == binding["input_fingerprint"] and old.get("config_fingerprint") == binding["config_fingerprint"]:
            if old.get("migration_intent"):
                archive = member(root, f".migrations/{old['migration_intent']}")
                verify_archive(archive)
                atomic(archive / "migration-status.json", {"schema": MIGRATION_SCHEMA,
                    "status": "SWITCHED", "migration_intent": old["migration_intent"]})
            return root, active, None
        recovery_sha = None
        if legacy:
            if not recovery_bundle:
                raise WorkspaceError("VERIFIED_RECOVERY_BUNDLE_REQUIRED")
            recovery_sha = verify_recovery_bundle(recovery_bundle, recovery_bundle_sha256)
        rows, external, unavailable = inventory(active)
        intent = digest({"state": sha(state_path), "files": rows, "binding": binding,
                         "target_schema": 2, "migration_revision": 2, "unavailable_optional": unavailable})
        archive = member(root, f".migrations/{intent}")
        if archive.exists():
            manifest = verify_archive(archive)
            if (manifest["migration_intent"] != intent or manifest["files"] != rows
                    or manifest.get("unavailable_optional_references", []) != unavailable
                    or manifest["source_identity"] != binding
                    or manifest["recovery_bundle_sha256"] != recovery_sha):
                raise WorkspaceError("MIGRATION_INTENT_MISMATCH")
        else:
            required = sum(r["bytes"] for r in rows) + 16 * 1024 * 1024
            if shutil.disk_usage(root).free < required:
                raise WorkspaceError("MIGRATION_DISK_SPACE_INSUFFICIENT")
            temporary = root / ".migrations" / f".pending-{intent}"
            if temporary.exists():
                # Do not overwrite an interrupted or possibly still-live attempt.
                temporary = root / ".migrations" / f".pending-{intent}-{os.urandom(8).hex()}"
            temporary.mkdir(parents=True, exist_ok=False)
            for row in rows:
                checked_copy(Path(row["original_path"]), member(temporary / "files", row["path"]), row)
            if interrupt:
                interrupt("copied")
            if inventory(active) != (rows, external, unavailable):
                raise WorkspaceError("MIGRATION_INPUT_CHANGED")
            manifest = {"schema": RECOVERY_SCHEMA, "migration_intent": intent, "files": rows,
                        "external_references_not_copied": external, "source_identity": binding,
                        "unavailable_optional_references": unavailable,
                        "recovery_bundle_sha256": recovery_sha, "created_at": now(),
                        "original_task_root": str(root), "previous_active": str(active),
                        "scope": "byte preservation; not source/QC/creative certification"}
            atomic(temporary / "recovery-manifest.json", manifest)
            verify_archive(temporary)
            temporary.rename(archive)
        if interrupt:
            interrupt("archived")
        generation = member(root, f".generations/{intent}")
        if not generation.exists():
            generation.mkdir(parents=True, exist_ok=False)
        if not (generation / "state.json").exists():
            atomic(generation / GENERATION, {"schema": WORKSPACE_SCHEMA, "task_root": str(root),
                                             "relative": str(generation.relative_to(root))})
            state = {"schema_version": 2, "project_name": old.get("project_name", "film"),
                     "created_at": now(), "updated_at": now(), "input_paths": binding["input_paths"],
                     "input_fingerprint": binding["input_fingerprint"],
                     "config_fingerprint": binding["config_fingerprint"],
                     "stages": {name: {"status": "pending"} for name in old.get("stages", {})},
                     "last_error": None, "migration_intent": intent,
                     "recovery_manifest": str(archive / "recovery-manifest.json")}
            atomic(generation / "state.json", state)
        else:
            prepared = read(generation / "state.json")
            marker = read(generation / GENERATION)
            if (type(prepared.get("schema_version")) is not int or prepared["schema_version"] != 2
                    or prepared.get("migration_intent") != intent
                    or prepared.get("input_fingerprint") != binding["input_fingerprint"]
                    or prepared.get("config_fingerprint") != binding["config_fingerprint"]
                    or prepared.get("input_paths") != binding["input_paths"]
                    or any(r.get("status") != "pending" for r in prepared.get("stages", {}).values())
                    or marker != {"schema": WORKSPACE_SCHEMA, "task_root": str(root),
                                   "relative": str(generation.relative_to(root))}):
                raise WorkspaceError("PREPARED_GENERATION_MISMATCH")
        prepared_state_sha = sha(generation / "state.json")
        prepared_marker_sha = sha(generation / GENERATION)
        if interrupt:
            interrupt("prepared")
        # A manual JSON edit need not update state.json: recheck all observed bytes.
        if inventory(active) != (rows, external, unavailable):
            raise WorkspaceError("MIGRATION_INPUT_CHANGED")
        pointer_after = sha(root / POINTER) if (root / POINTER).exists() else None
        if pointer_after != pointer_before:
            raise WorkspaceError("MIGRATION_POINTER_CHANGED")
        verified = verify_archive(archive)
        if verified["files"] != rows or verified["source_identity"] != binding:
            raise WorkspaceError("MIGRATION_ARCHIVE_CHANGED")
        if (sha(generation / "state.json") != prepared_state_sha
                or sha(generation / GENERATION) != prepared_marker_sha):
            raise WorkspaceError("PREPARED_GENERATION_CHANGED")
        atomic(root / POINTER, {"schema": WORKSPACE_SCHEMA, "active": str(generation.relative_to(root)),
                               "migration_intent": intent,
                               "recovery_manifest_sha256": sha(archive / "recovery-manifest.json")})
        if interrupt:
            interrupt("switched")
        atomic(archive / "migration-status.json", {"schema": MIGRATION_SCHEMA, "status": "SWITCHED",
                                                   "migration_intent": intent})
        return root, generation, manifest


def recover(archive, destination):
    archive, destination = Path(archive).absolute(), Path(destination).absolute()
    for candidate in (archive, destination):
        if any(p.is_symlink() for p in (candidate, *candidate.parents)):
            raise WorkspaceError("RECOVERY_PATH_SYMLINK")
    archive = archive.resolve()
    manifest_sha = sha(archive / "recovery-manifest.json")
    manifest = verify_archive(archive, expected_manifest_sha256=manifest_sha)
    if (destination.resolve().is_relative_to(archive)
            or (manifest.get("original_task_root") and
                destination.resolve().is_relative_to(Path(manifest["original_task_root"]).resolve()))):
        raise WorkspaceError("RECOVERY_TARGET_MUST_BE_OUTSIDE_ORIGINAL_TASK")
    if destination.exists() or destination.is_symlink():
        raise WorkspaceError("RECOVERY_TARGET_EXISTS")
    destination.mkdir(parents=True, exist_ok=False)
    for row in manifest["files"]:
        checked_copy(member(archive / "files", row["path"]), member(destination, row["path"]), row)
    verify_archive(archive, expected_manifest_sha256=manifest_sha)
    expected = {r["path"] for r in manifest["files"]}
    actual = {str(p.relative_to(destination)) for p in destination.rglob("*") if p.is_file()}
    if actual != expected:
        raise WorkspaceError("RECOVERED_MEMBER_SET_MISMATCH")
    for row in manifest["files"]:
        p = member(destination, row["path"])
        if p.stat().st_size != row["bytes"] or sha(p) != row["sha256"]:
            raise WorkspaceError("RECOVERED_MEMBER_MISMATCH")
    if sha(archive / "recovery-manifest.json") != manifest_sha:
        raise WorkspaceError("RECOVERY_MANIFEST_DRIFTED")
    return {"schema": "film-recovery-result/1", "status": "RECOVERED_BYTES_ONLY",
            "manifest_sha256": manifest_sha,
            "production_authorized": False, "files": len(expected), "path": str(destination)}


def recovery_main():
    parser = argparse.ArgumentParser(description="Read-only film recovery; no production operations")
    parser.add_argument("operation", choices=("inspect", "recover", "run", "resume", "render", "tts", "delivery"))
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    try:
        if args.operation in ("run", "resume", "render", "tts", "delivery"):
            raise WorkspaceError("RECOVERY_VERSION_PRODUCTION_DISABLED")
        if args.operation == "inspect":
            if not args.work_dir:
                raise WorkspaceError("WORK_DIR_REQUIRED")
            _, active = preflight(args.work_dir, allow_legacy=True)
            print(json.dumps({"status": "READ_ONLY", "state": read(active / "state.json"),
                              "source_identity_certified": False}, ensure_ascii=False))
        else:
            if not args.archive or not args.out:
                raise WorkspaceError("ARCHIVE_AND_NEW_TARGET_REQUIRED")
            print(json.dumps(recover(args.archive, args.out), ensure_ascii=False))
    except (WorkspaceError, OSError, ValueError) as exc:
        print(json.dumps({"status": "REJECTED", "error": str(exc)}, ensure_ascii=False))
        return 2
    return 0


def commit_generation(path, *, replacements, expected_generation, expected_pointer_sha256,
                      validate, invalidate_from="pre_qc", binding=None, reason="", interrupt=None):
    """Publish a complete copied generation with one existing workspace pointer swap.

    ``validate`` is invoked under the existing lock both before copying and at the
    commit boundary. Only that pointer is an authority; archives/receipts are not
    writable revision heads. Interrupted private generations never become active.
    """
    from copy import deepcopy

    root, _ = preflight(path)
    with work_lock(root):
        root, active = preflight(root)
        generation_name = str(active.relative_to(root))
        pointer_sha = sha(root / POINTER) if (root / POINTER).exists() else None
        if generation_name != expected_generation or pointer_sha != expected_pointer_sha256:
            raise WorkspaceError("REVISION_BASE_CONFLICT")
        validate(active)
        rows, external, unavailable = inventory(active)
        old = read(active / "state.json")
        if old.get("schema_version") != 2:
            raise WorkspaceError("LEGACY_MIGRATION_REQUIRED")
        for relative in replacements:
            member(active, relative)
            if relative in {"state.json", POINTER, GENERATION}:
                raise WorkspaceError("REVISION_RESERVED_MEMBER")
        intent = digest({"operation": "protected_revision/1", "base": generation_name,
                         "pointer": pointer_sha, "files": rows, "replacements": replacements,
                         "binding": binding, "invalidate_from": invalidate_from, "reason": reason})
        archive = member(root, f".migrations/{intent}")
        if archive.exists():
            manifest = verify_archive(archive)
            if manifest.get("migration_intent") != intent or manifest["files"] != rows:
                raise WorkspaceError("REVISION_ARCHIVE_CONFLICT")
        else:
            required = 2 * sum(row["bytes"] for row in rows) + 16 * 1024 * 1024
            if shutil.disk_usage(root).free < required:
                raise WorkspaceError("MIGRATION_DISK_SPACE_INSUFFICIENT")
            pending = member(root, f".migrations/.pending-{intent}-{os.urandom(8).hex()}")
            pending.mkdir(parents=True, exist_ok=False)
            for row in rows:
                checked_copy(Path(row["original_path"]), member(pending / "files", row["path"]), row)
            if interrupt:
                interrupt("copied")
            manifest = {"schema": RECOVERY_SCHEMA, "migration_intent": intent,
                        "files": rows, "external_references_not_copied": external,
                        "unavailable_optional_references": unavailable,
                        "source_identity": binding or {"input_paths": old.get("input_paths", []),
                            "input_fingerprint": old.get("input_fingerprint"),
                            "config_fingerprint": old.get("config_fingerprint")},
                        "recovery_bundle_sha256": None, "created_at": now(),
                        "original_task_root": str(root), "previous_active": str(active),
                        "scope": "byte preservation; not source/QC/creative certification"}
            atomic(pending / "recovery-manifest.json", manifest)
            verify_archive(pending)
            _sync_tree(pending)
            pending.rename(archive)
            _sync_directory(archive.parent)
            _sync_directory(root)
        if interrupt:
            interrupt("archived")
        # A random suffix preserves incomplete attempts without overwriting them.
        target = member(root, f".generations/{intent}-{os.urandom(8).hex()}")
        target.mkdir(parents=True, exist_ok=False)
        for row in rows:
            checked_copy(member(archive / "files", row["path"]), member(target, row["path"]), row)
        # Old gate results remain in the recovery archive, never as apparently
        # current standalone PASSED reports beside a different authored snapshot.
        for relative in ("10_preflight_qc.json", "11_post_render_qc.json",
                         "output/delivery_report.md", "delivery_report.md"):
            member(target, relative).unlink(missing_ok=True)
        for relative, value in replacements.items():
            atomic(member(target, relative), value)
        state = deepcopy(old)
        order = ["ingest", "transcript", "scenes", "scene_analysis", "story", "highlights",
                 "plan", "storyboard", "tts", "pre_qc", "render", "post_qc", "delivery"]
        if invalidate_from not in order:
            raise WorkspaceError("REVISION_INVALIDATION_STAGE_INVALID")
        for name in order[order.index(invalidate_from):]:
            state.setdefault("stages", {})[name] = {"status": "pending"}
        if binding:
            for key in ("input_paths", "input_fingerprint", "config_fingerprint"):
                state[key] = binding[key]
        state.update(updated_at=now(), last_error=None, migration_intent=intent,
                     recovery_manifest=str(archive / "recovery-manifest.json"))
        atomic(target / "state.json", state)
        atomic(target / GENERATION, {"schema": WORKSPACE_SCHEMA, "task_root": str(root),
                                    "relative": str(target.relative_to(root))})
        # Full generation hashes include all private members, not just the JSON head.
        prepared = {str(p.relative_to(target)): sha(p) for p in target.rglob("*") if p.is_file()}
        _sync_tree(target)
        _sync_directory(root)
        if interrupt:
            interrupt("prepared")
        if (sha(root / POINTER) if (root / POINTER).exists() else None) != pointer_sha:
            raise WorkspaceError("REVISION_BASE_CONFLICT")
        validate(active)
        if inventory(active) != (rows, external, unavailable):
            raise WorkspaceError("REVISION_INPUT_CHANGED")
        if verify_archive(archive) != manifest:
            raise WorkspaceError("REVISION_ARCHIVE_CHANGED")
        current = {str(p.relative_to(target)): sha(p) for p in target.rglob("*") if p.is_file()}
        if current != prepared or any(p.is_symlink() for p in target.rglob("*")):
            raise WorkspaceError("PREPARED_GENERATION_CHANGED")
        atomic(root / POINTER, {"schema": WORKSPACE_SCHEMA, "active": str(target.relative_to(root)),
                               "migration_intent": intent,
                               "recovery_manifest_sha256": sha(archive / "recovery-manifest.json")})
        if interrupt:
            interrupt("switched")
        atomic(archive / "migration-status.json", {"schema": MIGRATION_SCHEMA,
               "status": "SWITCHED", "migration_intent": intent, "operation": "protected_revision"})
        return {"schema": "film-revision-result/1", "status": "ADOPTED",
                "generation": str(target.relative_to(root)), "active_dir": str(target),
                "archive": str(archive), "artifact_hashes": {name: sha(target / name) for name in replacements},
                "qc_status": "NOT_RUN", "reason": reason}
