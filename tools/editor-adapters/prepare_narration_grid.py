"""Explicit PCM tail-padding candidate; never adopts, renders or drops captions."""

import argparse
import hashlib
import io
import json
import math
import wave
from fractions import Fraction
from pathlib import Path


def require(condition, code):
    if not condition:
        raise ValueError(code)


def common_grid(fps, rates):
    require(type(fps) is int and 1 <= fps <= 120, "INTEGER_FPS_REQUIRED")
    require(
        rates and all(type(r) is int and 1 <= r <= 192000 for r in rates),
        "PCM_RATE_REQUIRED",
    )
    denominator = math.gcd(fps, *rates)
    # Existing storyboard decimal seconds cannot express thirds exactly.
    finite = 1
    for factor in (2, 5):
        while denominator % factor == 0:
            finite *= factor
            denominator //= factor
    return finite


def padded_count(count, rate, grid, max_padding_ms):
    require(type(count) is int and count > 0, "NONEMPTY_PCM_REQUIRED")
    require(rate % grid == 0, "INVALID_SHARED_GRID")
    quantum = rate // grid
    target = ((count + quantum - 1) // quantum) * quantum
    padding = Fraction(target - count, rate)
    require(padding <= Fraction(str(max_padding_ms)) / 1000, "PADDING_LIMIT_EXCEEDED")
    return target


def prepare(source, destination, *, fps, max_padding_ms, acknowledge_padding=False):
    require(acknowledge_padding, "EXPLICIT_PADDING_ACK_REQUIRED")
    require(0 <= max_padding_ms <= 500, "PADDING_LIMIT_MAX_500MS")
    source = Path(source).resolve(strict=True)
    require(source.stat().st_size <= 10_000_000, "STORYBOARD_SIZE_LIMIT")
    raw = source.read_bytes()
    candidate = json.loads(raw)
    require(not candidate.get("output"), "FROZEN_UNRENDERED_CANDIDATE_REQUIRED")
    destination = Path(destination).absolute()
    require(not destination.exists() and not destination.is_symlink(), "OUTPUT_EXISTS")
    require(type(fps) is int and 1 <= fps <= 120, "INTEGER_FPS_REQUIRED")
    require(0 < len(candidate["segments"]) <= 1000, "SEGMENT_LIMIT")
    for segment in candidate["segments"]:
        require(segment["mode"] in ("original", "voiceover"), "UNKNOWN_SEGMENT_MODE")
        require(segment.get("visuals"), "EMPTY_VISUALS")
        for visual in segment["visuals"]:
            start, end = Fraction(str(visual["start"])), Fraction(str(visual["end"]))
            require(0 <= start < end, "INVALID_VISUAL_RANGE")
            require(
                (start * fps).denominator == 1 and (end * fps).denominator == 1,
                "UNALIGNED_VISUAL_BOUNDARY",
            )
    voices = []
    for index, segment in enumerate(candidate["segments"]):
        if segment["mode"] != "voiceover":
            continue
        require(
            segment.get("audio_speed", 1) == 1 and segment.get("mute_original", True),
            "ONLY_UNMIXED_1X_NARRATION",
        )
        path = Path(segment["audio_file"])
        if not path.is_absolute():
            path = source.parent / path
        path = path.resolve(strict=True)
        require(path.stat().st_size <= 140_000_000, "PCM_FILE_SIZE_LIMIT")
        data = path.read_bytes()
        with wave.open(io.BytesIO(data)) as audio:
            require(
                audio.getcomptype() == "NONE"
                and audio.getsampwidth() == 2
                and audio.getnchannels() in (1, 2),
                "PCM_S16LE_ONLY",
            )
            count, rate, channels = (
                audio.getnframes(),
                audio.getframerate(),
                audio.getnchannels(),
            )
            require(0 < count <= rate * 180, "PCM_MAX_180_SECONDS")
            pcm = audio.readframes(count)
            require(len(pcm) == count * channels * 2, "TRUNCATED_PCM")
        require(
            abs(Fraction(str(segment["audio_duration_sec"])) - Fraction(count, rate))
            < Fraction(1, 10**8),
            "DECLARED_AUDIO_DURATION_MISMATCH",
        )
        voices.append((index, path, data, pcm, count, rate, channels))
    grid = common_grid(fps, [v[5] for v in voices])
    changes = []
    cursor = Fraction(0)
    voice_map = {v[0]: v for v in voices}
    for index, segment in enumerate(candidate["segments"]):
        if index in voice_map:
            _, path, data, pcm, count, rate, channels = voice_map[index]
            target = padded_count(count, rate, grid, max_padding_ms)
            duration = Fraction(target, rate)
            budget = sum(
                (
                    Fraction(str(v["end"])) - Fraction(str(v["start"]))
                    for v in segment["visuals"]
                ),
                Fraction(0),
            )
            require(budget >= duration, "INSUFFICIENT_VISUAL_BUDGET")
            require(
                (cursor * rate).denominator == 1 and (cursor * fps).denominator == 1,
                "UNALIGNED_TARGET_START",
            )
            changes.append(
                {
                    "segment_index": index,
                    "segment_id": segment["segment_id"],
                    "original_audio_path": str(path),
                    "original_sha256": hashlib.sha256(data).hexdigest(),
                    "original_samples": count,
                    "padded_samples": target,
                    "rate": rate,
                    "channels": channels,
                    "added_silence_sec": str(duration - Fraction(count, rate)),
                    "additional_source_picture_sec": str(
                        duration - Fraction(count, rate)
                    ),
                }
            )
            segment["audio_duration_sec"] = float(duration)
            segment["audio_source_duration_sec"] = float(duration)
            segment["planned_duration_sec"] = float(duration)
            segment["notes"] = segment.get("notes", "") + (
                " Explicit diagnostic grid candidate: PCM tail silence added; picture budget consumption extends; NOT adopted or QC accepted."
            )
        else:
            duration = sum(
                (
                    Fraction(str(v["end"])) - Fraction(str(v["start"]))
                    for v in segment["visuals"]
                ),
                Fraction(0),
            )
            require((duration * fps).denominator == 1, "UNALIGNED_ORIGINAL_DURATION")
        cursor += duration
    require(
        source.read_bytes() == raw
        and all(p.read_bytes() == data for _, p, data, *_ in voices),
        "INPUT_CHANGED",
    )
    destination.mkdir(parents=True, exist_ok=False)
    for change in changes:
        index = change["segment_index"]
        _, path, data, pcm, count, rate, channels = voice_map[index]
        target = change["padded_samples"]
        out = destination / f"narration-{index}.wav"
        with wave.open(str(out), "wb") as w:
            w.setnchannels(channels)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm + b"\0" * ((target - count) * channels * 2))
        with wave.open(str(out)) as w:
            actual = w.readframes(w.getnframes())
            require(
                w.getnframes() == target
                and actual[: len(pcm)] == pcm
                and not any(actual[len(pcm) :]),
                "PCM_PREFIX_VERIFICATION_FAILED",
            )
        change["padded_sha256"] = hashlib.sha256(out.read_bytes()).hexdigest()
        candidate["segments"][index]["audio_file"] = str(out)
    candidate["target_duration_sec"] = float(cursor)
    receipt = {
        "schema": "narration-grid-candidate/1",
        "source_storyboard_sha256": hashlib.sha256(raw).hexdigest(),
        "fps": fps,
        "grid_denominator": grid,
        "changes": changes,
        "max_padding_ms_per_segment": max_padding_ms,
        "total_added_silence_sec": str(
            sum((Fraction(c["added_silence_sec"]) for c in changes), Fraction(0))
        ),
        "adopted": False,
        "qc_status": "NOT_RUN",
        "plan_revalidation_required": True,
        "caption_text_and_timing_declarations": "preserved in candidate; output-timing must be rebuilt and reviewed",
        "vertical_layout": "not_changed_or_validated",
        "editable_captions": "not_implemented",
    }
    candidate["narration_grid_candidate"] = receipt
    (destination / "source-storyboard.json").write_bytes(raw)
    (destination / "candidate-storyboard.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2)
    )
    (destination / "receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2)
    )
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    parser.add_argument("--fps", type=int, required=True)
    parser.add_argument("--max-padding-ms", type=int, required=True)
    parser.add_argument("--acknowledge-padding", action="store_true")
    a = parser.parse_args()
    print(
        json.dumps(
            prepare(
                a.source,
                a.destination,
                fps=a.fps,
                max_padding_ms=a.max_padding_ms,
                acknowledge_padding=a.acknowledge_padding,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
