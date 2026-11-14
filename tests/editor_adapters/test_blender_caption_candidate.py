import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "caption_candidate", ROOT / "tools/editor-adapters/blender_caption_candidate.py"
)
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def row():
    return {"id": "a", "text": "Hello 世界", "start_frame": 0, "end_frame": 24,
            "declared_start_sec": 0, "declared_end_sec": 1,
            "start_delta_sec": 0, "end_delta_sec": 0}


def snap():
    return {"scene": {"volume": 1}, "strips": [
        {"name": "caption", "type": "TEXT", "custom": {"recap_caption_id": "a"},
         "text": "Hello 世界", "frame_final_start": 1, "frame_final_end": 25,
         "font": {"sha256": "fixed"}},
        {"name": "movie", "type": "MOVIE", "custom": {}, "gain": 1}]}


def test_identity_and_text_only():
    base = snap()
    assert m.compare(base, copy.deepcopy(base), [row()]) == []
    edited = copy.deepcopy(base)
    edited["strips"][0]["text"] = "你好世界"
    assert m.compare(base, edited, [row()]) == [
        {"id": "a", "before": "Hello 世界", "after": "你好世界"}]
    assert edited["strips"][0]["text"] == "你好世界"


@pytest.mark.parametrize("change", ["missing", "extra", "id", "time", "font", "video", "scene", "empty"])
def test_reject_non_text_changes(change):
    base, edited = snap(), snap()
    if change == "missing":
        edited["strips"].pop(0)
    elif change == "extra":
        edited["strips"].append(copy.deepcopy(edited["strips"][0]))
    elif change == "id":
        edited["strips"][0]["custom"]["recap_caption_id"] = "other"
    elif change == "time":
        edited["strips"][0]["frame_final_start"] += 1
    elif change == "font":
        edited["strips"][0]["font"]["sha256"] = "changed"
    elif change == "video":
        edited["strips"][1]["gain"] = .9
    elif change == "scene":
        edited["scene"]["volume"] = .9
    else:
        edited["strips"][0]["text"] = " \n"
    with pytest.raises(ValueError):
        m.compare(base, edited, [row()])


@pytest.mark.parametrize("value", ["", " \n", "a\x00b", "a\tb", "a\u202eb", "a\ud800b", "a\x7fb"])
def test_bad_text(value):
    with pytest.raises(ValueError):
        m.valid_text(value)


def test_map_and_half_up():
    r = row()
    assert m.validate_map({"rows": [r]}, 24, 24) == [r]
    r.update(declared_start_sec=.0625, start_frame=2, start_delta_sec=1/12-.0625)
    m.validate_map({"rows": [r]}, 24, 24)
    r["start_frame"] = 1
    with pytest.raises(ValueError, match="QUANTIZATION_MISMATCH"):
        m.validate_map({"rows": [r]}, 24, 24)


@pytest.mark.parametrize("change", ["duplicate", "reordered", "negative", "empty", "delta", "overflow", "bool"])
def test_bad_map(change):
    r = row()
    rows = [r]
    if change == "duplicate":
        rows.append(copy.deepcopy(r))
    elif change == "reordered":
        r2 = copy.deepcopy(r)
        r2["id"] = "b"
        rows += [r2]
    elif change == "negative":
        r["start_frame"] = -1
    elif change == "empty":
        rows = []
    elif change == "delta":
        r["end_delta_sec"] = .02
    elif change == "overflow":
        r["end_frame"] = 25
    else:
        r["start_frame"] = False
    with pytest.raises(ValueError):
        m.validate_map({"rows": rows}, 24, 24)


def test_duplicate_json_keys():
    with pytest.raises(ValueError, match="DUPLICATE_JSON_KEY"):
        json.loads('{"rows":[],"rows":[]}', object_pairs_hook=m.unique)


def test_stale_asset(tmp_path):
    p = tmp_path / "font"
    p.write_bytes(b"first")
    state = {"font": {"resolved_path": str(p), "sha256": m.digest(p)}}
    m.verify_assets(state)
    p.write_bytes(b"changed")
    with pytest.raises(ValueError, match="ASSET_CHANGED_DURING_READ"):
        m.verify_assets(state)


def test_base_map_text_mismatch():
    r = row()
    r["text"] = "stale"
    with pytest.raises(ValueError, match="BASE_MAP_MISMATCH"):
        m.compare(snap(), snap(), [r])


@pytest.mark.parametrize("change", ["same", "changed", "extra", "missing"])
def test_pinned_inventory(change):
    state = {"media": {"path": "/source.mov", "sha256": "a" * 64}}
    manifest = {"/source.mov": "a" * 64}
    if change == "changed":
        manifest["/source.mov"] = "b" * 64
    elif change == "extra":
        manifest["/other.mov"] = "c" * 64
    elif change == "missing":
        manifest = {}
    if change == "same":
        m.validate_inventory(state, manifest)
    else:
        with pytest.raises(ValueError):
            m.validate_inventory(state, manifest)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), object()])
def test_serialization_failure_leaves_no_output(tmp_path, bad):
    target = tmp_path / "candidate.json"
    with pytest.raises((ValueError, TypeError)):
        m.write_candidate(target, {"nested": [bad]})
    assert not target.exists()


def test_candidate_write_is_exclusive(tmp_path):
    target = tmp_path / "candidate.json"
    m.write_candidate(target, {"text": "字幕"})
    assert json.loads(target.read_text()) == {"text": "字幕"}
    with pytest.raises(FileExistsError):
        m.write_candidate(target, {"text": "replacement"})
    assert json.loads(target.read_text()) == {"text": "字幕"}


def test_unencodable_custom_leaves_no_output(tmp_path):
    target = tmp_path / "candidate.json"
    with pytest.raises(UnicodeEncodeError):
        m.write_candidate(target, {"custom": {"invalid": "\ud800"}})
    assert not target.exists()
