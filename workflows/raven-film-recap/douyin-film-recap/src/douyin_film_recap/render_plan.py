"""Pure dependency planning plus an explicit read-only input collection helper.

The plan is disposable evidence. Only the supplied Storyboard chooses content.
No cache hit, QC success, paid call, mutation or editorial adoption occurs here.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path
import shutil
import re
import sys
from typing import Any, Mapping

from .config import AppConfig
from .models import Storyboard
from .render_contracts import (PLAN_SCHEMA, PLANNER_REVISION, RENDERER_REVISION,
    ROUNDING_REVISION, RenderContractError, authority_payload, content_binding,
    digest, ratio, rational, validate_sha)
from .subtitles import build_cues, resolved_visual_spans
from .render_timeline import time_entry as _time_entry, realized_duration
from .utils import content_fingerprint, content_identity, run_command

# Field inventory is deliberately exhaustive; new fields require classification.
SEGMENT_FIELDS = {
    "segment_id": "reference", "beat_id": "review", "mode": "segment_av",
    "title": "review", "text": "cue_local", "text_raw": "review",
    "original_cues": "cue_local", "original_cues_verified": "review",
    "visuals": "segment_av+cue_local", "audio_owner": "review",
    "narration_job": "review", "mute_original": "segment_av:voiceover",
    "planned_duration_sec": "segment_av:voiceover-without-audio-duration",
    "audio_file": "locator:voice-bytes", "audio_source_duration_sec": "review",
    "audio_duration_sec": "segment_av:voiceover", "audio_speed": "segment_av:voiceover",
    "tts_word_boundaries": "cue_local", "highlight_id": "review",
    "hook_preposed": "review", "allow_reuse": "review", "notes": "review",
    "status": "not-consumed:execution", "rendered_file": "not-consumed:execution",
    "rendered_duration_sec": "not-consumed:container-duration",
}
RENDER_FIELDS = {
    **dict.fromkeys(("width", "height", "fps", "video_codec", "crf", "preset",
                    "audio_codec", "audio_bitrate", "layout"), "segment_av+finalize"),
    "blur_sigma": "segment_av:safe-fit-blur", "original_bed_db": "segment_av:voiceover-bed",
    **dict.fromkeys(("target_lufs", "true_peak_db", "subtitle_burn_in", "subtitle_font",
                    "subtitle_font_file", "subtitle_fonts_dir", "subtitle_font_size",
                    "subtitle_margin_v", "subtitle_outline"), "finalize"),
    "subtitle_max_chars_per_line": "cue_local", "subtitle_max_lines": "cue_local",
    "incremental_cache": "not-consumed:scheduling",
}


def _node(kind: str, node_id: str, params: dict, deps: list[dict], *, ready: bool,
          reasons: list[str] | None = None, toolchain: dict | None = None) -> dict:
    payload = {"schema": PLAN_SCHEMA, "kind": kind, "renderer_revision": RENDERER_REVISION,
               "params": params, "ordered_dependencies": deps, "toolchain": toolchain or {}}
    key = digest(payload)
    return {"node_id": node_id, "kind": kind, "semantic_key": key if ready else None,
            "provisional_key": None if ready else key, "key_state": "complete" if ready else "provisional",
            "params": params, "inputs": deps, "toolchain_digest": digest(toolchain or {}), "action": "build",
            "reason_codes": reasons or (["NOT_LOOKED_UP"] if ready else ["DEPENDENCY_UNREALIZED"])}




def compile_render_plan(
    storyboard: Storyboard, config: AppConfig, *,
    source_identities: Mapping[str, Mapping[str, Any]],
    audio_identities: Mapping[str, Mapping[str, Any]] | None = None,
    toolchain: Mapping[str, Any] | None = None,
    authority_sha256: str | None = None, workspace_generation: str | None = None,
    realized_artifacts: Mapping[str, Mapping[str, Any]] | None = None,
    previous_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile without I/O. Supplied identities must describe verified bytes.

    audio_identities is keyed by segment ID, realized_artifacts by segment node
    ID. Artifact entries bind semantic_key, sha256, size, media_contract and
    verification. Missing identities remain provisional, never cache-adoptable.
    """
    storyboard = Storyboard.model_validate(storyboard.model_dump(mode="json"))
    if not storyboard.segments:
        raise RenderContractError("EMPTY_STORYBOARD")
    fps = rational(config.render.fps)
    if fps <= 0:
        raise RenderContractError("INVALID_FPS")
    audio_identities = audio_identities or {}
    realized_artifacts = realized_artifacts or {}
    tc = dict(toolchain or {})
    tc_ready = tc.get("verified") is True and all(tc.get(k) for k in ("ffmpeg_sha256", "ffprobe_sha256", "version", "implementation_digest"))
    unknown = sorted(set(config.render.model_dump()) - set(RENDER_FIELDS))
    source_map = {s.source_id: s for s in storyboard.sources}
    if len(source_map) != len(storyboard.sources):
        raise RenderContractError("DUPLICATE_SOURCE_ID")
    nodes, expected, realized, intervals = [], [], [], []
    expected_cursor = realized_cursor = Fraction(0)
    all_realized = True
    source_bindings = {}
    segment_deps, cue_deps = [], []
    previous = {n["node_id"]: n for n in (previous_plan or {}).get("nodes", [])}
    for segment in storyboard.segments:
        sid = segment.segment_id
        unknown_segment = sorted(set(segment.model_dump()) - set(SEGMENT_FIELDS))
        local_sources = []
        spans = resolved_visual_spans(segment)
        if not spans or (segment.mode == "original" and len(spans) != 1):
            raise RenderContractError(f"INVALID_VISUAL_SPANS: {sid}")
        duration = (rational(segment.audio_duration_sec or segment.planned_duration_sec)
                    if segment.mode == "voiceover" else
                    sum((rational(v.end) - rational(v.start) for v in spans), Fraction(0)))
        if duration <= 0:
            raise RenderContractError(f"INVALID_SEGMENT_DURATION: {sid}")
        covered = sum((rational(v.end) - rational(v.start) for v in spans), Fraction(0))
        if covered + Fraction(1, 1000) < duration:
            raise RenderContractError(f"VISUALS_TOO_SHORT: {sid}")
        for visual in spans:
            if visual.source_id not in source_map or visual.source_id not in source_identities:
                raise RenderContractError(f"SOURCE_BINDING_MISSING: {visual.source_id}")
            source = source_map[visual.source_id]
            identity = content_binding(source_identities[visual.source_id])
            if source.fingerprint != identity["sha256"]:
                raise RenderContractError(f"SOURCE_BINDING_CHANGED: {visual.source_id}")
            if source.size_bytes is not None and source.size_bytes != identity["size"]:
                raise RenderContractError(f"SOURCE_SIZE_CHANGED: {visual.source_id}")
            if rational(visual.end) > rational(source.duration) + Fraction(1, 1000):
                raise RenderContractError(f"SOURCE_RANGE_EXCEEDED: {sid}")
            consume_audio = segment.mode == "original" or not segment.mute_original
            entry = {**identity, "video_stream": "0:v:0", "audio_stream":
                     "0:a:0" if consume_audio and source.has_audio else None,
                     "source_start": ratio(visual.start), "source_end": ratio(visual.end)}
            local_sources.append(entry)
            source_bindings[visual.source_id] = {"source_id": visual.source_id, **identity}
            intervals.append({"segment_id": sid, "source_id": visual.source_id,
                              "source_start": ratio(visual.start), "source_end": ratio(visual.end)})
        params = {name: getattr(config.render, name) for name in
                  ("width", "height", "fps", "video_codec", "crf", "preset", "audio_codec", "audio_bitrate", "layout")}
        params.update({"mode": segment.mode, "duration": ratio(duration), "sources": local_sources,
                       "audio_sample_rate": 48000, "channels": 2, "pixel_format": "yuv420p",
                       "fade_policy": "min(0.03,duration/4);millisecond-cli/1"})
        if config.render.layout not in {"center_crop", "fit_black"}:
            params["blur_sigma"] = config.render.blur_sigma
        deps = []
        ready = tc_ready and not unknown and not unknown_segment
        reasons = []
        if not tc_ready:
            reasons.append("TOOLCHAIN_UNVERIFIED")
        if unknown or unknown_segment:
            reasons.append("UNCLASSIFIED_PARAMETER")
        if segment.mode == "voiceover":
            params.update({"audio_speed": ratio(segment.audio_speed), "mute_original": segment.mute_original})
            if not segment.mute_original:
                params["original_bed_db"] = config.render.original_bed_db
            if sid in audio_identities:
                deps.append({"role": "voice_bytes", **content_binding(audio_identities[sid])})
            else:
                ready = False
                reasons.append("VOICE_IDENTITY_MISSING")
        node = _node("segment_av", f"segment_av:{sid}", params, deps, ready=ready, reasons=reasons, toolchain=tc)
        prior = previous.get(node["node_id"])
        if ready and prior and prior.get("semantic_key") == node["semantic_key"]:
            node.update(action="reuse_candidate", reason_codes=["KEY_UNCHANGED_REQUIRES_VERIFICATION"])
        elif prior and ready:
            node["reason_codes"] = ["LOCAL_DEPENDENCY_CHANGED"]
        node["segment_id"] = sid
        nodes.append(node)
        expected.append(_time_entry(sid, expected_cursor, duration, fps))
        expected_cursor += duration
        artifact = realized_artifacts.get(node["node_id"])
        dep = {"role": node["node_id"], "key": node["semantic_key"] or node["provisional_key"],
               "key_state": node["key_state"]}
        if artifact:
            if not ready or artifact.get("semantic_key") != node["semantic_key"]:
                raise RenderContractError(f"REALIZED_KEY_MISMATCH: {sid}")
            if not all(artifact.get("verification", {}).get(k) is True for k in
                       ("hash_checked", "probe_checked", "decode_checked")):
                raise RenderContractError(f"REALIZED_UNVERIFIED: {sid}")
            contract = dict(artifact.get("media_contract", {}))
            actual = realized_duration(segment, contract, fps, duration)
            realized.append(_time_entry(sid, realized_cursor, actual, fps))
            realized_cursor += actual
            if abs(realized_cursor - expected_cursor) > 1 / fps:
                raise RenderContractError(f"REALIZED_CUMULATIVE_DRIFT: {sid}")
            dep.update(content_binding(artifact))
            dep["media_contract"] = contract
        else:
            all_realized = False
        segment_deps.append(dep)
        local_board = storyboard.model_copy(update={"segments": [segment]})
        cues = [{"start": ratio(c.start), "end": ratio(c.end), "text": c.text}
                for c in build_cues(local_board, config)]
        cue = _node("cue_local", f"cue_local:{sid}", {"cues": cues, "implementation": "subtitles/1"}, [], ready=True)
        nodes.append(cue)
        cue_deps.append({"role": cue["node_id"], "key": cue["semantic_key"]})
    if all_realized:
        compatibility_fields = ("video_codec", "video_profile", "audio_codec", "audio_profile", "width", "height",
            "pix_fmt", "sar", "fps", "video_time_base", "audio_time_base", "sample_rate", "channel_layout",
            "color_primaries", "color_transfer", "color_space", "color_range")
        baseline = segment_deps[0]["media_contract"]
        for dependency in segment_deps[1:]:
            if any(dependency["media_contract"].get(field) != baseline.get(field) for field in compatibility_fields):
                raise RenderContractError("ASSEMBLY_MEDIA_CONTRACT_MISMATCH")
    assembly = _node("assembly", "assembly", {"concat_policy": "copy-or-reencode/1", "fps": ratio(fps),
                         "time_map": realized if all_realized else expected}, segment_deps, ready=all_realized,
                         toolchain=tc)
    nodes.append(assembly)
    placement = _node("cue_placement", "cue_placement", {"time_map": realized if all_realized else expected},
                      cue_deps, ready=all_realized)
    nodes.append(placement)
    # I1 always re-executes these stages. A plan cannot pre-bind unknown output bytes.
    final_params = {name: getattr(config.render, name) for name, role in RENDER_FIELDS.items()
                    if "finalize" in role}
    final = _node("finalize", "finalize", final_params,
                  [{"role": "assembly", "key": assembly["semantic_key"] or assembly["provisional_key"], "key_state": assembly["key_state"]},
                   {"role": "cue_placement", "key": placement["semantic_key"] or placement["provisional_key"], "key_state": placement["key_state"]}],
                  ready=False, reasons=["FINALIZE_ALWAYS_EXECUTED", "DEPENDENCY_BYTES_UNREALIZED"], toolchain=tc)
    if config.render.subtitle_burn_in:
        final["reason_codes"].append("FONT_RESOLUTION_REQUIRES_FINALIZE")
    nodes.append(final)
    for kind in ("preview", "technical_qc", "delivery_manifest"):
        nodes.append(_node(kind, kind, {}, [{"role": "finalize", "key": final["provisional_key"], "key_state": "provisional"}], ready=False,
                           reasons=["NEW_OUTPUT_REQUIRES_FULL_QC"] if kind == "technical_qc" else None))
    payload = authority_payload(storyboard)
    changes = []
    for node in nodes:
        old = previous.get(node["node_id"])
        if old is None:
            changes.append({"node_id": node["node_id"], "reason": "NEW_NODE"})
        elif (old.get("semantic_key"), old.get("provisional_key")) != (node["semantic_key"], node["provisional_key"]):
            changes.append({"node_id": node["node_id"], "reason": "DEPENDENCY_OR_PARAMETER_CHANGED"})
    current_ids = {node["node_id"] for node in nodes}
    changes.extend({"node_id": node_id, "reason": "REMOVED_NODE"} for node_id in previous if node_id not in current_ids)
    if previous_plan and previous_plan.get("review_binding", {}).get("sha256") != digest(payload):
        changes.append({"node_id": "review_binding", "reason": "AUTHORITY_CHANGED_REVIEW_REQUIRED"})
    return {"schema": PLAN_SCHEMA, "planner_revision": PLANNER_REVISION,
            "authority": {"kind": "storyboard", "document_sha256": validate_sha(authority_sha256) if authority_sha256 else digest(payload),
                          "workspace_generation": workspace_generation},
            "toolchain": tc, "source_bindings": list(source_bindings.values()), "nodes": nodes,
            "timeline": {"fps": ratio(fps), "audio_sample_rate": 48000,
                         "rounding_policy_revision": ROUNDING_REVISION,
                         "expected": expected, "realized": realized if all_realized else None,
                         "placement_state": "realized" if all_realized else "expected"},
            "source_intervals": intervals, "changes": changes,
            "review_binding": {"sha256": digest(payload), "must_recheck": ["pre_qc", "post_qc", "output_bound_review"]},
            "parameter_inventory": {"segment": SEGMENT_FIELDS, "render": RENDER_FIELDS,
                                    "unclassified_render": unknown},
            "limitations": ["derived_only", "no_verified_hits_in_dry_run", "whole_segment_av_only",
                            "full_finalize_and_qc_required", "no_real_media_validation_claim"]}


def collect_render_inputs(storyboard: Storyboard) -> dict[str, Any]:
    """Read-only helper for CLI/renderer; never invoked by the pure compiler."""
    def identify(path: str) -> dict[str, Any]:
        identity = content_identity(path)
        return {"sha256": identity["sha256"], "size": identity["bytes"]}
    sources = {source.source_id: identify(source.path) for source in storyboard.sources}
    audio = {segment.segment_id: identify(segment.audio_file)
             for segment in storyboard.segments if segment.mode == "voiceover" and segment.audio_file}
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    toolchain: dict[str, Any] = {"verified": False}
    if ffmpeg and ffprobe:
        toolchain = {"verified": True, "ffmpeg_sha256": content_fingerprint(ffmpeg),
                     "ffprobe_sha256": content_fingerprint(ffprobe),
                     "version": run_command([ffmpeg, "-version"]).stdout,
                     "implementation_digest": digest({name: content_fingerprint(Path(__file__).with_name(name))
                         for name in ("render.py", "render_plan.py", "render_contracts.py", "render_cache.py", "render_timeline.py", "subtitles.py", "alignment.py", "asr.py", "models.py")
                         if Path(__file__).with_name(name).exists()})}
        # Binary/version alone misses dynamically linked codec/filter changes.
        # Unresolved environments remain safe dry-run plans, never reusable keys.
        libraries = {}
        if sys.platform.startswith("linux") and shutil.which("ldd"):
            for binary in (ffmpeg, ffprobe):
                try:
                    linked = run_command(["ldd", binary]).stdout
                except RuntimeError:
                    toolchain["verified"] = False
                    continue
                if "not found" in linked:
                    toolchain["verified"] = False
                for line in linked.splitlines():
                    match = re.search(r"(?:=>\s+)?(/[^\s]+)\s+\(", line)
                    if match:
                        library = Path(match.group(1))
                        libraries[Path(binary).name + ":" + library.name] = identify(str(library))
            if not libraries:
                toolchain["verified"] = False
        else:
            toolchain["verified"] = False
        toolchain["linked_libraries"] = libraries
        toolchain["dependency_identity_scope"] = "linux-ldd-full-bytes/1" if libraries else "unverified"
    return {"source_identities": sources, "audio_identities": audio, "toolchain": toolchain}
