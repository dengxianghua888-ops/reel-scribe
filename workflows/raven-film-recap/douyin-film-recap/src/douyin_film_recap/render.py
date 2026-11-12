from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any
from uuid import uuid4
import threading
import time

from PIL import ImageFont

from .config import AppConfig
from .media import media_duration
from .models import SourceInfo, Storyboard, StoryboardSegment, VisualReference
from .parallel import run_parallel
from .subtitles import build_cues, output_timeline, resolved_visual_spans, segment_output_duration, write_srt
from .utils import content_fingerprint, content_identity, fingerprint_json, run_command


class ArtifactPathError(ValueError):
    """An output path is not a new artifact owned by this rendering attempt."""


def _safe_directory(path: Path, boundary: Path | None = None) -> None:
    """Reject existing directory links before creating descendants.

    Fresh private attempt directories protect ordinary writers. These checks do
    not claim to isolate a malicious process running with the same permissions.
    """
    if boundary is not None and not path.is_relative_to(boundary):
        raise ArtifactPathError("OUTPUT_OUTSIDE_ATTEMPT")
    if path.is_symlink():
        raise ArtifactPathError("OUTPUT_DIRECTORY_SYMLINK")
    if path.exists():
        if not path.is_dir():
            raise ArtifactPathError("OUTPUT_PARENT_NOT_DIRECTORY")
        if boundary is not None and path != boundary:
            _safe_directory(path.parent, boundary)
        return
    if path.parent != path:
        _safe_directory(path.parent, boundary)
    try:
        path.mkdir(mode=0o700)
    except FileExistsError:
        if path.is_symlink() or not path.is_dir():
            raise ArtifactPathError("OUTPUT_PARENT_CHANGED")


class _RenderAttempt:
    def __init__(self, work_dir: Path, protected: list[Path]):
        # Resolve the explicitly supplied task root once; descendants must never
        # be redirected by links in a previously used work directory.
        if work_dir.is_symlink():
            raise ArtifactPathError("WORK_DIRECTORY_SYMLINK")
        task_root = work_dir.absolute().resolve()
        _safe_directory(task_root)
        parent = task_root / "render_attempts"
        _safe_directory(parent, task_root)
        self.attempt_id = uuid4().hex
        self.task_root = task_root
        self.ffmpeg_calls = 0
        self.counter_lock = threading.Lock()
        self.root = parent / self.attempt_id
        self.root.mkdir(mode=0o700, exist_ok=False)
        identity = self.root.stat()
        self.directory_identity = (identity.st_dev, identity.st_ino)
        self.protected = [path.resolve() for path in protected]
        self.inputs = {str(path): content_identity(path) for path in self.protected}

    def prepare(self, path: Path) -> None:
        path = path.absolute()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ArtifactPathError(f"OUTPUT_OUTSIDE_ATTEMPT: {self.attempt_id}")
        _safe_directory(self.root, self.root)
        current = self.root.stat()
        if (current.st_dev, current.st_ino) != self.directory_identity:
            raise ArtifactPathError(f"ATTEMPT_DIRECTORY_CHANGED: {self.attempt_id}")
        _safe_directory(path.parent, self.root)
        _reject_existing_output(path, self.protected)


_segment_render_key: ContextVar[str | None] = ContextVar("segment_render_key", default=None)

_render_attempt: ContextVar[_RenderAttempt | None] = ContextVar("render_attempt", default=None)


def _reject_existing_output(path: Path, protected: list[Path]) -> None:
    if path.is_symlink():
        raise ArtifactPathError("OUTPUT_SYMLINK")
    for source in protected:
        if path.resolve() == source.resolve() or (path.exists() and source.exists() and path.samefile(source)):
            raise ArtifactPathError("OUTPUT_ALIASES_SOURCE")
    if path.exists():
        raise ArtifactPathError("OUTPUT_ALREADY_EXISTS")


def _prepare_output(path: Path, protected: list[Path] | None = None) -> None:
    attempt = _render_attempt.get()
    if attempt is not None:
        attempt.prepare(path)
    else:
        # Private helper calls also refuse existing files and linked parents.
        path = path.absolute()
        for ancestor in path.parents:
            if ancestor.is_symlink():
                raise ArtifactPathError("OUTPUT_DIRECTORY_SYMLINK")
        _safe_directory(path.parent)
        _reject_existing_output(path, protected or [])


def _write_new_json(path: Path, value: Any) -> None:
    _prepare_output(path)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.flush()
        os.fsync(handle.fileno())


def _render_command(*args, **kwargs):
    attempt = _render_attempt.get()
    if attempt is not None:
        with attempt.counter_lock:
            attempt.ffmpeg_calls += 1
    return run_command(*args, **kwargs)


def _segment_key(segment: StoryboardSegment, config: AppConfig) -> str:
    payload = segment.model_dump(mode="json")
    for name in ("status", "rendered_file", "rendered_duration_sec"):
        payload.pop(name, None)
    attempt = _render_attempt.get()
    return fingerprint_json({"schema": "film-render-artifact/2", "segment": payload,
                             "inputs": attempt.inputs if attempt else {},
                             "render": config.render.model_dump(mode="json")})


def _layout_filter(config: AppConfig) -> str:
    width, height, fps = config.render.width, config.render.height, config.render.fps
    if config.render.layout == "center_crop":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},setsar=1,fps={fps},format=yuv420p"
        )
    if config.render.layout == "fit_black":
        return (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black,"
            f"setsar=1,fps={fps},format=yuv420p"
        )
    return (
        f"fps={fps},split=2[bg][fg];"
        f"[bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},gblur=sigma={config.render.blur_sigma}[bg2];"
        f"[fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1,format=yuv420p"
    )


def _video_encode_args(config: AppConfig) -> list[str]:
    return [
        "-c:v",
        config.render.video_codec,
        "-preset",
        config.render.preset,
        "-crf",
        str(config.render.crf),
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(config.render.fps),
        "-movflags",
        "+faststart",
    ]


def _audio_encode_args(config: AppConfig) -> list[str]:
    return [
        "-c:a",
        config.render.audio_codec,
        "-b:a",
        config.render.audio_bitrate,
        "-ar",
        "48000",
        "-ac",
        "2",
    ]


def _source_map(storyboard: Storyboard) -> dict[str, SourceInfo]:
    return {source.source_id: source for source in storyboard.sources}


def _render_visual_piece(
    visual: VisualReference,
    source: SourceInfo,
    duration: float,
    output: Path,
    config: AppConfig,
    *,
    include_audio: bool = False,
) -> None:
    _prepare_output(output, [Path(source.path)])
    args: list[str | Path] = [
        "ffmpeg",
        "-n",
        "-v",
        "error",
        "-ss",
        f"{visual.start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        source.path,
    ]
    audio_input = "0:a:0"
    if include_audio and not source.has_audio:
        args.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{duration:.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
        audio_input = "1:a:0"
    args.extend(["-map", "0:v:0", "-vf", _layout_filter(config)])
    if include_audio:
        fade = min(0.03, duration / 4)
        args.extend(
            [
                "-map",
                audio_input,
                "-af",
                (
                    "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                    f"afade=t=in:st=0:d={fade:.3f},"
                    f"afade=t=out:st={max(0.0, duration - fade):.3f}:d={fade:.3f}"
                ),
                *_video_encode_args(config),
                *_audio_encode_args(config),
                "-shortest",
                output,
            ]
        )
    else:
        args.extend(["-an", *_video_encode_args(config), output])
    _render_command(args, timeout=config.runtime.stage_timeout_sec)


def _write_concat_list(paths: list[Path], output_path: Path) -> Path:
    _prepare_output(output_path, paths)
    lines = []
    for path in paths:
        escaped = str(path.resolve()).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    with output_path.open("x", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return output_path


def _concat_copy(paths: list[Path], output: Path, config: AppConfig) -> None:
    _prepare_output(output, paths)
    concat_list = _write_concat_list(paths, output.with_suffix(".concat.txt"))
    temporary = output.with_name(f".{output.stem}.copy-{uuid4().hex}{output.suffix}")
    _prepare_output(temporary, paths)
    try:
        _render_command(
            [
                "ffmpeg",
                "-n",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                temporary,
            ],
            timeout=config.runtime.stage_timeout_sec,
        )
    except RuntimeError:
        # Fallback re-encodes but remains deterministic when container timebases differ.
        # Keep any failed copy as evidence; the fallback gets a distinct target.
        _prepare_output(output, paths)
        _render_command(
            [
                "ffmpeg",
                "-n",
                "-v",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                concat_list,
                *_video_encode_args(config),
                *_audio_encode_args(config),
                output,
            ],
            timeout=config.runtime.stage_timeout_sec,
        )
    else:
        # Hard-link publication is no-clobber: an unexpected existing destination
        # raises instead of replacing it. Both names are inside this attempt.
        _prepare_output(output, paths)
        os.link(temporary, output, follow_symlinks=False)
        temporary.unlink()


def _render_voiceover_segment(
    segment: StoryboardSegment,
    source_map: dict[str, SourceInfo],
    output: Path,
    work_dir: Path,
    config: AppConfig,
) -> None:
    if not segment.audio_file or not Path(segment.audio_file).exists():
        raise FileNotFoundError(f"Missing voiceover audio: {segment.segment_id}")
    target_duration = float(segment.audio_duration_sec or segment.planned_duration_sec)
    remaining = target_duration
    pieces: list[Path] = []
    for index, visual in enumerate(resolved_visual_spans(segment), start=1):
        source = source_map[visual.source_id]
        available = visual.end - visual.start
        duration = min(available, remaining)
        piece = work_dir / "clips" / "visuals" / (_segment_render_key.get() or _segment_key(segment, config)) / f"v{index:03d}.mp4"
        _render_visual_piece(
            visual,
            source,
            duration,
            piece,
            config,
            include_audio=not segment.mute_original,
        )
        pieces.append(piece)
        remaining -= duration
    if remaining > 0.001:
        raise ValueError(
            f"Voiceover visuals are {remaining:.2f}s shorter than audio: {segment.segment_id}"
        )
    visual_base = work_dir / "clips" / "visuals" / (_segment_render_key.get() or _segment_key(segment, config)) / "visual_base.mp4"
    _concat_copy(pieces, visual_base, config)
    fade = min(0.03, target_duration / 4)
    _prepare_output(output, [visual_base, Path(segment.audio_file)])
    args: list[str | Path] = [
        "ffmpeg",
        "-n",
        "-v",
        "error",
        "-i",
        visual_base,
        "-i",
        segment.audio_file,
        "-map",
        "0:v:0",
    ]
    if segment.mute_original:
        speed_filter = (f"atempo={segment.audio_speed:.6f}," if abs(segment.audio_speed - 1.0) > 1e-4 else "")
        audio_filter = (
            speed_filter
            + "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"afade=t=in:st=0:d={fade:.3f},"
            f"afade=t=out:st={max(0.0, target_duration - fade):.3f}:d={fade:.3f}"
        )
        args.extend(["-map", "1:a:0", "-af", audio_filter])
    else:
        filter_complex = (
            f"[0:a]volume={config.render.original_bed_db}dB,"
            f"atrim=0:{target_duration:.3f},asetpts=PTS-STARTPTS[bed];"
            f"[1:a]{('atempo=' + format(segment.audio_speed, '.6f') + ',') if abs(segment.audio_speed - 1.0) > 1e-4 else ''}"
            f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"atrim=0:{target_duration:.3f},asetpts=PTS-STARTPTS[vo];"
            f"[bed][vo]amix=inputs=2:duration=longest:dropout_transition=0,"
            f"afade=t=in:st=0:d={fade:.3f},"
            f"afade=t=out:st={max(0.0, target_duration - fade):.3f}:d={fade:.3f}[mix]"
        )
        args.extend(["-filter_complex", filter_complex, "-map", "[mix]"])
    args.extend(
        [
            "-t",
            f"{target_duration:.3f}",
            "-vf",
            "setpts=PTS-STARTPTS",
            "-fps_mode",
            "cfr",
            *_video_encode_args(config),
            *_audio_encode_args(config),
            "-movflags",
            "+faststart",
            output,
        ]
    )
    _render_command(args, timeout=config.runtime.stage_timeout_sec)


def _render_original_segment(
    segment: StoryboardSegment,
    source_map: dict[str, SourceInfo],
    output: Path,
    config: AppConfig,
) -> None:
    visuals = resolved_visual_spans(segment)
    if len(visuals) != 1:
        raise ValueError(f"Original segment must have one continuous visual: {segment.segment_id}")
    visual = visuals[0]
    source = source_map[visual.source_id]
    duration = visual.end - visual.start
    fade = min(0.03, duration / 4)
    args: list[str | Path] = [
        "ffmpeg",
        "-n",
        "-v",
        "error",
        "-ss",
        f"{visual.start:.3f}",
        "-t",
        f"{duration:.3f}",
        "-i",
        source.path,
    ]
    if not source.has_audio:
        args.extend(
            [
                "-f",
                "lavfi",
                "-t",
                f"{duration:.3f}",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
        audio_input = "1:a:0"
    else:
        audio_input = "0:a:0"
    audio_filter = (
        f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
        f"afade=t=in:st=0:d={fade:.3f},"
        f"afade=t=out:st={max(0.0, duration - fade):.3f}:d={fade:.3f}"
    )
    args.extend(
        [
            "-map",
            "0:v:0",
            "-map",
            audio_input,
            "-vf",
            _layout_filter(config),
            "-af",
            audio_filter,
            *_video_encode_args(config),
            *_audio_encode_args(config),
            output,
        ]
    )
    _prepare_output(output, [Path(source.path)])
    _render_command(args, timeout=config.runtime.stage_timeout_sec)


def _escape_subtitle_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    value = value.replace(":", "\\:").replace("'", "\\'")
    return value


def _subtitle_style(config: AppConfig, font_name: str | None = None) -> str:
    if not 0 <= config.render.subtitle_margin_v < config.render.height:
        raise ValueError("Subtitle bottom margin must fit the output canvas")
    if not 0 < config.render.subtitle_font_size <= config.render.height:
        raise ValueError("Subtitle font size must fit the output canvas")
    return (
        # SRT's implicit ASS canvas is not the output canvas. Pin script
        # coordinates so configured size, outline and margins use output pixels.
        f"PlayResX={config.render.width},PlayResY={config.render.height},"
        f"FontName={font_name or config.render.subtitle_font},"
        f"FontSize={config.render.subtitle_font_size},"
        "Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,"
        "BackColour=&H66000000,BorderStyle=1,Shadow=0,Alignment=2,"
        f"Outline={config.render.subtitle_outline},"
        f"MarginV={config.render.subtitle_margin_v}"
    )


@contextmanager
def _subtitle_font_source(config: AppConfig):
    """Explicit files bypass unreliable system font discovery, including CoreText.

    libass accepts a directory, not a fontfile option. Give it a temporary
    directory containing only the selected file and use the file's real family.
    No font is installed, downloaded, or silently replaced.
    """
    font_file = config.render.subtitle_font_file
    fonts_dir = config.render.subtitle_fonts_dir
    if font_file and fonts_dir:
        raise ValueError("Set only subtitle_font_file or subtitle_fonts_dir, not both")
    if font_file:
        source = Path(font_file).expanduser().resolve()
        if not source.is_file():
            raise ValueError(f"Subtitle font file does not exist: {source}")
        try:
            family = ImageFont.truetype(str(source), 24).getname()[0]
        except OSError as exc:
            raise ValueError(f"Cannot read subtitle font file: {source}") from exc
        normalize = lambda value: re.sub(r"[\s_-]+", "", value).casefold()
        if normalize(family) != normalize(config.render.subtitle_font):
            raise ValueError(
                f"subtitle_font={config.render.subtitle_font!r} does not match the font file's "
                f"family {family!r}; set both explicitly or use subtitle_fonts_dir for a font collection"
            )
        with tempfile.TemporaryDirectory(prefix="film-recap-fonts-") as temporary:
            linked = Path(temporary) / source.name
            try:
                linked.symlink_to(source)
            except OSError:
                shutil.copy2(source, linked)
            yield family, Path(temporary), str(source)
    elif fonts_dir:
        directory = Path(fonts_dir).expanduser().resolve()
        if not directory.is_dir():
            raise ValueError(f"Subtitle fonts directory does not exist: {directory}")
        yield config.render.subtitle_font, directory, None
    else:
        yield config.render.subtitle_font, None, None


def _finalize(
    base_video: Path,
    subtitle_path: Path,
    final_path: Path,
    config: AppConfig,
    *,
    subtitles_expected: bool = True,
) -> str:
    audio_filter = (
        f"loudnorm=I={config.render.target_lufs}:"
        f"TP={config.render.true_peak_db}:LRA=11"
    )
    args: list[str | Path] = ["ffmpeg", "-n", "-v", "info", "-i", base_video]
    has_subtitles = subtitle_path.exists() and subtitle_path.stat().st_size > 0
    if subtitles_expected and not has_subtitles:
        raise ValueError("Expected captions are missing or empty; refusing silent subtitle loss")
    burn_status = "not_requested" if not config.render.subtitle_burn_in else "not_applicable"
    if config.render.subtitle_burn_in and has_subtitles:
        with _subtitle_font_source(config) as (family, fonts_dir, font_file):
            if any(character in family for character in "\n\r,[]'"):
                raise ValueError("Subtitle font family contains unsupported filter/style characters")
            subtitle_filter = f"subtitles='{_escape_subtitle_path(subtitle_path)}':"
            if fonts_dir:
                subtitle_filter += f"fontsdir='{_escape_subtitle_path(fonts_dir)}':"
            subtitle_filter += f"force_style='{_subtitle_style(config, family)}'"
            args.extend(["-vf", subtitle_filter, "-af", audio_filter, *_video_encode_args(config)])
            args.extend([*_audio_encode_args(config), "-movflags", "+faststart", final_path])
            _prepare_output(final_path, [base_video, subtitle_path])
            result = _render_command(args, timeout=config.runtime.stage_timeout_sec)
            log = (result.stderr or "") + "\n" + (result.stdout or "")
            font_lines = [line for line in log.splitlines() if any(marker in line.lower() for marker in (
                "fontselect:", "glyph", "loading font file", "using font provider", "error opening font",
            ))]
            missing = [line for line in font_lines if re.search(r"failed to find.*glyph|fontselect:.*failed|no usable font", line, re.I)]
            report_path = final_path.with_suffix(".fonts.json")
            _write_new_json(report_path, {"requested_family": config.render.subtitle_font,
                       "resolved_family": family, "font_file": font_file,
                       "fonts_dir": config.render.subtitle_fonts_dir,
                       "font_file_sha256": content_fingerprint(font_file) if font_file else None,
                       "status": "failed" if missing else "applied",
                       "font_selection_log": font_lines, "missing_glyph_errors": missing})
            if missing:
                final_path.unlink(missing_ok=True)
                raise ValueError(
                    "Subtitle font cannot render required glyphs; refusing a tofu-caption final. "
                    "Set render.subtitle_font_file to a readable CJK font, or subtitle_fonts_dir "
                    f"and the correct family. Diagnostics: {report_path}"
                )
        return "applied"
    else:
        # Concat-copy can retain AAC/container offsets between video packets.
        # Normalize the final frame grid even when captions are not burned in;
        # stream-copy would preserve irregular PTS and fail the configured FPS QC.
        args.extend(["-vf", f"fps={config.render.fps}", "-af", audio_filter,
                     *_video_encode_args(config)])
    args.extend([*_audio_encode_args(config), "-movflags", "+faststart", final_path])
    _prepare_output(final_path, [base_video, subtitle_path])
    _render_command(args, timeout=config.runtime.stage_timeout_sec)
    return burn_status


def _make_preview(final_path: Path, preview_path: Path, config: AppConfig) -> None:
    _prepare_output(preview_path, [final_path])
    _render_command(
        [
            "ffmpeg",
            "-n",
            "-v",
            "error",
            "-i",
            final_path,
            "-vf",
            "scale=720:1280:force_original_aspect_ratio=decrease,"
            "pad=720:1280:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v",
            config.render.video_codec,
            "-preset",
            "veryfast",
            "-crf",
            "27",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            preview_path,
        ],
        timeout=config.runtime.stage_timeout_sec,
    )


def build_edl(storyboard: Storyboard, *, realized_timeline: list[dict] | None = None) -> list[dict[str, Any]]:
    timeline = output_timeline(storyboard, realized_timeline=realized_timeline)
    timeline_map = {item["segment_id"]: item for item in timeline}
    realized_map = {item["segment_id"]: item for item in (realized_timeline or [])}
    entries: list[dict[str, Any]] = []
    for segment in storyboard.segments:
        output = timeline_map[segment.segment_id]
        source_spans = []
        cursor = float(output["start"])
        visuals = resolved_visual_spans(segment)
        local_cursor = 0.0
        for visual_index, visual in enumerate(visuals):
            duration = visual.end - visual.start
            end = cursor + duration
            if realized_timeline is not None:
                from .render_contracts import quantize, rational
                entry = realized_map[segment.segment_id]
                total_frames = entry["end_frame"] - entry["start_frame"]
                fps = total_frames / rational(entry["duration"])
                local_cursor += duration
                end = (float(output["end"]) if visual_index == len(visuals) - 1 else
                       float(output["start"]) + float(quantize(rational(local_cursor) * fps) / fps))
                if end <= cursor or end > float(output["end"]) + 0.001:
                    raise ValueError("EDL_REALIZED_SPAN_OUT_OF_RANGE")
            source_spans.append({
                "source_id": visual.source_id, "start": visual.start, "end": visual.end,
                "output_start": cursor, "output_end": end,
                "purpose": visual.purpose, "highlight_id": visual.highlight_id,
                "unit_id": getattr(visual, "unit_id", None),
            })
            cursor = end
        entries.append(
            {
                "segment_id": segment.segment_id,
                "beat_id": segment.beat_id,
                "mode": segment.mode,
                "output_start": output["start"],
                "output_end": output["end"],
                "source_spans": source_spans,
                "text": segment.text,
                "text_raw": segment.text_raw,
                "audio_owner": segment.audio_owner,
                "narration_job": segment.narration_job,
                "reason": segment.notes,
            }
        )
    return entries


def render_storyboard(
    storyboard: Storyboard,
    config: AppConfig,
    work_dir: Path,
) -> Storyboard:
    # Validate again at the write boundary: Pydantic objects can be mutated by
    # callers after construction. Work on a copy so a failed attempt cannot
    # publish partial status or replace the caller's last valid output record.
    storyboard = Storyboard.model_validate(storyboard.model_dump(mode="json"))
    if not storyboard.segments:
        raise ValueError("Cannot render an empty storyboard")
    protected = [Path(source.path) for source in storyboard.sources]
    protected.extend(Path(segment.audio_file) for segment in storyboard.segments if segment.audio_file)
    attempt = _RenderAttempt(Path(work_dir), protected)
    token = _render_attempt.set(attempt)
    try:
        result = _render_storyboard_in_attempt(storyboard, config, attempt)
        result.output["render_attempt_id"] = attempt.attempt_id
        result.output["artifact_schema"] = "film-render-artifact/2"
        return result
    finally:
        _render_attempt.reset(token)


def _render_storyboard_in_attempt(
    storyboard: Storyboard, config: AppConfig, attempt: _RenderAttempt,
) -> Storyboard:
    work_dir = attempt.root
    source_map = _source_map(storyboard)
    segment_dir = work_dir / "clips" / "rendered"
    render_jobs: list[tuple[int, StoryboardSegment, Path]] = []
    incremental = None
    if getattr(config.render, "incremental_cache", False):
        incremental = _prepare_incremental(storyboard, config, attempt)
        source_map = incremental["source_map"]
    for index, segment in enumerate(storyboard.segments, start=1):
        name = (incremental["nodes"][segment.segment_id]["semantic_key"] if incremental else _segment_key(segment, config))
        output = segment_dir / f"{index:04d}_{name}.mp4"
        render_jobs.append((index, segment, output))

    def render_one(job: tuple[int, StoryboardSegment, Path]) -> tuple[int, Path]:
        index, segment, output = job
        # Worker threads do not automatically inherit ContextVar bindings.
        token = _render_attempt.set(attempt)
        try:
            if incremental:
                _render_incremental_segment(segment, source_map, output, work_dir, config, attempt, incremental)
            elif segment.mode == "voiceover":
                _render_voiceover_segment(segment, source_map, output, work_dir, config)
            else:
                _render_original_segment(segment, source_map, output, config)
            segment.status = "rendered"
            segment.rendered_file = str(output)
            segment.rendered_duration_sec = media_duration(output)
            return index, output
        finally:
            _render_attempt.reset(token)

    rendered: dict[int, Path] = {}
    workers = max(1, min(config.runtime.max_parallel_ffmpeg, len(render_jobs) or 1))
    for index, output in run_parallel(render_jobs, render_one, max_workers=workers):
        rendered[index] = output
    segment_paths = [rendered[index] for index in sorted(rendered)]

    clock_evidence = []
    if incremental:
        from .render_plan import compile_render_plan
        plan = compile_render_plan(storyboard, config, **incremental["inputs"],
            realized_artifacts=incremental["artifacts"])
        realized_timeline = plan["timeline"]["realized"]
        _write_new_json(work_dir / "output" / "render_plan.json", plan)
    else:
        # Cache policy must not determine the precision of subtitles and EDL.
        from .render_cache import verify_media
        from .render_timeline import build_realized_timeline
        contracts = {}
        for segment, path in zip(storyboard.segments, segment_paths):
            params = {name: getattr(config.render, name) for name in
                      ("fps", "width", "height", "video_codec", "audio_codec")}
            params["duration"] = segment_output_duration(segment)
            measured = verify_media(path, params, timeout=config.runtime.stage_timeout_sec)
            contracts[segment.segment_id] = measured["media_contract"]
            clock_evidence.append({"segment_id": segment.segment_id, "sha256": measured["sha256"], "size": measured["size"]})
        realized_timeline = build_realized_timeline(storyboard, config.render.fps, contracts, strict_nominal=False)
    base_video = work_dir / "output" / "base_no_subtitles.mp4"
    _concat_copy(segment_paths, base_video, config)
    from .render_cache import verify_assembly_placement
    verify_assembly_placement(base_video, realized_timeline, config.render.fps,
                              timeout=config.runtime.stage_timeout_sec)
    cues = build_cues(storyboard, config, realized_timeline=realized_timeline)
    srt_path = work_dir / "subtitles" / "master.srt"
    _prepare_output(srt_path)
    with tempfile.TemporaryDirectory(prefix=".captions-", dir=srt_path.parent) as temporary:
        generated = write_srt(cues, Path(temporary) / "master.srt")
        _prepare_output(srt_path)
        os.link(generated, srt_path, follow_symlinks=False)
    final_path = work_dir / "output" / "final.mp4"
    burn_status = _finalize(base_video, srt_path, final_path, config, subtitles_expected=bool(cues))
    preview_path = work_dir / "output" / "preview.mp4"
    _make_preview(final_path, preview_path, config)
    edl_path = work_dir / "output" / "edit_decision_list.json"
    _write_new_json(edl_path, build_edl(storyboard, realized_timeline=realized_timeline))
    review_file = (str(work_dir / "output" / "review_evidence.json") if incremental else
                   storyboard.output.get("review_file", str(work_dir / "output" / "review_evidence.json")))
    storyboard.output = {
        "realized_timeline": realized_timeline,
        "timeline_policy": "strict-nominal/1" if incremental else "measured-segment-clock/1",
        "segment_clock_evidence": clock_evidence,
        "nominal_quantization_delta_sec": float(output_timeline(storyboard, realized_timeline=realized_timeline)[-1]["end"])
            - sum(segment_output_duration(segment) for segment in storyboard.segments),
        "base_video": str(base_video),
        "final_video": str(final_path),
        "preview_video": str(preview_path),
        "subtitle": str(srt_path),
        "edl": str(edl_path),
        "duration_sec": media_duration(final_path),
        "final_fingerprint": content_fingerprint(final_path),
        "subtitle_fingerprint": content_fingerprint(srt_path),
        "subtitle_burn_status": burn_status,
        "subtitle_cue_count": len(cues),
        "subtitle_font_report": str(final_path.with_suffix(".fonts.json")) if burn_status == "applied" else None,
        "review_file": review_file,
    }
    if incremental:
        from .workspace import preflight
        from .render_contracts import RenderContractError
        if preflight(attempt.task_root)[1].resolve() != attempt.task_root.resolve():
            raise RenderContractError("STALE_AUTHORITY")
        receipt_path = work_dir / "output" / "render_receipt.json"
        _write_new_json(receipt_path, {
            "schema": "film-render-receipt/1", "attempt_id": attempt.attempt_id,
            "authority_sha256": plan["authority"]["document_sha256"],
            "segments": [incremental["receipts"][s.segment_id] for s in storyboard.segments],
            "segments_planned": len(storyboard.segments),
            "segments_executed": sum(r["action"] == "executed" for r in incremental["receipts"].values()),
            "segments_reused": sum(r["action"] == "reused" for r in incremental["receipts"].values()),
            "cache_bytes_published": sum(r["size"] for r in incremental["receipts"].values() if r["action"] == "executed"),
            "ffmpeg_render_calls": attempt.ffmpeg_calls,
            "verification_decode_calls": incremental["cache"].stats.decode_calls,
            "verification_probe_calls": incremental["cache"].stats.probe_calls,
            "wall_seconds": time.monotonic() - incremental["started"],
            "wall_scope": "render-only; pipeline QC measured separately",
            "unmeasured_metrics": ["cpu_seconds", "peak_rss", "disk_io", "finalize_wall_seconds", "pipeline_qc_wall_seconds"],
            "finalize_executed": True, "qc_inherited": False,
            "validation_scope": "synthetic-technical-only; real-media-validation-not-run"})
        storyboard.output.update(render_plan=str(work_dir / "output" / "render_plan.json"),
            render_receipt=str(receipt_path), realized_timeline=realized_timeline)
    return storyboard


def _prepare_incremental(storyboard: Storyboard, config: AppConfig, attempt: _RenderAttempt) -> dict:
    from .render_cache import SegmentCache, copy_new
    from .render_contracts import RenderContractError
    from .render_plan import collect_render_inputs, compile_render_plan

    from .workspace import preflight
    cache_root, active = preflight(attempt.task_root)
    if active.resolve() != attempt.task_root.resolve():
        raise RenderContractError("STALE_AUTHORITY")
    started = time.monotonic()
    inputs = collect_render_inputs(storyboard)
    plan = compile_render_plan(storyboard, config, **inputs)
    nodes = {node["segment_id"]: node for node in plan["nodes"] if node["kind"] == "segment_av"}
    if any(node["semantic_key"] is None for node in nodes.values()):
        raise RenderContractError("INCREMENTAL_INPUT_CONTRACT_UNVERIFIED")
    # Freeze the bytes actually consumed; re-hashing mutable originals after a
    # render alone would not rule out replacement-and-restore during that render.
    snapshots = {}
    source_map = {}
    used = {visual.source_id for segment in storyboard.segments for visual in resolved_visual_spans(segment)}
    for source in storyboard.sources:
        if source.source_id not in used:
            continue
        identity = inputs["source_identities"][source.source_id]
        key = identity["sha256"]
        if key not in snapshots:
            target = attempt.root / "inputs" / (key + Path(source.path).suffix)
            attempt.prepare(target)
            copy_new(Path(source.path), target, identity)
            snapshots[key] = target
        source_map[source.source_id] = source.model_copy(update={"path": str(snapshots[key])})
    voices = {}
    for segment in storyboard.segments:
        if segment.mode != "voiceover":
            continue
        identity = inputs["audio_identities"][segment.segment_id]
        key = identity["sha256"]
        if key not in snapshots:
            target = attempt.root / "inputs" / (key + Path(segment.audio_file).suffix)
            attempt.prepare(target)
            copy_new(Path(segment.audio_file), target, identity)
            snapshots[key] = target
        voices[segment.segment_id] = snapshots[key]
    _write_new_json(attempt.root / "output" / "render_plan_expected.json", plan)
    return {"inputs": inputs, "nodes": nodes, "source_map": source_map, "voices": voices,
            "cache": SegmentCache(cache_root / "render_cache" / "segment_av_v1", timeout=config.runtime.stage_timeout_sec),
            "artifacts": {}, "receipts": {}, "started": started,
            "key_locks": {node["semantic_key"]: threading.Lock() for node in nodes.values()}}


def _render_incremental_segment_locked(segment: StoryboardSegment, source_map: dict[str, SourceInfo],
                                output: Path, work_dir: Path, config: AppConfig,
                                attempt: _RenderAttempt, incremental: dict) -> None:
    from .render_cache import verify_media
    node = incremental["nodes"][segment.segment_id]
    attempt.prepare(output)
    actual, reasons = incremental["cache"].materialize(node, output)
    action = "reused"
    if actual is None:
        action = "executed"
        token = _segment_render_key.set(node["semantic_key"])
        try:
            if segment.mode == "voiceover":
                rendering = segment.model_copy(update={"audio_file": str(incremental["voices"][segment.segment_id])})
                _render_voiceover_segment(rendering, source_map, output, work_dir, config)
            else:
                _render_original_segment(segment, source_map, output, config)
        finally:
            _segment_render_key.reset(token)
        actual = verify_media(output, node["params"], timeout=config.runtime.stage_timeout_sec, stats=incremental["cache"].stats)
        actual["semantic_key"] = node["semantic_key"]
        actual["cache_manifest"] = str(incremental["cache"].publish(node, output, actual, attempt_id=attempt.attempt_id))
    incremental["artifacts"][node["node_id"]] = actual
    incremental["receipts"][segment.segment_id] = {
        "segment_id": segment.segment_id, "semantic_key": node["semantic_key"],
        "action": action, "reason_codes": reasons if action == "executed" else ["VERIFIED_BYTES_AND_DECODE"],
        "sha256": actual["sha256"], "size": actual["size"], "media_contract": actual["media_contract"],
        "verification_seconds": actual["verification_seconds"], "cache_manifest": actual["cache_manifest"]}


def _render_incremental_segment(segment: StoryboardSegment, source_map: dict[str, SourceInfo],
                                output: Path, work_dir: Path, config: AppConfig,
                                attempt: _RenderAttempt, incremental: dict) -> None:
    key = incremental["nodes"][segment.segment_id]["semantic_key"]
    # Equal local content can occur under distinct stable segment IDs. Recheck
    # the cache after the first producer completes, without sharing write paths.
    with incremental["key_locks"][key]:
        _render_incremental_segment_locked(segment, source_map, output, work_dir,
                                           config, attempt, incremental)
