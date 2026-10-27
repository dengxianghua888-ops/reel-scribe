# R1 Beat-query retrieval against R0

Default `format.visual_retrieval: r0` retains the existing event-span,
Beat-stratified equal-sampling ordinary pool. The default ordinary limit is 160;
selected highlights are appended separately under exactly the same rule.

Opt in with `format.visual_retrieval: r1`. The real storyboard-writing path calls
`retrieval.rerank_visual_pool`: dependency-free lexical query re-ranking and
round-robin allocation. Query provenance retains exact event/Beat wording,
negation and sequence; internal-motivation wording is excluded. Names/aliases
are used only from non-temporary canonical character entries. This still searches
derived observations and does not independently prove the story is correct.

Source and planned knowledge-event constraints filter before scoring. Bounded
exploration outside an event's possibly-wrong spans defaults to 15% of the
ordinary limit (`format.visual_exploration_fraction`). Exploratory records are
explicitly context-only and require raw verification; generated direct-evidence
use fails rather than silently asserting support. Nothing automatically rewrites
the StoryGraph. Full current analyzed-index/manual evidence remains accepted by
resumed visual validation, independent of the retriever's writer pool.

## Fairness is measured, not assumed

R1 uses R0's actual pretty-printed UTF-8 writer-pool fragment size (matching the prompt's indentation and nesting) as its text envelope. Optional
`format.visual_pool_text_budget` further caps both runs, including highlights.
Highlights alone exceeding it is an error. Long summaries, duplicate units and
separate highlight append counts are included. The ordinary unit ceiling never
grows to compensate for extra Beats. A stable-ID round-robin schedule avoids
always favoring early narrative Beats; uncovered Beats remain explicitly UNKNOWN.

The persisted `Storyboard.retrieval_provenance` records per-Beat rankings,
exclusion reasons, missing coverage, selected IDs, exact serialized bytes, remote
request count (zero for retrieval) and comparison work. It is not added to the
writer prompt. This existing text-only writer sends zero retrieval images.

Serialized bytes are NOT provider tokens. Without an instrumented tokenizer,
`provider_token_budget_verified=false`, token counts are null and no same-token
or same-total-compute-cost claim is made. The public reranker accepts a
`token_counter` callback for actual tokenizer instrumentation, then additionally
caps R1 at R0's measured token count. Feature/model reranking is not implemented;
no dependency, encoder, weight or remote request is introduced.

`benchmark_supporting_spans` supports conjunctions of required evidence and
alternative supporting sets. It separates full-ranked candidate recall, writer
pool recall and actual render-consumed support (UNKNOWN unless supplied).
Empty gold is NOT_RUN. These diagnostics do not claim accuracy or quality gains.

### Locate a missing supporting conjunction

Use the existing benchmark's optional `indexed_unit_ids` for the current analyzed
index and `planned_unit_ids={beat_id: set(unit_ids)}` for actual Storyboard choices.
The optional consumption argument also accepts `{beat_id: set(unit_ids)}` from
the actual EDL, joined to the current Storyboard's segment-to-Beat mapping. An
observed empty set means no support was selected/consumed; an omitted argument
or missing Beat key means UNKNOWN. Do not fill a missing trace from the plan.

Each Beat now reports separate `layers` for `L1_ANALYSIS_INDEX`, `L2_RETRIEVAL`
(the writer pool), `L3_PLANNING`, and `L4_CONSUMPTION`, with PRESENT / MISSING /
UNKNOWN. `first_missing_layer` identifies the first missing layer only if all
earlier layers are known present; otherwise it remains UNKNOWN. With a complete
index but an incomplete writer pool, `retrieval_gap` distinguishes candidate
filter/ranking omissions from writer-pool selection/budget omissions. It does
not blame retrieval when the index itself is absent or unmeasured.

The legacy global consumed-ID set retains `render_consumed_support`, but records
`render_consumption_scope=global_unit_ids` and leaves the Beat's L4 UNKNOWN:
another Beat using the same unit does not certify this Beat's consumption.
Inputs must be derived from the current hash-bound artifacts. This helper only
compares caller-provided unit-ID membership; it does not authenticate the traces,
prove complete source-range consumption, or judge whether the pictures tell the
story correctly. It does not change retrieval, generation or rendering.

An explicit `visual_pool_text_budget` now trims the same ordinary tail in the
actual R0 path as in R1's R0 reference. Unconfigured R0 is unchanged. Selected
highlights remain appended, and highlights alone exceeding the cap still reject
both paths. This cap measures the serialized `visual_pool` writer fragment,
not the whole prompt or provider tokens.

The original 14 synthetic unittest cases cover 160+highlights accounting, real text envelopes,
instrumented token limits, Beat starvation, knowledge/source exclusions, wrong
span exploration, conjunctive gold, negation and actual storyboard integration.
Another 13 synthetic cases cover four-layer fault injection using a 120-minute,
240-unit metadata fixture with early lexical lures, a late action and a reaction
in the next shot. Action and reaction are one conjunctive gold set; lures are
negative examples. Tests use valid configuration (at least 12 ordinary slots),
the actual R0/R1 pool-building paths, and explicit writer-byte caps to inject
retrieval omissions. No film/model/quality or same-token acceptance is claimed.
