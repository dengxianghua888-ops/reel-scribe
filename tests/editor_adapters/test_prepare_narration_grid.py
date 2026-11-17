import importlib.util
import json
import wave
from fractions import Fraction
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "grid",
    Path(__file__).resolve().parents[2]
    / "tools/editor-adapters/prepare_narration_grid.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize(
    "fps,rates,expected",
    [
        (24, [22050], 2),
        (24, [48000], 8),
        (25, [44100], 25),
        (30, [22050, 48000], 10),
        (24, [22050, 48000], 2),
    ],
)
def test_grid(fps, rates, expected):
    assert m.common_grid(fps, rates) == expected


@pytest.mark.parametrize(
    "count,rate,grid,target",
    [
        (226972, 22050, 2, 231525),
        (346182, 22050, 2, 352800),
        (24000, 48000, 8, 24000),
        (24001, 48000, 8, 30000),
    ],
)
def test_exact_append_only_grid(count, rate, grid, target):
    assert m.padded_count(count, rate, grid, 500) == target
    assert Fraction(target, rate) * grid == int(Fraction(target, rate) * grid)


@pytest.mark.parametrize(
    "fps,rates", [(23.976, [48000]), (0, [48000]), (24, []), (24, [0]), (True, [48000])]
)
def test_grid_rejects(fps, rates):
    with pytest.raises(ValueError):
        m.common_grid(fps, rates)


def fixture(tmp_path, *, budget=2, declared=None, speed=1):
    w = tmp_path / "original.wav"
    pcm = (b"\1\0\xff\xff") * 11026
    with wave.open(str(w), "wb") as a:
        a.setnchannels(1)
        a.setsampwidth(2)
        a.setframerate(22050)
        a.writeframes(pcm)
    sb = {
        "segments": [
            {
                "segment_id": "v",
                "mode": "voiceover",
                "audio_file": str(w),
                "audio_duration_sec": declared or len(pcm) / 2 / 22050,
                "audio_speed": speed,
                "mute_original": True,
                "visuals": [{"start": 0, "end": budget}],
                "notes": "test",
                "text": "不能删除。",
                "tts_word_boundaries": [
                    {"text": "不能删除。", "start": 0, "duration": 1}
                ],
            }
        ],
        "output": {},
    }
    p = tmp_path / "09.json"
    p.write_text(json.dumps(sb))
    return p, w, pcm


def test_real_pcm_prefix_candidate_and_captions_retained(tmp_path):
    p, w, pcm = fixture(tmp_path)
    old = p.read_bytes()
    oldwav = w.read_bytes()
    r = m.prepare(
        p, tmp_path / "out", fps=24, max_padding_ms=500, acknowledge_padding=True
    )
    new = json.loads((tmp_path / "out/candidate-storyboard.json").read_text())
    assert p.read_bytes() == old and w.read_bytes() == oldwav and not r["adopted"]
    assert (
        new["segments"][0]["text"] == "不能删除。"
        and new["segments"][0]["tts_word_boundaries"]
        == json.loads(old)["segments"][0]["tts_word_boundaries"]
    )
    with wave.open(new["segments"][0]["audio_file"]) as a:
        data = a.readframes(a.getnframes())
        assert data.startswith(pcm) and not any(data[len(pcm) :])
    assert r["plan_revalidation_required"]


@pytest.mark.parametrize(
    "options,limit,code",
    [
        ({"budget": 1.125}, 500, "VISUAL_BUDGET"),
        ({}, 0, "PADDING_LIMIT"),
        ({"declared": 1}, 500, "DURATION_MISMATCH"),
        ({"speed": 1.1}, 500, "1X_NARRATION"),
    ],
)
def test_failures_before_destination(tmp_path, options, limit, code):
    p, _w, _pcm = fixture(tmp_path, **options)
    with pytest.raises(ValueError, match=code):
        m.prepare(
            p, tmp_path / "out", fps=24, max_padding_ms=limit, acknowledge_padding=True
        )
    assert not (tmp_path / "out").exists()


def test_explicit_ack_required(tmp_path):
    with pytest.raises(ValueError, match="ACK_REQUIRED"):
        m.prepare("missing", tmp_path / "out", fps=24, max_padding_ms=500)


def test_existing_output_preserved(tmp_path):
    p, _, _ = fixture(tmp_path)
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        m.prepare(p, tmp_path, fps=24, max_padding_ms=500, acknowledge_padding=True)


@pytest.mark.parametrize(
    "visuals,code",
    [
        ([], "EMPTY_VISUALS"),
        ([{"start": 2, "end": 1}], "INVALID_VISUAL_RANGE"),
        ([{"start": 0.01, "end": 2}], "UNALIGNED_VISUAL_BOUNDARY"),
    ],
)
def test_invalid_visuals_fail_early(tmp_path, visuals, code):
    p, _, _ = fixture(tmp_path)
    data = json.loads(p.read_text())
    data["segments"][0]["visuals"] = visuals
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match=code):
        m.prepare(
            p, tmp_path / "out", fps=24, max_padding_ms=500, acknowledge_padding=True
        )
    assert not (tmp_path / "out").exists()
