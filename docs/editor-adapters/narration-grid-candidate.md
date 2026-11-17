# Explicit PCM narration grid candidate (experimental)

This preparer addresses one bounded gap: narration sample counts that cannot be represented on the existing exact CFR/decimal timeline. It does not add vertical-layout or native editable-caption support. It never adopts, renders, rewrites the source 09, calls TTS, changes audio speed or removes original audio samples.

```
python tools/editor-adapters/prepare_narration_grid.py --source 09_storyboard.json --destination new-grid-candidate --fps 24 --max-padding-ms 500 --acknowledge-padding
```

Only unmixed 1x PCM S16LE mono/stereo narration is accepted. A finite-decimal grid must divide the video frame rate and every narration sample rate. For 24fps/22050Hz that grid is 0.5 seconds; for 24fps/48000Hz it is 0.125 seconds. Each voiceover is rounded UP by explicitly appending zero samples. A configurable maximum of 500ms applies PER SEGMENT, not to the entire film. Insufficient visual availability, invalid/off-grid visual boundaries, output conflicts or sample/declaration disagreement fail closed. Inputs are preserved, and the receipt records both additional silence and additional consumed source-picture duration. This may change pacing and reveal timing, so it requires plan/preflight/semantic review before any adoption.

Subtitle text, original-cue and word-boundary declarations remain unchanged. Their output placement and estimated timing must be rebuilt/reviewed; preserving declarations does NOT certify native caption import or word-level synchronization. The source plan fingerprint is retained as lineage, not an assertion that the changed timing plan has passed.

## Real bounded experiment

Public CC BY Tears of Steel plus explicitly approved offline mechanical eSpeak diagnosis:
- intro: 226972 original 22050Hz samples +4553 zero samples =231525 (10.5s).
- later: 346182 original samples +6618 zero samples =352800 (16s).
- Each original PCM prefix was independently compared byte-for-byte; additions are silence. Total added duration is 506.621315ms across two segments, not below500ms for the whole film.
- Original 14.5s exchange unchanged; new candidate41s. Original09 SHA bc27874853e0c4b08ad1c245e98cb03b9207c34125363fa9104c1595bf82d241 remains unchanged.
- The isolated host experiment used source geometry1280x534 solely for cut-clock verification, NOT the requested720x1280 film layout. Candidate subtitle declarations and a review SRT remain available; this host experiment explicitly omitted caption import because the adapter still rejects it. No final film was rendered from this experiment.
- Actual Blender4.3.2: three MOVIE strips, one original SOUND strip and two separate PCM narration SOUND strips; save/reopen/readback passed. A deliberate half-second trim of the original exchange followed by paired picture/narration ripple also passed. This edit removes content and is not semantic acceptance. Moving later narration alone correctly failed HOST_NARRATION_PICTURE_CHANGED and produced no accepted OTIO.

## Remaining capabilities

Vertical composition requires native transform/layer representation, bounded readback of each transform and visual equivalence verification. Editable subtitles require native TEXT-strip identity/font/style/timing mapping and negative tests rather than deleting caption sidecars. More general rational timing requires a schema-level exact frame/sample clock contract, not float tolerances. This small step keeps those unsupported and unclaimed. Listening, style preference and narrative acceptance remain outstanding.
