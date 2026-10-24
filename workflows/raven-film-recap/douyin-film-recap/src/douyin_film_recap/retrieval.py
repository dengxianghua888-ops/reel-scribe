"""Dependency-free R1 lexical retrieval against the existing R0 input budget.

This ranks derived observations, not raw truth. Negation and temporal terms are
retained. Actual provider token/compute equality is unknown unless instrumented.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
import hashlib
import json
import math
import re
from typing import Any, Callable

from .utils import fingerprint_json
from .narrative_contracts import diagnose_plan_references


@dataclass(frozen=True)
class RetrievalRequest:
    beat_id: str
    query_text: str
    query_provenance: tuple[str, ...]
    event_ids: tuple[str, ...] = ()
    canonical_character_ids: tuple[str, ...] = ()
    allowed_source_ids: tuple[str, ...] = ()
    preferred_spans: tuple[tuple[str, float, float], ...] = ()
    allowed_knowledge_event_ids: tuple[str, ...] = ()
    desired_visual_role: str = "direct_evidence"
    claims_are_derived: bool = True
    reference_diagnostics: tuple[dict[str, Any], ...] = ()


@dataclass
class RetrievalResult:
    pool: list[dict[str, Any]]
    provenance: dict[str, Any]


def writer_input_bytes(pool) -> int:
    # Match storyboard_prompt's indent=2 and the pool's nesting inside its
    # payload object. All other prompt fields are unchanged between R0 and R1.
    # This measures actual writer-fragment bytes, NOT provider token count.
    return len(json.dumps({"visual_pool": pool}, ensure_ascii=False, indent=2).encode("utf-8"))


def _terms(text: str) -> set[str]:
    result = set(re.findall(r"[a-z0-9]+", text.lower()))
    for run in re.findall(r"[\u3400-\u9fff]+", text):
        result.update(run[index:index+2] for index in range(max(1, len(run)-1)))
    return result


def _text(row):
    return " ".join(str(row.get(key, "")) for key in (
        "visible_facts", "dialogue_facts", "events", "performance_moments", "characters"))


def build_retrieval_requests(plan, story) -> list[RetrievalRequest]:
    event_counts = Counter(event.event_id for event in story.story_graph.events)
    character_counts = Counter(c.character_id for c in story.character_registry.characters)
    events = {event.event_id: event for event in story.story_graph.events
              if event_counts[event.event_id] == 1}
    characters = {c.character_id: c for c in story.character_registry.characters
                  if character_counts[c.character_id] == 1}
    diagnostics = diagnose_plan_references(plan, story)
    allowed = set()
    requests = []
    for beat in plan.beats:
        linked = [events[eid] for eid in beat.event_ids if eid in events]
        # Unknown/ambiguous IDs are reported, never converted into knowledge permission.
        allowed.update(eid for eid in beat.event_ids if eid in events)
        spans = tuple((span.source_id, span.start, span.end) for e in linked for span in e.source_spans)
        verified_characters = tuple(cid for cid in beat.character_focus if cid in characters
                                    and not characters[cid].temporary_name)
        aliases = [name for cid in verified_characters
                   for name in [characters[cid].display_name, *characters[cid].aliases]]
        # Exact derived event wording preserves "not", "before", Chinese negation
        # and sequence. It is a search query, never promoted to a fact by a match.
        query = " ".join([beat.change, *[event.event for event in linked], *aliases])
        # Motivation/internal knowledge are not observable retrieval assertions.
        if re.search(r"早就知道|心里|内心|动机|believ|secretly knew|intends? to", query, re.I):
            query = " ".join([*aliases, *[event.event for event in linked
                if not re.search(r"早就知道|心里|内心|动机|believ|secretly knew|intends? to", event.event, re.I)]])
        requests.append(RetrievalRequest(beat_id=beat.beat_id, query_text=query,
            query_provenance=(f"beat:{beat.beat_id}:change", *[f"event:{e.event_id}:text" for e in linked]),
            event_ids=tuple(beat.event_ids), canonical_character_ids=verified_characters,
            allowed_source_ids=tuple(sorted({span[0] for span in spans})), preferred_spans=spans,
            allowed_knowledge_event_ids=tuple(sorted(allowed)),
            reference_diagnostics=tuple(item for item in diagnostics if item["beat_id"] == beat.beat_id)))
    return requests


def _overlap(row, span):
    return row["source_id"] == span[0] and min(row["end"], span[2]) > max(row["start"], span[1])


def rerank_visual_pool(
    ordinary_units: list[dict[str, Any]], *, r0_pool: list[dict[str, Any]],
    requests: list[RetrievalRequest], ordinary_limit: int = 160,
    exploration_fraction: float = .15, text_byte_budget: int | None = None,
    token_counter: Callable[[list[dict[str, Any]]], int] | None = None,
    unit_event_ids: dict[str, list[str]] | None = None,
) -> RetrievalResult:
    """Round-robin R1 with the unchanged separate selected-highlight append rule.

    text_byte_budget caps both runs; R1 cannot exceed R0's measured envelope.
    A supplied tokenizer additionally enforces R0's actual token budget. Without
    it the report explicitly withholds token/API-cost equivalence.
    """
    if ordinary_limit < 0 or not 0 <= exploration_fraction <= 1:
        raise ValueError("Invalid retrieval budget")
    ids = [row["unit_id"] for row in ordinary_units]
    if len(ids) != len(set(ids)) or len({r.beat_id for r in requests}) != len(requests):
        raise ValueError("Duplicate retrieval unit or beat ID")
    highlights = [row for row in r0_pool if row.get("evidence_type") == "highlight"]
    baseline = [row for row in r0_pool if row.get("evidence_type") != "highlight"][:ordinary_limit]
    if text_byte_budget is not None:
        if writer_input_bytes(highlights) > text_byte_budget:
            raise ValueError("Selected highlights alone exceed the writer byte budget")
        while baseline and writer_input_bytes(baseline + highlights) > text_byte_budget:
            baseline.pop()
    requested_ordinary_limit = ordinary_limit
    ordinary_limit = min(ordinary_limit, len(baseline))
    r0 = baseline + highlights
    byte_limit = writer_input_bytes(r0)
    token_limit = token_counter(r0) if token_counter else None
    token_sets = {row["unit_id"]: _terms(_text(row)) for row in ordinary_units}
    frequency = {}
    for terms in token_sets.values():
        for term in terms:
            frequency[term] = frequency.get(term, 0) + 1
    rankings, exclusions, context_only = {}, {}, set()
    events_by_unit = unit_event_ids or {}
    for request in requests:
        query = _terms(request.query_text)
        ranked, excluded = [], []
        for row in ordinary_units:
            uid = row["unit_id"]
            if request.allowed_source_ids and row["source_id"] not in request.allowed_source_ids:
                excluded.append({"unit_id": uid, "reason": "source_constraint"})
                continue
            reveals = set(events_by_unit.get(uid, []))
            if reveals - set(request.allowed_knowledge_event_ids):
                excluded.append({"unit_id": uid, "reason": "knowledge_constraint"})
                continue
            direct = any(_overlap(row, span) for span in request.preferred_spans)
            matches = query & token_sets[uid]
            score = sum(math.log(1 + len(ordinary_units) / frequency[t]) for t in matches)
            if not direct and (exploration_fraction == 0 or score <= 0):
                excluded.append({"unit_id": uid, "reason": "no_query_evidence"})
                continue
            ranked.append({"unit_id": uid, "score": round(score, 8), "in_event_span": direct,
                           "role": request.desired_visual_role if direct else "context",
                           "requires_raw_verification": not direct,
                           "matched_terms": sorted(matches)})
        ranked.sort(key=lambda row: (-row["score"], not row["in_event_span"], row["unit_id"]))
        rankings[request.beat_id] = ranked
        exclusions[request.beat_id] = excluded
    direct_for_any_beat = {row["unit_id"] for rows in rankings.values() for row in rows if row["in_event_span"]}
    by_id = {row["unit_id"]: row for row in ordinary_units}
    chosen, chosen_ids, budget_exclusions = [], set(), []
    explored = set()
    exploration_limit = int(ordinary_limit * exploration_fraction)
    # Deterministic stable-ID order avoids always sacrificing late narrative beats
    # when the number of beats exceeds the input capacity; uncovered stays explicit.
    schedule = sorted(requests, key=lambda r: (hashlib.sha256(r.beat_id.encode()).hexdigest(), r.beat_id))
    cursors = {r.beat_id: 0 for r in schedule}
    while len(chosen) < ordinary_limit:
        progress = False
        for request in schedule:
            ranked = rankings[request.beat_id]
            while cursors[request.beat_id] < len(ranked):
                ranked_row = ranked[cursors[request.beat_id]]
                cursors[request.beat_id] += 1
                uid = ranked_row["unit_id"]
                if uid in chosen_ids:
                    continue
                if not ranked_row["in_event_span"] and len(explored) >= exploration_limit:
                    continue
                candidate_row = by_id[uid]
                if not ranked_row["in_event_span"] and uid not in direct_for_any_beat:
                    candidate_row = {**candidate_row, "retrieval_role_limit": "context",
                                     "requires_raw_verification": True}
                trial = chosen + [candidate_row] + highlights
                if (writer_input_bytes(trial) > byte_limit or
                    token_counter is not None and token_counter(trial) > token_limit):
                    budget_exclusions.append({"beat_id":request.beat_id,"unit_id":uid,"reason":"writer_budget"})
                    continue
                chosen.append(candidate_row); chosen_ids.add(uid)
                if not ranked_row["in_event_span"]:
                    explored.add(uid)
                    if uid not in direct_for_any_beat:
                        context_only.add(uid)
                progress = True
                break
            if len(chosen) >= ordinary_limit:
                break
        if not progress:
            break
    pool = chosen + highlights
    coverage = {}
    for request in requests:
        selected = [row for row in rankings[request.beat_id] if row["unit_id"] in chosen_ids]
        coverage[request.beat_id] = {
            "selected_unit_ids": [row["unit_id"] for row in selected],
            "direct_unit_ids": [row["unit_id"] for row in selected if row["in_event_span"]],
            "status": "candidate_evidence" if any(row["in_event_span"] for row in selected) else "unknown",
            "reason": "" if selected else "no_evidence_or_budget_exhausted",
        }
    return RetrievalResult(pool=pool, provenance={
        "schema_version":"beat-retrieval/1", "method":"r1-lexical/1", "baseline":"r0-beat-stratified/1",
        "requests":[r.__dict__ for r in requests], "per_beat_rankings":rankings,
        "exclusions":exclusions, "budget_exclusions":budget_exclusions, "coverage":coverage,
        "uncovered_beat_ids":[key for key,value in coverage.items() if value["status"] == "unknown"],
        "context_only_unit_ids":sorted(context_only), "pool_unit_ids":[row["unit_id"] for row in pool],
        "requested_ordinary_limit":requested_ordinary_limit,
        "ordinary_limit":ordinary_limit, "ordinary_count":len(chosen), "highlight_append_count":len(highlights),
        "deduplicated_pool_count":len({row["unit_id"] for row in pool}),
        "writer_bytes":writer_input_bytes(pool), "r0_writer_bytes":byte_limit,
        "writer_tokens":token_counter(pool) if token_counter else None, "r0_writer_tokens":token_limit,
        "provider_token_budget_verified":token_counter is not None,
        "writer_images":0, "remote_requests":0, "feature_encoding_requests":0,
        "retrieval_comparisons":len(requests) * len(ordinary_units),
        "same_total_compute_cost_verified":False, "semantic_acceptance":"not_performed",
        "highlights_unchanged_hash":fingerprint_json(highlights),
    })


def benchmark_supporting_spans(r0_pool, r1: RetrievalResult, gold: dict[str, list[list[str]]],
                               consumed_unit_ids: set[str] | None = None) -> dict:
    """Gold alternatives are disjunctions; IDs within each alternative are conjunctive.

    Missing gold never turns into zero failures or an apparent quality improvement.
    Writer selection and actual render consumption remain separate measurements.
    """
    baseline_ids = {row["unit_id"] for row in r0_pool}
    ranked = r1.provenance["per_beat_rankings"]
    chosen = {row["unit_id"] for row in r1.pool}
    metrics = {}
    for beat_id, alternatives in gold.items():
        if not alternatives or any(not group for group in alternatives):
            raise ValueError("Gold must contain nonempty supporting conjunctions")
        def hit(ids):
            return any(set(group) <= ids for group in alternatives)
        retrieved = {row["unit_id"] for row in ranked.get(beat_id, [])}
        metrics[beat_id] = {"r0_support_recalled":hit(baseline_ids),
            "r1_candidates_recalled":hit(retrieved), "r1_writer_pool_recalled":hit(chosen),
            "render_consumed_support":hit(consumed_unit_ids) if consumed_unit_ids is not None else None}
    return {"schema_version":"retrieval-benchmark/1", "gold_beats":len(gold), "per_beat":metrics,
            "quality_status":"synthetic_gold_only" if gold else "NOT_RUN",
            "fairness":{key:r1.provenance[key] for key in (
                "ordinary_limit","ordinary_count","highlight_append_count","writer_bytes","r0_writer_bytes",
                "writer_tokens","r0_writer_tokens","provider_token_budget_verified","same_total_compute_cost_verified")}}
