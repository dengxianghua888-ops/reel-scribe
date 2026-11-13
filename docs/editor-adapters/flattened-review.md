# Explicit flattened review derivative (experimental)

This is NOT source-editable film exchange and NOT a lossless roundtrip. The exact-cut exporter retains its geometry and frame-alignment refusals. This separate command accepts only a rendered 24 fps / 48 kHz film with burned captions, validates its SHA and source-storyboard segment binding, and requires `--ack-lossy-review`. It creates a fresh destination; it never mutates/adopts the original 09 storyboard.

```
python tools/editor-adapters/flattened_review_export.py --rendered-storyboard rendered-storyboard.json --source-storyboard 09_storyboard.json --output new-review-folder --ack-lossy-review
```

Layout, subtitles and original/narration mix remain baked in the picture/audio. H264 is re-encoded at CRF18 (generation loss); subtitle text, narration and individual original shots cannot be independently edited. The output is an ordinary single-source cut package with isolated authority identity. Do not adopt it into the source film workspace. A JSON provenance declaration is not a universal authorization firewall against arbitrary third-party manipulation.

At 24 fps, append 0–2 copies of the last video frame to reach a finite-decimal duration divisible by three frames, and pad PCM to that length. This is explicit review-only padding, not silent rounding of the source story. All frames/sample counts are verified with the existing full-frame probe. Unsupported rates, channels, non-CFR clocks and inputs over 180 seconds fail. Audio decoding is capped at 181 seconds and 120 seconds wall time; longer-than-target decoded audio is rejected, never truncated. Header limits are early checks, not proof of actual samples; full-frame probing and PCM prefix comparison still apply. The command needs the existing Python film dependencies and ffmpeg/ffprobe; it does not install anything or call a remote service.

## Actual diagnostic evidence

Base implementation 0d6642b61acbb76d7346f079bf363d3cb20f2868; public CC BY Tears of Steel plus user-approved offline eSpeak diagnostic. Original final video SHA 2cc4c2fc84719f956a9ee7bc833d6b7112d406b4011e7425a074d1340c9af7f8. Derived media SHA f490050a455a9de19a0184acc70cf6474dec022d67e9285a3f77a958572a0647.

973 frames became 975 (40.625 seconds), 720x1280. PCM decoded source 1,947,648 samples is byte-identical to the derivative prefix; 2,352 appended stereo sample frames are silence, total 1,950,000. This is sample evidence, not listening or final voice quality.

Blender 4.3.2 import/save/reopen/readback succeeded. Separate explicit editing experiments also succeeded: trimming both tracks three frames to 972 intentionally removes an original picture frame and may remove original audio; trimming two frames to 973 preserves original picture count but can still trim decoded audio tail. Neither trimmed version is claimed lossless. The untrimmed 975-frame derivative preserves the full decoded source PCM prefix. No readback was adopted.

Remaining: layered vertical composition, editable captions and exact narration sample/frame reconciliation are NOT implemented. Semantic/listening/style acceptance remains outstanding; upstream DEGRADED is not promoted by this export. Full-film retrieval and subjective story quality remain separate.
