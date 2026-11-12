"""Prepare and atomically adopt consistent 07/08/09 boundary revisions.

Preparation preserves the candidate ledger; declared raw cards trigger read-only
source redecoding. Publishing delegates
to revision.adopt_revision's existing workspace generation transaction.
"""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
from pathlib import Path
from typing import Any
from .boundary import (
    BoundaryProposal, TimebaseBinding, candidate_revision, highlight_reference_binding,
    proposal_hash, validate_boundary_proposal,
)
from .config import AppConfig
from .highlight import _compute_final_score, _deduplicate, _events_for_span, _select_diverse
from .models import (
    HighlightDocument, OriginalCue, RecapPlan, SceneAnalysisDocument, SceneIndex,
    SourceManifest, StoryBundle, Storyboard, TranscriptDocument, VisualReference,
)
from .narrative_contracts import get_plan_constraints, hook_eligibility
from .utils import fingerprint_json
from .subtitles import segment_output_duration
from .visual_evidence import validate_storyboard_visual_evidence

HIGHLIGHTS = "07_highlight_candidates.json"
PLAN = "08_recap_plan.json"
BOARD = "09_storyboard.json"
SIDECAR = ".receipts/boundary-adoption.json"


class BoundaryApplyError(ValueError):
    pass


@dataclass(frozen=True)
class PreparedBoundaryRevision:
    artifacts: dict[str, dict[str, Any]]
    affected_segment_ids: tuple[str, ...]
    evidence_revision: str


def _frozen(model):
    return fingerprint_json(model.model_dump(mode="json"))


def _cues(transcript, source_id, start, end):
    result = []
    for cue in transcript.segments:
        if cue.source_id != source_id or cue.end <= start or cue.start >= end:
            continue
        if cue.start >= start and cue.end <= end:
            result.append(OriginalCue.model_validate(cue.model_dump(mode="json")))
            continue
        words = [w for w in cue.words if w.timing_source in {"asr", "aligned"}
                 and w.start >= start and w.end <= end]
        if not words:
            raise BoundaryApplyError("PARTIAL_DIALOGUE_WITHOUT_RELIABLE_WORD_TIMING")
        result.append(OriginalCue(source_id=source_id, start=words[0].start, end=words[-1].end,
                                  text="".join(w.text for w in words), words=words))
    return result


def prepare_boundary_revision(
    proposal: BoundaryProposal, *, manifest: SourceManifest, highlights: HighlightDocument,
    plan: RecapPlan, storyboard: Storyboard, story: StoryBundle,
    transcript: TranscriptDocument, scene_index: SceneIndex,
    scene_analysis: SceneAnalysisDocument, config: AppConfig,
    timebases: dict[str, TimebaseBinding], current_artifact_hashes: dict[str, str],
    raw_cards: list | None = None, evidence_root: str | Path | None = None,
) -> PreparedBoundaryRevision:
    """Return a candidate transaction, rejecting stale/conflicting inputs unchanged."""
    if proposal.editorial_decision != "approved" or proposal.approved_proposal_hash != proposal_hash(proposal):
        raise BoundaryApplyError("PROPOSAL_NOT_APPROVED_AT_CURRENT_HASH")
    if not all(key in proposal.base_artifact_hashes for key in (HIGHLIGHTS, PLAN, BOARD)):
        raise BoundaryApplyError("BASE_07_08_09_HASHES_REQUIRED")
    if any(current_artifact_hashes.get(key) != value for key, value in proposal.base_artifact_hashes.items()):
        raise BoundaryApplyError("STALE_BASE_ARTIFACTS")
    matches = [h for h in highlights.candidates if h.highlight_id == proposal.candidate_id]
    if len(matches) != 1:
        raise BoundaryApplyError("CANDIDATE_ID_NOT_UNIQUE")
    old = matches[0]
    report = validate_boundary_proposal(proposal, manifest=manifest, candidate=old,
        scene_index=scene_index, scene_analysis=scene_analysis,
        knowledge_snapshot_hash=_frozen(story.knowledge_timeline), timebases=timebases)
    if report.validation_state != "accept":
        raise BoundaryApplyError(f"BOUNDARY_{report.validation_state.upper()}: " + "; ".join(
            f"{c.check}={c.state}" for c in report.checks if c.state != "accept"))
    raw_binding = {"state": "not_verified", "semantic_advisory": True,
                   "reason": "B1 evidence IDs and observations are caller-supplied; raw bytes not verified"}
    if proposal.raw_evidence_card_hashes:
        if raw_cards is None or evidence_root is None:
            raise BoundaryApplyError("DECLARED_RAW_EVIDENCE_CARDS_REQUIRED")
        from .raw_evidence import verify_boundary_raw_evidence
        raw_binding = verify_boundary_raw_evidence(proposal, raw_cards, manifest=manifest,
                                                  evidence_root=evidence_root)
    elif raw_cards is not None:
        raise BoundaryApplyError("RAW_CARDS_MUST_BE_BOUND_IN_APPROVED_PROPOSAL")
    source = next(s for s in manifest.sources if s.source_id == proposal.source_id)
    if highlights.source_fingerprints.get(source.source_id) != source.fingerprint:
        raise BoundaryApplyError("HIGHLIGHT_SOURCE_IDENTITY_CHANGED")
    if transcript.source_fingerprints.get(source.source_id) != source.fingerprint:
        raise BoundaryApplyError("TRANSCRIPT_SOURCE_IDENTITY_CHANGED")
    if old.must_hear_original and not proposal.must_preserve_source_track:
        raise BoundaryApplyError("ORIGINAL_AUDIO_PRESERVATION_DOWNGRADE")
    if "dialogue" in old.types and not proposal.dialogue_required:
        raise BoundaryApplyError("DIALOGUE_EVIDENCE_DOWNGRADE")
    # Do not silently overwrite a manually locked range, even within auto editing.
    if (old.model_extra or {}).get("protected") or (old.model_extra or {}).get("manual_lock"):
        raise BoundaryApplyError("PROTECTED_HIGHLIGHT")
    updated = highlights.model_copy(deep=True)
    candidate = next(h for h in updated.candidates if h.highlight_id == old.highlight_id)
    candidate.start, candidate.end = proposal.proposed_range.start, proposal.proposed_range.end
    events = _events_for_span(story, candidate.source_id, candidate.start, candidate.end)
    if set(proposal.event_ids) != {e.event_id for e in events}:
        raise BoundaryApplyError("EVENT_RANGE_RECONCILIATION_REQUIRED")
    candidate.event_ids = [e.event_id for e in events]
    known_characters = {c.character_id for c in story.character_registry.characters}
    participants = set(c for e in events for c in e.participants)
    if not participants <= known_characters or set(proposal.canonical_character_ids) != participants:
        raise BoundaryApplyError("CHARACTER_RECONCILIATION_REQUIRED")
    candidate.characters = sorted(participants)
    new_cues = _cues(transcript, candidate.source_id, candidate.start, candidate.end)
    candidate.quote = " ".join(cue.text for cue in new_cues)
    candidate.state_change = "; ".join(v for e in events for v in e.state_change.values())[:1000]
    candidate.scores.story_significance = max((e.confidence for e in events), default=0)
    states = {state.event_id: state for state in story.knowledge_timeline.states}
    contained = {e.event_id for e in events if e.event_id in states}
    old_events = {e.event_id for e in _events_for_span(story, old.source_id, old.start, old.end)}
    newly_exposed = contained - old_events
    if set(proposal.contained_reveal_ids) != contained or set(proposal.newly_exposed_reveal_ids) != newly_exposed:
        raise BoundaryApplyError("REVEAL_RANGE_RECONCILIATION_REQUIRED")
    if any(e.event_id not in states for e in events):
        raise BoundaryApplyError("REVEAL_EVIDENCE_UNKNOWN")
    candidate.risks.spoiler = max((0.85 if states[e.event_id].reveal_sensitivity == "high" else 0
                                  for e in events), default=0)
    # Semantic accept is advisory, so do not promote old boundary bools to hard
    # PASS. Store the explicit observation report alongside the new revision.
    candidate.boundary_review = report.model_dump(mode="json")
    candidate.must_hear_original = proposal.must_preserve_source_track
    candidate.source_sha256 = proposal.source_sha256
    candidate.timebase_hash = _frozen(proposal.timebase)
    candidate.unit_lineage = [ref.model_dump(mode="json") for ref in proposal.ordered_evidence_units]
    candidate.evidence_revision = fingerprint_json({"proposal": proposal_hash(proposal),
        "source": candidate.source_sha256, "range": [candidate.start, candidate.end],
        "timebase": candidate.timebase_hash, "units": candidate.unit_lineage})
    candidate.supersedes_evidence_revision = candidate_revision(old)
    candidate.evidence.append({"boundary_proposal": proposal_hash(proposal),
        "validation": report.model_dump(mode="json"), "old_highlight": old.model_dump(mode="json")})
    candidate.final_score = _compute_final_score(candidate, updated.weights)
    # Re-evaluate dedup/selection without erasing any rejected candidate. A
    # changed selected set needs a separate editorial revision of affected beats.
    comparison = [h.model_copy(deep=True) for h in updated.candidates
                  if h.rejection_reason != "candidate_pool_budget_exhausted"]
    for item in comparison:
        item.selected = False
    dedup = _deduplicate(comparison)
    selected = _select_diverse(dedup, config)
    if {h.highlight_id for h in selected} != {h.highlight_id for h in highlights.candidates if h.selected}:
        raise BoundaryApplyError("SELECTION_CHANGED_REPLAN_REQUIRED")
    selection_review = [{"highlight_id": h.highlight_id,
        "selected": h.selected, "rejection_reason": h.rejection_reason,
        "final_score": h.final_score} for h in comparison]
    new_plan, board = plan.model_copy(deep=True), storyboard.model_copy(deep=True)
    affected, beat_deltas = [], {}
    binding = highlight_reference_binding(candidate)
    for segment in board.segments:
        refs = [v for v in segment.visuals if v.highlight_id == old.highlight_id
                or v.unit_id == f"highlight:{old.highlight_id}"]
        if not refs and segment.highlight_id != old.highlight_id:
            continue
        if (segment.model_extra or {}).get("protected") or (segment.model_extra or {}).get("manual_lock"):
            raise BoundaryApplyError(f"PROTECTED_SEGMENT:{segment.segment_id}")
        affected.append(segment.segment_id)
        if segment.mode == "original":
            if len(segment.visuals) != 1 or (segment.visuals[0].source_id,
                segment.visuals[0].start, segment.visuals[0].end) != (old.source_id, old.start, old.end):
                raise BoundaryApplyError(f"MANUAL_ORIGINAL_RANGE_CONFLICT:{segment.segment_id}")
            previous_duration = segment.planned_duration_sec
            segment.visuals = [segment.visuals[0].model_copy(deep=True, update={
                "source_id": candidate.source_id, "start": candidate.start, "end": candidate.end,
                "highlight_id": candidate.highlight_id, "unit_id": f"highlight:{candidate.highlight_id}",
                **binding})]
            segment.planned_duration_sec = candidate.end - candidate.start
            segment.original_cues = new_cues
            segment.original_cues_verified = True
            segment.text_raw = candidate.quote
            segment.text = candidate.quote
            segment.mute_original = False
            beat_deltas[segment.beat_id] = beat_deltas.get(segment.beat_id, 0) + segment.planned_duration_sec - previous_duration
        else:
            for visual in refs:
                if visual.start < candidate.start or visual.end > candidate.end:
                    raise BoundaryApplyError(f"VO_SUBSPAN_OUTSIDE_NEW_EVIDENCE:{segment.segment_id}")
                for key, value in binding.items():
                    setattr(visual, key, value)
                # Its valid subrange and TTS remain unchanged.
        segment.status = "planned"
    for beat in new_plan.beats:
        delta = beat_deltas.get(beat.beat_id, 0)
        beat.target_original_sec += delta
        beat.target_duration_sec += delta
        if beat.target_original_sec < 0 or beat.target_duration_sec <= 0:
            raise BoundaryApplyError(f"INVALID_BEAT_BUDGET:{beat.beat_id}")
    if set(beat_deltas) - {beat.beat_id for beat in new_plan.beats}:
        raise BoundaryApplyError("UNKNOWN_STORYBOARD_BEAT")
    total_delta = sum(beat_deltas.values())
    new_plan.target_duration_sec += total_delta
    board.target_duration_sec += total_delta
    if new_plan.target_duration_sec <= 0:
        raise BoundaryApplyError("INVALID_TOTAL_BUDGET")
    hook = next((h for h in updated.candidates if h.highlight_id == new_plan.hook_highlight_id), None)
    if hook is None or not hook_eligibility(hook, story, config)[0]:
        raise BoundaryApplyError("HOOK_NO_LONGER_ELIGIBLE")
    allowed = proposal.allowed_output_position_constraints
    position = 0.0
    for segment in board.segments:
        if segment.segment_id in affected:
            if position < allowed.get("min_output_seconds", 0) or position > allowed.get("max_output_seconds", float("inf")):
                raise BoundaryApplyError("OUTPUT_REVEAL_POSITION_CONFLICT")
            if segment.hook_preposed and not hook_eligibility(candidate, story, config)[0]:
                raise BoundaryApplyError("NEW_REVEAL_FORBIDS_PREPOSE")
        position += segment_output_duration(segment)
    constraints = get_plan_constraints(new_plan, config)
    original_seconds = sum(segment_output_duration(s) for s in board.segments if s.mode == "original")
    actual_ratio = original_seconds / max(position, 0.001)
    lower, upper = constraints["original_ratio_range"]
    if not lower <= actual_ratio <= upper:
        raise BoundaryApplyError("ORIGINAL_RATIO_REPLAN_REQUIRED")
    new_plan.original_ratio_target = actual_ratio
    board.plan_fingerprint = _frozen(new_plan)
    validate_storyboard_visual_evidence(board, manifest, updated, scene_index, scene_analysis)
    artifacts = {HIGHLIGHTS: updated.model_dump(mode="json"), PLAN: new_plan.model_dump(mode="json"),
                 BOARD: board.model_dump(mode="json")}
    artifacts[SIDECAR] = {"schema_version": "boundary-adoption/1", "proposal": proposal.model_dump(mode="json"),
        "validation": report.model_dump(mode="json"), "raw_evidence_binding": raw_binding,
        "evidence_revision": candidate.evidence_revision,
        "base_artifact_hashes": proposal.base_artifact_hashes,
        "artifact_content_hashes": {key: fingerprint_json(value) for key, value in artifacts.items()},
        "affected_segment_ids": affected, "selection_review": selection_review,
        "original_seconds": original_seconds,
        "original_ratio": actual_ratio, "status": "prepared", "semantic_advisory": True,
        "downstream_recheck": ["tts_duration_coverage", "pre_qc", "render", "post_qc", "delivery"]}
    return PreparedBoundaryRevision(artifacts, tuple(affected), candidate.evidence_revision)


def apply_boundary_proposal(work_dir: str | Path, *, proposal: BoundaryProposal,
    base: dict, config: AppConfig, timebases: dict[str, TimebaseBinding],
    raw_cards: list | None = None, evidence_root: str | Path | None = None,
    candidate_check=None) -> dict:
    """Publish through I2; repeat preparation under its lock to prevent TOCTOU."""
    from .revision import adopt_revision
    from .workspace import preflight, read, sha
    from .models import CharacterRegistry, KnowledgeTimeline, StoryGraph

    def prepare_at(active):
        inputs = dict(manifest=SourceManifest.model_validate(read(active / "00_source_manifest.json")),
            highlights=HighlightDocument.model_validate(read(active / HIGHLIGHTS)),
            plan=RecapPlan.model_validate(read(active / PLAN)),
            storyboard=Storyboard.model_validate(read(active / BOARD)),
            transcript=TranscriptDocument.model_validate(read(active / "01_transcript.json")),
            scene_index=SceneIndex.model_validate(read(active / "02_scene_index.json")),
            scene_analysis=SceneAnalysisDocument.model_validate(read(active / "03_scene_analysis.json")))
        inputs["story"] = StoryBundle(
            character_registry=CharacterRegistry.model_validate(read(active / "04_character_registry.json")),
            story_graph=StoryGraph.model_validate(read(active / "05_story_graph.json")),
            knowledge_timeline=KnowledgeTimeline.model_validate(read(active / "06_knowledge_timeline.json")))
        prepared = prepare_boundary_revision(proposal, **inputs, config=config, timebases=timebases,
            current_artifact_hashes={key: sha(active / key) for key in proposal.base_artifact_hashes},
            raw_cards=raw_cards, evidence_root=evidence_root)
        if candidate_check is not None:
            audit = candidate_check(active, deepcopy(prepared.artifacts))
            if audit is not None:
                if not isinstance(audit, dict):
                    raise BoundaryApplyError("CANDIDATE_CHECK_AUDIT_INVALID")
                prepared.artifacts[SIDECAR]["additional_candidate_binding"] = deepcopy(audit)
        return prepared

    _, active = preflight(work_dir)
    prepared = prepare_at(active)

    def revalidate(current, artifacts):
        fresh = prepare_at(current)
        if fresh.artifacts != artifacts:
            raise BoundaryApplyError("PREPARED_BOUNDARY_CHANGED_UNDER_LOCK")

    return adopt_revision(work_dir, base=base, artifacts=prepared.artifacts,
        scope={"segment_ids": list(prepared.affected_segment_ids)}, kind="boundary",
        reason=f"Approved boundary proposal {proposal.proposal_id}", validator=revalidate)


def collect_boundary_timebases(manifest: SourceManifest) -> dict[str, TimebaseBinding]:
    """Read current demux clocks only after verifying full bytes before and after.

    Source seconds are elapsed from the first video stream's declared start PTS.
    Missing/contradictory clocks are a hard preparation error, never guessed CFR.
    This proves the mapping identity, not frame-perfect seek or AV semantics.
    """
    import math
    from fractions import Fraction
    from .media import ffprobe_json
    from .utils import content_fingerprint

    result = {}
    for source in manifest.sources:
        path = Path(source.path)
        if not path.is_file() or path.is_symlink() or source.identity_schema != "sha256-full/2":
            raise BoundaryApplyError(f"TIMEBASE_SOURCE_UNSAFE:{source.source_id}")
        if content_fingerprint(path) != source.fingerprint:
            raise BoundaryApplyError(f"TIMEBASE_SOURCE_SHA_CHANGED:{source.source_id}")
        data = ffprobe_json(path)
        videos = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"]
        if not videos:
            raise BoundaryApplyError(f"TIMEBASE_VIDEO_STREAM_MISSING:{source.source_id}")
        stream = videos[0]
        try:
            rate = Fraction(stream["time_base"])
            start_pts = int(stream["start_pts"])
            start_seconds = float(stream["start_time"])
            if rate <= 0 or not math.isfinite(start_seconds):
                raise ValueError("invalid timebase")
            # ffprobe decimal start_time is conventionally printed to six places.
            if abs(float(start_pts * rate) - start_seconds) > 0.000001:
                raise ValueError("contradictory PTS origin")
        except (KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
            raise BoundaryApplyError(f"TIMEBASE_MAPPING_UNKNOWN:{source.source_id}") from exc
        if content_fingerprint(path) != source.fingerprint:
            raise BoundaryApplyError(f"TIMEBASE_SOURCE_CHANGED_DURING_PROBE:{source.source_id}")
        result[source.source_id] = TimebaseBinding(mapping_version="ffprobe-stream-pts/1",
            numerator=rate.numerator, denominator=rate.denominator, origin_pts=start_pts,
            origin_seconds=0, method="demux_pts", verified=True)
    return result
