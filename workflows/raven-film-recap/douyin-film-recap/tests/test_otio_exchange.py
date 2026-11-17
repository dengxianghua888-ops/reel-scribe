import hashlib
import json
from pathlib import Path

import pytest

from douyin_film_recap import otio_exchange as x


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture
def exchange_fixture(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    sources = []
    facts = {}
    for i in (1, 2):
        path = work / f"source{i}.mp4"
        path.write_bytes(f"synthetic media {i}".encode())
        source = {"source_id": f"source{i}", "path": str(path), "filename": path.name,
            "fingerprint": hashlib.sha256(path.read_bytes()).hexdigest(),
            "duration": 10, "fps": 30, "width": 160, "height": 90, "has_audio": True}
        sources.append(source)
        facts[source["source_id"]] = {"cfr": True, "fps": "30/1", "start_time": 0,
            "sample_rate": 48000, "channels": 1, "video_stream_index": 0, "audio_stream_index": 0}
    voice = work / "voice.wav"
    voice.write_bytes(b"synthetic voice")
    facts["narration:s2"] = {"sample_rate": 48000, "channels": 1, "duration_samples": 96000,
                             "sha256": hashlib.sha256(voice.read_bytes()).hexdigest()}
    def segment(sid, source_id, mode="original"):
        return {"segment_id": sid, "beat_id": "b1", "mode": mode, "title": sid,
            "text": "同一句", "visuals": [{"source_id": source_id, "start": 1, "end": 3}],
            "audio_owner": "narration" if mode == "voiceover" else "action_sound",
            "planned_duration_sec": 2, "notes": "synthetic", "mute_original": True}
    story = {"schema_version": 1, "project_name": "交换测试", "sources": sources,
        "plan_fingerprint": "synthetic", "target_duration_sec": 6,
        "segments": [segment("s1", "source1"), segment("s2", "source2", "voiceover"),
                     segment("s3", "source1")]}
    story["segments"][1].update(audio_file=str(voice), audio_duration_sec=2)
    write(work / "09_storyboard.json", story)
    write(work / "00_source_manifest.json", {"schema_version": 2, "sources": sources})
    write(work / "state.json", {"schema_version": 2, "stages": {}})
    return work, story, facts, {"fps": "30/1", "width": 160, "height": 90}


def export(tmp_path, fixture, **kwargs):
    work, story, facts, profile = fixture
    return x.export_otio_package(work, tmp_path / "package", profile=profile, media_facts=facts,
        captions=[{"caption_id": "caption-independent", "start": 1, "end": 3,
                   "text": "跨切点字幕"}], **kwargs)


def test_x1_repeated_sources_audio_gap_captions_hashes_and_no_authority_write(tmp_path, exchange_fixture):
    work, story, _, _ = exchange_fixture
    before = {p.name: p.read_bytes() for p in work.iterdir()}
    result = export(tmp_path, exchange_fixture)
    package = Path(result["package"])
    assert result["status"] == "EXPORTED_UNVERIFIED_HOST"
    x.verify_package(package)
    for name, content in before.items():
        assert (work / name).read_bytes() == content
    otio = json.loads((package / "timeline.otio").read_bytes())
    tracks = otio["tracks"]["children"]
    video = next(t for t in tracks if t["kind"] == "Video")
    clips = video["children"]
    assert len(clips) == 3
    assert clips[0]["media_reference"]["target_url"] == clips[2]["media_reference"]["target_url"]
    assert clips[0]["metadata"]["recap"]["instance_id"] != clips[2]["metadata"]["recap"]["instance_id"]
    assert clips[0]["source_range"]["start_time"]["value"] == 30
    assert clips[0]["source_range"]["duration"]["value"] == 60
    voice = next(t for t in tracks if t["name"] == "narration")
    assert voice["children"][0]["OTIO_SCHEMA"] == "Gap.1"
    assert voice["children"][0]["source_range"]["duration"]["rate"] == 48000
    assert voice["children"][0]["source_range"]["duration"]["value"] == 96000
    assert "00:00:01,000 --> 00:00:03,000" in (package / "captions.srt").read_text()
    assert result["capability"]["evidence"]["saved_reopen"] == "NOT_RUN"
    assert not result["capability"]["active_host_write"]
    assert (package / "storyboard.snapshot.json").read_bytes() == before["09_storyboard.json"]
    with pytest.raises(x.ExchangeError, match="TARGET_EXISTS"):
        export(tmp_path, exchange_fixture)


def test_identity_map_is_stable_and_legacy_visual_edits_are_not_guessed(tmp_path, exchange_fixture):
    result = export(tmp_path, exchange_fixture)
    previous = json.loads((Path(result["package"]) / "identity-map.json").read_bytes())
    work, story, facts, profile = exchange_fixture
    story["segments"].reverse()
    write(work / "09_storyboard.json", story)
    again = x.export_otio_package(work, tmp_path / "again", profile=profile, media_facts=facts,
                                 identity_map=previous)
    current = json.loads((Path(again["package"]) / "identity-map.json").read_bytes())
    assert current["segments"] == previous["segments"]
    story["segments"][0]["visuals"][0]["end"] = 4
    write(work / "09_storyboard.json", story)
    with pytest.raises(x.ExchangeError, match="IDENTITY_AMBIGUOUS"):
        x.export_otio_package(work, tmp_path / "ambiguous", profile=profile, media_facts=facts,
                             identity_map=previous)
    assert not (tmp_path / "ambiguous").exists()


@pytest.mark.parametrize("mutation,code", [
    ("speed", "UNSUPPORTED_EDITABLE_CUTS"), ("overlay", "UNSUPPORTED_EDITABLE_CUTS"),
    ("vfr", "VIDEO_CLOCK"), ("mixed_fps", "VIDEO_CLOCK"), ("start_time", "VIDEO_CLOCK"),
    ("geometry", "GEOMETRY"), ("fractional", "UNALIGNED"),
    ("voice_duration", "NARRATION_DURATION"), ("source_sha", "SOURCE_MANIFEST"),
    ("source_bytes", "SOURCE_BYTES"), ("empty", "EMPTY_TIMELINE")])
def test_explicit_restricted_rejections(tmp_path, exchange_fixture, mutation, code):
    work, story, facts, _ = exchange_fixture
    if mutation == "speed": story["segments"][1]["audio_speed"] = 1.5
    if mutation == "overlay": story["segments"][0]["overlays"] = [{"opaque": True}]
    if mutation == "vfr": facts["source1"]["cfr"] = False
    if mutation == "mixed_fps": facts["source1"]["fps"] = "24000/1001"
    if mutation == "start_time": facts["source1"]["start_time"] = 10
    if mutation == "geometry": story["sources"][0]["height"] = 100
    if mutation == "fractional": story["segments"][0]["visuals"][0]["end"] = 3.001
    if mutation == "voice_duration": facts["narration:s2"]["duration_samples"] -= 1
    if mutation == "source_sha": story["sources"][0]["fingerprint"] = "0" * 64
    if mutation == "source_bytes": Path(story["sources"][0]["path"]).write_bytes(b"different")
    if mutation == "empty": story["segments"] = []
    write(work / "09_storyboard.json", story)
    with pytest.raises(x.ExchangeError, match=code):
        export(tmp_path, exchange_fixture)
    assert not (tmp_path / "package/checksums.json").exists()


def test_opaque_unknowns_preserved_and_never_claimed_exact(tmp_path, exchange_fixture):
    work, story, _, _ = exchange_fixture
    story["vendor_extension"] = {"future_filter": "unknown"}
    story["segments"][0]["host_private"] = {"anchor": 5}
    write(work / "09_storyboard.json", story)
    result = export(tmp_path, exchange_fixture)
    package = Path(result["package"])
    opaque = json.loads((package / "opaque.json").read_bytes())
    assert opaque["root"]["vendor_extension"] == story["vendor_extension"]
    loss = json.loads((package / "loss-report.json").read_bytes())["findings"]
    assert next(f for f in loss if f["field"] == "opaque_extensions")["fidelity"] == "unknown"


def test_path_escape_symlinks_and_package_tamper(tmp_path, exchange_fixture):
    result = export(tmp_path, exchange_fixture)
    package = Path(result["package"])
    with pytest.raises(x.ExchangeError, match="UNSAFE_PACKAGE_PATH"):
        x.safe_relative("../source.mp4")
    with pytest.raises(x.ExchangeError, match="UNSAFE_PACKAGE_PATH"):
        x.safe_relative("https://external.example/media.mp4")
    (package / "captions.srt").write_bytes(b"changed")
    with pytest.raises(x.ExchangeError, match="HASH_MISMATCH"):
        x.verify_package(package)
    alias = tmp_path / "alias"
    alias.symlink_to(tmp_path / "work", target_is_directory=True)
    with pytest.raises(x.ExchangeError, match="SYMLINK"):
        x.export_otio_package(exchange_fixture[0], alias / "new", profile=exchange_fixture[3],
                              media_facts=exchange_fixture[2])


def test_caption_rounding_sidecar_and_explicit_same_source_instances(tmp_path, exchange_fixture):
    work, story, facts, profile = exchange_fixture
    story["segments"][0]["visuals"][0]["clip_instance_id"] = "occurrence-a"
    story["segments"][2]["visuals"][0]["clip_instance_id"] = "occurrence-b"
    write(work / "09_storyboard.json", story)
    result = x.export_otio_package(work, tmp_path / "package", profile=profile, media_facts=facts,
        captions=[{"caption_id": "cue-a", "start": "1/30", "end": "2/30", "text": "中文"}])
    package = Path(result["package"])
    cap = json.loads((package / "caption-map.json").read_bytes())["captions"][0]
    assert cap["start"] == {"numerator": 1, "denominator": 30}
    assert cap["srt_start_ms"] == 33
    assert cap["srt_end_ms"] == 67
    loss = json.loads((package / "loss-report.json").read_bytes())["findings"]
    assert any(f["entity"] == "cue-a" and f["fidelity"] == "quantized" for f in loss)


def test_fractional_rate_exact_tick_roundtrip():
    assert x._rt("1001/30000", "30000/1001")["value"] == 1
    assert x.rational("30000/1001") == {"numerator": 30000, "denominator": 1001}
    with pytest.raises(x.ExchangeError, match="UNREPRESENTABLE"):
        x._rt(2, "30000/1001")


def test_json_duplicate_keys_and_nonfinite_are_rejected():
    with pytest.raises(x.ExchangeError, match="DUPLICATE"):
        x._json(b'{"a":1,"a":2}')
    with pytest.raises(x.ExchangeError, match="NONFINITE"):
        x._json(b'{"a":NaN}')
