from __future__ import annotations

import json
import math
import re
import shutil
import tempfile
import warnings
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from .config import AppConfig
from .models import (
    SceneDetectionMetadata,
    SceneIndex,
    SceneSignals,
    SceneUnit,
    SourceInfo,
    SourceManifest,
    TranscriptDocument,
)
from .utils import (
    clamp,
    discover_videos,
    content_identity,
    SourceChangedDuringRead,
    overlap_seconds,
    run_command,
    safe_slug,
)


def _fraction(value: str | int | float | None) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        try:
            return float(numerator) / float(denominator)
        except (ValueError, ZeroDivisionError):
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def ffprobe_json(path: str | Path) -> dict[str, Any]:
    result = run_command(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        timeout=120,
    )
    return json.loads(result.stdout)


def media_duration(path: str | Path) -> float:
    data = ffprobe_json(path)
    try:
        return float(data.get("format", {}).get("duration") or 0)
    except (TypeError, ValueError):
        return 0.0


def find_sidecar_subtitle(video_path: Path) -> Path | None:
    """Prefer an exact basename; accept explicit language suffixes, never numeric prefixes."""
    extensions = (".srt", ".ass", ".vtt", ".ssa")
    stem = video_path.stem.casefold()
    exact: list[Path] = []
    localized: list[Path] = []
    # A separator must precede the language tag: 1.zh-CN.srt is valid, 10.srt is not.
    language = re.compile(
        r"^(?:zh(?:[-_.](?:cn|tw|hk|hans|hant))?|en(?:[-_.](?:us|gb))?|"
        r"chs|cht|cn|eng|ja|jp|jpn|ko|kor|fr|de|es|ru|pt|it|"
        r"简体|繁体|中文|简体中文|繁体中文|中英|双语)"
        r"(?:[-_. ](?:forced|sdh|cc|default))*$", re.IGNORECASE,
    )
    for item in video_path.parent.iterdir():
        if not item.is_file() or item.suffix.casefold() not in extensions:
            continue
        candidate_stem = item.stem.casefold()
        if candidate_stem == stem:
            exact.append(item.resolve())
        elif candidate_stem.startswith(stem):
            suffix = candidate_stem[len(stem):]
            if suffix and suffix[0] in "._- " and language.fullmatch(suffix[1:]):
                localized.append(item.resolve())
    if exact:
        best_format = min(extensions.index(path.suffix.casefold()) for path in exact)
        candidates = sorted(path for path in exact if extensions.index(path.suffix.casefold()) == best_format)
    else:
        candidates = sorted(localized)
    if len(candidates) > 1:
        raise ValueError(
            f"Ambiguous sidecar subtitles for {video_path.name}: "
            + ", ".join(path.name for path in candidates)
            + ". Keep one exact basename subtitle or choose a single language file."
        )
    return candidates[0] if candidates else None


def extract_embedded_subtitle(video_path: Path, output_dir: Path) -> Path | None:
    data = ffprobe_json(video_path)
    subtitle_streams = [
        stream for stream in data.get("streams", []) if stream.get("codec_type") == "subtitle"
    ]
    # Bitmap subtitles cannot be converted to SRT without OCR. Skip them explicitly.
    unsupported = {"hdmv_pgs_subtitle", "dvd_subtitle", "dvb_subtitle", "xsub"}
    extraction_dir: Path | None = None
    for stream in subtitle_streams:
        if stream.get("codec_name") in unsupported:
            continue
        stream_index = stream.get("index")
        if stream_index is None:
            continue
        if extraction_dir is None:
            output_dir.mkdir(parents=True, exist_ok=True)
            # Each extraction owns a fresh directory. Re-ingest and basename/slug
            # collisions must never replace subtitles referenced by an old manifest.
            extraction_dir = Path(tempfile.mkdtemp(
                prefix=f"{safe_slug(video_path.stem)}.", dir=output_dir
            ))
        output = extraction_dir / f"stream_{stream_index}.embedded.srt"
        try:
            run_command(
                [
                    "ffmpeg",
                    "-n",
                    "-v",
                    "error",
                    "-i",
                    video_path,
                    "-map",
                    f"0:{stream_index}",
                    output,
                ],
                timeout=300,
            )
            if output.exists() and output.stat().st_size > 0:
                return output.resolve()
        except Exception:
            output.unlink(missing_ok=True)
    return None


def build_manifest(input_path: str | Path, config: AppConfig, work_dir: Path) -> SourceManifest:
    videos = discover_videos(input_path)
    subtitle_cache = work_dir / "subtitles" / "source"
    sources: list[SourceInfo] = []
    for order, video in enumerate(videos):
        identity = content_identity(video)
        probe = ffprobe_json(video)
        streams = probe.get("streams", [])
        video_stream = next(
            (stream for stream in streams if stream.get("codec_type") == "video"), None
        )
        if not video_stream:
            raise ValueError(f"No video stream found: {video}")
        duration = float(
            probe.get("format", {}).get("duration")
            or video_stream.get("duration")
            or 0
        )
        if duration <= 0:
            raise ValueError(f"Invalid duration for {video}")
        fps = _fraction(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate"))
        if fps <= 0:
            fps = 30.0
        sidecar = find_sidecar_subtitle(video) if config.asr.prefer_sidecar_subtitle else None
        if sidecar is None and config.asr.prefer_embedded_subtitle:
            sidecar = extract_embedded_subtitle(
                video, subtitle_cache / f"src_{order + 1:03d}" / identity["sha256"]
            )
        subtitle_identity = content_identity(sidecar) if sidecar else None
        if content_identity(video) != identity:
            raise SourceChangedDuringRead("Source changed while building the media manifest")
        sources.append(
            SourceInfo(
                source_id=f"src_{order + 1:03d}",
                path=str(video),
                fingerprint=identity["sha256"],
                identity_schema=identity["schema"],
                size_bytes=identity["bytes"],
                filename=video.name,
                duration=duration,
                width=int(video_stream.get("width") or 0),
                height=int(video_stream.get("height") or 0),
                fps=fps,
                has_audio=any(stream.get("codec_type") == "audio" for stream in streams),
                subtitle_path=str(sidecar) if sidecar else None,
                subtitle_fingerprint=subtitle_identity["sha256"] if subtitle_identity else None,
                subtitle_size_bytes=subtitle_identity["bytes"] if subtitle_identity else None,
                order=order,
            )
        )
    return SourceManifest(
        sources=sources,
        rights_confirmed=config.project.rights_confirmed,
        publish_mode=config.project.publish_mode,
        config_fingerprint=config.fingerprint(),
    )


def _fallback_shots(duration: float, max_unit: float) -> list[tuple[float, float]]:
    if max_unit <= 0:
        raise ValueError("Scene max_unit_sec must be positive")
    shots: list[tuple[float, float]] = []
    start = 0.0
    while start < duration:
        end = min(duration, start + max_unit)
        shots.append((start, end))
        start = end
    return shots


def _timecode_seconds(timecode: Any) -> float:
    # PySceneDetect 0.7 exposes ``seconds`` and deprecates ``get_seconds()``.
    seconds = getattr(timecode, "seconds", None)
    return float(seconds if seconds is not None else timecode.get_seconds())


def detect_shots_with_metadata(
    source: SourceInfo, config: AppConfig
) -> tuple[list[tuple[float, float]], SceneDetectionMetadata]:
    """Keep real detector evidence distinct from fixed analysis-only windows."""
    if config.scene.detector != "scenedetect":
        raise ValueError(f"Unsupported scene detector: {config.scene.detector}")
    fallback_reason = "no_usable_scenes"
    try:
        from scenedetect import ContentDetector, SceneManager, open_video

        video = open_video(source.path)
        manager = SceneManager()
        min_scene_len = max(1, int(config.scene.min_shot_sec * source.fps))
        manager.add_detector(
            ContentDetector(
                threshold=config.scene.content_threshold,
                min_scene_len=min_scene_len,
            )
        )
        manager.detect_scenes(video=video, show_progress=False)
        scenes = manager.get_scene_list(start_in_scene=True)
        shots = [
            (_timecode_seconds(start), min(_timecode_seconds(end), source.duration))
            for start, end in scenes
            if _timecode_seconds(end) - _timecode_seconds(start) >= 0.08
        ]
        if shots:
            return shots, SceneDetectionMetadata(
                detector_requested=config.scene.detector,
                detector_used="scenedetect",
                boundary_confidence="detector_estimated",
            )
    except ImportError as exc:
        fallback_reason = f"missing_dependency: {type(exc).__name__}: {exc}"
    except Exception as exc:
        fallback_reason = f"detection_error: {type(exc).__name__}: {exc}"
    warnings.warn(
        f"Scene detection for {source.source_id} used fixed-interval analysis windows: "
        f"{fallback_reason}. Shot boundaries and continuity are unknown.",
        RuntimeWarning,
        stacklevel=2,
    )
    return _fallback_shots(source.duration, config.scene.max_unit_sec), SceneDetectionMetadata(
        detector_requested=config.scene.detector,
        detector_used="fixed_interval",
        fallback_reason=fallback_reason,
        boundary_confidence="unknown",
    )


def detect_shots(source: SourceInfo, config: AppConfig) -> list[tuple[float, float]]:
    """Compatibility helper; scene-index production also persists detector metadata."""
    return detect_shots_with_metadata(source, config)[0]


def merge_shots_to_units(
    shots: list[tuple[float, float]], min_unit: float, max_unit: float
) -> list[list[tuple[float, float]]]:
    """Bound analysis windows without treating artificial splits as editorial cuts."""
    if max_unit <= 0 or min_unit < 0 or min_unit > max_unit:
        raise ValueError("Scene unit limits require 0 <= min_unit <= max_unit and max_unit > 0")
    bounded: list[tuple[float, float]] = []
    for start, end in shots:
        if end <= start:
            continue
        # Even windows avoid a tiny trailing window within a long continuous shot.
        count = max(1, math.ceil((end - start) / max_unit))
        for index in range(count):
            bounded.append((start + (end - start) * index / count,
                            start + (end - start) * (index + 1) / count))
    units: list[list[tuple[float, float]]] = []
    current: list[tuple[float, float]] = []
    for shot in bounded:
        if current and shot[1] - current[0][0] > max_unit + 1e-9:
            units.append(current)
            current = []
        current.append(shot)
    if current:
        units.append(current)
    if len(units) >= 2:
        last_duration = units[-1][-1][1] - units[-1][0][0]
        combined = units[-1][-1][1] - units[-2][0][0]
        if last_duration < min_unit and combined <= max_unit + 1e-9:
            units[-2].extend(units.pop())
    return units


def _transcript_for_range(
    transcript: TranscriptDocument, source_id: str, start: float, end: float
) -> tuple[str, list[int], float]:
    texts: list[str] = []
    indices: list[int] = []
    speech_seconds = 0.0
    for index, segment in enumerate(transcript.segments):
        if segment.source_id != source_id:
            continue
        overlap = overlap_seconds(start, end, segment.start, segment.end)
        if overlap <= 0:
            continue
        texts.append(segment.text.strip())
        indices.append(index)
        speech_seconds += overlap
    return " ".join(text for text in texts if text), indices, speech_seconds


def extract_frame(video_path: str | Path, timestamp: float, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_command(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-ss",
            f"{max(0.0, timestamp):.3f}",
            "-i",
            video_path,
            "-frames:v",
            "1",
            "-q:v",
            "2",
            output_path,
        ],
        timeout=120,
    )
    return output_path


def extract_frames_batch(
    video_path: str | Path,
    requests: list[tuple[float, Path]],
) -> list[Path]:
    """Extract representative frames with one decoder session when possible.

    OpenCV seeking is sufficient for analysis thumbnails and is much cheaper than
    launching one FFmpeg process per frame. Individual failures fall back to the
    precise FFmpeg helper.
    """
    if not requests:
        return []
    import cv2

    capture = cv2.VideoCapture(str(video_path))
    outputs: list[Path] = []
    try:
        for timestamp, output_path in sorted(requests, key=lambda item: item[0]):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            written = False
            if capture.isOpened():
                capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, timestamp) * 1000.0)
                ok, frame = capture.read()
                if ok and frame is not None:
                    written = bool(cv2.imwrite(str(output_path), frame))
            if not written:
                extract_frame(video_path, timestamp, output_path)
            outputs.append(output_path)
    finally:
        capture.release()
    return outputs


def _sample_times(start: float, end: float, count: int) -> list[float]:
    duration = end - start
    if count <= 1:
        return [start + duration * 0.5]
    margin = min(0.2, duration * 0.05)
    safe_start = start + margin
    safe_end = max(safe_start, end - margin)
    return [
        safe_start + (safe_end - safe_start) * (index + 0.5) / count
        for index in range(count)
    ]


def _load_font(size: int = 28) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/msyh.ttc",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            try:
                return ImageFont.truetype(candidate, size=size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_contact_sheet(
    frame_paths: list[str | Path],
    labels: list[str],
    output_path: Path,
    *,
    tile_width: int = 480,
) -> Path:
    if not frame_paths:
        raise ValueError("Cannot create contact sheet without frames")
    images = [Image.open(path).convert("RGB") for path in frame_paths]
    resized: list[Image.Image] = []
    tile_heights: list[int] = []
    caption_height = 52
    for image in images:
        ratio = tile_width / image.width
        height = max(1, int(image.height * ratio))
        resized_image = image.resize((tile_width, height), Image.Resampling.LANCZOS)
        resized.append(resized_image)
        tile_heights.append(height + caption_height)
    cols = min(3, len(resized))
    rows = math.ceil(len(resized) / cols)
    cell_height = max(tile_heights)
    canvas = Image.new("RGB", (cols * tile_width, rows * cell_height), "black")
    draw = ImageDraw.Draw(canvas)
    font = _load_font(24)
    for index, image in enumerate(resized):
        col = index % cols
        row = index // cols
        x = col * tile_width
        y = row * cell_height
        canvas.paste(image, (x, y))
        label = labels[index] if index < len(labels) else ""
        draw.text((x + 10, y + image.height + 10), label, font=font, fill="white")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=88)
    for image in images:
        image.close()
    return output_path


def motion_score(frame_paths: Iterable[str | Path]) -> float:
    import cv2

    frames: list[np.ndarray] = []
    for path in frame_paths:
        frame = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if frame is None:
            continue
        frame = cv2.resize(frame, (320, 180))
        frames.append(frame)
    if len(frames) < 2:
        return 0.0
    differences = [
        float(np.mean(cv2.absdiff(previous, current))) / 255.0
        for previous, current in zip(frames, frames[1:])
    ]
    return clamp(float(np.mean(differences)) * 4.0, 0.0, 1.0)


def build_scene_index(
    manifest: SourceManifest,
    transcript: TranscriptDocument,
    config: AppConfig,
    work_dir: Path,
) -> SceneIndex:
    frames_dir = work_dir / "frames"
    sheets_dir = work_dir / "contact_sheets" / "units"
    units: list[SceneUnit] = []
    source_detection: dict[str, SceneDetectionMetadata] = {}
    for source in manifest.sources:
        shots, detection = detect_shots_with_metadata(source, config)
        source_detection[source.source_id] = detection
        detected_shots = shots if detection.detector_used == "scenedetect" else []
        grouped = merge_shots_to_units(
            shots,
            min_unit=config.scene.min_unit_sec,
            max_unit=config.scene.max_unit_sec,
        )
        unit_specs: list[dict[str, Any]] = []
        frame_requests: list[tuple[float, Path]] = []
        for local_index, shot_group in enumerate(grouped, start=1):
            start = shot_group[0][0]
            end = shot_group[-1][1]
            unit_id = f"{source.source_id}_u{local_index:05d}"
            text, segment_indices, speech_seconds = _transcript_for_range(
                transcript, source.source_id, start, end
            )
            unit_frame_dir = frames_dir / source.source_id / unit_id
            sample_times = _sample_times(start, end, config.scene.sample_frames_per_unit)
            frame_paths: list[str] = []
            labels: list[str] = []
            for frame_index, timestamp in enumerate(sample_times, start=1):
                frame_path = unit_frame_dir / f"f{frame_index:02d}_{timestamp:.3f}.jpg"
                frame_requests.append((timestamp, frame_path))
                frame_paths.append(str(frame_path))
                labels.append(f"{unit_id} · {timestamp:.2f}s")
            unit_specs.append(
                {
                    "unit_id": unit_id,
                    "start": start,
                    "end": end,
                    "shot_group": shot_group,
                    "text": text,
                    "segment_indices": segment_indices,
                    "speech_seconds": speech_seconds,
                    "frame_paths": frame_paths,
                    "labels": labels,
                }
            )

        extract_frames_batch(source.path, frame_requests)
        for spec in unit_specs:
            contact_sheet = sheets_dir / f"{spec['unit_id']}.jpg"
            make_contact_sheet(spec["frame_paths"], spec["labels"], contact_sheet)
            duration = max(0.001, spec["end"] - spec["start"])
            signals = SceneSignals(
                motion=motion_score(spec["frame_paths"]),
                speech_density=clamp(spec["speech_seconds"] / duration, 0.0, 1.0),
                shot_density=clamp(
                    (len(spec["shot_group"]) / duration) / 1.5, 0.0, 1.0
                ) if detected_shots else 0.0,
                shot_density_available=bool(detected_shots),
            )
            units.append(
                SceneUnit(
                    unit_id=spec["unit_id"],
                    source_id=source.source_id,
                    start=spec["start"],
                    end=spec["end"],
                    shot_spans=spec["shot_group"],
                    original_shot_spans=[(start, end) for start, end in detected_shots
                                         if overlap_seconds(start, end, spec["start"], spec["end"]) > 0],
                    continuity_shot_ids=[f"{source.source_id}_shot{index:05d}"
                                         for index, (start, end) in enumerate(detected_shots, start=1)
                                         if overlap_seconds(start, end, spec["start"], spec["end"]) > 0],
                    analysis_window_only=not detected_shots or any(start < spec["start"] - 1e-6 or end > spec["end"] + 1e-6
                                             for start, end in shots
                                             if overlap_seconds(start, end, spec["start"], spec["end"]) > 0),
                    transcript=spec["text"],
                    transcript_segments=spec["segment_indices"],
                    frame_paths=spec["frame_paths"],
                    contact_sheet_path=str(contact_sheet),
                    signals=signals,
                    scene_detection=detection,
                )
            )
    detectors_used = {metadata.detector_used for metadata in source_detection.values()}
    return SceneIndex(
        units=units,
        source_fingerprints={source.source_id: source.fingerprint for source in manifest.sources},
        detector=(next(iter(detectors_used)) if len(detectors_used) == 1 else
                  "mixed" if detectors_used else "unknown"),
        source_detection=source_detection,
        detection_status=("detected" if detectors_used == {"scenedetect"} else
                          "fallback" if detectors_used == {"fixed_interval"} else
                          "mixed" if detectors_used else "unknown"),
        detector_params={
            "detector_requested": config.scene.detector,
            "content_threshold": config.scene.content_threshold,
            "min_shot_sec": config.scene.min_shot_sec,
            "min_unit_sec": config.scene.min_unit_sec,
            "max_unit_sec": config.scene.max_unit_sec,
        },
    )


def copy_or_link(source: str | Path, destination: str | Path) -> Path:
    src = Path(source)
    dst = Path(destination)
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        dst.symlink_to(src.resolve())
    except (OSError, NotImplementedError):
        shutil.copy2(src, dst)
    return dst
