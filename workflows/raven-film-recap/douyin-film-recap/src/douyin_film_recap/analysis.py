from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import (
    CharacterRegistry,
    KnowledgeTimeline,
    SceneAnalysisBatch,
    SceneAnalysisDocument,
    SceneAnalysisItem,
    SceneIndex,
    StoryBundle,
    StoryChunkSummary,
    StoryGraph,
)
from .prompts import (
    SCENE_ANALYSIS_SYSTEM,
    STORY_CHUNK_SYSTEM,
    STORY_GLOBAL_SYSTEM,
    scene_batch_prompt,
    story_chunk_prompt,
    story_global_prompt,
)
from .parallel import run_parallel
from .providers import OpenAICompatibleClient
from .utils import chunks, fingerprint_json


def _ensure_scene_items(
    units: list[Any], items: list[SceneAnalysisItem]
) -> list[SceneAnalysisItem]:
    by_id = {item.unit_id: item for item in items}
    output: list[SceneAnalysisItem] = []
    for unit in units:
        if unit.unit_id in by_id:
            output.append(by_id[unit.unit_id])
        else:
            output.append(
                SceneAnalysisItem(
                    unit_id=unit.unit_id,
                    dialogue_facts=[unit.transcript] if unit.transcript else [],
                    uncertainties=["视觉模型未返回该单元，需后续复核"],
                    scores={
                        "drama": 0.0,
                        "performance": 0.0,
                        "dialogue": unit.signals.speech_density,
                        "action": unit.signals.motion,
                        "emotion": 0.0,
                        "reveal": 0.0,
                        "suspense": 0.0,
                        "comedy": 0.0,
                        "visual": unit.signals.motion,
                        "state_change": 0.0,
                    },
                    confidence=0.15,
                )
            )
    return output


def analyze_scenes(
    scene_index: SceneIndex,
    config: AppConfig,
    client: OpenAICompatibleClient,
) -> SceneAnalysisDocument:
    groups = list(chunks(scene_index.units, config.scene.contact_sheet_units))

    def analyze_group(index: int, units: list[Any]) -> tuple[int, list[SceneAnalysisItem]]:
        images = [unit.contact_sheet_path for unit in units if unit.contact_sheet_path]
        batch = client.chat_json(
            intent_key=f"scene-analysis:batch:{index:04d}",
            system=SCENE_ANALYSIS_SYSTEM,
            prompt=scene_batch_prompt(units),
            model_type=SceneAnalysisBatch,
            vision=True,
            images=images,
            temperature=config.models.temperature.get("analysis", 0.1),
            max_tokens=7000,
        )
        return index, _ensure_scene_items(units, batch.items)

    ordered: dict[int, list[SceneAnalysisItem]] = {}
    max_workers = max(1, min(config.scene.max_scene_analysis_workers, len(groups) or 1))
    for index, items in run_parallel(
        [(index, list(group)) for index, group in enumerate(groups)],
        lambda job: analyze_group(*job), max_workers=max_workers,
    ):
        ordered[index] = items
    all_items = [item for index in sorted(ordered) for item in ordered[index]]
    return SceneAnalysisDocument(
        provider=config.models.provider,
        model=config.models.vlm_model,
        items=all_items,
        unit_fingerprint=fingerprint_json(
            [unit.model_dump(mode="json") for unit in scene_index.units]
        ),
    )


def _scene_payload(
    scene_index: SceneIndex,
    scene_analysis: SceneAnalysisDocument,
) -> list[dict[str, Any]]:
    unit_map = {unit.unit_id: unit for unit in scene_index.units}
    payload: list[dict[str, Any]] = []
    for item in scene_analysis.items:
        unit = unit_map.get(item.unit_id)
        if unit is None:
            continue
        payload.append(
            {
                "unit_id": item.unit_id,
                "source_id": unit.source_id,
                "start": unit.start,
                "end": unit.end,
                "transcript": unit.transcript,
                "scene_detection": (unit.scene_detection.model_dump(mode="json")
                                    if unit.scene_detection else None),
                "visible_facts": item.visible_facts,
                "dialogue_facts": item.dialogue_facts,
                "characters": [value.model_dump(mode="json") for value in item.characters],
                "events": item.events,
                "relationships": item.relationships,
                "emotions": item.emotions,
                "performance_moments": item.performance_moments,
                "uncertainties": item.uncertainties,
                "confidence": item.confidence,
            }
        )
    return payload


def build_story(
    scene_index: SceneIndex,
    scene_analysis: SceneAnalysisDocument,
    config: AppConfig,
    client: OpenAICompatibleClient,
) -> StoryBundle:
    payload = _scene_payload(scene_index, scene_analysis)
    chunk_summaries: list[StoryChunkSummary] = []
    for index, group in enumerate(chunks(payload, config.story.chunk_units), start=1):
        chunk_id = f"chunk_{index:04d}"
        summary = client.chat_json(
            intent_key=f"story:summary:{chunk_id}",
            system=STORY_CHUNK_SYSTEM,
            prompt=story_chunk_prompt(chunk_id, list(group)),
            model_type=StoryChunkSummary,
            temperature=config.models.temperature.get("analysis", 0.1),
            max_tokens=6000,
        )
        summary.chunk_id = chunk_id
        chunk_summaries.append(summary)

    context = ""
    if config.story.allow_external_context and config.project.context_file:
        context_path = Path(config.project.context_file).expanduser()
        if not context_path.is_file():
            # An enabled, configured context must not silently become "no context".
            raise FileNotFoundError(f"Configured story context file not found: {context_path}")
        context = context_path.read_text(encoding="utf-8", errors="replace")[:30000]

    bundle = client.chat_json(
        intent_key="story:global",
        system=STORY_GLOBAL_SYSTEM,
        prompt=story_global_prompt(
            [summary.model_dump(mode="json") for summary in chunk_summaries], context
        ),
        model_type=StoryBundle,
        temperature=config.models.temperature.get("analysis", 0.1),
        max_tokens=12000,
    )
    _validate_story_bundle(bundle)
    return bundle


def _validate_story_bundle(bundle: StoryBundle) -> None:
    character_ids = {character.character_id for character in bundle.character_registry.characters}
    event_ids = {event.event_id for event in bundle.story_graph.events}
    if not bundle.story_graph.events:
        raise ValueError("Story graph contains no events")
    if not bundle.character_registry.characters:
        raise ValueError("Character registry contains no characters")
    for event in bundle.story_graph.events:
        if not event.source_spans:
            raise ValueError(f"Story event has no source evidence: {event.event_id}")
        unknown = set(event.participants) - character_ids
        if unknown:
            bundle.story_graph.uncertainties.append(
                f"{event.event_id} references unknown characters: {sorted(unknown)}"
            )
    for state in bundle.knowledge_timeline.states:
        if state.event_id not in event_ids:
            raise ValueError(
                f"Knowledge timeline references unknown event: {state.event_id}"
            )


def load_story_bundle(
    character_registry: CharacterRegistry,
    story_graph: StoryGraph,
    knowledge_timeline: KnowledgeTimeline,
) -> StoryBundle:
    return StoryBundle(
        character_registry=character_registry,
        story_graph=story_graph,
        knowledge_timeline=knowledge_timeline,
    )
