import importlib.util
from fractions import Fraction
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "flattened",
    Path(__file__).resolve().parents[2]
    / "tools/editor-adapters/flattened_review_export.py",
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


@pytest.mark.parametrize(
    "frames,target", [(1, 3), (2, 3), (3, 3), (973, 975), (974, 975), (975, 975)]
)
def test_clock_is_explicit_append_only(frames, target):
    n, extra, duration = m.review_clock(frames, 24)
    assert n == target and n - frames == extra and 0 <= extra <= 2
    assert duration == Fraction(n, 24)


@pytest.mark.parametrize(
    "frames,rate",
    [(0, 24), (-1, 24), (True, 24), (1.5, 24), (10, 30), (10, Fraction(24000, 1001))],
)
def test_unsupported_clocks_rejected(frames, rate):
    with pytest.raises(ValueError):
        m.review_clock(frames, rate)


def test_no_implicit_lossy_export(tmp_path):
    with pytest.raises(ValueError, match="ACK_REQUIRED"):
        m.build("missing", "missing", tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_guard_not_assert():
    with pytest.raises(ValueError, match="MARKER"):
        m.require(False, "MARKER")


def test_pcm_prefix_and_silence():
    assert m.verify_pcm_prefix(
        b"\x01\x00\x02\x00", b"\x01\x00\x02\x00" + b"\0" * 8
    ) == {
        "source_decoded_samples": 1,
        "derivative_samples": 3,
        "appended_silent_samples": 2,
    }


@pytest.mark.parametrize(
    "original,derived,code",
    [
        (b"0", b"0", "ALIGNMENT"),
        (b"abcd", b"", "TRIMMED"),
        (b"abcd", b"xxxx", "CHANGED"),
        (b"abcd", b"abcdxxxx", "SILENCE"),
    ],
)
def test_pcm_fail_closed(original, derived, code):
    with pytest.raises(ValueError, match=code):
        m.verify_pcm_prefix(original, derived)


def build_inputs(tmp_path):
    import hashlib
    import json

    media = tmp_path / "input.mp4"
    media.write_bytes(b"fake-probed-separately")
    original = {"sources": [], "segments": [], "plan_fingerprint": "p"}
    rendered = dict(
        original,
        output={
            "final_video": str(media),
            "final_fingerprint": hashlib.sha256(media.read_bytes()).hexdigest(),
            "subtitle_burn_status": "applied",
        },
    )
    a = tmp_path / "source.json"
    b = tmp_path / "rendered.json"
    a.write_text(json.dumps(original))
    b.write_text(json.dumps(rendered))
    return a, b, rendered


def test_build_rejects_existing_destination(tmp_path):
    a, b, _ = build_inputs(tmp_path)
    with pytest.raises(ValueError, match="OUTPUT_EXISTS"):
        m.build(b, a, tmp_path, ack_lossy_review=True)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("plan_fingerprint", "other", "PLAN_MISMATCH"),
        ("sources", [{}], "SOURCE_MISMATCH"),
        ("segments", [{}], "SEGMENT_MISMATCH"),
    ],
)
def test_build_rejects_wrong_upstream(tmp_path, field, value, code):
    import json

    a, b, r = build_inputs(tmp_path)
    r[field] = value
    b.write_text(json.dumps(r))
    with pytest.raises(ValueError, match=code):
        m.build(b, a, tmp_path / "out", ack_lossy_review=True)


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("subtitle_burn_status", "skipped", "CAPTIONS_REQUIRED"),
        ("final_fingerprint", "0" * 64, "SHA_MISMATCH"),
    ],
)
def test_build_rejects_changed_render_or_missing_burn(tmp_path, field, value, code):
    import json

    a, b, r = build_inputs(tmp_path)
    r["output"][field] = value
    b.write_text(json.dumps(r))
    with pytest.raises(ValueError, match=code):
        m.build(b, a, tmp_path / "out", ack_lossy_review=True)


def test_decode_has_duration_and_wall_time_bounds(monkeypatch):
    def run(cmd, **kw):
        assert cmd[cmd.index("-t") + 1] == "181" and kw["timeout"] == 120
        return b""

    monkeypatch.setattr(m.subprocess, "check_output", run)
    assert m.decode_pcm("unused") == b""
