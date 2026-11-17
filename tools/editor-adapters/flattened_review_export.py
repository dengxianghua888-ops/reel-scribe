"""Explicit lossy flattened review derivative. Never updates film authority."""

import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

R = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(R / "workflows/raven-film-recap/douyin-film-recap/src"))
from douyin_film_recap.otio_exchange import (
    collect_media_facts,
    export_frozen_storyboard,
)


def require(condition, code):
    if not condition:
        raise ValueError(code)


def review_clock(frames, rate):
    """Explicit 24fps finite-decimal boundary; never trims source video."""
    if type(frames) is not int or frames <= 0 or Fraction(rate) != 24:
        raise ValueError("ONLY_POSITIVE_24FPS_REVIEW_SUPPORTED")
    target = ((frames + 2) // 3) * 3
    return target, target - frames, Fraction(target, 24)


def verify_pcm_prefix(original, derived):
    require(len(original) % 4 == 0 and len(derived) % 4 == 0, "PCM_STEREO_ALIGNMENT")
    require(len(derived) >= len(original), "AUDIO_WOULD_BE_TRIMMED")
    require(derived[: len(original)] == original, "PCM_PREFIX_CHANGED")
    require(not any(derived[len(original) :]), "PADDING_NOT_SILENCE")
    return {
        "source_decoded_samples": len(original) // 4,
        "derivative_samples": len(derived) // 4,
        "appended_silent_samples": (len(derived) - len(original)) // 4,
    }


def decode_pcm(path):
    return subprocess.check_output(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-map",
            "0:a:0",
            "-t",
            "181",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-",
        ],
        timeout=120,
    )


def build(rendered_path, storyboard_path, O, *, ack_lossy_review=False):
    if not ack_lossy_review:
        raise ValueError("EXPLICIT_LOSSY_REVIEW_ACK_REQUIRED")
    rendered_path = Path(rendered_path).resolve(strict=True)
    storyboard_path = Path(storyboard_path).resolve(strict=True)
    O = Path(O)
    if O.exists() or O.is_symlink():
        raise ValueError("OUTPUT_EXISTS")
    O.mkdir(parents=True, exist_ok=False)
    rendered_bytes = rendered_path.read_bytes()
    source_bytes = storyboard_path.read_bytes()
    render = json.loads(rendered_bytes)
    source = Path(render["output"]["final_video"])
    require(
        render["output"]["subtitle_burn_status"] == "applied",
        "BURNED_CAPTIONS_REQUIRED",
    )
    upstream = json.loads(source_bytes)
    require(
        render["plan_fingerprint"] == upstream["plan_fingerprint"],
        "UPSTREAM_PLAN_MISMATCH",
    )
    require(render["sources"] == upstream["sources"], "UPSTREAM_SOURCE_MISMATCH")
    clean = lambda rows: [
        {
            k: v
            for k, v in x.items()
            if k not in ("rendered_file", "rendered_duration_sec", "status")
        }
        for x in rows
    ]
    require(
        clean(render["segments"]) == clean(upstream["segments"]),
        "UPSTREAM_SEGMENT_MISMATCH",
    )
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    expected = render["output"]["final_fingerprint"]
    require(sha(source) == expected, "RENDER_SHA_MISMATCH")
    probe = json.loads(
        subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(source)]
        )
    )
    v = next(s for s in probe["streams"] if s["codec_type"] == "video")
    a = next(s for s in probe["streams"] if s["codec_type"] == "audio")
    rate = Fraction(v["avg_frame_rate"])
    require(rate == 24 and a["sample_rate"] == "48000", "ONLY_24FPS_48KHZ_SUPPORTED")
    frames = int(v["nb_frames"])
    require(0 < frames <= 24 * 180, "REVIEW_MAX_180_SECONDS")
    target, extra, duration = review_clock(frames, rate)
    require(Fraction(a["duration"]) <= duration, "AUDIO_HEADER_EXCEEDS_TARGET")
    input_facts = collect_media_facts(
        {
            "sources": [
                {"source_id": "input", "path": str(source), "fingerprint": expected}
            ],
            "segments": [],
        }
    )["input"]
    require(a["channels"] == 2, "ONLY_STEREO_SUPPORTED")
    require(input_facts["frame_count"] == frames, "INPUT_FRAME_COUNT_MISMATCH")
    require(
        extra in (0, 1, 2) and duration.denominator in (1, 2, 4, 8),
        "INVALID_REVIEW_CLOCK",
    )
    original_pcm = decode_pcm(source)
    require(len(original_pcm) // 4 <= int(duration * 48000), "AUDIO_WOULD_BE_TRIMMED")
    media = O / "flattened-review-v2.mov"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-n",
            "-i",
            str(source),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0",
            "-vf",
            f"tpad=stop_mode=clone:stop={extra}",
            "-af",
            f"apad=whole_len={int(duration * 48000)},atrim=end_sample={int(duration * 48000)},asetpts=N/SR/TB",
            "-c:v",
            "libx264",
            "-crf",
            "18",
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "pcm_s16le",
            "-ar",
            "48000",
            "-video_track_timescale",
            "24000",
            str(media),
        ],
        check=True,
    )
    require(sha(source) == expected, "SOURCE_CHANGED_DURING_DERIVATION")
    require(
        rendered_path.read_bytes() == rendered_bytes
        and storyboard_path.read_bytes() == source_bytes,
        "STORYBOARD_CHANGED_DURING_DERIVATION",
    )
    pcm_evidence = verify_pcm_prefix(original_pcm, decode_pcm(media))
    provenance = {
        "pcm_evidence": pcm_evidence,
        "schema": "flattened-review-derivative/1",
        "readback_policy": "review-only-no-authority-adoption",
        "upstream_storyboard_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "upstream_render_sha256": sha(source),
        "derivative_sha256": sha(media),
        "flattened": ["layout", "subtitles", "original/narration mix"],
        "losses": [
            "H264 generation loss",
            "individual source shots, subtitles and narration are no longer independently editable",
        ],
        "input_video_frames": frames,
        "output_video_frames": target,
        "appended_last_frames": extra,
        "original_video_duration": str(Fraction(frames, 24)),
        "derivative_duration": str(duration),
        "audio_header_duration": a["duration"],
        "padding_policy": "explicit cloned final frames plus silence to rational finite-decimal frame boundary; no speech stretched or removed",
        "adoption_performed": False,
        "acceptance": "diagnostic only; upstream DEGRADED unchanged",
    }
    (O / "provenance.json").write_text(json.dumps(provenance, indent=2))
    sb = {
        "project_name": "FLATTENED REVIEW ONLY - NOT SOURCE EDITS",
        "sources": [
            {
                "source_id": "baked",
                "path": str(media),
                "fingerprint": sha(media),
                "filename": media.name,
                "duration": float(duration),
                "width": v["width"],
                "height": v["height"],
                "fps": 24,
                "has_audio": True,
                "size_bytes": media.stat().st_size,
            }
        ],
        "plan_fingerprint": hashlib.sha256(b"flattened-review-only").hexdigest(),
        "target_duration_sec": float(duration),
        "segments": [
            {
                "segment_id": "baked",
                "beat_id": "baked",
                "mode": "original",
                "title": "Baked subtitles, picture and mix",
                "text": "",
                "visuals": [{"source_id": "baked", "start": 0, "end": float(duration)}],
                "audio_owner": "original_dialogue",
                "mute_original": False,
                "planned_duration_sec": float(duration),
                "notes": "Review derivative ONLY. No reverse mapping or source-storyboard adoption.",
            }
        ],
        "derivative_provenance": provenance,
    }
    raw = json.dumps(sb, ensure_ascii=False, indent=2).encode()
    (O / "derivative-storyboard.json").write_bytes(raw)
    facts = collect_media_facts(sb)
    (O / "facts.json").write_text(json.dumps(facts, indent=2))
    require(
        facts["baked"]["frame_count"] == target
        and facts["baked"]["duration_samples"] == int(duration * 48000),
        "DERIVATIVE_CLOCK_MISMATCH",
    )
    result = export_frozen_storyboard(
        raw,
        O / "package",
        authority={
            "storyboard_sha256": hashlib.sha256(raw).hexdigest(),
            "workspace_generation": "isolated-flattened-review-NOT-film-authority",
        },
        profile={"fps": 24, "width": v["width"], "height": v["height"]},
        media_facts=facts,
        reference_render=source,
    )
    (O / "export-result.json").write_text(json.dumps(result, indent=2))
    print(json.dumps(provenance, indent=2))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rendered-storyboard", required=True)
    parser.add_argument("--source-storyboard", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ack-lossy-review", action="store_true")
    args = parser.parse_args()
    build(
        args.rendered_storyboard,
        args.source_storyboard,
        args.output,
        ack_lossy_review=args.ack_lossy_review,
    )
