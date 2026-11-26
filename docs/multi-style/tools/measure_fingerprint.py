#!/usr/bin/env python3
"""Measure a video's style fingerprint and suggest the nearest catalog packs (design-stage prototype).

Measures what can be measured without models: cut rhythm (FFmpeg scene score), motion energy,
loudness (EBU R128), tone and colour (luma, contrast, warmth, saturation, 5-colour palette).
Caption density, graphics density and ornament need OCR or human labels and are left null.

The style vector uses only the measurable axes (tempo, warmth, contrast, motion); nearest packs are
ranked on those axes alone, so the result is a starting point for a human or the router, not a verdict.

Usage: python3 measure_fingerprint.py VIDEO [--packs ../catalog/packs.json] [--out result.json]
"""
import argparse
import json
import math
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SCENE_CUT = 0.30          # FFmpeg scene score above which a frame starts a new shot
SAMPLE_FPS = 2            # frames per second sampled for colour statistics
SAMPLE_W, SAMPLE_H = 96, 54


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def probe(path):
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height,r_frame_rate",
               "-of", "json", str(path)])
    info = json.loads(out.stdout)
    video = next(s for s in info["streams"] if s["codec_type"] == "video")
    num, den = (int(x) for x in video["r_frame_rate"].split("/"))
    return {"duration_s": float(info["format"]["duration"]), "width": video["width"], "height": video["height"],
            "fps": num / den, "has_audio": any(s["codec_type"] == "audio" for s in info["streams"])}


def scene_scores(path):
    res = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
               "select='gte(scene,0)',metadata=print:key=lavfi.scene_score", "-f", "null", "-"])
    times, scores, t = [], [], None
    for line in res.stderr.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            t = float(m.group(1))
        m = re.search(r"lavfi\.scene_score=([0-9.]+)", line)
        if m and t is not None:
            times.append(t)
            scores.append(float(m.group(1)))
    return np.array(times), np.array(scores)


def loudness(path):
    res = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"])
    summary = res.stderr.split("Summary:")[-1]
    i = re.search(r"I:\s+(-?[0-9.]+) LUFS", summary)
    p = re.search(r"Peak:\s+(-?[0-9.]+) dBFS", summary)
    return (float(i.group(1)) if i else None), (float(p.group(1)) if p else None)


def colour(path):
    res = subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf",
                          f"fps={SAMPLE_FPS},scale={SAMPLE_W}:{SAMPLE_H}", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True)
    frames = np.frombuffer(res.stdout, dtype=np.uint8).reshape(-1, SAMPLE_H, SAMPLE_W, 3).astype(np.float32) / 255.0
    r, g, b = frames[..., 0], frames[..., 1], frames[..., 2]
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    mx, mn = frames.max(axis=-1), frames.min(axis=-1)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    pixels = frames.reshape(-1, 3)
    rng = np.random.default_rng(0)
    pick = pixels[rng.choice(len(pixels), size=min(20000, len(pixels)), replace=False)]
    centres = pick[rng.choice(len(pick), size=5, replace=False)]
    for _ in range(20):
        labels = np.argmin(((pick[:, None, :] - centres[None]) ** 2).sum(-1), axis=1)
        centres = np.array([pick[labels == k].mean(0) if np.any(labels == k) else centres[k] for k in range(5)])
    share = np.bincount(labels, minlength=5) / len(labels)
    order = np.argsort(-share)
    palette = ["%02X%02X%02X" % tuple(int(round(c * 255)) for c in centres[k]) for k in order]
    return {"frames_sampled": int(len(frames)), "luma_mean": float(luma.mean()), "luma_std": float(luma.std()),
            "warmth_rb": float((r - b).mean()), "saturation_mean": float(sat.mean()),
            "palette": palette, "palette_share": [round(float(share[k]), 3) for k in order]}


def clamp(x):
    return max(0.0, min(1.0, x))


LOW_MARGIN = 0.03         # top-1 minus top-10 similarity below this: the measured axes do not pick a pack


def nearest_packs(vector, packs_path, k=5):
    packs = json.loads(Path(packs_path).read_text(encoding="utf-8"))["packs"]
    axes = [a for a, v in vector.items() if v is not None]
    ranked = []
    for p in packs:
        d = math.sqrt(sum((p["vector"][a] - vector[a]) ** 2 for a in axes)) / math.sqrt(len(axes))
        ranked.append((round(1 - d, 3), p["id"], p["name"], p["scenario_name"]))
    ranked.sort(reverse=True)
    votes = {}
    for _, _, _, sc in ranked[:20]:
        votes[sc] = votes.get(sc, 0) + 1
    margin = round(ranked[0][0] - ranked[9][0], 3)
    discrimination = {
        "top1": ranked[0][0], "top10": ranked[9][0], "margin_top1_top10": margin,
        "verdict": "low" if margin < LOW_MARGIN else "usable",
        "scenario_votes_top20": dict(sorted(votes.items(), key=lambda kv: -kv[1])[:6]),
    }
    return [{"similarity": s, "pack": i, "name": n, "scenario": sc} for s, i, n, sc in ranked[:k]], axes, discrimination


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--packs", default=str(HERE.parent / "catalog" / "packs.json"))
    ap.add_argument("--out")
    args = ap.parse_args()
    path = Path(args.video)
    meta = probe(path)
    times, scores = scene_scores(path)
    cuts = times[scores >= SCENE_CUT]
    cuts = cuts[cuts > 0.2]
    shots = len(cuts) + 1
    lufs, peak = loudness(path) if meta["has_audio"] else (None, None)
    col = colour(path)
    cuts_per_min = len(cuts) / (meta["duration_s"] / 60)
    motion_energy = float(np.mean(scores[scores < SCENE_CUT])) if np.any(scores < SCENE_CUT) else 0.0
    vector = {
        "tempo": round(clamp(cuts_per_min / 40), 3),                 # 40 cuts/min ≈ the fastest edits in the catalog
        "density": None,                                             # needs OCR of captions and graphics
        "ornament": None,                                            # needs human or model labels
        "warmth": round(clamp(0.5 + col["warmth_rb"] * 2.5), 3),     # R-B of ±0.2 spans the axis
        "contrast": round(clamp(col["luma_std"] / 0.3), 3),
        "formality": None,
        "motion": round(clamp(motion_energy * 8), 3),
    }
    near, axes, discrimination = nearest_packs(vector, args.packs)
    result = {
        "schema": "style-fingerprint/1",
        "source": {"path": path.name, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in meta.items()}},
        "exemplar_fingerprint": {
            "avg_shot_s": round(meta["duration_s"] / shots, 3),
            "cuts_per_min": round(cuts_per_min, 2),
            "loudness_lufs": lufs,
            "measured_with": [f"ffmpeg scene score >= {SCENE_CUT}", "ffmpeg ebur128", f"rgb sampling {SAMPLE_FPS} fps"],
        },
        "measurements": {"shots": shots, "cut_times_s": [round(float(t), 3) for t in cuts], "true_peak_dbfs": peak,
                         "motion_energy": round(motion_energy, 4), **col},
        "style_vector_partial": vector,
        "nearest_packs": near,
        "ranked_on_axes": axes,
        "discrimination": discrimination,
        "limits": ["字幕密度、图形密度、装饰度与正式度需要 OCR 或人工标注，未测",
                   "切点阈值对快速运动与闪光敏感，需人工抽检",
                   "最近包只在可测的轴上比较，是路由与人工的起点，不是结论",
                   "运动能量的换算系数尚未用标注样本校准"],
    }
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
