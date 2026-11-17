# Explicit subtitle compatibility import

The normal sidecar reader now raises a diagnostic for malformed timing arrows,
empty timed cues, unknown detached text blocks, reversed/nonchronological times, invalid clock ranges or
ambiguous multi-timing blocks. It no longer silently turns these into an empty
transcript that can trigger ASR fallback. Legitimate WebVTT header, NOTE blocks,
identifiers and cue positioning settings remain supported. Estimated per-word
positions remain `timing_source="estimated"`, never real alignment evidence.

For an explicitly selected nonstandard subtitle, call:

```python
from douyin_film_recap.asr import canonicalize_subtitle
receipt = canonicalize_subtitle("original.zh.srt", "new.canonical.zh.srt",
    identifier_policy="sequential-numeric")  # only after reviewing numeric IDs
```

This does not change the normal reader's strictness. It preserves the original
bytes, derives both the source hash and parsed text from the same byte read,
then rechecks source identity before publication. It first accepts already-valid input unchanged
in meaning, otherwise explicitly reblocks timing-led cues across extra blank
lines and accepts whole-second timestamps. It reports compatibility warnings,
including caller-declared numeric cue identifiers removed and whole-second expansion.
The default `reject-ambiguous` policy refuses numeric lines immediately before
a timing line in compatibility mode, since they may be dialogue. Only the
explicit caller-declared `sequential-numeric` policy may strip them, and then
identifiers must form a contiguous sequence. Already-valid multiline numeric
dialogue is preserved through the strict-parser-first path. Empty cues are
rejected. Review the warnings and original text: malformed input cannot
universally reveal whether a standalone numeric line is dialogue or a cue ID.
This narrow repair mode is not an arbitrary subtitle recovery engine.

Canonical SRT is generated with standard sequential indices and millisecond
timestamps, then checked by the **unchanged strict output QC** before exclusive
creation of a new output path. Publication writes and fsyncs a same-directory
staging file, verifies its full bytes, and exclusively hard-links the target.
Partial writes/fsync failures cannot expose a partial target. Existing files
(including the source used as destination) are never overwritten. Best-effort
staging cleanup cannot turn an already committed output into a reported failure;
a leftover `.pending` file is not an output or success receipt. Directory fsync
and crash-durable multi-file transactions are not promised. The return
value includes source/derived hashes, warnings and cue count; persist this receipt
with the derived subtitle if used downstream. Listening and translation review
are explicitly NOT_RUN. There is no English-to-Chinese timestamp substitution.

Real structural fixture checked outside the repository: official Tears of Steel
Chinese has 77 timing lines, including an unnumbered 4–6 second cue and pervasive
extra blank lines. Original default parsing now fails explicitly; compatibility
import with the explicitly declared numeric-ID policy yields 77 valid canonical cues. English yields 76. Chinese cue starting
43.000 seconds is preserved, not changed to the English 42.200-second start.
These checks establish structure only, not translation or listening accuracy.
