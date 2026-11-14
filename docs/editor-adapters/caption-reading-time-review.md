# Reading-time conflicts: review only

`tools/editor-adapters/analyze_caption_reading_time.py` consumes a pinned `caption-readability-plan/1` JSON and emits options/conflicts, **not a changed caption map**. No media, font, source storyboard or saved project is modified.

```sh
python tools/editor-adapters/analyze_caption_reading_time.py \
  --layout readability-layout-reviewed.json --layout-sha256 LAYOUT_SHA \
  --output fresh-reading-review.json
```

The tool checks duplicate JSON keys, required source/font references, positive integer timebase, source and candidate caption identities/order, original clocks/quantization, identical non-whitespace text and diagnostic word counts. Source and candidate fields except text must match. Existing measurements/flags must match recomputation from actual caption text. The input hash is checked before and after; output is exclusively created using the existing safe candidate writer.

## What is calculated

For each cue, required diagnostic frames are the maximum of:

- `2 × fps`;
- `ceil(non-whitespace characters × fps / 20)`;
- `ceil(ASCII-English words × 60 × fps / 240)`.

These are the existing layout planner's diagnostic thresholds, **not universal human readability standards**. Integer arithmetic avoids rounding down a required fraction of a frame. English words use the same ASCII token heuristic, including straight/curly apostrophe and hyphen connectors. Font is a pinned source reference, not reopened or remeasured by this timing-only tool.

Only a tail-extension option is considered: keep the original start and text; extend the end by the minimum required frames. An option is listed only when the entire added tail fits before the next caption start or scene end. If insufficient, `proposed_window=null` and a conflict reports required extra frames, available tail and shortfall. No partial extension, borrowing before the start, merging, deletion, rewriting or scene overrun is performed. Unflagged cues are identified but no new cue map is produced.

Every option reports the original/proposed window and added tail lag in frames, with `sync_status=UNVERIFIED`, `adopted=false`. This lag is an intentional proposed persistence change, **not** the existing nearest-frame quantization error. An interval without SRT text does not prove silence, the end of spoken dialogue, or semantic space. A human must review the actual audio/content and choose whether any option is appropriate; passing numeric diagnostics is not original-speech alignment or final readability acceptance.

The current experiment remains based on the 41-second PCM-padding review candidate, not automatic adoption into the authoritative original storyboard. Source spelling, cue content and all actual windows remain untouched. Where space conflicts persist, editing text, dividing cues using verified word timing, changing sequence timing or combining content are separate editorial decisions with their own validation; this tool neither chooses nor implements them.
