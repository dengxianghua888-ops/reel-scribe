# Native TEXT-only review candidate (Blender 4.3.2)

`tools/editor-adapters/blender_caption_candidate.py` is a separate versioned observation profile. It compares two saved native projects against a caller-pinned caption map and emits **a review candidate only**. It neither edits the projects nor adopts changes into a storyboard/WorkDocument. The existing strict cut adapter still rejects TEXT; this tool does not change that contract.

Run in an isolated cloud process with scripting disabled:

```sh
blender -b --disable-autoexec --python-exit-code 1 \
  --python tools/editor-adapters/blender_caption_candidate.py -- \
  --base original.blend --edited edited.blend --caption-map caption-map.json \
  --base-sha256 ORIGINAL_SHA --edited-sha256 EDITED_SHA --map-sha256 MAP_SHA \
  --assets-manifest reviewed-assets.json --assets-sha256 ASSETS_SHA \
  --output fresh-review-candidate.json
```

All four hashes must be supplied from the intended reviewed versions, not silently refreshed to bypass a stale-state rejection. The asset manifest is an exact JSON object mapping every resolved absolute media/font path to its reviewed SHA-256, e.g. `{"/media/source.mov":"64-hex-digest", "/fonts/font.ttc":"64-hex-digest"}`. Extra or missing entries and duplicate keys are rejected. Pin this inventory from reviewed source evidence: recomputing it from already-replaced resources cannot establish historical identity. Both projects must match it. An existing output is never overwritten. Opening projects uses `use_scripts=False`; the script never saves a blend or renders. Run only trusted project files in a restricted environment; autoexec disabling is not a universal malicious-file sandbox.

## Supported scope and rejection

Only the active, object-free, node-free sequencer scene in Blender **4.3.2** is supported. MOVIE, SOUND and TEXT strips are compared, with scalar/array RNA, strip custom properties, transform/crop/proxy/stereo/colorspace settings, external media/font bytes, channels (including mute), scene scalar properties, sequence settings, render and color settings. Caption IDs are exact and unique, and all base texts and windows must match the pinned map. Only a TEXT `text` field may differ.

Timing, layer, font, style, non-TEXT media/audio changes, missing/extra/duplicate captions, blank/control-character text, animations/drivers, modifiers, retiming keys, enabled proxies, packed assets, linked libraries, node compositing, motion blur, multiview, enabled color curves and unknown strip/nested pointers are rejected. Assets are hashed again after observation; input blend/map/asset-manifest hashes are checked before and after. Maps and strip counts have limits. No claim is made of full arbitrary native-project equivalence: inactive scenes, UI selection, current preview frame, runtime IDs and inactive bake/curve/multiview structures are outside this profile. These cannot supply supported strip content; referenced scene/effect strips are rejected.

## Time and candidate contract

Map rows carry stable `id`, `text`, zero-based `start_frame`/`end_frame`, `declared_start_sec`/`declared_end_sec` and `start_delta_sec`/`end_delta_sec`. Integer fps and host start frame 1 are required. Each boundary is independently verified as nearest-frame **half-up**, with delta recomputed from original seconds. Windows must be positive, ordered, non-overlapping and within the scene. This is an explicit quantized host representation, not a claim that source subframe clocks were preserved exactly.

Output has `source_rows`, `candidate_rows`, explicit `text_changes`, both snapshots and pinned source hashes. Candidate rows change only the selected texts, retain original seconds/frames/deltas, and have `status=REVIEW_CANDIDATE_ONLY`, `adopted=false`. A later review must decide whether and how to adopt; this tool provides no adoption endpoint.

## Actual evidence and limitations

Actual Blender 4.3.2 `native-text.blend` and `native-edited.blend` reopen comparison preserves 11 caption IDs/windows and identifies only the explicit `【诊断改字】` prefix in caption 0. The original experiment has 1280×534 source geometry, not a completed 720×1280 layered composition. Maximum previously measured quantization is 19.231 ms. Some English cues still contain 4–5 lines, and an inspected Chinese caption overlaps source opening credits. Neither typography/readability nor full vertical layout is accepted by this candidate tool. It is not ASR, listening, translation, film meaning or finished-voice-quality verification.
