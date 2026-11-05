from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Iterable

from .config import AppConfig
from .models import (
    SourceManifest,
    TranscriptDocument,
    TranscriptSegment,
    TranscriptWord,
)
from .utils import SourceChangedDuringRead, clamp, content_identity

_TAG_RE = re.compile(r"<[^>]+>|\{\\[^}]+\}")
_TOKEN_RE = re.compile(r"[\u3400-\u9fff]|[A-Za-z0-9]+(?:[-_.'’][A-Za-z0-9]+)*|[^\s]")


def _clean_text(value: str) -> str:
    text = html.unescape(_TAG_RE.sub("", value))
    text = text.replace("\\N", " ").replace("\\n", " ")
    return re.sub(r"\s+", " ", text).strip()


def _parse_timestamp(value: str) -> float:
    text = value.strip().replace(",", ".")
    parts = text.split(":")
    if len(parts) == 3:
        hours, minutes, seconds = parts
    elif len(parts) == 2:
        hours = "0"
        minutes, seconds = parts
    else:
        raise ValueError(f"Invalid subtitle timestamp: {value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _distributed_words(text: str, start: float, end: float) -> list[TranscriptWord]:
    tokens = _TOKEN_RE.findall(text)
    if not tokens or end <= start:
        return []
    weights = [0.25 if re.fullmatch(r"[，。！？；：、,.!?;:]", token) else 1.0 for token in tokens]
    total_weight = sum(weights)
    cursor = start
    words: list[TranscriptWord] = []
    for index, (token, weight) in enumerate(zip(tokens, weights)):
        if index == len(tokens) - 1:
            token_end = end
        else:
            token_end = cursor + (end - start) * weight / total_weight
        token_end = max(cursor + 0.001, token_end)
        words.append(TranscriptWord(start=cursor, end=token_end, text=token, timing_source="estimated"))
        cursor = token_end
        total_weight -= weight
        start = cursor
    return words


def _read_subtitle_text(path: str | Path) -> str:
    """Accept UTF-8 only; reject undecodable or NUL-containing subtitle input."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"SUBTITLE_ENCODING_UNSUPPORTED: {path}; convert to UTF-8") from exc
    if "\x00" in text or "\ufffd" in text:
        raise ValueError(f"SUBTITLE_ENCODING_INVALID: {path}; convert to UTF-8")
    return text


def parse_srt_or_vtt(path: str | Path, source_id: str) -> list[TranscriptSegment]:
    text = _read_subtitle_text(path)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text)
    segments: list[TranscriptSegment] = []
    time_re = re.compile(
        r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})\s*-->\s*"
        r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}|\d{1,2}:\d{2}[,.]\d{1,3})"
    )
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        match_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if match_index is None:
            continue
        match = time_re.search(lines[match_index])
        if not match:
            continue
        start = _parse_timestamp(match.group("start"))
        end = _parse_timestamp(match.group("end"))
        content = _clean_text(" ".join(lines[match_index + 1 :]))
        if not content or end <= start:
            continue
        segments.append(
            TranscriptSegment(
                source_id=source_id,
                start=start,
                end=end,
                text=content,
                words=_distributed_words(content, start, end),
            )
        )
    return segments


def parse_ass(path: str | Path, source_id: str) -> list[TranscriptSegment]:
    lines = _read_subtitle_text(path).splitlines()
    fields: list[str] | None = None
    segments: list[TranscriptSegment] = []
    for raw in lines:
        line = raw.strip()
        if line.lower().startswith("format:"):
            fields = [item.strip().lower() for item in line.split(":", 1)[1].split(",")]
            continue
        if not line.lower().startswith("dialogue:"):
            continue
        payload = line.split(":", 1)[1].lstrip()
        field_count = len(fields) if fields else 10
        parts = payload.split(",", field_count - 1)
        if len(parts) < field_count:
            continue
        if fields:
            row = dict(zip(fields, parts))
            start_raw, end_raw, text_raw = row.get("start"), row.get("end"), row.get("text")
        else:
            start_raw, end_raw, text_raw = parts[1], parts[2], parts[-1]
        if not start_raw or not end_raw or text_raw is None:
            continue
        start = _parse_timestamp(start_raw)
        end = _parse_timestamp(end_raw)
        content = _clean_text(text_raw)
        if not content or end <= start:
            continue
        segments.append(
            TranscriptSegment(
                source_id=source_id,
                start=start,
                end=end,
                text=content,
                words=_distributed_words(content, start, end),
            )
        )
    return segments


def parse_subtitle(path: str | Path, source_id: str) -> list[TranscriptSegment]:
    suffix = Path(path).suffix.lower()
    if suffix in {".ass", ".ssa"}:
        return parse_ass(path, source_id)
    return parse_srt_or_vtt(path, source_id)


def _load_whisper_model(config: AppConfig):
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError(
            "faster-whisper is not installed. Install with pip install -e '.[local-asr]'"
        ) from exc

    return WhisperModel(
        config.asr.model,
        device=config.asr.device,
        compute_type=config.asr.compute_type,
    )


def transcribe_with_faster_whisper(
    video_path: str | Path,
    source_id: str,
    config: AppConfig,
    *, model=None,
) -> list[TranscriptSegment]:
    if model is None:
        model = _load_whisper_model(config)
    raw_segments, _ = model.transcribe(
        str(video_path),
        language=config.asr.language or None,
        beam_size=config.asr.beam_size,
        word_timestamps=config.asr.word_timestamps,
        vad_filter=True,
    )
    results: list[TranscriptSegment] = []
    for segment in raw_segments:
        text = _clean_text(segment.text)
        if not text or segment.end <= segment.start:
            continue
        words: list[TranscriptWord] = []
        for word in segment.words or []:
            token = _clean_text(word.word)
            if not token or word.end <= word.start:
                continue
            probability = getattr(word, "probability", None)
            words.append(
                TranscriptWord(
                    start=float(word.start),
                    end=float(word.end),
                    text=token,
                    probability=float(probability) if probability is not None else None,
                    timing_source="asr",
                )
            )
        results.append(
            TranscriptSegment(
                source_id=source_id,
                start=float(segment.start),
                end=float(segment.end),
                text=text,
                confidence=clamp(
                    float(getattr(segment, "avg_logprob", 0.0) + 1.0) / 2.0,
                    0.0,
                    1.0,
                ),
                words=words or _distributed_words(text, float(segment.start), float(segment.end)),
            )
        )
    return results


def build_transcript(manifest: SourceManifest, config: AppConfig) -> TranscriptDocument:
    segments: list[TranscriptSegment] = []
    providers: set[str] = set()
    models: set[str] = set()
    # Stage-local lazy ownership: subtitle-only runs load nothing; separate
    # stages/configurations cannot retain a stale model or GPU allocation.
    whisper_model = None
    alignment_files = config.asr.alignment.result_files if config.asr.alignment.enabled else {}
    unknown_sources = set(alignment_files) - {source.source_id for source in manifest.sources}
    if unknown_sources:
        raise ValueError(f"Unknown alignment source IDs: {sorted(unknown_sources)}")
    for source in manifest.sources:
        source_segments: list[TranscriptSegment] = []
        if source.subtitle_path:
            subtitle_identity = content_identity(source.subtitle_path)
            if (source.subtitle_fingerprint is not None
                    and subtitle_identity["sha256"] != source.subtitle_fingerprint) or (
                source.subtitle_size_bytes is not None
                    and subtitle_identity["bytes"] != source.subtitle_size_bytes
            ):
                raise SourceChangedDuringRead(
                    f"Subtitle identity changed since ingest for {source.source_id}"
                )
            source_segments = parse_subtitle(source.subtitle_path, source.source_id)
            if content_identity(source.subtitle_path) != subtitle_identity:
                raise SourceChangedDuringRead(
                    f"Subtitle changed while transcribing {source.source_id}"
                )
            if source_segments:
                providers.add("subtitle")
                if source.source_id in alignment_files:
                    from .alignment import import_alignment
                    source_segments = import_alignment(
                        alignment_files[source.source_id], source, source_segments)
        if source.source_id in alignment_files and not source_segments:
            raise ValueError("Alignment import requires non-empty existing subtitles")
        if not source_segments and source.has_audio:
            if config.asr.provider != "faster_whisper":
                raise NotImplementedError(
                    f"ASR provider is not implemented in the bundled runtime: {config.asr.provider}"
                )
            if whisper_model is None:
                whisper_model = _load_whisper_model(config)
            source_segments = transcribe_with_faster_whisper(
                source.path, source.source_id, config, model=whisper_model)
            providers.add("faster_whisper")
            models.add(config.asr.model)
        segments.extend(source_segments)
    order_map = {source.source_id: source.order for source in manifest.sources}
    segments.sort(key=lambda item: (order_map[item.source_id], item.start, item.end))
    provider = next(iter(providers)) if len(providers) == 1 else "mixed"
    return TranscriptDocument(
        language=config.asr.language,
        provider=provider or "none",
        model=",".join(sorted(models)) or None,
        segments=segments,
        source_fingerprints={source.source_id: source.fingerprint for source in manifest.sources},
    )


def segments_in_range(
    transcript: TranscriptDocument,
    source_id: str,
    start: float,
    end: float,
) -> list[TranscriptSegment]:
    return [
        segment
        for segment in transcript.segments
        if segment.source_id == source_id and min(end, segment.end) > max(start, segment.start)
    ]


def transcript_text_in_range(
    transcript: TranscriptDocument,
    source_id: str,
    start: float,
    end: float,
) -> str:
    return " ".join(
        segment.text for segment in segments_in_range(transcript, source_id, start, end)
    ).strip()


def nearest_segment_boundaries(
    transcript: TranscriptDocument,
    source_id: str,
    start: float,
    end: float,
    *,
    max_distance: float = 1.2,
) -> tuple[float, float, bool, bool]:
    source_segments = [
        segment for segment in transcript.segments if segment.source_id == source_id
    ]
    if not source_segments:
        return start, end, False, False
    starts = [segment.start for segment in source_segments]
    ends = [segment.end for segment in source_segments]
    entry = min(starts, key=lambda value: abs(value - start))
    exit_ = min(ends, key=lambda value: abs(value - end))
    entry_safe = abs(entry - start) <= max_distance
    exit_safe = abs(exit_ - end) <= max_distance
    return (
        entry if entry_safe else start,
        exit_ if exit_safe else end,
        entry_safe,
        exit_safe,
    )


def transcript_char_count(segments: Iterable[TranscriptSegment]) -> int:
    return sum(len(re.sub(r"\s+", "", segment.text)) for segment in segments)
