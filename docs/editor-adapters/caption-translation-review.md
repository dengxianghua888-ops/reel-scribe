# Pinned translation-draft comparison, not automatic translation

`tools/editor-adapters/review_caption_translation.py` compares a separately authored Chinese translation draft with a pinned source caption map, its context and a pinned font. It produces only a review report. It does **not** translate, alter source captions/projects, generate a directly adoptable cue map, change timing or approve meaning.

```sh
python tools/editor-adapters/review_caption_translation.py \
  --source-map caption-map.json --source-sha256 SOURCE_SHA \
  --draft translation-draft.json --draft-sha256 DRAFT_SHA \
  --font /absolute/font.ttc --font-sha256 FONT_SHA \
  --fps 24 --frame-end 984 --minimum-size 32 --maximum-size 40 \
  --output fresh-translation-review.json
```

All three files must match the supplied hashes before and after analysis; the JSON inputs have size limits and duplicate-key rejection. The safe writer serializes/encodes before exclusively creating output and never overwrites a previous report.

For each JSON input, the tool reads at most 10,000,001 bytes once, rejects anything above 10,000,000 bytes, and hashes and parses that same captured byte sequence. A separate pathname read cannot supply different text under the pinned JSON hash. The final pathname checks still reject persistent drift. These checks are not filesystem locking. The build now also captures the pinned font once and verifies the same bytes supplied to every Pillow measurement through an in-memory stream, shared with the readability planner. A 64 MiB font limit bounds capture memory (at most 64 MiB + 1 byte is read); larger inputs raise FONT_SIZE_LIMIT without a report. Existing Noto CJK collections of approximately 20–28 MB are within the limit. The final font-path check still rejects persistent drift. Direct internal review/fit calls with the legacy pathname API remain unpinned; native-project observation is not changed.

## Draft schema

The root has exactly `schema="caption-translation-draft/1"` and `entries`. Each entry has exactly:

- `id`: unique existing source cue ID;
- `source_text`: exact source cue text, including original wrapping;
- `target_text`: nonblank single paragraph without LF/CR or Unicode line/paragraph separators (U+2028/U+2029); existing text safety and limited Unicode/grapheme rules apply;
- `target_language`: exactly `zh-CN`, a declaration, not proof of the text's actual language;
- `context_ids`: unique existing source IDs to show alongside the translation;
- `fidelity_notes`: list of nonblank draft notes, possibly empty;
- `omitted_information`: list of declared omissions, possibly empty.

Unknown fields, duplicate/unknown IDs, missing fields, mismatched source text or unknown context are rejected. Fields such as `approved` or `adopted` cannot be inserted to trigger acceptance. Free-form notes are reported as **unverified draft statements**, never treated as authorization or an instruction. No actual movie translation is hardcoded in the tool.

## Honest measurements and boundaries

The report displays original text, original frame/second windows and quantization deltas, context text/windows, unchanged draft target text, draft fidelity/omission notes and original versus target non-whitespace character rates. It uses the exact pinned font's face 0 with the previously reviewed pixel-width/two-line planner. Sizes are explicit and never below 32 px. A target that cannot fit yields `GEOMETRY_CONFLICT_AT_MINIMUM_SIZE`, retains the full target text and provides no truncated lines. The tool does not delete words or silently shrink text further.

Measured fit remains **Pillow-only**, not Blender raster verification. The two-second duration and twenty-character-per-second thresholds are diagnostic prompts, not new acceptance gates. A one-second cue retains a short-window warning even when a shorter Chinese draft lowers its character rate; it is neither automatically failed nor declared readable. All entries retain `semantic_fidelity=UNVERIFIED`, `audio_alignment=UNVERIFIED`, `human_readability=UNVERIFIED` and `adopted=false`. No `PASS` status is emitted.

Translation accuracy, implied meaning, contextual omissions and actual listening require independent review. An empty omission list does not prove that nothing was omitted. Existing clock quantization is not speech timing verification. No asset is uploaded and no external translation/voice provider is called.
