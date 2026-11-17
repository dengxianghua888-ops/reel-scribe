"""One-way, restricted OTIO cut packages derived from the film Storyboard.

No host API, alternate editable head, runtime OTIO dependency, or render/QC
claim is introduced. Package checksums seal saved bytes; they are not a trust
signature or protection against a hostile process with the same permissions.
"""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import uuid4

from . import workspace

SCHEMA = "film-otio-export/1"
PROJECTION_SCHEMA = "film-cut-projection/1"
PRODUCER = "film-otio-exchange/1"
PROFILE = "otio-cuts-cfr-1x/1"
SHA = re.compile(r"^[0-9a-f]{64}$")
BASE_FIELDS = {"schema_version", "created_at", "project_name", "sources", "plan_fingerprint",
               "target_duration_sec", "segments", "output"}
SEGMENT_FIELDS = {"segment_id", "beat_id", "mode", "title", "text", "text_raw", "original_cues",
    "original_cues_verified", "visuals", "audio_owner", "narration_job", "mute_original",
    "planned_duration_sec", "audio_file", "audio_source_duration_sec", "audio_duration_sec",
    "audio_speed", "tts_word_boundaries", "highlight_id", "hook_preposed", "allow_reuse",
    "notes", "status", "rendered_file", "rendered_duration_sec", "audio_instance_id"}
SOURCE_FIELDS = {"source_id", "path", "fingerprint", "identity_schema", "size_bytes", "filename",
    "duration", "width", "height", "fps", "has_audio", "subtitle_path", "subtitle_fingerprint",
    "subtitle_size_bytes", "order"}
VISUAL_FIELDS = {"source_id", "start", "end", "purpose", "highlight_id", "unit_id",
                 "visual_role", "clip_instance_id", "lineage"}
UNSUPPORTED = {"effects", "transitions", "visual_layers", "overlays", "keyframes",
               "speed_curve", "retime", "crop", "transform", "gain_db", "gain", "opacity"}


class ExchangeError(ValueError):
    def __init__(self, code: str, *, findings: list[dict] | None = None):
        super().__init__(code)
        self.code = code
        self.findings = findings or []


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def fraction(value: Any) -> Fraction:
    """Decimal floats retain only their supplied precision, never invented precision."""
    if isinstance(value, bool):
        raise ExchangeError("INVALID_RATIONAL_TIME")
    try:
        if isinstance(value, Mapping):
            n = value.get("numerator", value.get("num"))
            d = value.get("denominator", value.get("den"))
            if type(n) is not int or type(d) is not int:
                raise ValueError("rational components must be integers")
            return Fraction(n, d)
        return Fraction(str(value))
    except (ValueError, TypeError, ZeroDivisionError) as exc:
        raise ExchangeError("INVALID_RATIONAL_TIME") from exc


def rational(value: Any) -> dict[str, int]:
    value = fraction(value)
    return {"numerator": value.numerator, "denominator": value.denominator}


def _ticks(seconds: Any, rate: Any, code: str) -> int:
    value = fraction(seconds) * fraction(rate)
    if value.denominator != 1 or abs(value.numerator) > 2**53:
        raise ExchangeError(code)
    return value.numerator


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or path.is_absolute() or ".." in path.parts or "\\" in value
            or ":" in value or value != str(path) or any(ord(c) < 32 for c in value)):
        raise ExchangeError("UNSAFE_PACKAGE_PATH")
    return value


def _no_links(path: Path) -> Path:
    path = path.absolute()
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise ExchangeError("SYMLINK_REJECTED")
    return path


def read_stable(path: str | Path) -> tuple[bytes, str]:
    path = _no_links(Path(path))
    before = workspace.sha(path)
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != before or workspace.sha(path) != before:
        raise ExchangeError("FILE_CHANGED_DURING_SNAPSHOT")
    return raw, before


def _json(raw: bytes) -> Any:
    def invalid(value):
        raise ExchangeError("NONFINITE_JSON")
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ExchangeError("DUPLICATE_JSON_KEY")
            result[key] = value
        return result
    return json.loads(raw, parse_constant=invalid, object_pairs_hook=pairs)


def _write(path: Path, value: Any, *, raw: bool = False) -> None:
    data = value if raw else canonical(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())


def _copy_verified(source: Path, target: Path, expected: str) -> None:
    source = _no_links(source)
    if not SHA.fullmatch(expected):
        raise ExchangeError("FULL_SOURCE_SHA256_REQUIRED")
    target.parent.mkdir(parents=True, exist_ok=True)
    h = hashlib.sha256()
    with source.open("rb") as inp, target.open("xb") as out:
        before = os.fstat(inp.fileno())
        for block in iter(lambda: inp.read(1024 * 1024), b""):
            h.update(block)
            out.write(block)
        after = os.fstat(inp.fileno())
        out.flush()
        os.fsync(out.fileno())
    current = source.stat()
    attrs = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (h.hexdigest() != expected or any(getattr(before, a) != getattr(after, a)
            or getattr(after, a) != getattr(current, a) for a in attrs)):
        raise ExchangeError("SOURCE_BYTES_CHANGED")


def _finding(entity: str, field: str, fidelity: str, handling: str, *,
             blocking: bool = False, interval: Any = None, original_sha: str | None = None,
             direction: str = "export") -> dict:
    return {"entity": entity, "field": field, "direction": direction, "version": PRODUCER,
            "fidelity": fidelity, "severity": "error" if blocking else "warning",
            "blocks_claim": "editable_cuts" if blocking else "render_equivalent",
            "blocking": blocking, "handling": handling, "original_sha256": original_sha,
            "derived_sha256": None, "affected_interval": interval}


def _profile(profile: Mapping[str, Any]) -> dict:
    fps = fraction(profile["fps"])
    if fps <= 0 or fps > 240 or any(type(profile[k]) is not int or profile[k] <= 0
                                  for k in ("width", "height")):
        raise ExchangeError("INVALID_OUTPUT_PROFILE")
    return {"fps": rational(fps), "width": profile["width"], "height": profile["height"]}


def _unsupported(value: Any, path: str = "storyboard") -> list[dict]:
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if key in UNSUPPORTED and child not in (None, [], {}, 0, False):
                found.append(_finding(path, key, "unsupported", "reject; no effect is silently dropped",
                                      blocking=True))
            if key in ("speed", "audio_speed") and fraction(child) != 1:
                found.append(_finding(path, key, "unsupported", "only 1x cuts are supported",
                                      blocking=True))
            found.extend(_unsupported(child, f"{path}/{key}"))
    elif isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(_unsupported(child, f"{path}/{i}"))
    return found


def _opaque(storyboard: dict) -> dict:
    result = {"root": {k: v for k, v in storyboard.items() if k not in BASE_FIELDS},
              "segments": {}, "visuals": {}, "sources": {},
              "output": deepcopy(storyboard.get("output", {}))}
    for source in storyboard.get("sources", []):
        extra = {k: v for k, v in source.items() if k not in SOURCE_FIELDS}
        if extra:
            result["sources"][source["source_id"]] = extra
    for segment in storyboard.get("segments", []):
        sid = segment["segment_id"]
        extra = {k: v for k, v in segment.items() if k not in SEGMENT_FIELDS}
        if extra:
            result["segments"][sid] = extra
        for index, visual in enumerate(segment.get("visuals", [])):
            extra = {k: v for k, v in visual.items() if k not in VISUAL_FIELDS}
            if extra:
                result["visuals"][f"{sid}/{index}"] = extra
    return result


def _identity(storyboard: dict, sha: str, previous: dict | None) -> dict:
    """Allocate once; legacy pointer maps cannot be guessed across visual edits."""
    old = previous or {}
    old_segments = old.get("segments", {})
    result = {"schema": "film-exchange-identity/1", "storyboard_sha256": sha, "segments": {},
              "tracks": old.get("tracks") or {name: uuid4().hex for name in ("video", "original", "narration")}}
    all_ids = set(result["tracks"].values())
    seen_segments = set()
    for segment in storyboard.get("segments", []):
        sid = segment.get("segment_id")
        if not isinstance(sid, str) or not sid or sid in seen_segments:
            raise ExchangeError("SEGMENT_ID_MISSING_OR_DUPLICATE")
        seen_segments.add(sid)
        visuals = segment.get("visuals", [])
        prior = old_segments.get(sid)
        legacy_same = prior and prior["visuals_sha256"] == digest(visuals)
        instances = []
        for i, visual in enumerate(visuals):
            explicit = visual.get("clip_instance_id")
            if explicit:
                instance = explicit
            elif legacy_same:
                instance = prior["visual_instances"][i]
            elif prior:
                raise ExchangeError("LEGACY_VISUAL_IDENTITY_AMBIGUOUS")
            else:
                instance = uuid4().hex
            if not isinstance(instance, str) or not instance or instance in all_ids:
                raise ExchangeError("INSTANCE_ID_MISSING_OR_DUPLICATE")
            all_ids.add(instance)
            instances.append(instance)
        audio_id = segment.get("audio_instance_id") or (prior or {}).get("audio_instance") or uuid4().hex
        if audio_id in all_ids:
            raise ExchangeError("INSTANCE_ID_MISSING_OR_DUPLICATE")
        all_ids.add(audio_id)
        result["segments"][sid] = {"visuals_sha256": digest(visuals), "visual_instances": instances,
                                    "audio_instance": audio_id}
    return result


def compile_cut_projection(storyboard: dict, *, storyboard_sha256: str, authority: dict,
                           profile: Mapping[str, Any], media_facts: Mapping[str, dict],
                           identity_map: dict | None = None, captions: Sequence[dict] = ()) -> dict:
    """Pure exact-cut projection. Media facts are caller-supplied, not probe evidence.

    Duration uses the existing film resolver; exact raw-decimal arithmetic is
    checked against it. Anything needing a new frame/sample quantization is
    rejected rather than silently extending evidence or inventing render time.
    """
    from .models import Storyboard
    from .subtitles import resolved_visual_spans, segment_output_duration

    canonical(storyboard)
    if not SHA.fullmatch(storyboard_sha256) or authority.get("storyboard_sha256") != storyboard_sha256:
        raise ExchangeError("AUTHORITY_BINDING_MISMATCH")
    if not authority.get("workspace_generation"):
        raise ExchangeError("GENERATION_BINDING_REQUIRED")
    model = Storyboard.model_validate(storyboard)
    profile = _profile(profile)
    fps = fraction(profile["fps"])
    issues = _unsupported(storyboard)
    if issues:
        raise ExchangeError("UNSUPPORTED_EDITABLE_CUTS", findings=issues)
    ids = _identity(storyboard, storyboard_sha256, identity_map)
    sources = {source["source_id"]: source for source in storyboard["sources"]}
    if len(sources) != len(storyboard["sources"]):
        raise ExchangeError("DUPLICATE_SOURCE_ID")
    resources = {}
    narration_ids = {f"narration:{s['segment_id']}" for s in storyboard["segments"]
                     if s["mode"] == "voiceover"}
    if narration_ids.intersection(sources):
        raise ExchangeError("RESOURCE_ID_NAMESPACE_COLLISION")
    for sid, source in sources.items():
        sha = source["fingerprint"]
        if not SHA.fullmatch(sha) or source.get("identity_schema", "sha256-full/2") != "sha256-full/2":
            raise ExchangeError("FULL_SOURCE_SHA256_REQUIRED")
        facts = media_facts.get(sid, {})
        if (facts.get("cfr") is not True or fraction(facts.get("fps", 0)) != fps
                or fraction(facts.get("start_time", 0)) != 0):
            raise ExchangeError("UNSUPPORTED_OR_UNKNOWN_VIDEO_CLOCK")
        if (source["width"] != profile["width"] or source["height"] != profile["height"]
                or facts.get("video_stream_index", 0) != 0
                or facts.get("width", source["width"]) != source["width"]
                or facts.get("height", source["height"]) != source["height"]):
            raise ExchangeError("UNSUPPORTED_GEOMETRY_OR_STREAM")
        resources[sid] = {"resource_id": sid, "sha256": sha, "source_path": source["path"],
                         "duration": rational(source["duration"]), "kind": "source",
                         "facts": deepcopy(facts)}
    tracks = {key: {"track_id": ids["tracks"][key], "role": key,
                   "kind": "Video" if key == "video" else "Audio", "clips": []}
              for key in ("video", "original", "narration")}
    cursor = Fraction(0)
    for raw, segment in zip(storyboard["segments"], model.segments):
        sid = segment.segment_id
        duration = (fraction(raw.get("audio_duration_sec") or raw["planned_duration_sec"])
                    if raw["mode"] == "voiceover" else sum(
                        (fraction(v["end"]) - fraction(v["start"]) for v in raw["visuals"]), Fraction(0)))
        if abs(float(duration) - segment_output_duration(segment)) > 1e-8:
            raise ExchangeError("FILM_DURATION_RESOLUTION_MISMATCH")
        _ticks(cursor, fps, "UNALIGNED_OUTPUT_FRAME")
        _ticks(duration, fps, "UNALIGNED_OUTPUT_FRAME")
        remaining, local = duration, Fraction(0)
        resolved = resolved_visual_spans(segment)
        consumed = []
        for i, visual in enumerate(raw["visuals"]):
            if remaining <= 0:
                break
            start, end = fraction(visual["start"]), fraction(visual["end"])
            length = min(end - start, remaining)
            resource = resources.get(visual["source_id"])
            if resource is None or start < 0 or length <= 0 or start + length > fraction(resource["duration"]):
                raise ExchangeError("INVALID_SOURCE_RANGE")
            if (resource["facts"].get("frame_count") is not None
                    and (start + length) * fps > resource["facts"]["frame_count"]):
                raise ExchangeError("SOURCE_RANGE_EXCEEDS_VERIFIED_FRAMES")
            _ticks(start, fps, "UNALIGNED_SOURCE_FRAME")
            _ticks(length, fps, "UNALIGNED_SOURCE_FRAME")
            iid = ids["segments"][sid]["visual_instances"][i]
            clip = {"instance_id": iid, "segment_id": sid, "visual_index": i,
                    "resource_id": visual["source_id"], "source_start": rational(start),
                    "duration": rational(length), "target_start": rational(cursor + local),
                    "lineage": deepcopy(visual.get("lineage", [])), "speed": rational(1)}
            tracks["video"]["clips"].append(clip)
            consumed.append((start, start + length))
            source = sources[visual["source_id"]]
            if (raw["mode"] == "original" or not raw.get("mute_original", True)) and source.get("has_audio", True):
                facts = resource["facts"]
                rate = facts.get("sample_rate")
                if (type(rate) is not int or rate <= 0 or facts.get("channels") not in (1, 2)
                        or facts.get("audio_stream_index", 0) != 0):
                    raise ExchangeError("UNKNOWN_OR_UNSUPPORTED_AUDIO_CLOCK")
                _ticks(start, rate, "UNALIGNED_AUDIO_SAMPLE")
                _ticks(length, rate, "UNALIGNED_AUDIO_SAMPLE")
                _ticks(cursor + local, rate, "UNALIGNED_AUDIO_SAMPLE")
                if (facts.get("duration_samples") is not None
                        and (start + length) * rate > facts["duration_samples"]):
                    raise ExchangeError("SOURCE_RANGE_EXCEEDS_VERIFIED_SAMPLES")
                audio = deepcopy(clip)
                audio.update(instance_id=f"original:{iid}", linked_video_instance=iid)
                tracks["original"]["clips"].append(audio)
            remaining -= length
            local += length
        if remaining != 0 or len(resolved) != len(consumed) or any(
                abs(float(start) - view.start) > 1e-8 or abs(float(end) - view.end) > 1e-8
                for (start, end), view in zip(consumed, resolved)):
            raise ExchangeError("FILM_VISUAL_RESOLUTION_MISMATCH")
        if raw["mode"] == "voiceover":
            rid = f"narration:{sid}"
            facts = media_facts.get(rid, {})
            rate = facts.get("sample_rate")
            if (not raw.get("audio_file") or type(rate) is not int or rate <= 0
                    or facts.get("channels") not in (1, 2) or facts.get("audio_stream_index", 0) != 0
                    or not SHA.fullmatch(facts.get("sha256", ""))):
                raise ExchangeError("NARRATION_MEDIA_BINDING_REQUIRED")
            count = _ticks(duration, rate, "UNALIGNED_AUDIO_SAMPLE")
            _ticks(cursor, rate, "UNALIGNED_AUDIO_SAMPLE")
            if facts.get("duration_samples") != count:
                raise ExchangeError("NARRATION_DURATION_MISMATCH")
            resources[rid] = {"resource_id": rid, "sha256": facts["sha256"],
                "source_path": raw["audio_file"], "duration": rational(duration),
                "kind": "narration", "facts": deepcopy(facts)}
            tracks["narration"]["clips"].append({"instance_id": ids["segments"][sid]["audio_instance"],
                "segment_id": sid, "resource_id": rid, "source_start": rational(0),
                "duration": rational(duration), "target_start": rational(cursor), "speed": rational(1),
                "lineage": []})
        cursor += duration
    exported_ids = [c["instance_id"] for t in tracks.values() for c in t["clips"]]
    if len(set(exported_ids)) != len(exported_ids):
        raise ExchangeError("INSTANCE_ID_MISSING_OR_DUPLICATE")
    if cursor <= 0:
        raise ExchangeError("EMPTY_TIMELINE")
    caption_ids = set()
    cap = []
    for cue in captions:
        cid = cue.get("caption_id")
        start, end = fraction(cue["start"]), fraction(cue["end"])
        if (not isinstance(cid, str) or not cid or cid in caption_ids or start < 0
                or end <= start or end > cursor or not isinstance(cue.get("text"), str)):
            raise ExchangeError("INVALID_CAPTION")
        caption_ids.add(cid)
        cap.append({**deepcopy(cue), "start": rational(start), "end": rational(end)})
    opaque = _opaque(storyboard)
    losses = [_finding("timeline", "profile", "metadata_only",
                       "set and verify host project dimensions and fps explicitly"),
              _finding("timeline", "render_processing", "unsupported",
                       "cut skeleton only; local fades, mix/normalization, layout and subtitle styling are not reproduced"),
              _finding("timeline", "media_facts", "unknown",
                       "caller-declared clocks/streams; physical media verification is a separate check"),
              _finding("timeline", "host_audio_routing", "unknown",
                       "verify that Video tracks do not also play source audio; explicit Audio tracks are authoritative in this package")]
    if not cap:
        losses.append(_finding("timeline", "captions", "unknown",
            "no explicit caption map supplied; empty SRT is not proof that film subtitles were exported"))
    if opaque["root"] or opaque["segments"] or opaque["visuals"] or opaque["sources"] or opaque["output"]:
        losses.append(_finding("storyboard", "opaque_extensions", "unknown",
                               "preserved in original bytes and opaque sidecar; never executed or reapplied"))
    if resources and all(r["facts"].get("verification", {}).get("method") == "ffprobe-full-frames/1"
                         for r in resources.values()):
        losses = [f for f in losses if f["field"] != "media_facts"]
    return {"schema": PROJECTION_SCHEMA, "producer": PRODUCER, "authority": deepcopy(authority),
            "name": storyboard["project_name"], "profile": profile, "duration": rational(cursor),
            "tracks": list(tracks.values()), "resources": resources, "captions": cap,
            "identity_map": ids, "opaque": opaque, "losses": losses}


def _rt(seconds: Any, rate: Any) -> dict:
    ticks = _ticks(seconds, rate, "UNREPRESENTABLE_OTIO_TIME")
    return {"OTIO_SCHEMA": "RationalTime.1", "value": ticks, "rate": float(fraction(rate))}


def _range(start: Any, duration: Any, rate: Any) -> dict:
    return {"OTIO_SCHEMA": "TimeRange.1", "start_time": _rt(start, rate),
            "duration": _rt(duration, rate)}


def serialize_otio(projection: dict, export_id: str) -> dict:
    """Serialize the fixed Timeline.1/Stack.1/Track.1/Clip.1/Gap.1 subset."""
    fps = fraction(projection["profile"]["fps"])
    tracks = []
    for track in projection["tracks"]:
        children = []
        cursor = Fraction(0)
        for clip in track["clips"]:
            start = fraction(clip["target_start"])
            duration = fraction(clip["duration"])
            resource = projection["resources"][clip["resource_id"]]
            rate = fps if track["kind"] == "Video" else resource["facts"]["sample_rate"]
            if start < cursor or duration <= 0:
                raise ExchangeError("OVERLAPPING_OR_EMPTY_TRACK_CLIP")
            if start > cursor:
                # Audio gaps retain their own sample clock, rather than rounding to video frames.
                children.append({"OTIO_SCHEMA": "Gap.1", "name": "gap", "metadata": {},
                    "source_range": _range(0, start - cursor, rate),
                    "effects": [], "markers": [], "enabled": True})
            children.append({"OTIO_SCHEMA": "Clip.1", "name": clip["instance_id"],
                "metadata": {"recap": {"export_id": export_id, **deepcopy(clip),
                                        "resource_sha256": resource["sha256"]}},
                "source_range": _range(clip["source_start"], duration, rate),
                "media_reference": {"OTIO_SCHEMA": "ExternalReference.1", "name": clip["resource_id"],
                    "metadata": {"recap": {"resource_id": clip["resource_id"], "sha256": resource["sha256"]}},
                    "target_url": safe_relative(resource["package_path"]),
                    "available_range": None, "available_image_bounds": None},
                "effects": [], "markers": [], "enabled": True})
            cursor = start + duration
        if children:
            tracks.append({"OTIO_SCHEMA": "Track.1", "name": track["role"], "kind": track["kind"],
                "metadata": {"recap": {"track_id": track["track_id"], "role": track["role"]}},
                "children": children, "source_range": None, "effects": [], "markers": [], "enabled": True})
    return {"OTIO_SCHEMA": "Timeline.1", "name": projection["name"],
        "metadata": {"recap": {"export_id": export_id, "producer": PRODUCER,
            "profile": projection["profile"], "authority": projection["authority"],
            "identity_warning": "metadata persistence has not been host-tested"}},
        "global_start_time": _rt(0, fps),
        "tracks": {"OTIO_SCHEMA": "Stack.1", "name": "tracks", "metadata": {},
            "children": tracks, "source_range": None, "effects": [], "markers": [], "enabled": True}}


def _srt_time(milliseconds: int) -> str:
    seconds, ms = divmod(milliseconds, 1000)
    minutes, sec = divmod(seconds, 60)
    hours, minute = divmod(minutes, 60)
    return f"{hours:02}:{minute:02}:{sec:02},{ms:03}"


def _round_ms(seconds: Any) -> int:
    value = fraction(seconds) * 1000
    return (2 * value.numerator + value.denominator) // (2 * value.denominator)


def _captions(projection: dict) -> tuple[bytes, list[dict]]:
    text, mapping = [], []
    for i, cue in enumerate(projection["captions"], 1):
        start, end = _round_ms(cue["start"]), _round_ms(cue["end"])
        if end <= start or "\n\n" in cue["text"] or "\r" in cue["text"] or "-->" in cue["text"]:
            raise ExchangeError("CAPTION_NOT_REPRESENTABLE_AS_SRT")
        text.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{cue['text']}\n")
        mapping.append({**cue, "srt_index": i, "srt_start_ms": start, "srt_end_ms": end,
                        "rounding_policy": "nearest-ms-half-up/1"})
        if fraction(cue["start"]) != Fraction(start, 1000) or fraction(cue["end"]) != Fraction(end, 1000):
            projection["losses"].append(_finding(cue["caption_id"], "caption_time", "quantized",
                "original rational seconds retained in caption map; SRT rounds nearest-ms-half-up",
                interval={"start": cue["start"], "end": cue["end"]}))
    return ("\n".join(text)).encode("utf-8"), mapping


def verify_package(package_dir: str | Path) -> dict:
    root = _no_links(Path(package_dir))
    manifest = _json(read_stable(root / "checksums.json")[0])
    if manifest.get("schema") != SCHEMA or manifest.get("completion_state") != "COMPLETE":
        raise ExchangeError("INCOMPLETE_EXPORT_PACKAGE")
    expected = set(manifest["files"]) | {"checksums.json"}
    actual = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ExchangeError("SYMLINK_REJECTED")
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise ExchangeError("PACKAGE_MEMBER_SET_CHANGED")
    for relative, row in manifest["files"].items():
        path = root / safe_relative(relative)
        if path.stat().st_size != row["bytes"] or workspace.sha(path) != row["sha256"]:
            raise ExchangeError("PACKAGE_MEMBER_HASH_MISMATCH")
    return manifest


def export_frozen_storyboard(storyboard_bytes: bytes, destination: str | Path, *, authority: dict,
                             profile: Mapping[str, Any], media_facts: Mapping[str, dict],
                             base_dir: str | Path = ".", identity_map: dict | None = None,
                             captions: Sequence[dict] = (), reference_render: str | Path | None = None) -> dict:
    """Create a new hash-sealed package. Failure never overwrites any destination.

    Failed private output is retained without a COMPLETE manifest for diagnosis.
    No hardlinks/symlinks are used, and source media is only read.
    """
    sha = hashlib.sha256(storyboard_bytes).hexdigest()
    projection = compile_cut_projection(_json(storyboard_bytes), storyboard_sha256=sha,
        authority=authority, profile=profile, media_facts=media_facts, identity_map=identity_map,
        captions=captions)
    destination = _no_links(Path(destination))
    if destination.exists():
        raise ExchangeError("EXPORT_TARGET_EXISTS")
    base_dir = _no_links(Path(base_dir))
    export_id = uuid4().hex
    # Reserve a new directory without ever replacing an existing empty directory.
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.mkdir(mode=0o700, exist_ok=False)
    try:
        copied = {}
        for resource in projection["resources"].values():
            source = Path(resource["source_path"])
            if not source.is_absolute():
                source = base_dir / source
            source = _no_links(source)
            suffix = source.suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                suffix = ".media"
            relative = f"media/{resource['sha256']}{suffix}"
            if relative not in copied:
                _copy_verified(source, destination / relative, resource["sha256"])
                copied[relative] = True
            else:
                if workspace.sha(source) != resource["sha256"]:
                    raise ExchangeError("SOURCE_BYTES_CHANGED")
            resource["package_path"] = relative
            resource["size_bytes"] = (destination / relative).stat().st_size
        srt, caption_map = _captions(projection)
        timeline = serialize_otio(projection, export_id)
        _write(destination / "timeline.otio", timeline)
        _write(destination / "captions.srt", srt, raw=True)
        _write(destination / "caption-map.json", {"schema": "film-caption-map/1", "captions": caption_map})
        _write(destination / "storyboard.snapshot.json", storyboard_bytes, raw=True)
        _write(destination / "identity-map.json", projection["identity_map"])
        _write(destination / "opaque.json", projection["opaque"])
        _write(destination / "media-manifest.json", {"copy_policy": "independent verified copies",
                                                      "resources": projection["resources"]})
        _write(destination / "projection.json", projection)
        if reference_render is not None:
            ref = Path(reference_render)
            if not ref.is_absolute():
                ref = base_dir / ref
            ref_sha = workspace.sha(_no_links(ref))
            _copy_verified(ref, destination / "reference" / ("render" + ref.suffix.lower()), ref_sha)
        capability = {"schema": SCHEMA, "profile": PROFILE, "mode": "editable-cuts",
            "evidence": {"serialized_subset": "VALIDATED", "official_otio_parser": "NOT_RUN",
                "host_import": "NOT_RUN", "saved_reopen": "NOT_RUN", "render_equivalence": "NOT_RUN",
                "reversible_readback": "NOT_RUN"},
            "host": None, "media_facts": "FFPROBE_FULL_FRAME_SCAN" if all(
                r["facts"].get("verification", {}).get("method") == "ffprobe-full-frames/1"
                for r in projection["resources"].values()) else "CALLER_DECLARED_NOT_PROBED",
            "supported": ["CFR same geometry/fps", "1x cut ranges", "explicit track gaps",
                "separate original/narration audio", "external SRT text and time"],
            "unsupported": ["retime", "VFR", "mixed fps", "nonzero source start",
                "effects", "transitions", "gain", "overlay", "native project profile enforcement"],
            "reference_render": "COPIED_NOT_VERIFIED" if reference_render else "NOT_PROVIDED",
            "active_host_write": False, "baked_segments": "NOT_IMPLEMENTED"}
        _write(destination / "capability-report.json", capability)
        _write(destination / "loss-report.json", {"schema": SCHEMA, "findings": projection["losses"]})
        binding = {"schema": SCHEMA, "producer": PRODUCER, "export_id": export_id,
            "authority": deepcopy(authority), "storyboard_sha256": sha,
            "source_bindings": {k: v["sha256"] for k, v in projection["resources"].items()},
            "projection_sha256": digest(projection), "identity_map_sha256": digest(projection["identity_map"]),
            "timeline_sha256": workspace.sha(destination / "timeline.otio"),
            "format_reference": "OpenTimelineIO v0.17.0 Clip.1 native JSON subset",
            "new_runtime_dependencies": [], "authoritative": False}
        _write(destination / "export-binding.json", binding)
        rows = {p.relative_to(destination).as_posix(): {"sha256": workspace.sha(p), "bytes": p.stat().st_size}
                for p in sorted(destination.rglob("*")) if p.is_file()}
        _write(destination / "checksums.json", {"schema": SCHEMA, "completion_state": "COMPLETE",
                                                "export_id": export_id, "files": rows})
        verify_package(destination)
        return {"schema": SCHEMA, "status": "EXPORTED_UNVERIFIED_HOST", "export_id": export_id,
                "package": str(destination), "binding": binding, "capability": capability}
    except Exception:
        # Retain evidence; absent COMPLETE manifest is never mistaken for an export.
        raise


def export_otio_package(work_dir: str | Path, destination: str | Path, *, profile: Mapping[str, Any],
                        media_facts: Mapping[str, dict] | None = None, captions: Sequence[dict] = (),
                        identity_map: dict | None = None, reference_render: str | Path | None = None) -> dict:
    """Freeze the existing workspace generation while holding its existing lock."""
    root, active = workspace.preflight(work_dir)
    if not (active / "state.json").is_file():
        raise ExchangeError("WORKSPACE_STATE_REQUIRED")
    with workspace.work_lock(root):
        _, current = workspace.preflight(work_dir)
        if current != active:
            raise ExchangeError("WORKSPACE_GENERATION_CHANGED")
        storyboard_bytes, sha = read_stable(active / "09_storyboard.json")
        manifest_bytes, manifest_sha = read_stable(active / "00_source_manifest.json")
        storyboard, manifest = _json(storyboard_bytes), _json(manifest_bytes)
        if media_facts is None:
            media_facts = collect_media_facts(storyboard, base_dir=active)
        expected = {s["source_id"]: s["fingerprint"] for s in manifest["sources"]}
        observed = {s["source_id"]: s["fingerprint"] for s in storyboard["sources"]}
        if (expected != observed or len(expected) != len(manifest["sources"])
                or len(observed) != len(storyboard["sources"])):
            raise ExchangeError("SOURCE_MANIFEST_BINDING_MISMATCH")
        authority = {"kind": "film-storyboard", "workspace_generation": str(active.relative_to(root)),
            "generation_marker_sha256": workspace.sha(active / workspace.GENERATION)
                if (active / workspace.GENERATION).exists() else None,
            "storyboard_sha256": sha, "source_manifest_sha256": manifest_sha}
        result = export_frozen_storyboard(storyboard_bytes, destination, authority=authority,
            profile=profile, media_facts=media_facts, base_dir=active, captions=captions,
            identity_map=identity_map, reference_render=reference_render)
        if (workspace.preflight(work_dir)[1] != active
                or workspace.sha(active / "09_storyboard.json") != sha
                or workspace.sha(active / "00_source_manifest.json") != manifest_sha
                or ((active / workspace.GENERATION).exists() and
                    workspace.sha(active / workspace.GENERATION) != authority["generation_marker_sha256"])):
            raise ExchangeError("WORKSPACE_CHANGED_EXPORT_IS_HISTORICAL_ONLY")
        return result


def collect_media_facts(storyboard: dict, *, base_dir: str | Path = ".", timeout: int = 300) -> dict:
    """Read all frame PTS/sample counts with installed ffprobe, without changing media.

    Conservative: exactly one video stream, at most one audio stream, zero
    start times, and every video PTS step exactly one frame. A header-only
    r_frame_rate/avg_frame_rate match does not establish CFR.
    """
    facts = {}
    base = _no_links(Path(base_dir))
    targets = [(s["source_id"], s["path"], s["fingerprint"], True) for s in storyboard["sources"]]
    targets += [(f"narration:{s['segment_id']}", s["audio_file"], None, False)
                for s in storyboard["segments"] if s["mode"] == "voiceover" and s.get("audio_file")]
    version = subprocess.run(["ffprobe", "-version"], check=True, capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=30).stdout.splitlines()[0]
    for rid, name, expected, video_required in targets:
        path = Path(name)
        if not path.is_absolute():
            path = base / path
        path = _no_links(path)
        before = workspace.sha(path)
        if expected is not None and before != expected:
            raise ExchangeError("SOURCE_BYTES_CHANGED")
        command = ["ffprobe", "-v", "error", "-show_streams", "-show_frames", "-show_entries",
            "stream=index,codec_type,width,height,r_frame_rate,avg_frame_rate,time_base,start_time,sample_rate,channels:"
            "frame=media_type,best_effort_timestamp,nb_samples", "-of", "json", str(path)]
        try:
            result = subprocess.run(command, check=True, capture_output=True, timeout=timeout)
        except (subprocess.SubprocessError, OSError) as exc:
            raise ExchangeError("MEDIA_CLOCK_PROBE_FAILED") from exc
        if workspace.sha(path) != before:
            raise ExchangeError("SOURCE_BYTES_CHANGED")
        data = _json(result.stdout)
        videos = [s for s in data["streams"] if s["codec_type"] == "video"]
        audios = [s for s in data["streams"] if s["codec_type"] == "audio"]
        if len(videos) != int(video_required) or len(audios) > 1 or (not video_required and len(audios) != 1):
            raise ExchangeError("UNSUPPORTED_MEDIA_STREAM_COUNT")
        row = {"sha256": before, "verification": {"method": "ffprobe-full-frames/1",
            "tool": version, "media_sha256": before, "probe_sha256": hashlib.sha256(result.stdout).hexdigest()}}
        if videos:
            stream = videos[0]
            rate = fraction(stream["r_frame_rate"])
            time_base = fraction(stream["time_base"])
            frames = [f for f in data["frames"] if f["media_type"] == "video"]
            pts = [f.get("best_effort_timestamp") for f in frames]
            if (not pts or any(type(p) is not int for p in pts) or rate <= 0 or pts[0] != 0
                    or fraction(stream.get("start_time", 0)) != 0
                    or fraction(stream["avg_frame_rate"]) != rate
                    or any((b - a) * time_base != 1 / rate for a, b in zip(pts, pts[1:]))):
                raise ExchangeError("UNSUPPORTED_OR_UNKNOWN_VIDEO_CLOCK")
            row.update(cfr=True, fps=rational(rate), start_time=0, video_stream_index=0,
                       width=stream["width"], height=stream["height"], frame_count=len(pts))
        if audios:
            stream = audios[0]
            if fraction(stream.get("start_time", 0)) != 0:
                raise ExchangeError("NONZERO_AUDIO_START_UNSUPPORTED")
            audio_frames = [f for f in data["frames"] if f["media_type"] == "audio"]
            if not audio_frames or any(type(f.get("nb_samples")) is not int for f in audio_frames):
                raise ExchangeError("UNKNOWN_AUDIO_SAMPLE_COUNT")
            row.update(sample_rate=int(stream["sample_rate"]), channels=int(stream["channels"]),
                       audio_stream_index=0, duration_samples=sum(f["nb_samples"] for f in audio_frames))
        facts[rid] = row
    return facts


def main(argv: list[str] | None = None) -> int:
    """Standalone opt-in entry, also usable by the shared CLI without coupling."""
    import argparse
    parser = argparse.ArgumentParser(description="Export a restricted, unverified-host OTIO cut package")
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--fps", required=True, help="Exact rate such as 30 or 30000/1001")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument("--captions-json", help="Explicit caption_id/start/end/text list; SRT sidecar only")
    args = parser.parse_args(argv)
    try:
        captions = _json(read_stable(args.captions_json)[0]) if args.captions_json else []
        result = export_otio_package(args.work_dir, args.output_dir,
            profile={"fps": args.fps, "width": args.width, "height": args.height}, captions=captions)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except (ExchangeError, workspace.WorkspaceError) as exc:
        print(json.dumps({"status": "BLOCKED", "reason": str(exc),
                          "losses": getattr(exc, "findings", [])}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
