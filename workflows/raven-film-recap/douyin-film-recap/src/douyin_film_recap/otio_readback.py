"""Saved OTIO snapshot readback and conservative three-way proposals (X2).

Every operation is read-only with respect to the host and film authority. A
proposal is not an adopted edit, a native-host round trip, or a CAS transaction.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import math
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import otio_exchange as x
from . import workspace

SNAPSHOT_SCHEMA = "film-host-snapshot/1"
PROPOSAL_SCHEMA = "film-host-readback-proposal/1"
PRODUCER = "film-otio-readback/1"
FIELDS = ("resource_id", "source_start", "duration", "target_start", "track_id")
TIMING_FIELDS = set(FIELDS)
PROTECTION_KEYS = {"protected", "protection", "protected_fields", "protected_segments",
                   "protected_segment_ids", "locked", "locks", "user_modified", "manual_lock"}
SEMANTIC_FIELDS = {"text", "mode", "audio_owner", "audio_file", "audio_duration_sec", "audio_speed",
                   "original_cues", "narration_job", "highlight_id", "hook_preposed", "mute_original"}


def _problem(code: str, entity: str = "timeline", *, detail: Any = None) -> dict:
    return {"code": code, "entity_id": entity, "detail": detail, "blocking_adoption": True}


def _seal(root: Path, manifest: dict) -> None:
    x._write(root / "snapshot-manifest.json", manifest)
    files = {p.relative_to(root).as_posix(): {"sha256": workspace.sha(p), "bytes": p.stat().st_size}
             for p in sorted(root.rglob("*")) if p.is_file()}
    x._write(root / "checksums.json", {"schema": SNAPSHOT_SCHEMA, "completion_state": "COMPLETE",
                                      "files": files})


def _sealed_member(root: Path, seal: dict, relative: str, error: str) -> bytes:
    """Consume exactly one buffer bound to an already verified checksum row."""
    relative = x.safe_relative(relative)
    row = seal["files"].get(relative)
    if row is None:
        raise x.ExchangeError(error)
    raw, actual = x.read_stable(root / relative)
    if actual != row["sha256"] or len(raw) != row["bytes"]:
        raise x.ExchangeError(error)
    return raw


def _verified_package(root: Path, expected_sha: str | None = None) -> tuple[dict, str]:
    raw, seal_sha = x.read_stable(root / "checksums.json")
    if expected_sha is not None and seal_sha != expected_sha:
        raise x.ExchangeError("EXPORT_PACKAGE_CHANGED_DURING_READBACK")
    seal = x._json(raw)
    if x.verify_package(root) != seal or workspace.sha(root / "checksums.json") != seal_sha:
        raise x.ExchangeError("EXPORT_PACKAGE_CHANGED_DURING_READBACK")
    return seal, seal_sha


def _verified_snapshot(root: str | Path, expected_sha: str | None = None) -> tuple[dict, dict, str]:
    root = x._no_links(Path(root))
    raw, seal_sha = x.read_stable(root / "checksums.json")
    if expected_sha is not None and seal_sha != expected_sha:
        raise x.ExchangeError("HOST_SNAPSHOT_CHANGED_DURING_READBACK")
    seal = x._json(raw)
    if seal.get("schema") != SNAPSHOT_SCHEMA or seal.get("completion_state") != "COMPLETE":
        raise x.ExchangeError("INCOMPLETE_HOST_SNAPSHOT")
    actual = set()
    for member in root.rglob("*"):
        if member.is_symlink():
            raise x.ExchangeError("SYMLINK_REJECTED")
        if member.is_file():
            actual.add(member.relative_to(root).as_posix())
    if actual != set(seal["files"]) | {"checksums.json"}:
        raise x.ExchangeError("HOST_SNAPSHOT_MEMBER_SET_CHANGED")
    for relative, row in seal["files"].items():
        path = root / x.safe_relative(relative)
        if workspace.sha(path) != row["sha256"] or path.stat().st_size != row["bytes"]:
            raise x.ExchangeError("HOST_SNAPSHOT_HASH_MISMATCH")
    manifest = x._json(_sealed_member(root, seal, "snapshot-manifest.json", "HOST_SNAPSHOT_HASH_MISMATCH"))
    if manifest.get("saved_file_sha256") != seal["files"].get("saved.otio", {}).get("sha256"):
        raise x.ExchangeError("HOST_SNAPSHOT_SAVED_FILE_BINDING_MISMATCH")
    bindings = [*manifest.get("resources", {}).values(), *manifest.get("companions", {}).values()]
    if manifest.get("caption_document") is not None:
        bindings.append(manifest["caption_document"])
    for binding in bindings:
        if not isinstance(binding, dict) or "snapshot_path" not in binding:
            continue  # Opaque legacy metadata is not a new required media field.
        row = seal["files"].get(x.safe_relative(binding["snapshot_path"]))
        if (row is None or binding.get("sha256") != row["sha256"] or
                "bytes" in binding and binding["bytes"] != row["bytes"]):
            raise x.ExchangeError("HOST_SNAPSHOT_MEMBER_BINDING_MISMATCH")
    if workspace.sha(root / "checksums.json") != seal_sha:
        raise x.ExchangeError("HOST_SNAPSHOT_CHANGED_DURING_READBACK")
    return manifest, seal, seal_sha


def verify_saved_snapshot(root: str | Path) -> dict:
    return _verified_snapshot(root)[0]


def _references(value: Any):
    if isinstance(value, dict):
        if value.get("OTIO_SCHEMA") == "ExternalReference.1":
            yield value
        for child in value.values():
            yield from _references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _references(child)


def _capture_path(value: str | Path) -> Path:
    path = Path(value)
    # Reject traversal before filesystem lookup, including nonexistent parents.
    # Resolving first could erase a symlink segment and bypass _no_links.
    if ".." in path.parts:
        raise x.ExchangeError("HOST_SNAPSHOT_PATH_TRAVERSAL")
    return x._no_links(path).resolve(strict=False)


def capture_saved_snapshot(saved_otio: str | Path, destination: str | Path, *,
                           export_package: str | Path, media_root: str | Path | None = None,
                           caption_document: str | Path | None = None,
                           companion_files: dict[str, str | Path] | None = None) -> dict:
    """Archive already-saved bytes and referenced local resources into a new path.

    Relative references resolve only against the explicit media_root (by default
    the saved file's parent). Never chase an absolute path, URL or path escape.
    Unsupported references remain preserved in raw bytes with blocking findings.
    Companion files are opaque evidence, not implicitly parsed or adopted.
    """
    package = _capture_path(export_package)
    package_seal, package_sha = _verified_package(package)
    binding_bytes = _sealed_member(package, package_seal, "export-binding.json", "PACKAGE_MEMBER_HASH_MISMATCH")
    binding_sha = hashlib.sha256(binding_bytes).hexdigest()
    binding = x._json(binding_bytes)
    saved = _capture_path(saved_otio)
    raw, saved_sha = x.read_stable(saved)
    document = x._json(raw)
    root = _capture_path(destination)
    if root.exists():
        raise x.ExchangeError("HOST_SNAPSHOT_TARGET_EXISTS")
    if root.is_relative_to(package) or package.is_relative_to(root):
        raise x.ExchangeError("HOST_SNAPSHOT_CANNOT_MODIFY_EXPORT_PACKAGE")
    media_root = _capture_path(media_root) if media_root is not None else saved.parent
    root.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(mode=0o700, exist_ok=False)
    x._write(root / "saved.otio", raw, raw=True)
    resources, findings = {}, []
    for reference in _references(document):
        target = reference.get("target_url")
        if isinstance(target, str) and target in resources:
            continue
        try:
            path = media_root / x.safe_relative(target)
            sha = workspace.sha(x._no_links(path))
            relative = f"resources/{sha}.media"
            if not (root / relative).exists():
                x._copy_verified(path, root / relative, sha)
            resources[target] = {"sha256": sha, "snapshot_path": relative,
                                 "source_reference": target, "bytes": path.stat().st_size}
        except (x.ExchangeError, OSError, TypeError, AttributeError) as exc:
            findings.append(_problem("UNRESOLVED_OR_UNSAFE_MEDIA_REFERENCE", detail={
                "target_url": target, "reason": str(exc)}))
    captions = None
    if caption_document is not None:
        raw_captions, caption_sha = x.read_stable(caption_document)
        # Caption identity is supplied explicitly; SRT sequence numbers are not stable IDs.
        captions = {"sha256": caption_sha, "snapshot_path": "captions.saved.json"}
        x._json(raw_captions)
        x._write(root / captions["snapshot_path"], raw_captions, raw=True)
    companions = {}
    for key, source in (companion_files or {}).items():
        safe = x.safe_relative(key)
        raw_companion, sha = x.read_stable(source)
        relative = "companions/" + safe
        x._write(root / relative, raw_companion, raw=True)
        companions[key] = {"snapshot_path": relative, "sha256": sha}
    # This detects a saved-file rewrite during capture, never pretends to lock the host.
    if workspace.sha(saved) != saved_sha:
        raise x.ExchangeError("HOST_FILE_CHANGED_DURING_CAPTURE")
    manifest = {"schema": SNAPSHOT_SCHEMA, "producer": PRODUCER, "snapshot_id": uuid4().hex,
        "export_id": binding["export_id"], "base_binding_sha256": binding_sha,
        "saved_file_sha256": saved_sha, "saved_origin": str(saved), "resources": resources,
        "caption_document": captions, "companions": companions, "findings": findings,
        "mode": "saved-branch-only", "host_cas": False, "active_host_write": False,
        "host_import_reopen_render": "NOT_RUN"}
    _seal(root, manifest)
    verify_saved_snapshot(root)
    _verified_package(package, package_sha)
    return {"schema": SNAPSHOT_SCHEMA, "snapshot_dir": str(root), "manifest": manifest}


def _time(value: dict, expected_rate: Fraction) -> Fraction:
    if not isinstance(value, dict) or value.get("OTIO_SCHEMA") != "RationalTime.1":
        raise x.ExchangeError("INVALID_HOST_RATIONAL_TIME")
    ticks = x.fraction(value.get("value"))
    rate = x.fraction(value.get("rate"))
    if (ticks.denominator != 1 or abs(ticks) > 2**53 or rate <= 0
            or not math.isclose(float(rate), float(expected_rate), rel_tol=1e-12, abs_tol=0)):
        raise x.ExchangeError("HOST_CLOCK_OR_SUBFRAME_UNSUPPORTED")
    # Restore the known exact rate only after comparing its serialized double.
    return ticks / expected_rate


def _media_reference(clip: dict) -> dict:
    if clip.get("OTIO_SCHEMA") == "Clip.1":
        return clip.get("media_reference", {})
    if clip.get("OTIO_SCHEMA") == "Clip.2":
        refs = clip.get("media_references", {})
        key = clip.get("active_media_reference_key", "DEFAULT_MEDIA")
        if key in refs and len(refs) == 1:
            return refs[key]
    raise x.ExchangeError("HOST_CLIP_SCHEMA_OR_REFERENCE_UNSUPPORTED")


def _extras(obj: dict, known: set[str]) -> dict:
    result = {k: deepcopy(v) for k, v in obj.items() if k not in known}
    metadata = obj.get("metadata", {})
    non_recap = {k: deepcopy(v) for k, v in metadata.items() if k != "recap"}
    known_recap = {"export_id", "instance_id", "segment_id", "visual_index", "resource_id",
        "source_start", "duration", "target_start", "lineage", "speed", "resource_sha256",
        "track_id", "role", "producer", "profile", "authority", "identity_warning", "sha256",
        "linked_video_instance"}
    recap_extra = {k: deepcopy(v) for k, v in metadata.get("recap", {}).items() if k not in known_recap}
    if recap_extra:
        non_recap["recap"] = recap_extra
    if non_recap:
        result["metadata"] = non_recap
    if obj.get("effects"):
        result["effects"] = deepcopy(obj["effects"])
    if obj.get("markers"):
        result["markers"] = deepcopy(obj["markers"])
    return result


def _entities(projection: dict) -> dict:
    return {clip["instance_id"]: {**deepcopy(clip), "track_id": track["track_id"],
            "track_role": track["role"], "track_kind": track["kind"]}
            for track in projection["tracks"] for clip in track["clips"]}


def _parse_snapshot(base_projection: dict, binding: dict, manifest: dict,
                    document_raw: bytes, caption_raw: bytes | None) -> dict:
    """Interpret verified input buffers while retaining unsupported raw bytes."""
    document = x._json(document_raw)
    problems = deepcopy(manifest["findings"])
    opaque, entities, track_ends = {}, {}, {}
    base_entities = _entities(base_projection)
    base_tracks = {t["track_id"]: t for t in base_projection["tracks"]}
    known_item = {"OTIO_SCHEMA", "name", "metadata", "source_range", "effects", "markers", "enabled"}
    if (document.get("OTIO_SCHEMA") != "Timeline.1" or
            document.get("tracks", {}).get("OTIO_SCHEMA") != "Stack.1"):
        return {"entities": {}, "problems": problems + [_problem("HOST_TIMELINE_SCHEMA_UNSUPPORTED")],
                "opaque": {"timeline": document}, "captions": None}
    recap = document.get("metadata", {}).get("recap", {})
    if recap.get("export_id") != binding["export_id"]:
        problems.append(_problem("EXPORT_ID_MISSING_OR_MISMATCH"))
    extra = _extras(document, {"OTIO_SCHEMA", "name", "metadata", "global_start_time", "tracks"})
    stack = document["tracks"]
    stack_extra = _extras(stack, known_item | {"children"})
    if stack.get("source_range") is not None or stack.get("enabled", True) is not True:
        problems.append(_problem("HOST_STACK_TRIM_OR_DISABLE_UNSUPPORTED"))
    if extra or stack_extra:
        opaque["timeline"] = {"timeline": extra, "stack": stack_extra}
    fps = x.fraction(base_projection["profile"]["fps"])
    if document.get("global_start_time") is not None:
        try:
            if _time(document["global_start_time"], fps) != 0:
                problems.append(_problem("HOST_GLOBAL_START_CHANGED"))
        except x.ExchangeError as exc:
            problems.append(_problem(exc.code))
    seen_tracks = set()
    for track_index, track in enumerate(stack.get("children", [])):
        tid = track.get("metadata", {}).get("recap", {}).get("track_id")
        entity_name = tid or f"unidentified-track-{track_index}"
        if not tid or tid not in base_tracks or tid in seen_tracks:
            problems.append(_problem("TRACK_ID_MISSING_UNKNOWN_OR_DUPLICATE", entity_name))
            continue
        seen_tracks.add(tid)
        baseline = base_tracks[tid]
        if track.get("OTIO_SCHEMA") != "Track.1" or track.get("kind") != baseline["kind"]:
            problems.append(_problem("HOST_TRACK_KIND_OR_SCHEMA_CHANGED", tid))
            continue
        if track.get("source_range") is not None or track.get("enabled", True) is not True:
            problems.append(_problem("HOST_TRACK_TRIM_OR_DISABLE_UNSUPPORTED", tid))
        extra = _extras(track, known_item | {"children", "kind"})
        if extra:
            opaque[tid] = extra
        cursor = Fraction(0)
        for index, item in enumerate(track.get("children", [])):
            schema = item.get("OTIO_SCHEMA")
            label = f"{tid}/{index}"
            if schema == "Gap.1":
                try:
                    # Gaps may use any known track media clock (sample clocks can differ by source).
                    rates = {fps} if track["kind"] == "Video" else {
                        x.fraction(r["facts"]["sample_rate"]) for r in base_projection["resources"].values()
                        if r["facts"].get("sample_rate")}
                    incoming = x.fraction(item["source_range"]["duration"]["rate"])
                    rate = next((r for r in rates if math.isclose(float(incoming), float(r), rel_tol=1e-12)), None)
                    if rate is None:
                        raise x.ExchangeError("HOST_GAP_CLOCK_UNSUPPORTED")
                    duration = _time(item["source_range"]["duration"], rate)
                    if duration <= 0:
                        raise x.ExchangeError("HOST_EMPTY_GAP")
                    cursor += duration
                    extra = _extras(item, known_item)
                    if extra:
                        opaque.setdefault(tid, {})[label] = extra
                    if item.get("enabled", True) is not True:
                        problems.append(_problem("HOST_DISABLED_GAP_UNSUPPORTED", label))
                except (x.ExchangeError, KeyError, TypeError) as exc:
                    problems.append(_problem("HOST_GAP_INVALID", label, detail=str(exc)))
                continue
            if schema not in ("Clip.1", "Clip.2"):
                opaque[label] = deepcopy(item)
                problems.append(_problem("HOST_ITEM_SCHEMA_UNSUPPORTED", label))
                continue
            rec = item.get("metadata", {}).get("recap", {})
            iid = rec.get("instance_id")
            if not iid or iid not in base_entities or iid in entities:
                problems.append(_problem("INSTANCE_ID_MISSING_UNKNOWN_OR_DUPLICATE", iid or label))
                continue
            original = base_entities[iid]
            if original["track_kind"] != baseline["kind"]:
                problems.append(_problem("CLIP_MEDIA_KIND_CHANGED", iid))
            if rec.get("export_id") != binding["export_id"]:
                problems.append(_problem("CLIP_EXPORT_ID_MISSING_OR_MISMATCH", iid))
            try:
                reference = _media_reference(item)
                if reference.get("OTIO_SCHEMA") != "ExternalReference.1":
                    raise x.ExchangeError("HOST_MEDIA_REFERENCE_UNSUPPORTED")
                rid = reference.get("metadata", {}).get("recap", {}).get("resource_id")
                if not rid or rid not in base_projection["resources"] or rec.get("resource_id") != rid:
                    raise x.ExchangeError("RESOURCE_ID_MISSING_OR_MISMATCH")
                resource = base_projection["resources"][rid]
                observation = manifest["resources"].get(reference.get("target_url"))
                if (observation is None or observation["sha256"] != resource["sha256"]
                        or reference.get("metadata", {}).get("recap", {}).get("sha256") != resource["sha256"]):
                    raise x.ExchangeError("SOURCE_ID_BYTES_DRIFTED")
                rate = fps if track["kind"] == "Video" else x.fraction(resource["facts"]["sample_rate"])
                source_range = item["source_range"]
                if source_range.get("OTIO_SCHEMA") != "TimeRange.1":
                    raise x.ExchangeError("HOST_SOURCE_RANGE_INVALID")
                start, duration = _time(source_range["start_time"], rate), _time(source_range["duration"], rate)
                if start < 0 or duration <= 0 or start + duration > x.fraction(resource["duration"]):
                    raise x.ExchangeError("HOST_SOURCE_RANGE_INVALID")
                verified_limit = (resource["facts"].get("frame_count") if track["kind"] == "Video"
                                  else resource["facts"].get("duration_samples"))
                if verified_limit is not None and (start + duration) * rate > verified_limit:
                    raise x.ExchangeError("HOST_RANGE_EXCEEDS_VERIFIED_MEDIA")
                x._ticks(cursor, rate, "HOST_TARGET_OFF_CLOCK")
                if item.get("enabled", True) is not True:
                    problems.append(_problem("HOST_DISABLED_CLIP_UNSUPPORTED", iid))
                entities[iid] = {**deepcopy(original), "resource_id": rid,
                    "source_start": x.rational(start), "duration": x.rational(duration),
                    "target_start": x.rational(cursor), "track_id": tid,
                    "track_role": baseline["role"], "track_kind": baseline["kind"]}
                cursor += duration
                extra = _extras(item, known_item | {"media_reference", "media_references", "active_media_reference_key"})
                ref_extra = _extras(reference, {"OTIO_SCHEMA", "name", "metadata", "target_url",
                                               "available_range", "available_image_bounds"})
                if extra or ref_extra:
                    opaque[iid] = {"clip": extra, "reference": ref_extra}
            except (x.ExchangeError, KeyError, TypeError) as exc:
                problems.append(_problem(getattr(exc, "code", "HOST_CLIP_INVALID"), iid, detail=str(exc)))
        track_ends[tid] = x.rational(cursor)
        last_clip_end = max((x.fraction(e["target_start"]) + x.fraction(e["duration"])
                            for e in entities.values() if e["track_id"] == tid), default=Fraction(0))
        if cursor > last_clip_end:
            # Storyboard cut projections cannot express terminal blank intervals.
            # Preserve the measured endpoint and block instead of dropping the gap.
            problems.append(_problem("HOST_TRAILING_GAP_REQUIRES_EXPLICIT_MAPPING", tid,
                detail={"track_end": x.rational(cursor), "last_clip_end": x.rational(last_clip_end)}))
    captions = None
    if manifest["caption_document"]:
        captions = {}
        cap_doc = x._json(caption_raw)
        for cap in cap_doc.get("captions", []) if isinstance(cap_doc, dict) else cap_doc:
            cid = cap.get("caption_id")
            if not cid or cid in captions:
                problems.append(_problem("CAPTION_ID_MISSING_OR_DUPLICATE", str(cid)))
                continue
            try:
                start, end = x.fraction(cap["start"]), x.fraction(cap["end"])
                if start < 0 or end <= start or not isinstance(cap["text"], str):
                    raise x.ExchangeError("HOST_CAPTION_INVALID")
                captions[cid] = {**deepcopy(cap), "start": x.rational(start), "end": x.rational(end)}
            except (x.ExchangeError, KeyError, TypeError) as exc:
                problems.append(_problem("HOST_CAPTION_INVALID", cid, detail=str(exc)))
    return {"entities": entities, "problems": problems, "opaque": opaque, "captions": captions,
            "track_ends": track_ends}


def parse_snapshot(snapshot_dir: str | Path, base_projection: dict, binding: dict, *,
                   expected_seal_sha256: str | None = None) -> dict:
    """Malformed host structures stay opaque; byte drift is a blocking error."""
    root = x._no_links(Path(snapshot_dir))
    manifest, seal, seal_sha = _verified_snapshot(root, expected_seal_sha256)
    # Identity checks stay outside the structure-compatibility catch. A changed
    # archive must not become an opaque-but-VERIFIED proposal.
    document_raw = _sealed_member(root, seal, "saved.otio", "HOST_SNAPSHOT_HASH_MISMATCH")
    caption_raw = (_sealed_member(root, seal, manifest["caption_document"]["snapshot_path"],
                                 "HOST_SNAPSHOT_HASH_MISMATCH") if manifest["caption_document"] else None)
    try:
        result = _parse_snapshot(base_projection, binding, manifest, document_raw, caption_raw)
    except (ValueError, TypeError, KeyError, AttributeError, StopIteration) as exc:
        result = {"entities": {}, "captions": None,
                  "opaque": {"timeline": {"preserved_saved_file": "saved.otio"}},
                  "problems": [_problem("HOST_STRUCTURE_UNSUPPORTED", detail=str(exc))]}
    _verified_snapshot(root, seal_sha)
    return result


def _protected(value: Any) -> bool:
    if isinstance(value, dict):
        return any((k in PROTECTION_KEYS and bool(v)) or _protected(v) for k, v in value.items())
    if isinstance(value, list):
        return any(_protected(v) for v in value)
    return False


def _field_changes(base: dict, current: dict, host: dict, fields: tuple[str, ...], entity: str) -> list[dict]:
    changes = []
    for field in fields:
        b, c, h = base.get(field), current.get(field), host.get(field)
        if b == c == h:
            continue
        classification = ("converged" if c == h else "host_only" if c == b
                          else "current_only" if h == b else "conflict")
        changes.append({"entity_id": entity, "segment_id": base.get("segment_id"), "field": field,
            "base": deepcopy(b), "current": deepcopy(c), "host": deepcopy(h),
            "classification": classification, "current_value_sha256": x.digest(c)})
    return changes


def three_way_compare(base: dict, current: dict, host: dict, *, base_storyboard: dict,
                      current_storyboard: dict) -> dict:
    """Pure diff; confirmed identity is required before any host-only proposal."""
    b, c, h = _entities(base), _entities(current), host["entities"]
    conflicts = deepcopy(host["problems"])
    changes = []
    def projected_ends(projection):
        return {track["track_id"]: x.rational(max((x.fraction(clip["target_start"]) +
            x.fraction(clip["duration"]) for clip in track["clips"]), default=Fraction(0)))
            for track in projection["tracks"] if track["clips"]}

    base_ends, current_ends = projected_ends(base), projected_ends(current)
    host_ends = host.get("track_ends", {})
    for tid in sorted(set(base_ends) | set(current_ends) | set(host_ends)):
        delta = _field_changes({"track_end": base_ends.get(tid)},
            {"track_end": current_ends.get(tid)}, {"track_end": host_ends.get(tid)},
            ("track_end",), tid)
        changes.extend(delta)
        if any(row["host"] != row["base"] for row in delta):
            conflicts.append(_problem("HOST_TRACK_END_REQUIRES_EXPLICIT_MAPPING", tid))
    base_segments = {s["segment_id"]: s for s in base_storyboard["segments"]}
    current_segments = {s["segment_id"]: s for s in current_storyboard["segments"]}
    for iid in sorted(set(b) | set(c) | set(h)):
        if iid not in b:
            conflicts.append(_problem("UNCONFIRMED_NEW_INSTANCE", iid))
            continue
        if iid not in c or iid not in h:
            if iid not in c and iid not in h:
                continue
            field = {"entity_id": iid, "segment_id": b[iid]["segment_id"], "field": "presence",
                "base": True, "current": iid in c, "host": iid in h,
                "classification": "host_only" if iid in c else "current_only",
                "current_value_sha256": x.digest(iid in c)}
            changes.append(field)
            # Missing host IDs are indistinguishable from removal after stripping IDs.
            conflicts.append(_problem("INSTANCE_REMOVAL_REQUIRES_EXPLICIT_MAPPING", iid))
            continue
        delta = _field_changes(b[iid], c[iid], h[iid], FIELDS, iid)
        changes.extend(delta)
        current_changed = {row["field"] for row in delta if row["current"] != row["base"]}
        host_changed = {row["field"] for row in delta if row["host"] != row["base"]}
        if not host_changed:
            continue
        sid = b[iid]["segment_id"]
        if any(row["classification"] == "conflict" for row in delta):
            conflicts.append(_problem("SAME_FIELD_CHANGED_BOTH", iid))
        if (current_changed & TIMING_FIELDS and host_changed & TIMING_FIELDS
                and any(c[iid].get(f) != h[iid].get(f) for f in FIELDS)):
            conflicts.append(_problem("CROSS_FIELD_TIMING_DEPENDENCY", iid))
        if _protected(current_segments.get(sid, {})) or any(
                k in PROTECTION_KEYS and bool(v) for k, v in current_storyboard.items()):
            conflicts.append(_problem("PROTECTED_STORYBOARD_ENTITY", iid))
        if any(base_segments.get(sid, {}).get(f) != current_segments.get(sid, {}).get(f)
               for f in SEMANTIC_FIELDS):
            conflicts.append(_problem("CURRENT_SEMANTIC_ANCHOR_CHANGED", iid))
        affected_opaque = [key for key in ("timeline", iid, b[iid]["track_id"], h[iid]["track_id"])
                           if key in host["opaque"]]
        board_opaque = (base.get("opaque", {}).get("root") or current.get("opaque", {}).get("root")
            or any(base.get("opaque", {}).get("sources", {}).get(rid)
                   or current.get("opaque", {}).get("sources", {}).get(rid)
                   for rid in {b[iid]["resource_id"], c[iid]["resource_id"], h[iid]["resource_id"]})
            or base.get("opaque", {}).get("segments", {}).get(sid)
            or current.get("opaque", {}).get("segments", {}).get(sid)
            or any(key.startswith(sid + "/") for key in base.get("opaque", {}).get("visuals", {}))
            or any(key.startswith(sid + "/") for key in current.get("opaque", {}).get("visuals", {})))
        if affected_opaque or board_opaque:
            conflicts.append(_problem("UNKNOWN_TEMPORAL_DEPENDENCY", iid, detail=affected_opaque))
    if host["captions"] is not None:
        base_caps = {cap["caption_id"]: cap for cap in base["captions"]}
        current_caps = {cap["caption_id"]: cap for cap in current["captions"]}
        for cid, cap in host["captions"].items():
            if cid not in base_caps or cid not in current_caps:
                conflicts.append(_problem("CAPTION_ID_UNCONFIRMED", cid))
                continue
            delta = _field_changes(base_caps[cid], current_caps[cid], cap, ("start", "end", "text"), cid)
            changes.extend(delta)
            if any(row["classification"] == "conflict" for row in delta):
                conflicts.append(_problem("CAPTION_CHANGED_BOTH", cid))
            host_changed = {row["field"] for row in delta if row["host"] != row["base"]}
            if host_changed:
                linked_segment = current_caps[cid].get("segment_id")
                if (_protected(current_caps[cid]) or _protected(current_segments.get(linked_segment, {}))
                        or any(k in PROTECTION_KEYS and bool(v) for k, v in current_storyboard.items())):
                    conflicts.append(_problem("PROTECTED_CAPTION_OR_DOCUMENT", cid))
                known_caption = {"caption_id", "start", "end", "text", "segment_id", "srt_index",
                                 "srt_start_ms", "srt_end_ms", "rounding_policy"}
                unknown_caption = any(set(item) - known_caption for item in (base_caps[cid], current_caps[cid], cap))
                if host_changed & {"start", "end"} and (unknown_caption or "timeline" in host["opaque"]):
                    conflicts.append(_problem("UNKNOWN_CAPTION_TEMPORAL_DEPENDENCY", cid))
        for cid in set(base_caps) - set(host["captions"]):
            conflicts.append(_problem("CAPTION_REMOVAL_REQUIRES_EXPLICIT_MAPPING", cid))
    # An unsupported item can move subsequent anchors; never approve unaffected-looking JSON fields.
    global_block = bool(host["problems"]) or any(
        p["code"] == "HOST_TRACK_END_REQUIRES_EXPLICIT_MAPPING" for p in conflicts)
    blocked = {problem["entity_id"] for problem in conflicts}
    proposed = [row for row in changes if row["classification"] == "host_only"
                and not global_block and row["entity_id"] not in blocked]
    return {"changes": changes, "proposed_changes": proposed, "conflicts": conflicts,
            "opaque": deepcopy(host["opaque"])}


def observe_saved_origin(manifest: dict) -> dict:
    try:
        observed = workspace.sha(x._no_links(Path(manifest["saved_origin"])))
    except (OSError, x.ExchangeError, workspace.WorkspaceError):
        return {"state": "UNKNOWN", "reason": "live saved file is unavailable; archived snapshot remains valid"}
    return {"state": "UNCHANGED_SAVED_FILE" if observed == manifest["saved_file_sha256"] else "DIVERGED",
            "observed_sha256": observed, "snapshot_sha256": manifest["saved_file_sha256"],
            "is_host_cas": False}


def propose_saved_readback(export_package: str | Path, current_work_dir: str | Path,
                           saved_snapshot: str | Path, *, current_captions: list[dict] | None = None) -> dict:
    """Freeze current film authority, compare three versions, return a proposal only."""
    from .revision import freeze_revision, assert_revision_base

    package = x._no_links(Path(export_package))
    package_seal, package_sha = _verified_package(package)
    binding_bytes = _sealed_member(package, package_seal, "export-binding.json", "PACKAGE_MEMBER_HASH_MISMATCH")
    binding_sha = hashlib.sha256(binding_bytes).hexdigest()
    binding = x._json(binding_bytes)
    base = x._json(_sealed_member(package, package_seal, "projection.json", "PACKAGE_MEMBER_HASH_MISMATCH"))
    original = x._json(_sealed_member(package, package_seal, "storyboard.snapshot.json", "PACKAGE_MEMBER_HASH_MISMATCH"))
    manifest, _, snapshot_sha = _verified_snapshot(saved_snapshot)
    if manifest["export_id"] != binding["export_id"] or manifest["base_binding_sha256"] != binding_sha:
        raise x.ExchangeError("HOST_SNAPSHOT_EXPORT_BINDING_MISMATCH")
    if x.digest(base) != binding["projection_sha256"]:
        raise x.ExchangeError("EXPORT_PROJECTION_BINDING_MISMATCH")
    host = parse_snapshot(saved_snapshot, base, binding, expected_seal_sha256=snapshot_sha)
    root, _ = workspace.preflight(current_work_dir)
    with workspace.work_lock(root):
        token = freeze_revision(current_work_dir)
        active = assert_revision_base(current_work_dir, token)
        raw, current_sha = x.read_stable(active / "09_storyboard.json")
        current_storyboard = x._json(raw)
        authority = {"kind": "film-storyboard", "workspace_generation": token["generation"],
                     "storyboard_sha256": current_sha}
        media_facts = {key: deepcopy(resource["facts"]) for key, resource in base["resources"].items()}
        current_audio = {item["path"]: item["sha256"] for item in token["audio"]}
        for segment in current_storyboard["segments"]:
            key = f"narration:{segment['segment_id']}"
            if key in media_facts and segment.get("audio_file") in current_audio:
                media_facts[key]["sha256"] = current_audio[segment["audio_file"]]
        try:
            # Existing captions are known only when bound to this exact Storyboard or explicitly supplied.
            captions_known = current_captions is not None or current_sha == binding["storyboard_sha256"]
            captions = base["captions"] if current_captions is None else current_captions
            current = x.compile_cut_projection(current_storyboard, storyboard_sha256=current_sha,
                authority=authority, profile=base["profile"], media_facts=media_facts,
                identity_map=base["identity_map"], captions=captions)
            comparison = three_way_compare(base, current, host, base_storyboard=original,
                                            current_storyboard=current_storyboard)
            if host["captions"] is not None and not captions_known:
                comparison["conflicts"].append(_problem("CURRENT_CAPTION_BINDING_REQUIRED"))
                comparison["proposed_changes"] = [r for r in comparison["proposed_changes"]
                    if r["field"] not in {"start", "end", "text"}]
            # A source rebind in the current authority is a different media branch, never guessed.
            if {key: r["sha256"] for key, r in current["resources"].items()} != binding["source_bindings"]:
                comparison["conflicts"].append(_problem("CURRENT_SOURCE_BINDING_CHANGED"))
                comparison["proposed_changes"] = []
        except x.ExchangeError as exc:
            comparison = {"changes": [], "proposed_changes": [], "opaque": host["opaque"],
                "conflicts": host["problems"] + [_problem("CURRENT_IDENTITY_OR_SUBSET_UNRESOLVED", detail=exc.code)]}
        assert_revision_base(current_work_dir, token)
    origin = observe_saved_origin(manifest)
    _verified_package(package, package_sha)
    _verified_snapshot(saved_snapshot, snapshot_sha)
    if origin["state"] == "DIVERGED":
        comparison["conflicts"].append(_problem("HOST_ORIGIN_DIVERGED"))
        comparison["proposed_changes"] = []
    changed = any(row["classification"] in ("host_only", "conflict") for row in comparison["changes"])
    status = ("DIVERGED" if origin["state"] == "DIVERGED" else "CONFLICT" if comparison["conflicts"]
              else "READY_FOR_REVIEW" if changed else "NEEDS_REVIEW" if comparison["opaque"] else "NO_CHANGES")
    return {"schema": PROPOSAL_SCHEMA, "producer": PRODUCER, "proposal_id": uuid4().hex,
        "status": status, "base_export_id": binding["export_id"], "base_binding_sha256": binding_sha,
        "saved_snapshot_id": manifest["snapshot_id"], "saved_file_sha256": manifest["saved_file_sha256"],
        "current_storyboard_sha256": current_sha, "current_revision_base": token,
        "live_origin": origin, **comparison, "adoption_performed": False,
        "active_host_write": False, "host_cas": False,
        "adoption_contract": {"entry": "revision.adopt_revision", "requires": [
            "explicit authorized scope", "fresh current_revision_base", "Storyboard candidate mapping",
            "existing evidence and protection validation", "all relevant conflicts resolved"],
            "automatic_mapping": "NOT_IMPLEMENTED; host trims do not infer narration or story intent"},
        "required_reviews": ["source evidence and protected ranges", "narration/visual and caption anchors",
            "pre_qc and downstream render/post_qc after any eventual adoption"],
        "claims": {"saved_snapshot_bytes": "VERIFIED", "three_way_fields": "COMPARED",
            "native_host_import_reopen_render": "NOT_RUN", "adopted_roundtrip": "NOT_RUN"}}


def write_readback_proposal(proposal: dict, path: str | Path) -> Path:
    """Save a new report, never an authority document or a live host project."""
    path = x._no_links(Path(path))
    if path.exists():
        raise x.ExchangeError("PROPOSAL_TARGET_EXISTS")
    if path.name in {"09_storyboard.json", "state.json", workspace.POINTER, workspace.GENERATION}:
        raise x.ExchangeError("PROPOSAL_CANNOT_TARGET_AUTHORITY")
    x._write(path, proposal)
    return path


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Capture saved OTIO bytes or propose a read-only three-way diff")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--export-package", required=True)
    capture.add_argument("--saved-otio", required=True)
    capture.add_argument("--snapshot-dir", required=True)
    capture.add_argument("--media-root")
    capture.add_argument("--caption-document")
    capture.add_argument("--companions-json", help="Map archive names to explicit saved companion files")
    propose = sub.add_parser("propose")
    propose.add_argument("--export-package", required=True)
    propose.add_argument("--work-dir", required=True)
    propose.add_argument("--snapshot-dir", required=True)
    propose.add_argument("--current-captions-json")
    propose.add_argument("--output", help="New proposal file; omitted prints without writing a report")
    args = parser.parse_args(argv)
    try:
        if args.command == "capture":
            companions = x._json(x.read_stable(args.companions_json)[0]) if args.companions_json else None
            result = capture_saved_snapshot(args.saved_otio, args.snapshot_dir,
                export_package=args.export_package, media_root=args.media_root,
                caption_document=args.caption_document, companion_files=companions)
        else:
            captions = x._json(x.read_stable(args.current_captions_json)[0]) if args.current_captions_json else None
            result = propose_saved_readback(args.export_package, args.work_dir, args.snapshot_dir,
                                            current_captions=captions)
            if args.output:
                write_readback_proposal(result, args.output)
        print(json.dumps(result, ensure_ascii=False))
        return 2 if result.get("status") in {"CONFLICT", "DIVERGED"} else 0
    except (x.ExchangeError, workspace.WorkspaceError, OSError, ValueError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
