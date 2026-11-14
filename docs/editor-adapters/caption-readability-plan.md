# Fixed-time portrait caption readability candidate

`tools/editor-adapters/plan_caption_readability.py` produces a **plan only**, not a rendered video, native project, or adopted storyboard. It uses the already-installed Pillow and an explicitly pinned font file. No model, service or software installation is performed.

```sh
python tools/editor-adapters/plan_caption_readability.py \
  --caption-map caption-map.json --map-sha256 MAP_SHA \
  --font /absolute/font.ttc --font-sha256 FONT_SHA \
  --fps 24 --frame-end 984 --minimum-size 32 --maximum-size 40 \
  --acknowledge-reflow --output fresh-layout.json
```

The acknowledgment declares **existing generated line breaks to be soft wraps**, not poetic/semantic line breaks. Adjacent Chinese characters separated by a newline are rejoined; other old newlines become spaces. Non-whitespace characters, punctuation and spelling must remain identical. Fitting Latin words are not split. Punctuation boundaries are preferred where both lines fit. This is not Chinese word segmentation or translation.

Every original cue ID, source seconds, host frame window and quantization delta is retained unchanged. No cue is split, paginated, extended or moved; no word timestamps are fabricated. A single font size is chosen for all cues, largest fitting within the explicit range, never below 32 pixels. If any cue cannot fit two lines at the minimum, the entire plan fails rather than dropping text or quietly shrinking it. Pixel-width and conservative line-height measurements use the exact font bytes and font face 0. Input map/font hashes are checked before and after; output is exclusive and never overwrites a file.

## Proposed spatial layout

Coordinates are top-left pixels on 720×1280 canvas:

- Whole-picture fit box: x=0, y=160, width=720, height=600. Preserve the entire source picture and aspect ratio; unused canvas is black, not stretched or cropped.
- Separate caption box: x=48, y=900, width=624, height=240. It does not overlap the picture box. Subtitles on the source picture remain part of the original picture and are not erased.

This deliberately conservative layout trades picture size for a physically separate caption area. It is a review alternative, not a claimed final visual style. Host coordinates must be explicitly converted from the top-left convention. Pillow width/height is **not** a substitute for actual Blender raster verification: the resulting native render must be inspected for font equivalence, clipping, glyphs, placement and overlap.

## Space is not reading-time acceptance

Measurements include host-window duration, non-whitespace characters per second and ASCII-English words per minute. Flags use diagnostic triggers of <2 seconds, >20 non-whitespace characters/second, or >240 English words/minute; these are review prompts, **not universal standards or proof of human readability**. Text-only changes are not automatically made to improve these numbers.

The real 11-cue test can fit at a unified 36 px with no more than two lines in the pinned Noto font. Its one-second caption 6 still contains 37 non-whitespace characters (43 including spaces), so spatial fit does not solve reading time. Preserve that limitation and obtain semantic/listening review before any rewriting, shortening or timing change. The existing spelling `Fourty` and any source-caption alignment uncertainty are deliberately retained, not silently corrected. Original pictures, voice, dialogue and cue timing remain unchanged by this planning tool.

The real layout experiment starts from the prior **41-second PCM-padding candidate**, not the authoritative original approximately 40.493-second storyboard. It is a separate derivative, not automatic end-to-end adoption. Full-picture fitting preserves the field of view but resamples source pixels; it is not pixel-lossless. The existing TEXT-only edit-candidate tool still rejects geometry/style changes. This spatial experiment does not relax that tool or convert its text-only acceptance into layout acceptance.


## Deliberately limited text segmentation

The line-break heuristic protects ASCII words, Latin code points U+00C0–U+024F and straight/curly apostrophe connectors (U+2018/U+2019), and permits character boundaries for the supported Chinese use case. It is not a tokenizer for every script. Combining-mark sequences (Unicode categories M, including variation selectors) are explicitly rejected instead of being split into unattached marks; the tool does not normalize or discard them. Complex-script/grapheme handling requires a separate implementation and actual font verification. Frames per second and final frame must be positive integers, not booleans or fractional values.
