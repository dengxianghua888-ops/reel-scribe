from __future__ import annotations

import asyncio
import base64
import inspect
import re
import uuid
from pathlib import Path
from typing import Any

from .config import AppConfig
from .media import media_duration
from .models import Storyboard, StoryboardSegment
from .prompts import shorten_narration_prompt
from .providers import OpenAICompatibleClient
from .send_guard import check_active_send, guarded_async_send
from .utils import content_fingerprint, fingerprint_json, read_json, safe_slug, write_json


def _text_units(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]|[A-Za-z0-9]+", text))


def _clean_model_text(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^```(?:text)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {'"', "'"}:
        text = text[1:-1]
    return re.sub(r"\s+", " ", text).strip()


def shorten_text(
    segment: StoryboardSegment,
    target_chars: int,
    client: OpenAICompatibleClient,
    config: AppConfig,
    phase: str = "pre-fit",
) -> str:
    raw = client.chat(
        system="你是影视解说文案编辑，只做准确压缩。",
        prompt=shorten_narration_prompt(
            segment.text, target_chars, segment.narration_job
        ),
        temperature=config.models.temperature.get("creative", 0.45),
        max_tokens=1000,
        intent_key=f"tts:{segment.segment_id}:shorten:{phase}",
    )
    result = _clean_model_text(raw)
    if not result:
        raise ValueError(f"Narration rewrite returned empty text: {segment.segment_id}")
    return result


def prepare_edge_tts(*, text: str, voice: str, rate: str, pitch: str, volume: str):
    """Validate the installed API and inputs without opening a network stream."""
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts is not installed. Install with pip install -e '.[tts]'") from exc
    kwargs = dict(text=text, voice=voice, rate=rate, pitch=pitch, volume=volume,
                  boundary="WordBoundary")
    try:
        inspect.signature(edge_tts.Communicate).bind(**kwargs)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(
            "Incompatible edge-tts API: WordBoundary is required. "
            "Install the supported version with pip install -U -e '.[tts]'"
        ) from exc
    return edge_tts.Communicate(**kwargs)


async def _edge_tts_stream(
    *,
    text: str,
    output_path: Path,
    voice: str,
    rate: str,
    pitch: str,
    volume: str,
    intent_key: str | None = None,
) -> list[dict[str, Any]]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    boundaries: list[dict[str, Any]] = []
    communicate = None

    def prepare():
        nonlocal communicate
        communicate = prepare_edge_tts(
            text=text, voice=voice, rate=rate, pitch=pitch, volume=volume,
        )

    async def send():
        audio = bytearray()
        check_active_send()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio.extend(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                # edge-tts reports offset/duration in 100-nanosecond ticks.
                boundaries.append(
                    {
                        "text": chunk.get("text", ""),
                        "start": float(chunk.get("offset", 0)) / 10_000_000,
                        "duration": float(chunk.get("duration", 0)) / 10_000_000,
                    }
                )
        return {"audio_base64": base64.b64encode(audio).decode("ascii"), "boundaries": boundaries}

    result = await guarded_async_send("edge_tts", {"text": text, "voice": voice,
        "rate": rate, "pitch": pitch, "volume": volume, "boundary": "WordBoundary"}, send,
        intent_key=intent_key, prepare=prepare)
    with output_path.open("xb") as audio_handle:
        audio_handle.write(base64.b64decode(result["audio_base64"], validate=True))
    return result["boundaries"]


def synthesize_edge_tts(
    *,
    text: str,
    output_path: Path,
    config: AppConfig,
    intent_key: str | None = None,
) -> list[dict[str, Any]]:
    return asyncio.run(
        _edge_tts_stream(
            text=text,
            output_path=output_path,
            voice=config.tts.voice,
            rate=config.tts.rate,
            pitch=config.tts.pitch,
            volume=config.tts.volume,
            intent_key=intent_key,
        )
    )


def _generate_segment_audio(
    segment: StoryboardSegment,
    audio_dir: Path,
    config: AppConfig,
    phase: str = "initial",
) -> None:
    if config.tts.provider != "edge_tts":
        raise NotImplementedError(
            f"TTS provider is not implemented in the bundled runtime: {config.tts.provider}"
        )
    filename = f"{safe_slug(segment.segment_id)}.mp3"
    attempt = audio_dir / f"attempt-{uuid.uuid4().hex}"
    attempt.mkdir(parents=True, exist_ok=False)
    output = attempt / filename
    temporary = output.with_suffix(".partial.mp3")
    try:
        boundaries = synthesize_edge_tts(text=segment.text, output_path=temporary, config=config,
                                        intent_key=f"tts:{segment.segment_id}:audio:{phase}")
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RuntimeError(f"TTS produced no audio: {segment.segment_id}")
        duration = media_duration(temporary)
        if duration <= 0:
            raise RuntimeError(f"TTS produced invalid audio duration: {segment.segment_id}")
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    segment.audio_file = str(output)
    segment.audio_source_duration_sec = duration
    segment.audio_duration_sec = segment.audio_source_duration_sec
    segment.audio_speed = 1.0
    segment.tts_word_boundaries = boundaries
    segment.status = "audio_ready"


def _fit_audio_timing(
    segment: StoryboardSegment,
    *,
    desired_duration: float,
    min_speed: float,
    max_speed: float,
) -> None:
    raw_duration = float(segment.audio_source_duration_sec or segment.audio_duration_sec or 0.0)
    if raw_duration <= 0 or desired_duration <= 0:
        return
    required_speed = raw_duration / desired_duration
    if min_speed <= required_speed <= max_speed:
        segment.audio_speed = required_speed
        segment.audio_duration_sec = raw_duration / required_speed
        if abs(required_speed - 1.0) > 1e-4:
            for boundary in segment.tts_word_boundaries:
                boundary["start"] = float(boundary.get("start", 0.0)) / required_speed
                boundary["duration"] = float(boundary.get("duration", 0.0)) / required_speed
    else:
        segment.audio_speed = 1.0
        segment.audio_duration_sec = raw_duration


_CACHED_AUDIO_FIELDS = (
    "text", "planned_duration_sec", "audio_file", "audio_source_duration_sec",
    "audio_duration_sec", "audio_speed", "tts_word_boundaries", "status",
)


def _segment_cache_key(segment: StoryboardSegment, config: AppConfig) -> str:
    return fingerprint_json({
        "version": 1,
        "segment_id": segment.segment_id,
        "text": segment.text,
        "narration_job": segment.narration_job,
        "planned_duration_sec": segment.planned_duration_sec,
        "visuals": [visual.model_dump(mode="json") for visual in segment.visuals],
        "tts": config.tts.model_dump(mode="json"),
        "max_cps": config.format.vo_chars_per_sec[1],
        "rewrite_model": config.models.llm_model,
        "rewrite_temperature": config.models.temperature.get("creative", 0.45),
    })


def _restore_segment_cache(segment: StoryboardSegment, path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        data = read_json(path)
        audio = Path(data["segment"]["audio_file"])
        if not audio.is_file() or content_fingerprint(audio) != data["audio_fingerprint"]:
            return False
        validated = StoryboardSegment.model_validate({**segment.model_dump(mode="json"), **data["segment"]})
        for key in _CACHED_AUDIO_FIELDS:
            setattr(segment, key, getattr(validated, key))
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def synthesize_storyboard(
    storyboard: Storyboard,
    config: AppConfig,
    client: OpenAICompatibleClient,
    work_dir: Path,
) -> Storyboard:
    audio_dir = work_dir / "audio" / "voiceover"
    max_cps = config.format.vo_chars_per_sec[1]
    for segment in storyboard.segments:
        if segment.mode != "voiceover":
            continue
        request_key = _segment_cache_key(segment, config)
        metadata_path = audio_dir / "cache" / f"{request_key}.json"
        if config.runtime.cache and _restore_segment_cache(segment, metadata_path):
            continue
        segment_audio_dir = audio_dir / request_key
        planned_target = segment.planned_duration_sec
        visual_duration = sum(visual.end - visual.start for visual in segment.visuals)
        max_chars = max(8, int(planned_target * max_cps))
        if _text_units(segment.text) > max_chars:
            segment.text = shorten_text(segment, max_chars, client, config)
        _generate_segment_audio(segment, segment_audio_dir, config)
        assert segment.audio_source_duration_sec is not None
        if segment.audio_source_duration_sec > visual_duration + 0.15:
            ratio = visual_duration / max(segment.audio_source_duration_sec, 0.001)
            tighter_target = max(6, int(_text_units(segment.text) * ratio * 0.92))
            segment.text = shorten_text(segment, tighter_target, client, config, phase="post-fit")
            _generate_segment_audio(segment, segment_audio_dir, config, phase="post-fit")
        desired_duration = min(visual_duration, planned_target)
        _fit_audio_timing(
            segment,
            desired_duration=desired_duration,
            min_speed=config.tts.min_speedup,
            max_speed=config.tts.max_speedup,
        )
        if segment.audio_duration_sec:
            segment.planned_duration_sec = segment.audio_duration_sec
        if not segment.audio_file:
            raise RuntimeError(f"Missing generated TTS audio: {segment.segment_id}")
        cache_entry = {
            "request_fingerprint": request_key,
            "audio_fingerprint": content_fingerprint(segment.audio_file),
            "segment": {key: getattr(segment, key) for key in _CACHED_AUDIO_FIELDS},
        }
        write_json(metadata_path, cache_entry)
        # A successful rewrite changes text/duration. The saved storyboard should hit the same audio.
        final_key = _segment_cache_key(segment, config)
        if final_key != request_key:
            write_json(audio_dir / "cache" / f"{final_key}.json", cache_entry)
    return storyboard
