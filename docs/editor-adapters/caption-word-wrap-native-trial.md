# Word-aware SRT wrapping and native TEXT feasibility

## Shipped correction

Latin-word captions no longer wrap ordinary fitting words at arbitrary character positions (the real Tears of Steel cue had `ju` / `st`). Spaces after punctuation are retained instead of `Fine! I'm` collapsing to `Fine!I'm`. The supported token class is ASCII plus Latin-1 letters/digits and internal apostrophes/hyphens, not all scripts/combining sequences. Words longer than the hard code-point line limit still use an explicit hard-width fallback. This is not font-pixel measurement. Pure Chinese captions retain their previous sentence/punctuation wrapping path.

Real diagnostic SRT comparison: all11 cue starts/ends and every non-whitespace character are unchanged. Corrected SRT SHA256 d689c2172d6f2e36253fdb3dcac50d7cb298612a0c12498e0683671585c2eb6b. English original-sound cues can still occupy4–5lines; this existing original-cue layout path does not enforce the desired two-line readability result. This patch fixes broken fitting words, not all typography or subtitle accessibility.

## Actual Blender4.3.2 experiment, NOT production adapter support

On an isolated copy of the41-second source-geometry narration engineering project, eleven native TEXT strips were created from the complete corrected cue list, preserving text and source times in a separate map. Explicit nearest-frame half-up projection was recorded at24fps (maximum observed boundary displacement19.231ms). It is not exact sample/word synchronization, and no authoritative storyboard was adopted.

A real save/reopen verified every caption ID, string and projected frame window. A separate edit prefixed only caption0 with a diagnostic marker; another save/reopen confirmed only that string changed while all other texts and every window remained unchanged. A real1280x534 PNG showed CJK text rendering using installed Noto Sans CJK; source opening credits overlap the trial text. Therefore native text editability is feasible but layout/readability is NOT accepted.

The ordinary strict adapter still correctly fails with HOST_STRIP_TYPE_UNSUPPORTED on this TEXT-bearing project and produces no accepted OTIO. No caption sidecar was deleted or emptied to disguise this limitation. Experimental scripts and media remain evidence, not a shipped supported import route.

## Minimum supported native-caption route still required

Before production enablement: define a versioned caption identity/text/font-hash/style/timing contract; represent original and realized clocks with explicit quantization approval; validate native font/style properties and missing fonts; safely map reviewed edits without changing unrelated picture/audio; reject overlaps/unknown modifiers/stale source; preserve full captions through save/reopen; and test actual composed layout at requested vertical dimensions. A TEXT object alone is not this contract. Vertical composition and whole-film/listening/style acceptance remain separate open work.
