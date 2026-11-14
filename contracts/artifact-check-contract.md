# Tutorial artifact check v1

Operation `tutorial-artifact-check`, implementation `artifact_check_ops.execute`.
Dependencies: ffprobe for the existing ExecutionPlan normalizer. No new authority,
Work mutation, render, file download or automatic semantic inspection.

## Request

Required and only top-level fields:

```text
operation: tutorial-artifact-check
plan: ExecutionPlan
expected_revision: fingerprint(plan)
tutorial: {steps: [...existing tutorial steps...], result_cues: [...]}
checks: [{
  id, step_id,
  input_artifacts: [{path,sha256}],
  result_artifact: {path,sha256} | null,
  inspection: {clip_id,start,end,min_visible_seconds,evidence:{path,sha256}},
  observation: {actor_kind: agent-observation|user-reported, statement}
}]
artifact_cues: [{id,check_id,start,end,text}]
```

1–64 checks, unique nonempty IDs (≤128 characters), ≤16 input artifacts per check,
≤128 cues. Input artifacts may be empty: an on-screen setting need not have a local
input file. The result file must be genuine accessible local bytes or null, never
an invented placeholder to obtain a complete status. Artifact identity alone does
not establish what those bytes mean or how they were produced.

All file references use existing strict path/SHA shape. Absolute local regular
files only; directories and symlinks (including parent-directory aliases) are
rejected. No URL retrieval. The exact sources/evidence used by tutorial compilation,
input/result files and inspection evidence are checked before use and again before
publishing the final report. Source ID must match the step capture, not merely a
similar path or coincident timestamp. Input/output may deliberately refer to the
same bytes; the checker does not infer a transformation from different names.

The existing tutorial compiler validates before/action/result and prerequisites.
`inspection.start/end` are **declared source seconds** within its selected clip,
not file mtime or clock time. Both source and mapped output inspection intervals
must start at or after the corresponding result interval's end. The full inspection
must survive frame quantization and meet its explicit positive minimum display
length. Source reuse/retiming still follows normal ExecutionPlan rules.

`artifact_cues` use output seconds, must reference a nonmissing result artifact,
and stay wholly inside that check's inspection interval. Early cues and cues for
missing files fail. Text is not interpreted or certified: a false “saved” sentence
cannot gain semantic legitimacy merely by passing a timing check. Undeclared cues
elsewhere are not automatically inspected.

## Output and evidence boundary

`artifact-check.json` contains the plan digest, existing tutorial proof, each file
identity, source/result anchors, declared observation and mapped inspection, plus
cue linkage. Status `LINKAGE_VALIDATED` means all supplied result files exist with
matching bytes and the declared linkage validates. `INCOMPLETE` is a normal result
when any result_artifact is null; that item is `MISSING_ARTIFACT`. It does not assert
that backend saving failed or that an absent artifact never existed.

Always retain:

- `observation_truth: NOT_VERIFIED`, `observer_identity_verified: false`.
- `frame_derivation: FRAME_DERIVATION_NOT_VERIFIED`. An evidence PNG's hash does not
  prove it was extracted from the stated capture/time; even an argv/PTS note is a
  declaration unless independently reproduced.
- `artifact_production_link: DECLARED_ONLY`, `backend_persistence: NOT_VERIFIED`.
- `semantic_review: NOT_RUN`, `publication_gate: false`, `work_changed: false`.

A screenshot of a Save button only supplies accessible image bytes and an attributed
observation. It cannot certify a click, persisted settings, saved file, publication,
reopen success or the provenance of another result artifact. `user-reported` is
attribution, not authenticated identity or authorization.

The delegated tutorial files live under `tutorial-validation/`. If later artifact
checks fail, these intermediate files may remain for diagnosis; they are NOT a
successful artifact check. No successful `artifact-check.json` is written on error.
Use a fresh operation directory and the top-level runtime receipt/status when
consuming the operation. Successful linkage is not a new release gate or whole-card
style acceptance.
