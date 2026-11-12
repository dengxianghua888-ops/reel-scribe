# Reference transfer preparation / 1

`reference-transfer-prepare` only prepares a caption-presentation request for current Work. It neither observes a reference automatically nor applies, renders or commits an edit. The reference is not inserted in output.

## Request

Required fields: `operation`, `store`, `expected_version`, `scene` (film/speech/software target), `reference` (local video path + SHA256), `items` (1–32).

Each item explicitly supplies `id`, `axis` (`narrative` or `audiovisual`), `mechanism`, `decision` (`adopt`, `adapt`, `omit`), `reason`, `observation`, `parameters`.

- Observed: `{status: "observed", start, end, method, evidence, description}`. Intervals must lie within the probed reference. Method is visual-review or audiovisual-review. Evidence is a local path + SHA. **This checks identity and declared range only, never certifies observation content or actual watching/listening.** The caller must truthfully record what was inspected. A screenshot or text file hash is not a truth certificate.
- Unobserved: `{status: "unobserved"}`; decision must be omit. Audio mechanisms cannot be adopted through a visual declaration.
- Omitted items require empty parameters, retain their reason and do not create downstream actions.
- At most one selected item is supported: axis audiovisual, mechanism caption-presentation. Both adopt and adapt require explicit target values; adopt does not copy or measure reference pixels. Narrative mechanisms, music, transitions and result-preview adoption are unsupported, not silently transformed into captions.

Selected parameters contain only `variants`, using the existing creation-brief caption-presentation contract: 2–4 recipes with canonical SHA, explicit font size/margin/color, fixed current captions and freeze scopes. This reuses its validator and produces `style-recipe-preview`. No media processing is performed by preparation other than probing the reference.

## Binding and outputs

Reference/evidence/card identities are checked again before publication, as is current Work version. Each recipe is bound by its fingerprint. The draft carries store/version and must undergo the original downstream validation. It is not a signed authorization token: a caller modifying a draft creates a different request.

`reference-transfer.json` records every choice, reference identity, base Work version/document SHA, request fingerprint, draft fingerprint and non-certification boundaries. `prepared-request.json` exists only when a transfer is selected. All-omit returns NO_TRANSFER_SELECTED. READY_FOR_DOWNSTREAM_VALIDATION does not mean style, media, observation or user approval accepted. Before later execution recheck reference/evidence and current Work, then use existing operations; no direct Work replacement.

## Explicitly unfinished

No automatic scene/style recommendation, reference aesthetic scoring, whole-style certification, acoustic observation, causal inference or narrative/result-preview bridge. No reference media copying or license grant; source/use permission remains the caller's responsibility. A real reference observation, target render, layout check and actual viewing/listening remain distinct acceptance steps. This slice tests engineering preparation only.
