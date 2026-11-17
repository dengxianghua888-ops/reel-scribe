# Explicit local media normalization (experimental)

This standalone import aid is **not** a runtime fallback or a relaxation of
source clock checks. It writes a new derived source and an immutable JSON
receipt. It does not update any Work, source reference, subtitle or timeline.
Original-file rejection remains rejection even when the derived file succeeds.

## Completion protocol (required for consumers)

Only the fixed `receipt.json` path with schema `normalized-import/1`, status
`SUCCEEDED_TECHNICAL_NEEDS_REVIEW`, and a matching derived path/size/SHA-256
commits an import. Use `completed_import(directory)` to verify it. The presence
of `normalized.mov`, `pending.mov` or a staging JSON is never success.
The receipt is fully written and file-fsynced before an exclusive hard-link
publication; no fallible cleanup follows that commit point. Pending hard links
are intentionally retained and are not an additional copied video.

If receipt publication fails, the tool attempts to remove only the media link
it published, checking its inode. Permission errors may prevent cleanup or even
a failure receipt. Such files are uncommitted and must not be consumed. The tool
reports failure, never promises complete rollback, and never replaces an existing
receipt. This is a completion-marker protocol, not a guarantee of atomic
multi-file rollback or power-loss durability of the containing directory.

```sh
python scripts/normalize_media.py /absolute/source.webm \
  --expected-sha256 SOURCE_SHA256 --output /existing/parent/new-import \
  --start 45 --end 51 --fps 30 --accept-lossy \
  --attribution 'Creator and source URL' --license-url 'License URL'
```

## Trust boundary

Use only trusted, self-contained local recordings. This tool is not a sandbox
for hostile media or a general-purpose external-reference resolver. Preflight
uses existing runtime FFprobe clock readers, which do not themselves apply a
protocol whitelist. Before any reader, the importer rejects playlist signatures
and checks the ISO-BMFF data-reference hierarchy: external URL/URN entries and
QuickTime reference movies are rejected. WebM is treated as a trusted recording.
Do not infer from file magic alone that arbitrary attacker-controlled files are
safe. Encoding and final decode additionally restrict protocols to `file`.

## Narrow support and safety

- Local regular WebM/ISO-BMFF media only; network URLs, pipes, playlists and
  symlink components are rejected. The encoding/decode commands restrict
  protocols to `file`. Do not use this utility to ingest untrusted playlists.
- Exactly one video and one audio stream, no rotation metadata, positive finite
  window up to 600 seconds, whole output-frame duration, 1–120 fps.
- The destination must be a new directory in an existing nonsymlink parent.
  Existing files/directories are never overwritten. Failures after preflight reserve
  their directory and retain a FAILED receipt; choose another output for retry.
- Source hash is checked before processing and again after encoding/validation.
  Tools use the existing executable identity checks. Originals are never edited.
- Defaults bound **each observed uncovered interval** to 50ms video / 20ms
  audio; explicit overrides cannot exceed 250ms. These evidence gaps do not
  necessarily mean audible/visible gaps. They are not a guarantee of total
  correction size; exact changed samples/frames are reported UNKNOWN.
- A first picture delayed by more than one output frame is rejected, rather
  than silently advancing it. Sub-frame leading picture hold can occur and is
  disclosed. Arbitrary leading-video offsets are not supported.

## Timing and loss disclosure

FFmpeg uses `-copyts`, source-time `trim/atrim` and subtracts the **same source
window start** from both streams, never independent STARTPTS resets. Audio
resampling honors its remaining PTS; silence may be inserted and audio trimmed.
CFR selection may duplicate/drop frames, hold a leading picture by a sub-frame,
and clone a bounded final frame. Video is H.264 CRF18 (lossy); audio is 48kHz
PCM s16 after resampling/compensation, not an original-byte-preserving copy.
The complete argv, original clock evidence, selected gap policy, tool identity,
source/derived hashes and probes are in `receipt.json`.

Output is validated using existing strict selected-video coverage and
sample-resolving full-audio coverage, plus complete FFmpeg decoding. Only then
is `normalized.mov` exclusively published. Success is deliberately named
`SUCCEEDED_TECHNICAL_NEEDS_REVIEW`: listening, semantic quality and creative
acceptance remain NOT_RUN. Rebind derived media explicitly, and review/rebuild
any timing-sensitive annotations; a timestamp mapping alone is not word-level
alignment evidence. Carry source license/attribution to redistributed derivatives.

## Acceptance scope

`tests/media_import` uses real FFmpeg synthetic fixtures. Signed ±120ms audio
pulse/video-event offsets are measured from decoded PCM and actual video pixels;
these are technical fixtures, not natural-speech listening tests. Tests cover
immutability, existing destinations, invalid hashes/inputs/windows, symlinks,
real excessive audio gaps, missing audio, encoder failure and source mutation.

Local real-media smoke checks (not bundled or downloaded by tests): The Green
Interview WebM 45–51s (B-roll) and 100–106s (speaking subject) and WikEd tutorial WebM 25–31s have passed derived strict
clock and full-decode checks. Their original source rejection is unchanged.
This is not broad WebM compatibility, nor proof of lossless reconstruction.
