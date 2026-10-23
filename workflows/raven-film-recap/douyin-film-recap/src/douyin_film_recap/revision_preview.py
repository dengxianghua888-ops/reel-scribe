"""Read-only projections of existing selection and local revision evidence.

No lock is created: the existing revision snapshot is checked before and after
reading. This is an inspection, never an adoption or a QC/semantic verdict.
"""
from __future__ import annotations

from copy import deepcopy

from .models import SourceManifest, Storyboard, StoryboardSegment
from .revision import (BOARD, HIGHLIGHTS, LOCAL_FIELDS, PLAN, _file_identity,
                       _freeze, _protected, _validate_board, assert_revision_base)
from .workspace import WorkspaceError, digest, member, preflight, read


def _optional(active, name):
    path = member(active, name)
    value = read(path) if path.is_file() else {}
    if not isinstance(value, dict):
        raise WorkspaceError(f"PREVIEW_OPTIONAL_ARTIFACT_MUST_BE_OBJECT:{name}")
    return value


def _consumption(active, board, state, *, candidate, external, base):
    """Accept the existing render plan's content binding, never a loose EDL.

    Historical nonincremental output has no such binding. It stays unknown even
    when its old output dictionary contains a realized clock.
    """
    unknown = {"status": "unknown", "segments": []}
    if candidate:
        return {**unknown, "reason": "candidate_has_not_been_rendered"}
    parsed = Storyboard.model_validate(board)
    manifest = SourceManifest.model_validate(_optional(active, "00_source_manifest.json"))
    if parsed.sources != manifest.sources:
        return {**unknown, "reason": "render_storyboard_source_binding_mismatch"}
    timeline = board.get("output", {}).get("realized_timeline")
    if not timeline:
        return {**unknown, "reason": "realized_timeline_missing"}
    plan_path = board.get("output", {}).get("render_plan")
    record = state.get("stages", {}).get("render", {})
    if not plan_path or record.get("status") != "passed":
        return {**unknown, "reason": "render_evidence_not_bound"}
    try:
        outputs = board["output"]
        identities = {}
        for key in ("final_video", "preview_video", "subtitle", "edl", "render_plan", "render_receipt"):
            if key == "render_receipt" and not outputs.get(key):
                continue
            identity = _file_identity(outputs[key])
            external.append(identity)
            identities[key] = identity
            if record.get("artifacts", {}).get(identity["path"]) != identity["sha256"]:
                return {**unknown, "reason": "render_artifact_binding_mismatch", "artifact": key}
        render_plan = read(plan_path)
        from .render_contracts import PLAN_SCHEMA, authority_payload, digest as render_digest
        from .render import build_edl

        if (render_plan.get("schema") != PLAN_SCHEMA
                or render_plan.get("review_binding", {}).get("sha256") != render_digest(authority_payload(parsed))
                or render_plan.get("timeline", {}).get("realized") != timeline):
            return {**unknown, "reason": "render_plan_storyboard_binding_mismatch"}
        # Bind recorded narration to the same byte snapshot used by the preview.
        # Paths locate bytes; only digest and length establish content identity.
        audio = {row["path"]: row for row in base["audio"]}
        nodes = render_plan.get("nodes", [])
        for segment in parsed.segments:
            if segment.mode != "voiceover":
                continue
            identity = audio.get(segment.audio_file)
            matching = [node for node in nodes if node.get("kind") == "segment_av"
                        and node.get("segment_id") == segment.segment_id]
            if identity is None or len(matching) != 1:
                return {**unknown, "reason": "render_voice_binding_mismatch"}
            voices = [dep for dep in matching[0].get("inputs", [])
                      if dep.get("role") == "voice_bytes"]
            expected = {"role": "voice_bytes", "sha256": identity["sha256"], "size": identity["bytes"]}
            if voices != [expected]:
                return {**unknown, "reason": "render_voice_binding_mismatch"}
        consumed = read(outputs["edl"])
        if consumed != build_edl(parsed, realized_timeline=timeline):
            return {**unknown, "reason": "render_edl_storyboard_binding_mismatch"}
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
        return {**unknown, "reason": "render_evidence_unusable", "detail": str(exc)}
    return {"status": "recorded", "reason": "existing_render_plan_content_binding",
            "render_plan": identities["render_plan"], "segments": consumed,
            "media_reverified": False, "qc_inherited": False}


def _unit_locations(index, highlights):
    result = {row["unit_id"]: {key: row.get(key) for key in ("unit_id", "source_id", "start", "end")}
              for row in index.get("units", [])}
    for row in highlights.get("candidates", []):
        uid = f"highlight:{row['highlight_id']}"
        result[uid] = {"unit_id": uid, **{key: row.get(key)
                       for key in ("source_id", "start", "end", "highlight_id")}}
    return result


def _pool_ids(provenance):
    pool_ids = provenance.get("pool_unit_ids", [])
    if not isinstance(pool_ids, list) or any(not isinstance(uid, str) for uid in pool_ids):
        raise WorkspaceError("PREVIEW_RETRIEVAL_POOL_IDS_MUST_BE_STRING_LIST")
    return pool_ids


def _retrieval(provenance, beat_id, locations):
    pool_ids = _pool_ids(provenance)
    method = provenance.get("method", "unknown")
    if not isinstance(method, str):
        method = "unknown"
    if method != "r1-lexical/1":
        return {"status": "not_applicable" if method.startswith("r0-") else "unknown",
                "method": method, "reason": "no_recorded_r1_beat_evidence"}
    for key in ("per_beat_rankings", "coverage", "exclusions"):
        if not isinstance(provenance.get(key, {}), dict):
            raise WorkspaceError(f"PREVIEW_RETRIEVAL_FIELD_MUST_BE_OBJECT:{key}")
    for key in ("pool_unit_ids", "budget_exclusions"):
        if not isinstance(provenance.get(key, []), list):
            raise WorkspaceError(f"PREVIEW_RETRIEVAL_FIELD_MUST_BE_LIST:{key}")
    pool = set(pool_ids)
    rankings = provenance.get("per_beat_rankings", {}).get(beat_id, [])
    if not isinstance(rankings, list) or any(
            not isinstance(row, dict) or not isinstance(row.get("unit_id"), str) for row in rankings):
        raise WorkspaceError("PREVIEW_RETRIEVAL_RANKINGS_MUST_HAVE_UNIT_IDS")
    if any(not isinstance(row, dict) for row in provenance.get("budget_exclusions", [])):
        raise WorkspaceError("PREVIEW_RETRIEVAL_BUDGET_ROWS_MUST_BE_OBJECTS")
    ranked = []
    for row in rankings:
        uid = row["unit_id"]
        ranked.append({**deepcopy(row), "location": locations.get(uid),
                       "entered_candidate_pool": uid in pool,
                       "beat_role": "direct" if row.get("in_event_span") else "context_only"})
    coverage = deepcopy(provenance.get("coverage", {}).get(beat_id, {}))
    return {"status": "recorded", "method": method, "rankings": ranked,
            "exclusions": deepcopy(provenance.get("exclusions", {}).get(beat_id, [])),
            "budget_exclusions": [deepcopy(row) for row in provenance.get("budget_exclusions", [])
                                  if row.get("beat_id") == beat_id],
            "coverage": coverage or {"status": "unknown", "reason": "beat_coverage_not_recorded"},
            "support_complete": "unknown",
            "limitation": "candidate overlap does not establish all event spans or cross-episode support"}


def _raw_cards(cards, base):
    from .raw_evidence import RawEvidenceCard

    sources = {row["source_id"]: row["sha256"] for row in base["sources"]}
    result = []
    seen = set()
    validated = []
    for row in cards:
        card = RawEvidenceCard.model_validate(row)
        if card.evidence_id in seen:
            raise WorkspaceError("PREVIEW_DUPLICATE_RAW_EVIDENCE_ID")
        seen.add(card.evidence_id)
        validated.append(card)
        if sources.get(card.source_id) != card.source_sha256:
            raise WorkspaceError("PREVIEW_RAW_SOURCE_BINDING_MISMATCH")
        result.append({"card": deepcopy(row), "card_sha256": digest(row),
                       "asset_bytes_verified": False, "coverage_status": "unknown",
                       "reason": "declared_raw_card_only; no extraction, decoding or claim verification"})
    return result, validated


def preview_revision(work_dir, *, proposal=None, base=None, beat_ids=None, raw_cards=None):
    """Inspect current artifacts or an existing ``revise`` local proposal.

    ``base`` accepts the existing film-revision-base/1 snapshot. A candidate
    supplies its own base and exact local scope; dedicated domain requests keep
    their own commands. Returned target hashes are references, not apply tokens.
    """
    root, active = preflight(work_dir)
    proposal = deepcopy(proposal)
    raw_cards = deepcopy(raw_cards) if raw_cards is not None else []
    if not isinstance(raw_cards, list):
        raise WorkspaceError("RAW_CARDS_MUST_BE_A_LIST")
    if proposal is not None:
        if base is not None:
            raise WorkspaceError("PREVIEW_BASE_AND_PROPOSAL_ARE_EXCLUSIVE")
        if (not isinstance(proposal, dict)
                or set(proposal) - {"base", "artifacts", "scope", "kind", "reason"}):
            raise WorkspaceError("PREVIEW_LOCAL_PROPOSAL_REQUIRED; use dedicated narration/boundary commands")
        if proposal.get("kind", "local") != "local":
            raise WorkspaceError("DOMAIN_PROPOSAL_REQUIRES_DEDICATED_VALIDATOR")
        if set(proposal.get("artifacts", {})) != {BOARD}:
            raise WorkspaceError("REVISION_LOCAL_MEMBERS_INVALID")
        base = proposal.get("base")
        if base is None:
            raise WorkspaceError("REVISION_BASE_REQUIRED")
    if base is None:
        base = _freeze(active, root)
    else:
        base = deepcopy(base)
    active = assert_revision_base(root, base)
    original = read(member(active, BOARD))
    board = proposal["artifacts"][BOARD] if proposal else original
    parsed_board = Storyboard.model_validate(board)  # Keep raw fields and hashes unchanged.
    scope = deepcopy(proposal.get("scope", {})) if proposal else None
    scope_check = {"status": "not_requested"}
    if proposal:
        try:
            changed = _validate_board(original, board, scope, local=True)
            scope_check = {"status": "within_existing_local_scope", "changed_segment_ids": changed}
        except (ValueError, TypeError, AttributeError) as exc:
            scope_check = {"status": "rejected", "reason": str(exc)}

    plan = _optional(active, PLAN)
    highlights = _optional(active, HIGHLIGHTS)
    index = _optional(active, "02_scene_index.json")
    locations = _unit_locations(index, highlights)
    provenance = board.get("retrieval_provenance", {})
    if not isinstance(provenance, dict):
        raise WorkspaceError("PREVIEW_RETRIEVAL_PROVENANCE_MUST_BE_OBJECT")
    _pool_ids(provenance)  # Validate even when no beats are available to project.
    known_beats = {beat["beat_id"]: beat for beat in plan.get("beats", [])}
    for segment in board["segments"]:
        known_beats.setdefault(segment["beat_id"], None)
    selected = list(known_beats) if not beat_ids else list(dict.fromkeys(beat_ids))
    if not set(selected) <= set(known_beats):
        raise WorkspaceError("PREVIEW_UNKNOWN_BEAT:" + ",".join(sorted(set(selected) - set(known_beats))))

    external = []
    state = read(member(active, "state.json"))
    consumption = _consumption(active, board, state, candidate=proposal is not None, external=external, base=base)
    cards, typed_cards = _raw_cards(raw_cards, base)
    beats = []
    for beat_id in selected:
        references = []
        for segment in board["segments"]:
            if segment["beat_id"] != beat_id:
                continue
            references.append({"segment_id": segment["segment_id"], "mode": segment["mode"],
                "title": segment["title"], "text": segment["text"], "notes": segment["notes"],
                "highlight_id": segment.get("highlight_id"), "visuals": deepcopy(segment["visuals"]),
                "protected": _protected(segment),
                "unknown_fields": {k: deepcopy(v) for k, v in segment.items()
                                   if k not in StoryboardSegment.model_fields},
                "target_sha256": digest(segment)})
        visuals = [v for segment in parsed_board.segments if segment.beat_id == beat_id
                   for v in segment.visuals]
        card_ids = [card.evidence_id for card in typed_cards if any(
            visual.source_id == card.source_id
            and min(visual.end, card.requested_range.end)
                > max(visual.start, card.requested_range.start)
            for visual in visuals)]
        beats.append({"beat_id": beat_id, "plan": deepcopy(known_beats[beat_id]),
            "plan_binding": "recorded_reference" if known_beats[beat_id] is not None else "missing_beat",
            "retrieval": _retrieval(provenance, beat_id, locations),
            "storyboard_references": references, "overlapping_raw_card_ids": card_ids,
            "render_consumption": {**{k: v for k, v in consumption.items() if k != "segments"},
                "segments": [row for row in consumption["segments"] if row["beat_id"] == beat_id]}})

    pool_ids = provenance.get("pool_unit_ids")
    result = {"schema": "film-revision-preview/1", "base": base,
        "binding": {"storyboard_document_sha256": base["artifact_hashes"][BOARD],
            "target_content_sha256": digest(board),
            "proposal_sha256": digest(proposal) if proposal is not None else None,
            "raw_cards_sha256": digest(raw_cards)},
        "scope": scope, "scope_check": scope_check,
        "adoption": {"status": "not_validated", "command": "revise" if proposal else None,
            "supported_local_fields": sorted(LOCAL_FIELDS),
            "dedicated_commands": ["apply-boundary", "narration-revise-plan", "narration-revise-apply"]},
        "candidate_pool": {"status": "recorded" if pool_ids is not None else "unknown",
            "reason": "recorded_pool_ids" if pool_ids is not None else "pool_membership_not_recorded",
            "units": [deepcopy(locations.get(uid, {"unit_id": uid, "location": "unknown"}))
                      for uid in pool_ids or []]},
        "highlights": deepcopy(highlights.get("candidates", [])), "raw_evidence": cards, "beats": beats,
        "qc_status": "NOT_RUN", "semantic_and_av_review_inherited": False,
        "limitations": ["read_only_projection; no adoption, rendering, models or raw extraction",
            "scope_check is partial; original adoption validators and fresh QC remain required",
            "retrieval and raw declarations do not establish complete narrative support"]}
    # Recheck byte identities after all projection, including optional render
    # evidence outside the snapshot. No lock file or derived artifact is written.
    for identity in external:
        if _file_identity(identity["path"]) != identity:
            raise WorkspaceError("PREVIEW_RENDER_EVIDENCE_CHANGED")
    assert_revision_base(root, base)
    return result
