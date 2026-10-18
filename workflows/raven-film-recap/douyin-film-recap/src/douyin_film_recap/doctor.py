from __future__ import annotations

import importlib.util
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import AppConfig
from .providers import OpenAICompatibleClient
from .tts import prepare_edge_tts
from .utils import run_command


@dataclass
class DoctorCheck:
    name: str
    status: str
    detail: str
    critical: bool = False


def _binary_check(name: str, critical: bool = True) -> DoctorCheck:
    path = shutil.which(name)
    return DoctorCheck(
        name=name,
        status="PASS" if path else "FAIL",
        detail=path or "not found on PATH",
        critical=critical and not bool(path),
    )


def run_doctor(config: AppConfig, config_path: Path | None = None) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    checks.append(
        DoctorCheck(
            name="Python",
            status="PASS" if sys.version_info >= (3, 11) else "FAIL",
            detail=sys.version.split()[0],
            critical=sys.version_info < (3, 11),
        )
    )
    checks.extend([_binary_check("ffmpeg"), _binary_check("ffprobe")])

    if shutil.which("ffmpeg"):
        try:
            output = run_command(["ffmpeg", "-hide_banner", "-filters"], timeout=30).stdout
            has_subtitles = bool(
                " subtitles " in output or " ass " in output or "subtitles" in output
            )
            checks.append(
                DoctorCheck(
                    name="FFmpeg libass",
                    status="PASS" if has_subtitles else "FAIL",
                    detail="subtitles/ass filter available"
                    if has_subtitles
                    else "missing subtitles/ass filter",
                    critical=config.render.subtitle_burn_in and not has_subtitles,
                )
            )
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    name="FFmpeg filters",
                    status="FAIL",
                    detail=str(exc),
                    critical=config.render.subtitle_burn_in,
                )
            )

    asr_available = importlib.util.find_spec("faster_whisper") is not None
    checks.append(
        DoctorCheck(
            name="Local ASR",
            status="PASS" if asr_available else "WARN",
            detail="faster-whisper installed"
            if asr_available
            else "not installed; sidecar subtitles can still work",
            critical=False,
        )
    )
    try:
        prepare_edge_tts(text="doctor", voice=config.tts.voice, rate=config.tts.rate,
                         pitch=config.tts.pitch, volume=config.tts.volume)
        tts_available, tts_detail = True, "edge-tts WordBoundary API and settings validated (offline)"
    except Exception as exc:
        tts_available, tts_detail = False, str(exc)
    checks.append(
        DoctorCheck(
            name="TTS",
            status="PASS" if tts_available else "FAIL",
            detail=tts_detail,
            critical=config.tts.provider == "edge_tts" and not tts_available,
        )
    )

    placeholders = {
        "your-llm-model",
        "your-vlm-model",
        "",
    }
    model_ok = (
        config.models.llm_model not in placeholders
        and config.models.vlm_model not in placeholders
    )
    checks.append(
        DoctorCheck(
            name="Model names",
            status="PASS" if model_ok else "FAIL",
            detail=f"LLM={config.models.llm_model}; VLM={config.models.vlm_model}",
            critical=not model_ok,
        )
    )

    try:
        client = OpenAICompatibleClient(config.models)
        ok, detail = client.healthcheck()
        checks.append(
            DoctorCheck(
                name="Model provider",
                status="PASS" if ok else "FAIL",
                detail=detail,
                critical=not ok,
            )
        )
    except Exception as exc:
        checks.append(
            DoctorCheck(
                name="Model provider",
                status="FAIL",
                detail=str(exc),
                critical=True,
            )
        )

    if config.project.publish_mode == "publish" and not config.project.rights_confirmed:
        checks.append(
            DoctorCheck(
                name="Rights confirmation",
                status="FAIL",
                detail="publish mode requires project.rights_confirmed=true",
                critical=True,
            )
        )
    else:
        checks.append(
            DoctorCheck(
                name="Rights confirmation",
                status="PASS" if config.project.rights_confirmed else "WARN",
                detail="confirmed"
                if config.project.rights_confirmed
                else "draft mode only; publishing rights not confirmed",
                critical=False,
            )
        )

    try:
        base = config_path.parent if config_path else Path.cwd()
        with tempfile.NamedTemporaryFile(dir=base, prefix=".film-recap-write-test-", delete=True):
            pass
        checks.append(
            DoctorCheck("Output directory", "PASS", str(base.resolve()), critical=False)
        )
    except Exception as exc:
        checks.append(
            DoctorCheck("Output directory", "FAIL", str(exc), critical=True)
        )

    return checks
