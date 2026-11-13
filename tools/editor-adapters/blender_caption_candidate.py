"""Blender 4.3.2 TEXT-only review candidate. Never writes a blend or adopts a plan."""
import argparse
import hashlib
import json
import math
import sys
import unicodedata
from fractions import Fraction
from pathlib import Path

PROFILE = "blender-4.3.2-caption-text-candidate-v1"


def require(ok, code):
    if not ok:
        raise ValueError(code)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def unique(pairs):
    out = {}
    for k, v in pairs:
        require(k not in out, "DUPLICATE_JSON_KEY")
        out[k] = v
    return out


def valid_text(text):
    require(isinstance(text, str) and text.strip() and len(text) <= 10000,
            "INVALID_TEXT")
    require(all(c == "\n" or not unicodedata.category(c).startswith("C")
                for c in text), "TEXT_CONTROL_CHARACTER")


def validate_map(data, fps, frame_end):
    rows = data["rows"]
    require(isinstance(rows, list) and 0 < len(rows) <= 1000, "CAPTION_LIMIT")
    ids, previous = set(), 0
    for r in rows:
        require(isinstance(r["id"], str) and r["id"] and r["id"] not in ids,
                "DUPLICATE_OR_INVALID_ID")
        ids.add(r["id"])
        valid_text(r["text"])
        a, b = r["start_frame"], r["end_frame"]
        require(type(a) is int and type(b) is int and previous <= a < b <= frame_end,
                "INVALID_CAPTION_WINDOW")
        previous = b
        for boundary, frame in (("start", a), ("end", b)):
            sec = Fraction(str(r[f"declared_{boundary}_sec"]))
            require(sec >= 0, "NEGATIVE_SOURCE_TIME")
            x = sec * fps
            rounded = (2 * x.numerator + x.denominator) // (2 * x.denominator)
            require(frame == rounded, "QUANTIZATION_MISMATCH")
            delta = Fraction(frame, fps) - sec
            require(abs(float(delta) - r[f"{boundary}_delta_sec"]) < 1e-9,
                    "QUANTIZATION_DELTA_MISMATCH")
    return rows


def scalars(obj, exclude=()):
    result = {}
    for p in obj.bl_rna.properties:
        if p.identifier in exclude or p.type in {"POINTER", "COLLECTION"}:
            continue
        v = getattr(obj, p.identifier)
        if getattr(p, "is_array", False):
            v = list(v)
        if isinstance(v, set):
            v = sorted(v)
        require(not isinstance(v, float) or math.isfinite(v), "NONFINITE_RNA")
        result[p.identifier] = v
    return result


def plain(obj, depth=0):
    """Nested non-ID RNA; reject unknown pointers rather than dropping them."""
    require(depth < 6, "RNA_DEPTH_LIMIT")
    result = scalars(obj)
    for p in obj.bl_rna.properties:
        k = p.identifier
        if k == "rna_type":
            continue
        v = getattr(obj, k)
        if p.type == "POINTER":
            require(v is None, "UNSUPPORTED_NESTED_POINTER:" + k)
            result[k] = None
        elif p.type == "COLLECTION":
            require(len(v) == 0, "UNSUPPORTED_NESTED_COLLECTION:" + k)
            result[k] = []
    return result


def asset(obj, bpy):
    require(obj is not None and not obj.packed_file and not obj.library
            and not obj.override_library and not obj.is_missing, "EXTERNAL_ASSET_REQUIRED")
    path = Path(bpy.path.abspath(obj.filepath)).resolve(strict=True)
    # ID runtime bookkeeping isn't a render property; data properties are retained.
    omitted = {"session_uid", "users", "tag", "is_evaluated", "is_runtime_data"}
    out = scalars(obj, omitted)
    for p in obj.bl_rna.properties:
        if p.type in {"POINTER", "COLLECTION"} and p.identifier not in {"rna_type", "original"}:
            v = getattr(obj, p.identifier)
            require(v is None or (p.type == "COLLECTION" and not len(v)),
                    "UNSUPPORTED_ASSET_POINTER:" + p.identifier)
    out["resolved_path"] = str(path)
    out["sha256"] = digest(path)
    return out


def image_settings(obj):
    out = scalars(obj)
    for p in obj.bl_rna.properties:
        k = p.identifier
        if k == "rna_type":
            continue
        v = getattr(obj, k)
        if p.type == "COLLECTION":
            require(not len(v), "IMAGE_COLLECTION_UNSUPPORTED")
        elif p.type == "POINTER":
            if k == "view_settings":
                require(not v.use_curve_mapping, "IMAGE_COLOR_CURVES_UNSUPPORTED")
                out[k] = scalars(v)
            elif k in {"stereo_3d_format", "display_settings", "linear_colorspace_settings"}:
                out[k] = plain(v) if v is not None else None
            else:
                require(v is None, "IMAGE_POINTER_UNSUPPORTED:" + k)
    return out


def verify_assets(value):
    if isinstance(value, dict):
        if "sha256" in value and ("resolved_path" in value or "path" in value):
            require(digest(value.get("resolved_path", value.get("path"))) == value["sha256"],
                    "ASSET_CHANGED_DURING_READ")
        for v in value.values():
            verify_assets(v)
    elif isinstance(value, list):
        for v in value:
            verify_assets(v)


def asset_inventory(value):
    result = {}
    def visit(v):
        if isinstance(v, dict):
            if "sha256" in v and ("resolved_path" in v or "path" in v):
                path = v.get("resolved_path", v.get("path"))
                require(path not in result or result[path] == v["sha256"], "ASSET_ID_CONFLICT")
                result[path] = v["sha256"]
            for x in v.values():
                visit(x)
        elif isinstance(v, list):
            for x in v:
                visit(x)
    visit(value)
    return result


def validate_inventory(snapshot_value, manifest):
    require(isinstance(manifest, dict) and manifest and all(
        isinstance(k, str) and isinstance(v, str) and len(v) == 64
        for k, v in manifest.items()), "INVALID_ASSET_MANIFEST")
    require(asset_inventory(snapshot_value) == manifest, "STALE_ASSET_INVENTORY")


def snapshot(bpy):
    require(tuple(bpy.app.version) == (4, 3, 2), "HOST_VERSION_UNSUPPORTED")
    s = bpy.context.scene
    require(not bpy.data.libraries, "LINKED_LIBRARY_UNSUPPORTED")
    require(not s.objects and not s.use_nodes and not s.animation_data,
            "SEQUENCER_ONLY_NO_ANIMATION")
    require(s.sequence_editor and s.render.use_sequencer, "SEQUENCER_REQUIRED")
    require(not s.render.use_motion_blur and not s.render.use_multiview,
            "COMPOSITOR_OR_MOTION_BLUR_UNSUPPORTED")
    require(not s.view_settings.use_curve_mapping, "COLOR_CURVES_UNSUPPORTED")
    strips = []
    for t in s.sequence_editor.sequences_all:
        require(t.type in {"MOVIE", "SOUND", "TEXT"}, "STRIP_TYPE_UNSUPPORTED")
        require(not getattr(t, "use_proxy", False), "PROXY_UNSUPPORTED")
        item = scalars(t)
        item["custom"] = dict(t.items())
        for p in t.bl_rna.properties:
            k = p.identifier
            if k == "rna_type":
                continue
            v = getattr(t, k)
            if p.type == "POINTER":
                if k in {"font", "sound"}:
                    item[k] = asset(v, bpy)
                elif k in {"transform", "crop", "proxy", "stereo_3d_format", "colorspace_settings"}:
                    item[k] = plain(v) if v is not None else None
                else:
                    require(v is None, "STRIP_POINTER_UNSUPPORTED:" + k)
                    item[k] = None
            elif p.type == "COLLECTION":
                if k == "elements":
                    require(len(v) <= 1000, "ELEMENT_LIMIT")
                    item[k] = [plain(x) for x in v]
                else:
                    require(len(v) == 0, "STRIP_COLLECTION_UNSUPPORTED:" + k)
                    item[k] = []
        if t.type == "MOVIE":
            path = Path(bpy.path.abspath(t.filepath)).resolve(strict=True)
            item["media"] = {"path": str(path), "sha256": digest(path)}
        strips.append(item)
    require(len(strips) <= 2000, "STRIP_LIMIT")
    require(len({t["name"] for t in strips}) == len(strips), "DUPLICATE_STRIP_NAME")
    return {
        "scene": scalars(s, {"frame_current", "frame_subframe", "frame_current_final", "session_uid", "users", "tag"}),
        "scene_custom": dict(s.items()),
        "render": scalars(s.render),
        "image": image_settings(s.render.image_settings),
        "ffmpeg": scalars(s.render.ffmpeg),
        "view": scalars(s.view_settings),
        "display": plain(s.display_settings),
        "sequencer_color": plain(s.sequencer_colorspace_settings),
        "sequencer": scalars(s.sequence_editor),
        "channels": [plain(c) for c in s.sequence_editor.channels],
        "strips": sorted(strips, key=lambda t: t["name"]),
    }


def compare(base, edited, rows):
    before = {t["custom"].get("recap_caption_id"): t for t in base["strips"] if t["type"] == "TEXT"}
    texts = [t for t in base["strips"] if t["type"] == "TEXT"]
    require(len(before) == len(texts) == len(rows) and set(before) == {r["id"] for r in rows},
            "CAPTION_ID_SET_MISMATCH")
    for r in rows:
        t = before[r["id"]]
        require(t["text"] == r["text"] and t["frame_final_start"] == r["start_frame"] + 1
                and t["frame_final_end"] == r["end_frame"] + 1, "BASE_MAP_MISMATCH")
    # Only text value can differ. Everything else serialized stays fixed.
    copy = json.loads(json.dumps(edited))
    changes = []
    for t in copy["strips"]:
        if t["type"] == "TEXT":
            identity = t["custom"].get("recap_caption_id")
            require(identity in before, "CAPTION_ID_SET_MISMATCH")
            valid_text(t["text"])
            if t["text"] != before[identity]["text"]:
                changes.append({"id": identity, "before": before[identity]["text"], "after": t["text"]})
            t["text"] = before[identity]["text"]
    require(base == copy, "NON_TEXT_STATE_CHANGED")
    return changes


def run(args):
    import bpy
    paths = [Path(args.base).resolve(strict=True), Path(args.edited).resolve(strict=True),
             Path(args.caption_map).resolve(strict=True), Path(args.assets_manifest).resolve(strict=True)]
    expected = [args.base_sha256, args.edited_sha256, args.map_sha256, args.assets_sha256]
    require(all(digest(p) == h for p, h in zip(paths, expected)), "STALE_INPUT")
    require(all(p.stat().st_size <= 10_000_000 for p in paths[2:]), "MAP_SIZE_LIMIT")
    data = json.loads(paths[2].read_text(), object_pairs_hook=unique)
    assets = json.loads(paths[3].read_text(), object_pairs_hook=unique)
    bpy.ops.wm.open_mainfile(filepath=str(paths[0]), use_scripts=False)
    base = snapshot(bpy)
    validate_inventory(base, assets)
    fps = base["render"]["fps"]
    require(base["render"]["fps_base"] == 1 and base["scene"]["frame_start"] == 1,
            "INTEGER_FPS_START_ONE_REQUIRED")
    rows = validate_map(data, fps, base["scene"]["frame_end"])
    bpy.ops.wm.open_mainfile(filepath=str(paths[1]), use_scripts=False)
    edited = snapshot(bpy)
    validate_inventory(edited, assets)
    changes = compare(base, edited, rows)
    verify_assets(base)
    verify_assets(edited)
    candidate_rows = json.loads(json.dumps(rows))
    replacements = {c["id"]: c["after"] for c in changes}
    for row in candidate_rows:
        row["text"] = replacements.get(row["id"], row["text"])
    require(all(digest(p) == h for p, h in zip(paths, expected)), "INPUT_CHANGED_DURING_READ")
    result = {"profile": PROFILE, "status": "REVIEW_CANDIDATE_ONLY", "adopted": False,
              "base_sha256": expected[0], "edited_sha256": expected[1], "map_sha256": expected[2], "assets_manifest_sha256": expected[3],
              "quantization": "nearest frame half-up; original seconds and deltas retained",
              "source_rows": rows, "candidate_rows": candidate_rows, "text_changes": changes,
              "limitations": ["Fixed timing/style, no automatic source-plan adoption", "Layout/readability not accepted; original trial has 4-5 lines and credit overlap", "Not full vertical composition or speech/semantic acceptance"],
              "base_snapshot": base, "edited_snapshot": edited}
    write_candidate(args.output, result)


def write_candidate(path, result):
    # Complete serialization before creating the output: rejected values leave no file.
    serialized = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    with Path(path).open("xb") as f:
        f.write(serialized)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "edited", "caption-map", "base-sha256", "edited-sha256", "map-sha256", "assets-manifest", "assets-sha256", "output"):
        p.add_argument("--" + name, required=True)
    run(p.parse_args(sys.argv[sys.argv.index("--") + 1:]))


if __name__ == "__main__":
    main()
