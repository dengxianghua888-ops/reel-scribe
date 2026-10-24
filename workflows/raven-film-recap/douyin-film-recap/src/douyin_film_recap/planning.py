from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import (
    HighlightDocument,
    RecapPlan,
    RhythmProfile,
    SceneAnalysisDocument,
    SceneIndex,
    SourceManifest,
    StoryBundle,
    Storyboard,
    StoryboardSegment,
    TranscriptDocument,
    VisualReference,
)
from .prompts import PLAN_SYSTEM, STORYBOARD_SYSTEM, plan_prompt, storyboard_prompt
from .narrative_contracts import (
    diagnose_plan_references,
    duration_bounds,
    get_plan_constraints,
    hook_eligibility,
    resolve_format_constraints,
    validate_visual_reference,
)
from .providers import OpenAICompatibleClient
from .utils import clamp, fingerprint_json


def _text_units(text: str) -> int:
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    non_cjk_words = len(re.findall(r"[A-Za-z0-9]+", text))
    punctuation = len(re.findall(r"[，。！？；：,.!?;:]", text))
    return cjk + non_cjk_words + max(0, punctuation // 3)


def choose_target_duration(
    manifest: SourceManifest,
    story: StoryBundle,
    config: AppConfig,
) -> tuple[str, float]:
    mode = config.format.duration_mode
    source_duration = sum(source.duration for source in manifest.sources)
    event_count = len(story.story_graph.events)
    character_count = len(story.character_registry.characters)
    reveal_count = sum(
        1
        for state in story.knowledge_timeline.states
        if state.reveal_sensitivity == "high"
    )

    def midpoint(bounds: tuple[int, int]) -> float:
        return float(sum(bounds) / 2)

    if mode == "highlight":
        return mode, midpoint(config.format.highlight_range_sec)
    if mode == "short":
        return mode, midpoint(config.format.short_range_sec)
    if mode == "standard":
        return mode, midpoint(config.format.standard_range_sec)
    if mode == "deep":
        return mode, midpoint(config.format.deep_range_sec)
    if mode == "series":
        # The bundled runtime makes one part per run. The report will recommend splitting.
        return mode, float(config.format.deep_range_sec[1])

    complexity = event_count + character_count * 1.5 + reveal_count * 2.5
    compressed_by_source = source_duration * (0.10 if source_duration > 5400 else 0.13)
    compressed_by_story = 150 + complexity * 9
    target = max(compressed_by_source, compressed_by_story)
    if complexity < 28 and source_duration < 2400:
        bounds = config.format.short_range_sec
        chosen_mode = "short"
    elif complexity < 58 and source_duration < 5400:
        bounds = config.format.standard_range_sec
        chosen_mode = "standard"
    else:
        bounds = config.format.deep_range_sec
        chosen_mode = "deep"
    target = clamp(target, float(bounds[0]), float(bounds[1]))
    return chosen_mode, round(target, 1)


def build_plan(
    manifest: SourceManifest,
    transcript: TranscriptDocument,
    story: StoryBundle,
    highlights: HighlightDocument,
    config: AppConfig,
    client: OpenAICompatibleClient,
) -> RecapPlan:
    selected = [candidate for candidate in highlights.candidates if candidate.selected]
    if not selected:
        raise ValueError("No highlight candidates passed selection")
    chosen_mode, suggested_duration = choose_target_duration(manifest, story, config)
    payload = {
        "platform": "douyin",
        "language": config.project.language,
        "duration_mode": chosen_mode,
        "suggested_target_duration_sec": suggested_duration,
        "source_duration_sec": sum(source.duration for source in manifest.sources),
        "content_unit": config.format.content_unit,
        "editorial_brief": config.project.editorial_brief.model_dump(mode="json"),
        "format_constraints": resolve_format_constraints(
            config, story.story_graph.genres, duration_mode=chosen_mode
        ),
        "story": {
            "genres": story.story_graph.genres,
            "main_plot": story.story_graph.main_plot,
            "themes": story.story_graph.themes,
            "events": [event.model_dump(mode="json") for event in story.story_graph.events],
            "knowledge_timeline": [
                state.model_dump(mode="json") for state in story.knowledge_timeline.states
            ],
            "characters": [
                character.model_dump(mode="json")
                for character in story.character_registry.characters
            ],
            "uncertainties": story.story_graph.uncertainties
            + story.character_registry.unresolved_conflicts,
        },
        "selected_highlights": [
            candidate.model_dump(mode="json") for candidate in selected
        ],
        "transcript_stats": {
            "segment_count": len(transcript.segments),
            "providers": transcript.provider,
        },
    }
    hook_checks = {
        candidate.highlight_id: hook_eligibility(candidate, story, config)
        for candidate in selected
    }
    eligible_ids = [key for key, (eligible, _) in hook_checks.items() if eligible]
    if not eligible_ids:
        raise ValueError(
            "No eligible opening highlight: all candidates have forbidden or unverified "
            "reveal order. Review event/knowledge evidence or provide an explicit editorial decision."
        )
    payload["eligible_hook_highlight_ids"] = eligible_ids
    payload["hook_eligibility"] = {
        key: {"eligible": eligible, "reason": reason}
        for key, (eligible, reason) in hook_checks.items()
    }
    # One bounded replan preserves the whole opening decision instead of silently
    # swapping in an unrelated or spoiler-heavy highest-ranked clip.
    for attempt in range(2):
        plan = client.chat_json(
            system=PLAN_SYSTEM,
            prompt=plan_prompt(payload),
            model_type=RecapPlan,
            temperature=config.models.temperature.get("creative", 0.45),
            max_tokens=9000,
            intent_key=f"plan:attempt:{attempt}",
        )
        if plan.hook_highlight_id in eligible_ids:
            break
        if attempt == 1:
            raise ValueError(f"Plan returned an ineligible hook after replan: {plan.hook_highlight_id}")
        payload["revision_required"] = (
            f"Previous hook {plan.hook_highlight_id!r} is ineligible. Replan the opening and "
            "its related beats using only eligible_hook_highlight_ids; do not change reveal permission."
        )
    constraints = payload["format_constraints"]
    plan.resolved_constraints = constraints
    plan.content_unit = config.format.content_unit
    plan.editorial_brief = config.project.editorial_brief.model_dump(mode="json")
    hook_reason = hook_checks[plan.hook_highlight_id][1]
    if hook_reason.startswith("explicit_spoiler_override:"):
        plan.risks.append(hook_reason)
    plan.duration_mode = chosen_mode
    lower, upper = duration_bounds(config, chosen_mode)
    plan.target_duration_sec = clamp(plan.target_duration_sec, float(lower), float(upper))
    plan.original_ratio_target = clamp(
        plan.original_ratio_target,
        constraints["original_ratio_range"][0],
        constraints["original_ratio_range"][1],
    )
    plan.rhythm = RhythmProfile(
        **{
            **plan.rhythm.model_dump(mode="python"),
            "first_payoff_deadline_sec": constraints["first_highlight_deadline_sec"],
            "micro_cycle_sec": constraints["micro_cycle_sec"],
            "reset_interval_sec": constraints["reset_interval_sec"],
            "vo_chars_per_sec": constraints["vo_chars_per_sec"],
            "original_ratio": constraints["original_ratio_range"],
            "max_original_over_15s": constraints["max_original_over_15s"],
        }
    )
    minimum_beats, maximum_beats = constraints["beat_count_range"]
    if not minimum_beats <= len(plan.beats) <= maximum_beats:
        raise ValueError(
            f"Recap plan must contain {minimum_beats}-{maximum_beats} beats for "
            f"{chosen_mode}, got {len(plan.beats)}"
        )
    seen_beat_ids: set[str] = set()
    for index, beat in enumerate(plan.beats, start=1):
        if not beat.beat_id or beat.beat_id in seen_beat_ids:
            beat.beat_id = f"beat_{index:02d}"
        seen_beat_ids.add(beat.beat_id)
    diagnostics = diagnose_plan_references(plan, story, highlights)
    missing = [item for item in diagnostics if item["blocking"]]
    if missing:
        raise ValueError("Plan reference check failed: " + "; ".join(
            f"{item['path']} (beat {item['beat_id']!r}): {item['message']}" for item in missing
        ))
    for item in diagnostics:
        plan.risks.append(
            f"{item['rule_id']} {item['path']} (beat {item['beat_id']!r}): "
            f"{item['message']} [status=unknown]"
        )
    return plan


def _sample_evenly(values: list[Any], count: int) -> list[Any]:
    if count <= 0:
        return []
    if len(values) <= count:
        return values
    if count == 1:
        return values[:1]
    return [values[index * (len(values) - 1) // (count - 1)] for index in range(count)]


def _build_visual_pool_r0(
    manifest: SourceManifest,
    story: StoryBundle,
    highlights: HighlightDocument,
    plan: RecapPlan,
    config: AppConfig,
    scene_index: SceneIndex | None,
    scene_analysis: SceneAnalysisDocument | None,
) -> list[dict[str, Any]]:
    """Offer ordinary, evidenced scene units as well as highlight-only visuals.

    A bounded, beat-stratified pool avoids feeding an entire long film back to
    the writer. This is a retrieval aid, not a claim that the final shots have
    been visually accepted.
    """
    sources = {source.source_id: source for source in manifest.sources}
    analyses = {item.unit_id: item for item in scene_analysis.items} if scene_analysis else {}
    units = []
    seen: set[str] = set()
    for unit in scene_index.units if scene_index else []:
        if unit.unit_id in seen:
            raise ValueError(f"Duplicate scene unit_id: {unit.unit_id}")
        seen.add(unit.unit_id)
        source = sources.get(unit.source_id)
        if source is None or unit.start < 0 or unit.end > source.duration + 0.001:
            raise ValueError(f"Scene unit has an invalid source range: {unit.unit_id}")
        if unit.unit_id in analyses:
            units.append(unit)
    limit = config.format.visual_pool_size
    chosen: dict[str, Any] = {}
    events = {event.event_id: event for event in story.story_graph.events}
    per_beat = max(1, limit // max(1, len(plan.beats)))
    for beat in plan.beats:
        spans = [
            span for event_id in beat.event_ids if event_id in events
            for span in events[event_id].source_spans
        ]
        related = [
            unit for unit in units if any(
                unit.source_id == span.source_id
                and min(unit.end, span.end) > max(unit.start, span.start)
                for span in spans
            )
        ]
        for unit in _sample_evenly(related, per_beat):
            if len(chosen) < limit:
                chosen[unit.unit_id] = unit
    remaining = [unit for unit in units if unit.unit_id not in chosen]
    for unit in _sample_evenly(remaining, limit - len(chosen)):
        chosen[unit.unit_id] = unit
    pool = []
    for unit in chosen.values():
        item = analyses[unit.unit_id]
        pool.append(
            {
                "unit_id": unit.unit_id,
                "source_id": unit.source_id,
                "start": unit.start,
                "end": unit.end,
                "evidence_type": "scene_analysis",
                "visible_facts": item.visible_facts,
                "dialogue_facts": item.dialogue_facts,
                "characters": [character.model_dump(mode="json") for character in item.characters],
                "events": item.events,
                "performance_moments": item.performance_moments,
                "uncertainties": item.uncertainties,
                "confidence": item.confidence,
                "scene_detection": (unit.scene_detection.model_dump(mode="json")
                                    if unit.scene_detection else None),
                "analysis_window_only": (unit.model_extra or {}).get("analysis_window_only", False),
                "original_shot_spans": (unit.model_extra or {}).get("original_shot_spans", unit.shot_spans),
                "continuity_shot_ids": (unit.model_extra or {}).get("continuity_shot_ids", []),
            }
        )
    from .boundary import highlight_reference_binding
    for highlight in highlights.candidates:
        if not highlight.selected:
            continue
        pool.append(
            {
                "unit_id": f"highlight:{highlight.highlight_id}",
                **highlight_reference_binding(highlight),
                "source_id": highlight.source_id,
                "start": highlight.start,
                "end": highlight.end,
                "evidence_type": "highlight",
                "highlight_id": highlight.highlight_id,
                "story_function": highlight.story_function,
                "quote": highlight.quote,
                "event_ids": highlight.event_ids,
                "confidence": highlight.confidence,
            }
        )
    return pool



def _build_visual_pool(
    manifest, story, highlights, plan, config, scene_index, scene_analysis,
    *, retrieval_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """R0 stays default; R1 uses its exact ordinary/highlight writer envelope."""
    baseline = _build_visual_pool_r0(manifest, story, highlights, plan, config,
                                     scene_index, scene_analysis)
    method = config.format.visual_retrieval
    if method == "r0":
        if retrieval_report is not None:
            from .retrieval import writer_input_bytes
            retrieval_report.update(method="r0-beat-stratified/1",
                ordinary_count=sum(row["evidence_type"] != "highlight" for row in baseline),
                highlight_append_count=sum(row["evidence_type"] == "highlight" for row in baseline),
                writer_bytes=writer_input_bytes(baseline), provider_token_budget_verified=False)
        return baseline
    if method != "r1":
        raise ValueError(f"Unsupported visual retrieval method: {method}")
    from .retrieval import build_retrieval_requests, rerank_visual_pool
    from .visual_evidence import _scene_unit_fingerprints
    if scene_index is None or scene_analysis is None:
        raise ValueError("R1 requires the current complete analyzed evidence index")
    if scene_index.source_fingerprints != {s.source_id:s.fingerprint for s in manifest.sources} or scene_analysis.unit_fingerprint not in _scene_unit_fingerprints(scene_index):
        raise ValueError("R1 evidence index has stale source/analysis bindings")
    expanded = config.model_copy(deep=True)
    expanded.format.visual_pool_size = len(scene_index.units)
    all_pool = _build_visual_pool_r0(manifest, story, highlights, plan, expanded,
                                    scene_index, scene_analysis)
    ordinary = [row for row in all_pool if row["evidence_type"] != "highlight"]
    event_ids = {row["unit_id"]:[event.event_id for event in story.story_graph.events
        if any(row["source_id"] == span.source_id and min(row["end"],span.end) > max(row["start"],span.start)
               for span in event.source_spans)] for row in ordinary}
    result = rerank_visual_pool(ordinary, r0_pool=baseline,
        requests=build_retrieval_requests(plan,story), ordinary_limit=config.format.visual_pool_size,
        exploration_fraction=config.format.visual_exploration_fraction,
        text_byte_budget=config.format.visual_pool_text_budget, unit_event_ids=event_ids)
    if retrieval_report is not None:
        retrieval_report.update(result.provenance)
    return result.pool


def _storyboard_payload(
    project_name: str,
    manifest: SourceManifest,
    story: StoryBundle,
    highlights: HighlightDocument,
    plan: RecapPlan,
    config: AppConfig,
    scene_index: SceneIndex | None = None,
    scene_analysis: SceneAnalysisDocument | None = None,
    *, retrieval_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    selected = [candidate for candidate in highlights.candidates if candidate.selected]
    minimum_segments = 3 if plan.duration_mode == "highlight" else 12
    estimated_segments = max(minimum_segments, min(64, int(math.ceil(plan.target_duration_sec / 14))))
    return {
        "project_name": project_name,
        "sources": [source.model_dump(mode="json") for source in manifest.sources],
        "plan_fingerprint": fingerprint_json(plan.model_dump(mode="json")),
        "target_duration_sec": plan.target_duration_sec,
        "estimated_segment_count": estimated_segments,
        "recap_plan": plan.model_dump(mode="json"),
        "characters": [
            character.model_dump(mode="json")
            for character in story.character_registry.characters
        ],
        "events": [event.model_dump(mode="json") for event in story.story_graph.events],
        "knowledge_timeline": [
            state.model_dump(mode="json") for state in story.knowledge_timeline.states
        ],
        "highlights": [candidate.model_dump(mode="json") for candidate in selected],
        "visual_pool": _build_visual_pool(
            manifest, story, highlights, plan, config, scene_index, scene_analysis,
            retrieval_report=retrieval_report,
        ),
        "constraints": get_plan_constraints(plan, config),
    }


def build_storyboard(
    *,
    project_name: str,
    manifest: SourceManifest,
    story: StoryBundle,
    highlights: HighlightDocument,
    plan: RecapPlan,
    config: AppConfig,
    client: OpenAICompatibleClient,
    scene_index: SceneIndex | None = None,
    scene_analysis: SceneAnalysisDocument | None = None,
) -> Storyboard:
    retrieval_report: dict[str, Any] = {}
    payload = _storyboard_payload(
        project_name, manifest, story, highlights, plan, config, scene_index, scene_analysis,
        retrieval_report=retrieval_report,
    )
    storyboard = client.chat_json(
        system=STORYBOARD_SYSTEM,
        prompt=storyboard_prompt(payload),
        model_type=Storyboard,
        temperature=config.models.temperature.get("creative", 0.45),
        max_tokens=16000,
        intent_key="storyboard:primary",
    )
    storyboard.project_name = project_name
    storyboard.sources = manifest.sources
    storyboard.plan_fingerprint = fingerprint_json(plan.model_dump(mode="json"))
    storyboard.target_duration_sec = plan.target_duration_sec
    if config.format.visual_retrieval == "r1":
        storyboard.retrieval_provenance = retrieval_report
        rankings = retrieval_report.get("per_beat_rankings", {})
        pool_kinds = {row["unit_id"]:row["evidence_type"] for row in payload["visual_pool"]}
        for segment in storyboard.segments:
            if segment.beat_id not in rankings:
                raise ValueError(f"R1 writer returned unknown Beat: {segment.beat_id}")
            allowed = {row["unit_id"]:row for row in rankings[segment.beat_id]}
            for visual in segment.visuals:
                if pool_kinds.get(visual.unit_id) == "highlight":
                    continue  # The unchanged selected-highlight append contract.
                row = allowed.get(visual.unit_id)
                if row is None:
                    raise ValueError(f"R1 visual violates Beat source/knowledge constraints: {segment.beat_id}/{visual.unit_id}")
                if row["requires_raw_verification"] and visual.visual_role == "direct_evidence":
                    raise ValueError("Exploration retrieval requires raw verification before direct-evidence use")
    _normalize_storyboard(
        storyboard, manifest, highlights, config,
        visual_pool=payload["visual_pool"], constraints=payload["constraints"],
    )
    return storyboard


def _normalize_storyboard(
    storyboard: Storyboard,
    manifest: SourceManifest,
    highlights: HighlightDocument,
    config: AppConfig,
    *,
    visual_pool: list[dict[str, Any]] | None = None,
    constraints: dict[str, Any] | None = None,
) -> None:
    source_map = {source.source_id: source for source in manifest.sources}
    highlight_map = {
        candidate.highlight_id: candidate for candidate in highlights.candidates
    }
    pool_map = {unit["unit_id"]: unit for unit in visual_pool} if visual_pool is not None else None
    # Generated and imported boards use the same reference contract. Invalid
    # IDs must be corrected before normalization, not silently rebound here.
    storyboard.unique_segment_ids()
    for index, segment in enumerate(storyboard.segments, start=1):
        normalized_visuals: list[VisualReference] = []
        for visual in segment.visuals:
            if segment.mode == "voiceover" and pool_map is not None:
                validate_visual_reference(visual, pool_map)
                visual.highlight_id = pool_map[visual.unit_id].get("highlight_id")
            source = source_map.get(visual.source_id)
            if source is None or visual.start < 0 or visual.end > source.duration:
                raise ValueError(f"Visual has invalid source range: {segment.segment_id}")
            # Preserve revision/protection/unknown metadata. Never clamp a new
            # boundary back into an old window or discard evidence bindings.
            normalized_visuals.append(visual.model_copy(deep=True))
        segment.visuals = normalized_visuals
        visual_highlight_ids = {
            visual.highlight_id for visual in segment.visuals if visual.highlight_id
        }
        if not segment.highlight_id and len(visual_highlight_ids) == 1:
            segment.highlight_id = next(iter(visual_highlight_ids))
        if segment.mode == "original":
            if segment.highlight_id and segment.highlight_id in highlight_map:
                highlight = highlight_map[segment.highlight_id]
                from .boundary import highlight_reference_binding, validate_highlight_reference_binding
                binding = highlight_reference_binding(highlight)
                if binding:
                    for visual in segment.visuals:
                        validate_highlight_reference_binding(visual, highlight)
                segment.visuals = [
                    VisualReference(
                        source_id=highlight.source_id,
                        start=highlight.start,
                        end=highlight.end,
                        purpose=highlight.story_function,
                        highlight_id=highlight.highlight_id,
                        unit_id=f"highlight:{highlight.highlight_id}",
                        visual_role="direct_evidence",
                        **binding,
                    )
                ]
                segment.text_raw = segment.text_raw or highlight.quote
                segment.text = segment.text_raw or segment.text
                segment.planned_duration_sec = highlight.end - highlight.start
                segment.mute_original = False
                # Keeping the source track does not imply speech. Preserve the
                # chosen role so action, ambience, music and silence do not acquire
                # dialogue-only sentence-boundary requirements.
            if not segment.visuals:
                raise ValueError(f"Original segment has no valid visual: {segment.segment_id}")
            segment.narration_job = "none"
            segment.mute_original = False
        else:
            if not segment.visuals:
                raise ValueError(f"Voiceover segment has no valid visual: {segment.segment_id}")
            units = _text_units(segment.text)
            min_cps, max_cps = (constraints or {}).get("vo_chars_per_sec", config.format.vo_chars_per_sec)
            ideal_duration = units / ((min_cps + max_cps) / 2) if units else 1.0
            visual_duration = sum(visual.end - visual.start for visual in segment.visuals)
            segment.planned_duration_sec = clamp(
                max(segment.planned_duration_sec, ideal_duration),
                max(1.0, units / max_cps if units else 1.0),
                max(1.0, visual_duration),
            )
            segment.audio_owner = "narration"
        if not segment.notes.strip():
            segment.notes = "由 dramatic editor 生成，需在 QC 中复核画面任务与声音分工。"

    if not storyboard.segments:
        raise ValueError("Storyboard contains no segments")
    if storyboard.segments[0].mode == "voiceover" and not storyboard.segments[0].text.strip():
        raise ValueError("Opening voiceover is empty")


def storyboard_expected_duration(storyboard: Storyboard) -> float:
    return sum(
        segment.audio_duration_sec
        if segment.mode == "voiceover" and segment.audio_duration_sec
        else segment.planned_duration_sec
        for segment in storyboard.segments
    )


def write_human_script(storyboard: Storyboard, output_path: str | Path) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"# {storyboard.project_name} · 解说与原片混排稿", ""]
    for index, segment in enumerate(storyboard.segments, start=1):
        label = "解说" if segment.mode == "voiceover" else "原片"
        source = ""
        if segment.visuals:
            first = segment.visuals[0]
            source = f" `{first.source_id} {first.start:.2f}-{first.end:.2f}s`"
        lines.extend(
            [
                f"## {index:02d}. [{label}] {segment.title}{source}",
                "",
                segment.text_raw if segment.mode == "original" else segment.text,
                "",
                f"> {segment.notes}",
                "",
            ]
        )
    target.write_text("\n".join(lines), encoding="utf-8")
    return target
