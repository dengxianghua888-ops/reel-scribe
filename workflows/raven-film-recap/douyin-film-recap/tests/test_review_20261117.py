"""Regressions from the 2026-11-17 repository review.

The FFmpeg checks run real filtergraphs on synthetic lavfi input; they verify
that libass opens the files named by the escaped paths, not caption quality.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from douyin_film_recap.analysis import build_story
from douyin_film_recap.doctor import run_doctor
from douyin_film_recap.models import SceneAnalysisDocument, SceneIndex
from douyin_film_recap.render import _escape_subtitle_path

SPECIAL_DIRECTORIES = ["plain", "John's project", "a:b", "c,d", "e[f]", "g;h", "back\\slash",
                       "all a'b:c,d[e]f;g\\h%i=j k"]
SRT = "1\n00:00:00,000 --> 00:00:00,900\nHello\n\n"


def _has_subtitles_filter() -> bool:
    if not shutil.which("ffmpeg"):
        return False
    filters = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    return re.search(r"^\s*\S+\s+subtitles\s", filters, re.MULTILINE) is not None


def _font_file() -> Path | None:
    for pattern in ("*.ttf", "*.ttc", "*.otf"):
        for root in (Path("/usr/share/fonts"), Path("/System/Library/Fonts")):
            if root.is_dir():
                found = next(root.rglob(pattern), None)
                if found is not None:
                    return found
    return None


def test_apostrophe_is_escaped_outside_quotes():
    escaped = _escape_subtitle_path(Path("/tmp/John's project/sub.srt"))
    assert escaped.endswith("/John\\\\\\'s project/sub.srt")  # /tmp may resolve to /private/tmp.
    assert escaped.count("'") == 1  # Only the escaped literal; no quoting span is opened.


@pytest.mark.skipif(not _has_subtitles_filter(), reason="FFmpeg libass subtitles filter required")
@pytest.mark.parametrize("name", SPECIAL_DIRECTORIES)
def test_subtitles_filter_opens_paths_with_filtergraph_special_characters(tmp_path, name):
    directory = tmp_path / name
    directory.mkdir()
    subtitle = directory / "sub.srt"
    subtitle.write_text(SRT, encoding="utf-8")
    graph = f"subtitles=filename={_escape_subtitle_path(subtitle)}"
    font = _font_file()
    if font is not None:
        fonts_dir = tmp_path / ("fonts " + name)
        fonts_dir.mkdir()
        shutil.copyfile(font, fonts_dir / font.name)
        graph += f":fontsdir={_escape_subtitle_path(fonts_dir)}"
    completed = subprocess.run(
        ["ffmpeg", "-hide_banner", "-v", "verbose", "-f", "lavfi", "-i", "color=black:s=64x64:d=1",
         "-vf", graph, "-f", "null", "-"], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr[-2000:]
    if font is not None:
        assert f"Loading font file '{fonts_dir}" in completed.stderr


def test_configured_missing_story_context_is_not_silently_dropped(app_config, tmp_path):
    config = app_config.model_copy(deep=True)
    config.story.allow_external_context = True
    config.project.context_file = str(tmp_path / "missing-context.md")
    index = SceneIndex(units=[], source_fingerprints={}, detector="fixture")
    analysis = SceneAnalysisDocument(provider="fixture", model="fixture", items=[], unit_fingerprint="0")

    class Client:
        def chat_json(self, **request):
            raise AssertionError("no model request may be sent without the configured context")

    with pytest.raises(FileNotFoundError, match="story context file not found"):
        build_story(index, analysis, config, Client())


def test_doctor_requires_the_subtitles_filter_name_not_a_description(app_config, monkeypatch):
    import douyin_film_recap.doctor as doctor

    class Completed:
        stdout = (" ... drawtext          V->V       Draw text; not subtitles burn-in.\n"
                  " ... null              V->V       Pass the source unchanged.\n")

    monkeypatch.setattr(doctor, "run_command", lambda *args, **kwargs: Completed())
    monkeypatch.setattr(doctor.shutil, "which", lambda name: "/usr/bin/" + name)
    checks = {check.name: check for check in run_doctor(app_config)}
    assert checks["FFmpeg libass"].status == "FAIL"
