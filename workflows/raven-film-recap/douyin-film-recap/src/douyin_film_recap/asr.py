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
from .utils import CONTENT_IDENTITY_SCHEMA, SourceChangedDuringRead, clamp, content_identity

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


def _decode_subtitle_bytes(data: bytes, path: str | Path) -> str:
    """Decode exactly the bytes whose identity is used by the importer."""
    try:
        text = data.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError(f"SUBTITLE_ENCODING_UNSUPPORTED: {path}; convert to UTF-8") from exc
    if "\x00" in text or "\ufffd" in text:
        raise ValueError(f"SUBTITLE_ENCODING_INVALID: {path}; convert to UTF-8")
    return text


def _read_subtitle_text(path: str | Path) -> str:
    return _decode_subtitle_bytes(Path(path).read_bytes(), path)


def _subtitle_rows(text: str, *, compatibility: bool = False, identifier_policy: str = "reject-ambiguous"):
    """Parse cue boundaries without silently dropping malformed timed input."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    is_vtt = text.lstrip().startswith("WEBVTT")
    fraction = r"[,.]\d{1,3}"
    if compatibility:
        fraction = "(?:" + fraction + ")?"
    stamp = r"(?:\d{2,}:)?\d{2}:\d{2}" + fraction
    timing = re.compile(r"^(" + stamp + r")\s+-->\s+(" + stamp + r")"
                        + (r"(?:\s+(?:vertical|line|position|size|align|region):\S+)*" if is_vtt else "") + r"$")
    warnings = []
    blocks = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if not lines:
            continue
        if is_vtt and lines[0].startswith("WEBVTT") and any("-->" in x for x in lines):
            raise ValueError("SUBTITLE_VTT_HEADER_BOUNDARY_INVALID")
        if is_vtt and (lines[0].startswith("WEBVTT") or
                       re.match(r"^NOTE(?:\s|$)", lines[0]) or lines[0] in {"STYLE", "REGION"}):
            continue
        blocks.append(lines)
    rows = []
    if compatibility:
        flat = [line for block in blocks for line in block]
        locations = [i for i, line in enumerate(flat) if "-->" in line]
        if not locations:
            return [], warnings
        # Compatibility is explicit and reports every stripped cue identifier.
        # Only numeric contiguous identifiers or no identifiers are accepted.
        identifiers = []
        for i in locations:
            if i and flat[i-1].isdigit():
                identifiers.append((i-1, int(flat[i-1])))
        values = [value for _, value in identifiers]
        if identifiers and identifier_policy != "sequential-numeric":
            raise ValueError("SUBTITLE_COMPAT_IDENTIFIER_POLICY_REQUIRED: numeric lines may be dialogue; explicitly choose sequential-numeric only after inspecting the source")
        if values and values != list(range(values[0], values[0]+len(values))):
            raise ValueError("SUBTITLE_COMPAT_AMBIGUOUS_IDENTIFIERS")
        ids = {index for index, _ in identifiers}
        if identifiers:
            warnings.append({"code": "NUMERIC_IDENTIFIERS_REMOVED", "values": values,
                             "policy": identifier_policy, "meaning": "Caller-declared numeric IDs; not automatically inferred dialogue semantics."})
        if locations[0] and any(i not in ids for i in range(locations[0])):
            raise ValueError("SUBTITLE_COMPAT_UNATTACHED_TEXT")
        for n, i in enumerate(locations):
            stop = locations[n+1] if n+1 < len(locations) else len(flat)
            rows.append((flat[i], [flat[j] for j in range(i+1, stop) if j not in ids]))
        warnings.append({"code": "EXPLICIT_COMPATIBILITY_REBLOCKING", "cue_count": len(rows),
                         "meaning": "Blank-line layout normalized; review inferred cue boundaries."})
    else:
        for lines in blocks:
            hits = [i for i, line in enumerate(lines) if "-->" in line]
            if not hits:
                raise ValueError("SUBTITLE_UNATTACHED_TEXT_BLOCK: use explicit compatibility import after reviewing source")
            if len(hits) != 1:
                raise ValueError("SUBTITLE_TIMING_AMBIGUOUS")
            i = hits[0]
            if i > 1 or (i == 1 and not (lines[0].isdigit() or is_vtt)):
                raise ValueError("SUBTITLE_CUE_PREFIX_INVALID")
            rows.append((lines[i], lines[i+1:]))
    parsed = []
    previous = -1.0
    for index, (line, contents) in enumerate(rows, 1):
        match = timing.fullmatch(line)
        if not match:
            raise ValueError(f"SUBTITLE_TIMING_INVALID: cue {index}: {line}")
        for value in match.groups():
            parts = value.replace(",", ".").split(":")
            if not (0 <= int(parts[-2]) < 60 and 0 <= float(parts[-1]) < 60):
                raise ValueError(f"SUBTITLE_TIMING_RANGE_INVALID: cue {index}")
        start, end = map(_parse_timestamp, match.groups())
        if end <= start or start < previous:
            raise ValueError(f"SUBTITLE_TIMING_ORDER_INVALID: cue {index}")
        content = _clean_text(" ".join(contents))
        if not content:
            raise ValueError(f"SUBTITLE_CUE_EMPTY: cue {index}")
        if compatibility and any(not re.search(r"[,.]\d+$", value) for value in match.groups()):
            warnings.append({"code": "WHOLE_SECONDS_NORMALIZED", "cue": index})
        parsed.append((start, end, content)); previous = start
    return parsed, warnings


def parse_srt_or_vtt(path: str | Path, source_id: str) -> list[TranscriptSegment]:
    rows, _ = _subtitle_rows(_read_subtitle_text(path))
    return [TranscriptSegment(source_id=source_id, start=start, end=end, text=content,
                              words=_distributed_words(content, start, end))
            for start, end, content in rows]


def canonicalize_subtitle(path: str | Path, output_path: str | Path, *,
                          identifier_policy: str = "reject-ambiguous") -> dict:
    """Explicit compatibility import to a new canonical SRT; never edit source.

    Returns provenance/warnings, not semantic or listening acceptance. Estimated
    boundaries in downstream transcript words remain explicitly estimated.
    """
    import hashlib
    import os
    import tempfile
    from .subtitles import SubtitleCue, write_srt
    from .qc import _parse_srt
    if identifier_policy not in {"reject-ambiguous", "sequential-numeric"}:
        raise ValueError("SUBTITLE_COMPAT_IDENTIFIER_POLICY_INVALID")
    source = Path(path)
    source_bytes = source.read_bytes()
    before = {"schema": CONTENT_IDENTITY_SCHEMA,
              "sha256": hashlib.sha256(source_bytes).hexdigest(), "bytes": len(source_bytes)}
    text = _decode_subtitle_bytes(source_bytes, source)
    try:
        rows, warnings = _subtitle_rows(text)
    except ValueError:
        rows, warnings = _subtitle_rows(text, compatibility=True, identifier_policy=identifier_policy)
    if not rows:
        raise ValueError("SUBTITLE_COMPAT_NO_CUES")
    if content_identity(source) != before:
        raise SourceChangedDuringRead("Subtitle changed during compatibility import")
    # Validate derived representation with the unchanged strict output QC first.
    with tempfile.TemporaryDirectory(prefix="canonical-subtitle-") as directory:
        temp = write_srt([SubtitleCue(a, b, text) for a, b, text in rows], Path(directory)/"canonical.srt")
        checked = _parse_srt(temp)
        if len(checked) != len(rows):
            raise ValueError("SUBTITLE_CANONICAL_CUE_COUNT_MISMATCH")
        canonical = temp.read_bytes()
    target = Path(output_path)
    if content_identity(source) != before:
        raise SourceChangedDuringRead("Subtitle changed before compatibility publication")
    # Publish only fully written bytes: an exclusive hard link is the commit
    # point. Never expose a partial canonical target or overwrite an old one.
    receipt = {"schema": "subtitle-compat-import/1", "source": {"path": str(source), **before},
               "canonical": {"path": str(target), "sha256": hashlib.sha256(canonical).hexdigest(),
                             "bytes": len(canonical)}, "cue_count": len(rows), "warnings": warnings,
               "identifier_policy": identifier_policy, "strict_output_qc": "PASS",
               "listening_review": "NOT_RUN", "translation_review": "NOT_RUN"}
    descriptor, staging_name = tempfile.mkstemp(prefix=".subtitle-import-", suffix=".pending", dir=target.parent)
    staging = Path(staging_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(canonical)
            stream.flush()
            os.fsync(stream.fileno())
        if staging.read_bytes() != canonical:
            raise ValueError("SUBTITLE_CANONICAL_WRITE_MISMATCH")
        if content_identity(source) != before:
            raise SourceChangedDuringRead("Subtitle changed before compatibility publication")
        os.link(staging, target)
    finally:
        # Cleanup is best effort, never a reason to report a committed import
        # as failed. Leftover staging is not a canonical output or receipt.
        try:
            staging.unlink()
        except OSError:
            pass
    return receipt



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
