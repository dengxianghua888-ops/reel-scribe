# Reference transfer preparation / 2

`reference-transfer-prepare` prepares one supported presentation or result-first request for current Work. It does not observe a reference automatically, render or commit an edit. Caption preparation does not compile; the result-first bridge runs the existing compiler in a disposable directory, explicitly reporting that validation execution. This operation does not insert reference media. The target may already contain the same media or derived content.

## Request

Required fields: `operation`, `store`, `expected_version`, `scene` (film/speech/software target), `reference` (local video path + SHA256), `items` (1–32).

Each item explicitly supplies `id`, `axis` (`narrative` or `audiovisual`), `mechanism`, `decision` (`adopt`, `adapt`, `omit`), `reason`, `observation`, `parameters`.

- Observed: `{status: "observed", start, end, method, evidence, description}`. Intervals must lie within the probed reference. Method is visual-review or audiovisual-review. Evidence is a local path + SHA. **This checks identity and declared range only, never certifies observation content or actual watching/listening.** The caller must truthfully record what was inspected. A screenshot or text file hash is not a truth certificate.
- Unobserved: `{status: "unobserved"}`; decision must be omit. Audio mechanisms cannot be adopted through a visual declaration.
- Omitted items require empty parameters, retain their reason and do not create downstream actions.
- At most one selected item is supported. Caption path: axis audiovisual, mechanism caption-presentation. Both adopt and adapt require explicit target values; adopt does not copy or measure reference pixels. Other mechanisms are not silently transformed into captions. The separately bounded narrative result-first adaptation is specified below.

Selected parameters contain only `variants`, using the existing creation-brief caption-presentation contract: 2–4 recipes with canonical SHA, explicit font size/margin/color, fixed current captions and freeze scopes. This reuses its validator and produces `style-recipe-preview`. Caption preparation only probes the reference; result-first additionally performs existing target compiler validation, but neither path renders.

## Binding and outputs

Reference/evidence/card identities are checked again before publication, as is current Work version. Each recipe is bound by its fingerprint. The draft carries store/version and must undergo the original downstream validation. It is not a signed authorization token: a caller modifying a draft creates a different request.

`reference-transfer.json` records every choice, reference identity, base Work version/document SHA, request fingerprint, draft fingerprint and non-certification boundaries. `prepared-request.json` exists only when a transfer is selected. All-omit returns NO_TRANSFER_SELECTED. READY_FOR_DOWNSTREAM_VALIDATION does not mean style, media, observation or user approval accepted. Before later execution recheck reference/evidence and current Work, then use existing operations; no direct Work replacement.

## Explicitly unfinished

No automatic scene/style recommendation, reference aesthetic scoring, whole-style certification, acoustic observation, causal inference or general narrative transfer. No reference media copying or license grant; source/use permission remains the caller's responsibility. A real reference observation, target render, layout check and actual viewing/listening remain distinct acceptance steps. Engineering validation is distinct from target viewing/listening acceptance.

## Result-first adaptation bridge

Select exactly one `axis: narrative`, `mechanism: result-first`, `decision: adapt` item, with target `scene: software`. `adopt` is deliberately unsupported: reference order cannot automatically certify target meaning. Do not combine a caption transfer in the same request. Other items may be explicitly omitted.

In addition to the normal observed fields, observation requires:

- `sequence`: 2–8 declared observed intervals, each `{role,start,end,evidence,description}`. First role is `result-preview`, all following roles `process`; intervals are positive, chronological, non-overlapping and contained in the outer observation span. Each evidence identity is rechecked. One timestamp, one frame or one interval does not supply narrative ordering evidence.
- `unknowns`: explicit list of remaining unknowns. Empty means no unknowns were supplied, not that everything was verified. Visual review never certifies listening; runtime still marks observation truth as caller declaration only.

Parameters are exactly the existing result-preview-compile fields `mechanism_card,tutorial,preview,shift_clip_ids,scope`. They refer to the **target Work**, never the reference media. The authoritative compiler runs in a temporary directory: target before/action/result windows, all-original-clips preservation, fixed visible preview/return labels, source/frame constraints, current Work identity, and persistent protection scope and maps all retain their original validation. Independent audio/visual layers and unsupported retiming remain rejected. Never remove protections to enable transfer. Temporary candidates/proofs are discarded; only a ready request and validation summary are published.

Report `executed=true` means `execution_kind=TEMPORARY_COMPILER_VALIDATION_ONLY`, not rendering or adoption. `rendered=false`, `applied_to_work=false`, `committed=false`. `downstream_validation=COMPILER_VALIDATED_RECHECK_BEFORE_USE` requires compiling again against the current target when actually using the prepared request. Caption-path execution semantics are unchanged. The nested compiler still correctly states `reference_video_adaptation=NOT_PERFORMED`: it knows only the target mechanism, not the outer caller observation. Neither statement grants aesthetic/causal/whole-style acceptance.

Final reference, per-event observation evidence, target source/tutorial evidence/card/font/protection identities and Work head are rechecked before publication. Reference bytes are not newly copied into target by this operation; existing target content is preserved. Any later change requires fresh validation.

## Report v2: insertion is not absence

Requests are unchanged. Output schema `reference-transfer/2` replaces the ambiguous v1 `reference_media_in_output=false` field; consumers must handle v2 explicitly rather than treating the removed field as false. No automatic migration of old reports or truth claims is performed.

- `reference_media_inserted_by_transfer=false`: this operation does not add reference media to Work.
- `reference_target_source_matches`: current Work `plan.sources`, `audio_tracks` and `visual_layers` entries with the same SHA256 as the reference, independent of file path. Each record contains `collection`, `id`, and `source`; matched source identities are rechecked before publication. An unused plan source or muted layer can still match. These are identity matches, not proof of actual output consumption.
- `reference_output_presence=NOT_EVALUATED`: neither a match nor no match determines future output presence. Crops, transcodes and other derived content may have different hashes. This preparation does not render/analyze output or grant a license.

Same-source reference is allowed, but cannot serve as evidence of independent reference research or material absence from a future output.
