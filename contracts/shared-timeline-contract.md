# Same-batch caption timeline reuse

This internal optimization does not introduce a global cache or grant QA approval.
It is available only inside a locked `work-batch-render` run, from an already
successful native (not itself reused) donor job in that batch and Work version.
Only documents identical except `caption_style` and `style_bindings` qualify;
existing captions must be nonempty and independent audio/visual layers absent.
The complete plan, explicit audio backend and source-consumption request, runtime
files, tools, source contents, candidate identity and current head remain bound.

A donor's successful full receipt and timeline receipt/request/artifacts are
verified before copying. Media are copied and hashed in bounded chunks. Original
receipt bytes are retained as donor evidence, not represented as new execution.
`timeline-reuse.json` and `result.timeline_reuse` explicitly identify the donor,
its expected receipt hash and artifact set, with `REUSED_VERIFIED_NOT_EXECUTED`
and `qa_inherited:false`. Donor and copied artifacts are rechecked after rendering.
Each recipient independently renders its captions and runs final technical QC.
Its normal source-consumption session, current-head checks, candidate and final
output binding still apply. Batch retries revalidate the donor dependency; a
changed donor cannot be silently re-endorsed. Invalid eligible donors fail closed
rather than converting corruption into a cache miss.

No shot-level cache, audio-layer cache, semantic QA, listening approval, final
style acceptance or source-audio fidelity claim is added. The existing broad
revision QA invalidation is unchanged. Synthetic FFmpeg tests establish plumbing
and decoded baseline equivalence only, not real-content quality or a general
speedup. Copied task-local bytes do not isolate against a malicious same-user
process; pre/post checks retain the underlying source-binding threat model.
