# Experimental Blender cut import (opt-in)

`tools/editor-adapters/blender_cut_import.py` is a standalone, limited **Blender 4.3.2 only** host importer. It is not registered as a runtime adapter and does not change the general OTIO export capability report. Existing `.blend` projects are not accepted as input. Run in a fresh background Blender process on trusted, locally generated Reel packages. Checksums detect accidental changes, not hostile forgery or authenticity. Keep the package immutable while importing.

## Contract

- Integer CFR 1–120 fps, single-video-stream media, at most one audio stream per resource, common geometry, zero media clock start, 1× hard cuts/gaps, frame-aligned picture **and** sound windows.
- Current supported media resources are original source video with optionally separated original audio. Audio-only narration, variable/fractional fps, effects/transitions, scaling, overlays, native titles, nonempty caption sidecars and reverse Reel readback are not supported. Unsupported input is rejected, not rounded or silently discarded.
- All package membership, hashes, paths, restricted OTIO schemas, windows and basic media probes validate before host mutation. Existing scenes remain untouched; successful imports create a new scene. Failed preflight does not touch host state or output. Host creation failure removes the new scene; use an isolated process rather than claiming rollback of every internal Blender datablock.
- This tool saves only a new `.blend`; it never renders, edits a supplied project, deploys, or publishes. No fixture-specific trimming API is exposed. Saving the project references package files; retain/move the package with appropriate relinking. It is not a self-contained backup.
- `ffprobe` must already be available. No dependency is installed. Blender saves all scenes in the process, so use `--factory-startup` as below, never a session containing unrelated/private work.

## Usage

```sh
blender -b --factory-startup --python-exit-code 1 \
  --python tools/editor-adapters/blender_cut_import.py -- \
  /absolute/path/to/verified-package /absolute/path/to/new-project.blend
python -m unittest discover -s tests/editor_adapters -v
```

Use only trusted media: codecs and host importers execute native parsers. Existing output files and unsupported host versions fail closed. No untrusted `.blend` is loaded by this command.

## Acceptance evidence, 2026-11-12

Blender 4.3.2 actually imported a package created by Reel's existing exporter from **Tears of Steel** original windows 25–27 s and 55–57 s, 24 fps, 1280×534, with paired original sound. Four separate host processes imported/saved, reopened/rendered, trimmed the first paired picture/sound by 12 frames and rippled the later pair, then saved/reopened/rendered again. 96 frames became 84. Source offsets remained 600/1320 frames; edited/reopened decoded frame hashes matched. This host edit was an acceptance fixture, not a production API.

Source SHA-256: `efa9062d9cdb7a338e40ad530dfdf234806743f29ae6a1a136b97ece4e588e8f` (unchanged).
Source: https://download.blender.org/demo/movies/ToS/tears_of_steel_720p.mov
License/attribution: [(CC) Blender Foundation | mango.blender.org](https://mango.blender.org/sharing/), [CC BY 3.0](https://creativecommons.org/licenses/by/3.0/). Changes: local excerpts, trims and re-encoding; no endorsement. The separate BY-ND soundtrack was not used. Media and derivatives are not included here.

Four image samples per export had mean absolute RGB error below 1.38/255 versus the corresponding source window; two interior 0.5-second audio windows had correlation ≥0.9938 and RMS ratio 0.9974–0.9995. These are finite fixture measurements, not generic perceptual guarantees or sample-exact AAC equivalence. One rendered frame was visually inspected; audio was measured, not listened to; the whole film was not watched. Synthetic paired color/tone tests also completed the lifecycle (120→105 frames).

After hardening into this standalone importer, the actual 24 fps package was imported again, saved, and reopened/rendered in a separate Blender process. The stdlib validation suite uses fake media and stub probes; it is **not** a substitute for that actual-host check.

Not claimed: GUI/manual/Kdenlive acceptance, caption roundtrip, reverse authority binding, whole-film semantic quality, Chinese content evaluation, user-preference acceptance, or general editor interoperability.

### Metadata and clock trust boundary

The current exporter rejects storyboard gain/crop/transform/effects and emits only identity, lineage and clock fields in clip metadata, and track identity/role fields. This adapter explicitly allowlists those emitted fields at timeline/stack/track/clip/reference levels; gain, volume, normalization, crop/transform, foreign namespaces and unknown profile processing are rejected, including explicit defaults, rather than silently omitted. There is no supported non-default processing metadata. `lineage` remains inert provenance, not an executable editing instruction.

The importer requires a **trusted package whose source clocks were already full-frame verified by the Reel exporter**. It does not freshly establish CFR from every media frame. Matching `avg_frame_rate`/`r_frame_rate` and the bound facts only checks obvious inconsistencies; matching values alone cannot prove CFR. Recomputed checksums on a forged package are not authentication. The importer does not claim to verify arbitrary external OTIO packages.
