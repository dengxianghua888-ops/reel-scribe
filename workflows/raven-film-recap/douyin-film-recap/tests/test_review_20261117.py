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


# --- JSON Schema prompt rendering and superseded send intents -------------

import json  # noqa: E402

import httpx  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from douyin_film_recap import send_guard as guard  # noqa: E402
from douyin_film_recap.providers import OpenAICompatibleClient  # noqa: E402

SCOPE = {"binding": "synthetic full identity", "stage": "story", "stage_inputs": "stable"}


class _Answer(BaseModel):
    number: int
    note: str | None = None


@pytest.fixture
def chat_provider(app_config, monkeypatch):
    monkeypatch.setenv("FILM_RECAP_BASE_URL", "https://synthetic.invalid/v1")
    monkeypatch.setenv("FILM_RECAP_API_KEY", "test-key-must-not-be-recorded")
    return OpenAICompatibleClient(app_config.models)


def _transport(monkeypatch, results):
    sent = []

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, endpoint, **kwargs):
            sent.append(json.loads(json.dumps(kwargs["json"])))
            result = results[len(sent) - 1]
            if isinstance(result, Exception):
                raise result
            return httpx.Response(200, json={"choices": [{"message": {"content": result}}]})

    monkeypatch.setattr("douyin_film_recap.providers.httpx.Client", FakeClient)
    return sent


def _logical_keys(root):
    return {guard.read(path)["logical_key"] for path in (root / ".remote-intents").glob("*.json")}


def test_schema_prompt_is_json_not_python_repr(tmp_path, chat_provider, monkeypatch):
    sent = _transport(monkeypatch, ['{"number": 1}'])
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        assert chat_provider.chat_json(system="s", prompt="p", model_type=_Answer,
                                       intent_key="role").number == 1
    prompt = sent[0]["messages"][1]["content"]
    rendered = prompt.split("\n", 3)[-1]
    assert json.loads(rendered) == _Answer.model_json_schema()
    assert "'properties'" not in prompt and "None" not in prompt
    assert _logical_keys(tmp_path) == {"role:schema-json:format-0"}


def test_unknown_send_under_former_key_blocks_its_replacement(tmp_path, chat_provider, monkeypatch):
    sent = _transport(monkeypatch, [httpx.ReadTimeout("synthetic: outcome unknown")])
    # Same logical request and key shape an earlier release produced for chat_json.
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        with pytest.raises(httpx.ReadTimeout):
            chat_provider.chat(system="s", prompt="old schema prompt", intent_key="role")
    for authorized in (True, False):
        with guard.send_session(tmp_path, SCOPE, authorized=authorized):
            with pytest.raises(guard.SendBlocked, match="SEND_OUTCOME_UNKNOWN: superseded intent"):
                chat_provider.chat_json(system="s", prompt="p", model_type=_Answer, intent_key="role")
    assert len(sent) == 1 and _logical_keys(tmp_path) == {"role:format-0"}


def test_succeeded_former_key_needs_fresh_authorization_not_payload_conflict(tmp_path, chat_provider,
                                                                              monkeypatch):
    sent = _transport(monkeypatch, ['{"number": 1}', '{"number": 2}'])
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        chat_provider.chat(system="s", prompt="old schema prompt", intent_key="role")
    with guard.send_session(tmp_path, SCOPE):
        with pytest.raises(guard.SendBlocked, match="REMOTE_AUTHORIZATION_REQUIRED"):
            chat_provider.chat_json(system="s", prompt="p", model_type=_Answer, intent_key="role")
    with guard.send_session(tmp_path, SCOPE, authorized=True):
        assert chat_provider.chat_json(system="s", prompt="p", model_type=_Answer,
                                       intent_key="role").number == 2
    assert len(sent) == 2
    assert _logical_keys(tmp_path) == {"role:format-0", "role:schema-json:format-0"}


# --- Story context consumed from the bound bytes ---------------------------

import hashlib  # noqa: E402

from douyin_film_recap.analysis import read_story_context  # noqa: E402
from douyin_film_recap.pipeline import FilmRecapPipeline  # noqa: E402
from douyin_film_recap.utils import content_identity  # noqa: E402


def _context_config(app_config, path):
    config = app_config.model_copy(deep=True)
    config.story.allow_external_context = True
    config.project.context_file = str(path)
    return config


def test_bound_story_context_must_match_recorded_identity(app_config, tmp_path):
    path = tmp_path / "context.md"
    path.write_text("角色背景：原稿", encoding="utf-8")
    config = _context_config(app_config, path)
    identity = content_identity(path)
    assert read_story_context(config, identity, bound=True) == "角色背景：原稿"
    path.write_text("角色背景：被替换", encoding="utf-8")
    with pytest.raises(ValueError, match="CONTEXT_BINDING_CHANGED"):
        read_story_context(config, identity, bound=True)
    with pytest.raises(ValueError, match="CONTEXT_BINDING_CHANGED"):
        read_story_context(config, None, bound=True)  # Absent when bound, present now.
    assert read_story_context(app_config, None, bound=True) == ""  # Context disabled.


def test_story_stage_passes_verified_context_without_reread(app_config, tmp_path, monkeypatch):
    path = tmp_path / "context.md"
    path.write_text("bound context", encoding="utf-8")
    pipeline = FilmRecapPipeline.__new__(FilmRecapPipeline)
    pipeline.config = _context_config(app_config, path)
    pipeline.binding = {"context_identity": content_identity(path)}
    pipeline.work_dir = tmp_path
    pipeline._client = object()
    monkeypatch.setattr(pipeline, "_scene_index", lambda: "index", raising=False)
    monkeypatch.setattr(pipeline, "_scene_analysis", lambda: "analysis", raising=False)
    captured = {}

    def fake_build_story(index, analysis, config, client, *, context=None):
        captured["context"] = context
        raise RuntimeError("stop after capture")

    monkeypatch.setattr("douyin_film_recap.pipeline.build_story", fake_build_story)
    with pytest.raises(RuntimeError, match="stop after capture"):
        pipeline._stage_story()
    assert captured["context"] == "bound context"
    path.write_text("changed after binding", encoding="utf-8")
    with pytest.raises(ValueError, match="CONTEXT_BINDING_CHANGED"):
        pipeline._stage_story()
    assert hashlib.sha256(b"bound context").hexdigest() == pipeline.binding["context_identity"]["sha256"]


def test_build_story_uses_supplied_context_and_does_not_read_the_file(app_config, tmp_path):
    config = _context_config(app_config, tmp_path / "absent.md")
    index = SceneIndex(units=[], source_fingerprints={}, detector="fixture")
    analysis = SceneAnalysisDocument(provider="fixture", model="fixture", items=[], unit_fingerprint="0")
    prompts = []

    class Client:
        def chat_json(self, **request):
            prompts.append(request["prompt"])
            raise RuntimeError("stop before validation")

    with pytest.raises(RuntimeError, match="stop before validation"):
        build_story(index, analysis, config, Client(), context="verified context text")
    assert "verified context text" in prompts[0]


# --- Rational render frame rates -------------------------------------------

from fractions import Fraction  # noqa: E402

from douyin_film_recap.config import RenderConfig  # noqa: E402


@pytest.mark.parametrize("value,stored,rational", [
    (30, 30, Fraction(30)), ("30", 30, Fraction(30)), (24.0, 24, Fraction(24)),
    ("30000/1001", "30000/1001", Fraction(30000, 1001)), ("60000/2002", "30000/1001", Fraction(30000, 1001)),
    ("50/2", 25, Fraction(25)),
])
def test_render_fps_accepts_integers_and_exact_rationals(value, stored, rational):
    config = RenderConfig(fps=value)
    assert config.fps == stored and config.fps_rational == rational


@pytest.mark.parametrize("value", [0, -1, 29.97, True, "1/0", "0/1", "29.97", "abc", None])
def test_render_fps_rejects_inexact_or_nonpositive_rates(value):
    with pytest.raises(ValueError):
        RenderConfig(fps=value)


def test_integer_fps_keeps_existing_config_fingerprint_shape(app_config):
    assert app_config.render.model_dump(mode="json")["fps"] == 24
