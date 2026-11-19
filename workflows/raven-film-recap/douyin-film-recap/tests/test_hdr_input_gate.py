"""HDR / wide-gamut sources are refused before ingest and before rendering.

Fixtures are real zscale HLG/PQ encodings of a synthetic SDR test pattern, not
camera footage. Measured on such charts, the previous passthrough produced
8-bit video still tagged BT.2020 HLG/PQ that SDR decoding showed about 13 L*
darker with roughly half the chroma. These tests check the refusal only.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from douyin_film_recap.media import build_manifest, hdr_signal
from douyin_film_recap.models import OriginalCue, SourceInfo, Storyboard, StoryboardSegment, VisualReference
from douyin_film_recap.render import render_storyboard

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg required")


def _clip(directory: Path, transfer: str | None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    out = directory / f"{transfer or 'sdr'}.mp4"
    source = ("testsrc2=size=160x90:rate=24:duration=2,format=yuv420p,"
              "setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv")
    args = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source]
    if transfer:
        args += ["-vf", f"zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=2020:t={transfer}:m=2020_ncl:r=tv,"
                       "format=yuv420p10le", "-color_primaries", "bt2020", "-color_trc", transfer,
                 "-colorspace", "bt2020nc", "-color_range", "tv"]
    else:
        args += ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv"]
    subprocess.run([*args, "-c:v", "libx264", "-preset", "ultrafast", str(out)], check=True, timeout=120)
    return out


@pytest.mark.parametrize("stream,expected", [
    ({"color_transfer": "bt709", "color_primaries": "bt709"}, None),
    ({}, None),
    ({"color_transfer": "arib-std-b67", "color_primaries": "bt2020"}, "color_transfer=arib-std-b67, color_primaries=bt2020"),
    ({"color_transfer": "smpte2084"}, "color_transfer=smpte2084"),
    ({"color_transfer": "bt709", "color_primaries": "bt2020"}, "color_primaries=bt2020"),
])
def test_hdr_signal_classification(stream, expected):
    assert hdr_signal(stream) == expected


@pytest.mark.parametrize("transfer", ["arib-std-b67", "smpte2084"])
def test_ingest_refuses_hdr_sources_before_any_model_stage(tmp_path, app_config, transfer):
    source = _clip(tmp_path / "input", transfer)
    with pytest.raises(ValueError, match="SOURCE_HDR_INPUT_UNSUPPORTED"):
        build_manifest(source, app_config, tmp_path / "work")


def test_ingest_accepts_sdr_source(tmp_path, app_config):
    manifest = build_manifest(_clip(tmp_path / "input", None), app_config, tmp_path / "work")
    assert manifest.sources[0].width == 160


def test_render_refuses_hdr_source_from_existing_storyboard(tmp_path, app_config):
    source = _clip(tmp_path / "input", "arib-std-b67")
    info = SourceInfo(source_id="s1", path=str(source), fingerprint="synthetic-fixture",
                      filename=source.name, duration=2, width=160, height=90, fps=24)
    board = Storyboard(project_name="hdr-gate", sources=[info], plan_fingerprint="fixture", target_duration_sec=1,
                       segments=[StoryboardSegment(
                           segment_id="orig", beat_id="b1", mode="original", title="t", text="x", text_raw="x",
                           audio_owner="original_dialogue", original_cues_verified=True,
                           original_cues=[OriginalCue(source_id="s1", start=0.2, end=0.8, text="x")],
                           visuals=[VisualReference(source_id="s1", start=0, end=1)],
                           planned_duration_sec=1, notes="synthetic HDR gate fixture")])
    with pytest.raises(ValueError, match="SOURCE_HDR_INPUT_UNSUPPORTED"):
        render_storyboard(board, app_config, tmp_path / "render")
    assert not list((tmp_path / "render").rglob("*.mp4"))
