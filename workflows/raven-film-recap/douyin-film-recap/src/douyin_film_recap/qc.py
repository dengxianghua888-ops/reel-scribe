from __future__ import annotations

import difflib
import json
import math
import re
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from .asr import nearest_segment_boundaries
from .config import AppConfig
from .media import ffprobe_json, media_duration
from .models import (
    HighlightDocument,
    QCFinding,
    QCLocation,
    QCReport,
    RecapPlan,
    SceneAnalysisDocument,
    SceneIndex,
    SemanticQCBundle,
    SourceManifest,
    StoryBundle,
    Storyboard,
    TranscriptDocument,
)
from .prompts import SEMANTIC_QC_SYSTEM, semantic_qc_prompt
from .providers import OpenAICompatibleClient
from .subtitles import build_cues, output_timeline, resolved_visual_spans, segment_output_duration
from .utils import content_fingerprint, overlap_seconds, run_command
from .narrative_contracts import diagnose_plan_references, get_plan_constraints, hook_eligibility
from .visual_evidence import VisualEvidenceError, validate_storyboard_visual_evidence


class FindingBuilder:
    def __init__(self, prefix: str):
        self.prefix = prefix
        self.counter = 1
        self.findings: list[QCFinding] = []

    def add(
        self,
        *,
        stage: str,
        severity: str,
        blocking: bool,
        deterministic: bool,
        rule_id: str,
        message: str,
        segment_id: str | None = None,
        source_id: str | None = None,
        source_time: float | None = None,
        output_time: float | None = None,
        evidence: dict[str, Any] | None = None,
        next_action: str = "",
    ) -> None:
        finding_id = f"{self.prefix}_{self.counter:03d}"
        self.counter += 1
        self.findings.append(
            QCFinding(
                finding_id=finding_id,
                stage=stage,
                severity=severity,  # type: ignore[arg-type]
                blocking=blocking,
                deterministic=deterministic,
                rule_id=rule_id,
                message=message,
                location=QCLocation(
                    segment_id=segment_id,
                    source_id=source_id,
                    source_time=source_time,
                    output_time=output_time,
                ),
                evidence=evidence or {},
                next_action=next_action,
            )
        )


def _segment_highlight_ids(segment: Any) -> set[str]:
    ids: set[str] = set()
    if getattr(segment, "highlight_id", None):
        ids.add(segment.highlight_id)
    for visual in getattr(segment, "visuals", []) or []:
        if getattr(visual, "highlight_id", None):
            ids.add(visual.highlight_id)
    return ids


def _consumed_highlight_offset(segment: Any, highlight: Any) -> float | None:
    """Locate the first actual source overlap, including an offset inside a cut.

    A declared ID is not playback evidence. Surplus VO visuals and unconsumed
    tails are excluded by the same range resolver used by rendering and the EDL.
    """
    cursor = 0.0
    for visual in resolved_visual_spans(segment):
        if visual.source_id == highlight.source_id:
            overlap_start = max(visual.start, highlight.start)
            overlap_end = min(visual.end, highlight.end)
            if overlap_end - overlap_start > 1e-9:
                return cursor + overlap_start - visual.start
        cursor += visual.end - visual.start
    return None


def report_status(findings: Iterable[QCFinding]) -> str:
    values = list(findings)
    if any(item.blocking for item in values):
        return "BLOCKED"
    if any(item.severity in {"warning", "error", "critical"} for item in values):
        return "DEGRADED"
    return "PASSED"


def _semantic_qc(
    *,
    story: StoryBundle,
    highlights: HighlightDocument,
    plan: RecapPlan,
    storyboard: Storyboard,
    config: AppConfig,
    client: OpenAICompatibleClient,
) -> list[QCFinding]:
    # Match the pipeline's storyboard input identity: rendering only adds these
    # derived fields, and must not change a replayed semantic request's payload.
    semantic_storyboard = storyboard.model_dump(mode="json")
    semantic_storyboard.pop("output", None)
    for segment in semantic_storyboard.get("segments", []):
        for key in ("status", "rendered_file", "rendered_duration_sec"):
            segment.pop(key, None)
    payload = {
        "story": {
            "characters": [
                character.model_dump(mode="json")
                for character in story.character_registry.characters
            ],
            "events": [event.model_dump(mode="json") for event in story.story_graph.events],
            "knowledge_timeline": [
                state.model_dump(mode="json") for state in story.knowledge_timeline.states
            ],
        },
        "highlights": [
            candidate.model_dump(mode="json")
            for candidate in highlights.candidates
            if candidate.selected
        ],
        "plan": plan.model_dump(mode="json"),
        "storyboard": semantic_storyboard,
    }
    bundle = client.chat_json(
        intent_key="pre-qc:semantic",
        system=SEMANTIC_QC_SYSTEM,
        prompt=semantic_qc_prompt(payload),
        model_type=SemanticQCBundle,
        temperature=config.models.temperature.get("qc", 0.0),
        max_tokens=5000,
    )
    normalized: list[QCFinding] = []
    for index, finding in enumerate(bundle.findings, start=1):
        finding.finding_id = f"sem_{index:03d}"
        finding.stage = "pre_render"
        finding.deterministic = False
        finding.blocking = False
        if finding.severity == "critical":
            finding.severity = "error"
        normalized.append(finding)
    return normalized


def preflight_qc(
    *,
    manifest: SourceManifest,
    transcript: TranscriptDocument,
    story: StoryBundle,
    highlights: HighlightDocument,
    plan: RecapPlan,
    storyboard: Storyboard,
    config: AppConfig,
    client: OpenAICompatibleClient | None = None,
    scene_index: SceneIndex | None = None,
    scene_analysis: SceneAnalysisDocument | None = None,
) -> QCReport:
    builder = FindingBuilder("pre")
    if scene_index is not None:
        for source_id, detection in scene_index.source_detection.items():
            if detection.fallback_reason:
                builder.add(stage="pre_render", severity="warning", blocking=False, deterministic=True,
                            rule_id="SCENE_DETECTION_FALLBACK", source_id=source_id,
                            message="镜头检测已降级为分析窗口，切点不能视为已验证的真实镜头边界。",
                            evidence=detection.model_dump(mode="json"),
                            next_action="复核受影响素材的镜头边界与动作连续性。")
    visual_evidence_valid = True
    try:
        validate_storyboard_visual_evidence(
            storyboard, manifest, highlights, scene_index, scene_analysis,
        )
    except VisualEvidenceError as exc:
        visual_evidence_valid = False
        builder.add(stage="pre_render", severity="error", blocking=True, deterministic=True,
                    rule_id="VISUAL_EVIDENCE_INVALID", segment_id=exc.segment_id,
                    message=f"VO 画面证据无效：{exc}",
                    next_action="修正 unit_id、来源和时间范围；新镜头需登记场景单元及其分析证据。")
    source_map = {source.source_id: source for source in manifest.sources}
    constraints = get_plan_constraints(plan, config)
    storyboard_sources = {source.source_id: source for source in storyboard.sources}
    if len(source_map) != len(manifest.sources) or len(storyboard_sources) != len(storyboard.sources):
        builder.add(stage="pre_render", severity="critical", blocking=True, deterministic=True,
                    rule_id="DUPLICATE_SOURCE_ID", message="素材清单或 Storyboard 含重复 source_id。")
    if source_map.keys() != storyboard_sources.keys():
        builder.add(stage="pre_render", severity="critical", blocking=True, deterministic=True,
                    rule_id="SOURCE_IDENTITY_MISMATCH", message="Storyboard 与已索引素材清单的来源集合不同。",
                    evidence={"manifest": sorted(source_map), "storyboard": sorted(storyboard_sources)})
    for source_id in source_map.keys() & storyboard_sources.keys():
        indexed, rendered = source_map[source_id], storyboard_sources[source_id]
        differences = {}
        if Path(indexed.path).expanduser().resolve() != Path(rendered.path).expanduser().resolve():
            differences["path"] = [indexed.path, rendered.path]
        if indexed.fingerprint != rendered.fingerprint:
            differences["fingerprint"] = [indexed.fingerprint, rendered.fingerprint]
        if abs(indexed.duration - rendered.duration) > 0.001:
            differences["duration"] = [indexed.duration, rendered.duration]
        for field in ("width", "height", "fps", "has_audio"):
            if getattr(indexed, field) != getattr(rendered, field):
                differences[field] = [getattr(indexed, field), getattr(rendered, field)]
        if differences:
            builder.add(stage="pre_render", severity="critical", blocking=True, deterministic=True,
                        rule_id="SOURCE_IDENTITY_MISMATCH", source_id=source_id,
                        message="Storyboard 的实际渲染来源与已索引 Manifest 不一致。", evidence=differences)
    highlight_ids = {candidate.highlight_id for candidate in highlights.candidates}
    beat_ids = {beat.beat_id for beat in plan.beats}
    character_ids = {character.character_id for character in story.character_registry.characters}

    if story.character_registry.unresolved_conflicts:
        builder.add(
            stage="pre_render",
            severity="error",
            blocking=False,
            deterministic=False,
            rule_id="UNRESOLVED_CHARACTER_CONFLICT",
            message="人物注册表仍存在未解决身份冲突，成片不能标记为完全通过。",
            evidence={"conflicts": story.character_registry.unresolved_conflicts},
            next_action="复核人物名、别名、服装变化与相似角色。",
        )
    low_confidence_characters = [
        character.character_id
        for character in story.character_registry.characters
        if character.confidence < config.story.character_confidence_threshold
    ]
    if low_confidence_characters:
        builder.add(
            stage="pre_render",
            severity="warning",
            blocking=False,
            deterministic=False,
            rule_id="LOW_CHARACTER_CONFIDENCE",
            message="部分主要人物身份置信度低于阈值。",
            evidence={
                "characters": low_confidence_characters,
                "threshold": config.story.character_confidence_threshold,
            },
        )
    if story.story_graph.confidence < config.story.story_confidence_threshold:
        builder.add(
            stage="pre_render",
            severity="warning",
            blocking=False,
            deterministic=False,
            rule_id="LOW_STORY_CONFIDENCE",
            message="全局故事理解置信度低于配置阈值。",
            evidence={
                "actual": story.story_graph.confidence,
                "threshold": config.story.story_confidence_threshold,
            },
        )
    for event in story.story_graph.events:
        unknown_characters = set(event.participants) - character_ids
        if unknown_characters:
            builder.add(
                stage="pre_render",
                severity="critical",
                blocking=True,
                deterministic=True,
                rule_id="EVENT_UNKNOWN_CHARACTER",
                message=f"事件 {event.event_id} 引用了人物注册表中不存在的角色。",
                evidence={"unknown": sorted(unknown_characters)},
            )
        for span in event.source_spans:
            source = source_map.get(span.source_id)
            if source is None or span.start < 0 or span.end > (source.duration if source else 0) + 0.02:
                builder.add(
                    stage="pre_render",
                    severity="critical",
                    blocking=True,
                    deterministic=True,
                    rule_id="EVENT_EVIDENCE_OUT_OF_BOUNDS",
                    message=f"事件 {event.event_id} 的证据时间越界或来源不存在。",
                    source_id=span.source_id,
                    source_time=span.start,
                    evidence={"start": span.start, "end": span.end},
                )
    for diagnostic in diagnose_plan_references(plan, story, highlights):
        # Keep historical missing-ID gates, including on manually edited plans.
        # Narrative uncertainty is not promoted to a deterministic QC failure.
        if diagnostic["blocking"]:
            builder.add(
                stage="pre_render",
                severity="critical",
                blocking=True,
                deterministic=True,
                rule_id=diagnostic["rule_id"],
                message=f"Beat {diagnostic['beat_id']} {diagnostic['path']}: {diagnostic['message']}",
                evidence={"unknown": diagnostic["references"], **diagnostic},
            )

    if manifest.publish_mode == "publish" and not manifest.rights_confirmed:
        builder.add(
            stage="pre_render",
            severity="critical",
            blocking=True,
            deterministic=True,
            rule_id="RIGHTS_NOT_CONFIRMED",
            message="发布模式下尚未确认素材处理与发布权利。",
            next_action="在 config.yaml 中确认 rights_confirmed，或改用 draft 模式。",
        )

    used_ranges: list[tuple[str, float, float, str, bool]] = []
    original_duration = 0.0
    total_duration = 0.0
    long_originals = 0
    for segment_index, segment in enumerate(storyboard.segments):
        duration = segment_output_duration(segment)
        if segment.beat_id not in beat_ids:
            builder.add(
                stage="pre_render",
                severity="critical",
                blocking=True,
                deterministic=True,
                rule_id="STORYBOARD_UNKNOWN_BEAT",
                message=f"Storyboard 段 {segment.segment_id} 引用了未知 Beat。",
                segment_id=segment.segment_id,
                evidence={"beat_id": segment.beat_id},
            )
        total_duration += duration
        if segment.mode == "voiceover" and not segment.text.strip():
            builder.add(
                stage="pre_render",
                severity="error",
                blocking=True,
                deterministic=True,
                rule_id="EMPTY_SEGMENT_TEXT",
                message="Storyboard 段落没有文案或原片台词。",
                segment_id=segment.segment_id,
                next_action="补充 VO 文案或真实原片台词。",
            )
        if segment.highlight_id and segment.highlight_id not in highlight_ids:
            builder.add(
                stage="pre_render",
                severity="error",
                blocking=True,
                deterministic=True,
                rule_id="UNKNOWN_HIGHLIGHT",
                message=f"Storyboard 引用了不存在的高光 {segment.highlight_id}。",
                segment_id=segment.segment_id,
            )
        if segment.mode == "voiceover":
            if not segment.audio_file or not Path(segment.audio_file).exists():
                builder.add(
                    stage="pre_render",
                    severity="critical",
                    blocking=config.qc.fail_on_missing_audio,
                    deterministic=True,
                    rule_id="MISSING_TTS_AUDIO",
                    message="VO 段缺少可用 TTS 音频。",
                    segment_id=segment.segment_id,
                    next_action="重新执行 tts 阶段。",
                )
            elif not segment.audio_duration_sec or segment.audio_duration_sec <= 0:
                builder.add(
                    stage="pre_render",
                    severity="critical",
                    blocking=True,
                    deterministic=True,
                    rule_id="INVALID_TTS_DURATION",
                    message="VO 音频时长无效。",
                    segment_id=segment.segment_id,
                )
            visual_duration = sum(visual.end - visual.start for visual in segment.visuals)
            if segment.audio_duration_sec and visual_duration + 0.001 < segment.audio_duration_sec:
                builder.add(
                    stage="pre_render",
                    severity="critical",
                    blocking=config.qc.fail_on_tts_truncation,
                    deterministic=True,
                    rule_id="VISUAL_SHORTER_THAN_TTS",
                    message="VO 画面总时长短于音频，渲染会裁掉尾音。",
                    segment_id=segment.segment_id,
                    evidence={
                        "visual_duration": visual_duration,
                        "audio_duration": segment.audio_duration_sec,
                    },
                    next_action="缩短整句或补充不重复的相关画面。",
                )
        else:
            original_duration += duration
            if duration > 15:
                long_originals += 1
            if not segment.original_cues_verified:
                builder.add(
                    stage="pre_render",
                    severity="error",
                    blocking=False,
                    deterministic=True,
                    rule_id="ORIGINAL_CAPTIONS_UNVERIFIED",
                    message="原片段尚未绑定可信源时间字幕；不把场景描述伪造成对白字幕。",
                    segment_id=segment.segment_id,
                    next_action="从 transcript 绑定 original_cues；经检查无对白可为空。",
                )
            if len(segment.visuals) != 1:
                builder.add(
                    stage="pre_render",
                    severity="critical",
                    blocking=True,
                    deterministic=True,
                    rule_id="ORIGINAL_NOT_CONTIGUOUS",
                    message="原片高光必须引用一个连续源时间段。",
                    segment_id=segment.segment_id,
                )
            for cue in segment.original_cues:
                for visual in resolved_visual_spans(segment):
                    if cue.source_id != visual.source_id or cue.end <= visual.start or cue.start >= visual.end:
                        continue
                    partial = cue.start < visual.start - 0.001 or cue.end > visual.end + 0.001
                    reliable_words = [word for word in cue.words if word.timing_source in {"asr", "aligned"}
                                      and word.start >= visual.start - 0.001 and word.end <= visual.end + 0.001]
                    if partial and not reliable_words:
                        builder.add(stage="pre_render", severity="warning", blocking=False, deterministic=True,
                                    rule_id="PARTIAL_ORIGINAL_CAPTION_UNTIMED",
                                    message="原片裁切跨过源字幕边界且无可靠词级时间；不会按字数猜测字幕。",
                                    segment_id=segment.segment_id, source_id=cue.source_id,
                                    evidence={"cue": [cue.start, cue.end], "visual": [visual.start, visual.end]})

        if segment_index > 0:
            previous = storyboard.segments[segment_index - 1]
            previous_text = re.sub(r"\W+", "", previous.text_raw or previous.text)
            current_text = re.sub(r"\W+", "", segment.text_raw or segment.text)
            if previous_text and current_text:
                similarity = difflib.SequenceMatcher(None, previous_text, current_text).ratio()
                if similarity >= 0.72 and previous.mode != segment.mode:
                    builder.add(
                        stage="pre_render",
                        severity="warning",
                        blocking=False,
                        deterministic=True,
                        rule_id="ADJACENT_VO_ORIGINAL_DUPLICATION",
                        message="相邻 VO 与原片文本高度相似，可能把同一信息说了两遍。",
                        segment_id=segment.segment_id,
                        evidence={"previous_segment": previous.segment_id, "similarity": similarity},
                    )

        if segment.allow_reuse and not config.highlight.allow_hook_reuse:
            builder.add(
                stage="pre_render",
                severity="critical",
                blocking=True,
                deterministic=True,
                rule_id="HOOK_REUSE_DISABLED",
                message="Storyboard 声明了素材复用，但配置已关闭钩子复用。",
                segment_id=segment.segment_id,
            )

        for visual in resolved_visual_spans(segment):
            source = source_map.get(visual.source_id)
            if source is None:
                builder.add(
                    stage="pre_render",
                    severity="critical",
                    blocking=True,
                    deterministic=True,
                    rule_id="UNKNOWN_SOURCE",
                    message=f"引用了未知 source_id {visual.source_id}。",
                    segment_id=segment.segment_id,
                )
                continue
            if visual.start < 0 or visual.end > source.duration + 0.02 or visual.end <= visual.start:
                builder.add(
                    stage="pre_render",
                    severity="critical",
                    blocking=True,
                    deterministic=True,
                    rule_id="SOURCE_RANGE_OUT_OF_BOUNDS",
                    message="源时间范围越界或无效。",
                    segment_id=segment.segment_id,
                    source_id=visual.source_id,
                    source_time=visual.start,
                    evidence={"start": visual.start, "end": visual.end, "duration": source.duration},
                )
            for used_source, used_start, used_end, used_segment, used_allow in used_ranges:
                if used_source != visual.source_id:
                    continue
                overlap = overlap_seconds(visual.start, visual.end, used_start, used_end)
                if overlap > 0.2 and not (segment.allow_reuse or used_allow):
                    builder.add(
                        stage="pre_render",
                        severity="error",
                        blocking=True,
                        deterministic=True,
                        rule_id="UNDECLARED_SOURCE_REUSE",
                        message=f"与 {used_segment} 重复使用同一源时间，且未声明钩子复用。",
                        segment_id=segment.segment_id,
                        source_id=visual.source_id,
                        source_time=visual.start,
                        evidence={"overlap_sec": overlap},
                    )
            used_ranges.append(
                (visual.source_id, visual.start, visual.end, segment.segment_id, segment.allow_reuse)
            )

        if segment.mode == "original" and segment.visuals:
            visual = segment.visuals[0]
            entry_safe = exit_safe = True
            if segment.audio_owner == "original_dialogue":
                _, _, entry_safe, exit_safe = nearest_segment_boundaries(
                    transcript,
                    visual.source_id,
                    visual.start,
                    visual.end,
                    max_distance=0.45,
                )
            # A source track can contain speech even when action or ambience owns
            # the segment. Check actual cue cuts independently of that label, but
            # allow complete cues surrounded by a longer non-dialogue window.
            cut_cues = []
            for cue in transcript.segments:
                if cue.source_id != visual.source_id or not cue.text.strip():
                    continue
                entry_cut = cue.start + 0.02 < visual.start < cue.end - 0.02
                exit_cut = cue.start + 0.02 < visual.end < cue.end - 0.02
                if entry_cut or exit_cut:
                    entry_safe = entry_safe and not entry_cut
                    exit_safe = exit_safe and not exit_cut
                    cut_cues.append({"start": cue.start, "end": cue.end,
                                     "entry_cut": entry_cut, "exit_cut": exit_cut})
            if not entry_safe or not exit_safe:
                builder.add(
                    stage="pre_render",
                    severity="critical",
                    blocking=config.qc.fail_on_sentence_cut,
                    deterministic=True,
                    rule_id="UNSAFE_DIALOGUE_BOUNDARY",
                    message="原声对白没有落在可靠句段边界，存在残句风险。",
                    segment_id=segment.segment_id,
                    source_id=visual.source_id,
                    source_time=visual.start,
                    evidence={"entry_safe": entry_safe, "exit_safe": exit_safe,
                              "audio_owner": segment.audio_owner, "cut_cues": cut_cues},
                    next_action="移动到邻近完整句界，或改为 VO 压缩。",
                )

    if total_duration <= 0:
        builder.add(
            stage="pre_render",
            severity="critical",
            blocking=True,
            deterministic=True,
            rule_id="EMPTY_TIMELINE",
            message="Storyboard 总时长为 0。",
        )
    else:
        ratio = original_duration / total_duration
        lower, upper = constraints["original_ratio_range"]
        if ratio < lower or ratio > upper:
            builder.add(
                stage="pre_render",
                severity="warning",
                blocking=False,
                deterministic=True,
                rule_id="ORIGINAL_RATIO_OUTSIDE_BUDGET",
                message="原片占比偏离规划区间。",
                evidence={"actual": ratio, "expected": [lower, upper]},
                next_action="检查是否变成纯剧情口播或原片高光堆砌。",
            )
        target_delta = abs(total_duration - plan.target_duration_sec)
        if target_delta > max(45.0, plan.target_duration_sec * 0.25):
            builder.add(
                stage="pre_render",
                severity="error",
                blocking=target_delta > plan.target_duration_sec * 0.5,
                deterministic=True,
                rule_id="TARGET_DURATION_DRIFT",
                message="Storyboard 总时长与计划差距过大。",
                evidence={
                    "actual": total_duration,
                    "target": plan.target_duration_sec,
                    "delta": target_delta,
                },
            )
    if long_originals > constraints["max_original_over_15s"]:
        builder.add(
            stage="pre_render",
            severity="warning",
            blocking=False,
            deterministic=True,
            rule_id="TOO_MANY_LONG_ORIGINALS",
            message="超过 15 秒的长原片数量超出预算。",
            evidence={
                "actual": long_originals,
                "max": constraints["max_original_over_15s"],
            },
        )

    hook = next((item for item in highlights.candidates if item.highlight_id == plan.hook_highlight_id), None)
    hook_start = None
    if storyboard.segments:
        first = storyboard.segments[0]
        declared_first_ids = _segment_highlight_ids(first)
        first_highlight_ids = {
            item.highlight_id for item in highlights.candidates
            if item.highlight_id in declared_first_ids
            and _consumed_highlight_offset(first, item) is not None
        }
        if first_highlight_ids and plan.hook_highlight_id not in first_highlight_ids:
            builder.add(
                stage="pre_render",
                severity="warning",
                blocking=False,
                deterministic=True,
                rule_id="HOOK_MISMATCH",
                message="Storyboard 开头使用的高光与 RecapPlan 钩子不一致。",
                segment_id=first.segment_id,
            )
        cursor = 0.0
        longest_mode_run = {"voiceover": 0.0, "original": 0.0}
        current_mode = storyboard.segments[0].mode
        current_run = 0.0
        for segment in storyboard.segments:
            duration = segment_output_duration(segment)
            offset = _consumed_highlight_offset(segment, hook) if hook is not None else None
            if hook is not None and plan.hook_highlight_id in _segment_highlight_ids(segment) and offset is None:
                builder.add(
                    stage="pre_render", severity="error", blocking=True, deterministic=True,
                    rule_id="HOOK_REFERENCE_WITHOUT_SOURCE_EVIDENCE",
                    message="段落声明了钩子高光，但实际消费画面未包含该高光源范围。",
                    segment_id=segment.segment_id, output_time=cursor,
                    evidence={
                        "hook_highlight_id": hook.highlight_id,
                        "expected_source": {"source_id": hook.source_id, "start": hook.start, "end": hook.end},
                        "consumed_visuals": [visual.model_dump(mode="json") for visual in resolved_visual_spans(segment)],
                    },
                    next_action="将实际高光画面放入音频时长覆盖的有效区间，或移除伪挂引用并重排开头。",
                )
            if offset is not None and hook_start is None:
                hook_start = cursor + offset
            if segment.mode == current_mode:
                current_run += duration
            else:
                longest_mode_run[current_mode] = max(longest_mode_run[current_mode], current_run)
                current_mode = segment.mode
                current_run = duration
            cursor += duration
        longest_mode_run[current_mode] = max(longest_mode_run[current_mode], current_run)
        if hook_start is None:
            builder.add(
                stage="pre_render",
                severity="error",
                blocking=True,
                deterministic=True,
                rule_id="HOOK_NOT_USED",
                message="RecapPlan 选定的真实高光没有出现在实际消费的画面中。",
                evidence={"hook_highlight_id": plan.hook_highlight_id},
            )
        elif hook_start > constraints["first_highlight_deadline_sec"]:
            builder.add(
                stage="pre_render",
                severity="error",
                blocking=False,
                deterministic=True,
                rule_id="HOOK_TOO_LATE",
                message="第一处计划高光出现得晚于开头预算。",
                output_time=hook_start,
                evidence={
                    "actual_sec": hook_start,
                    "deadline_sec": constraints["first_highlight_deadline_sec"],
                },
            )
        if longest_mode_run["voiceover"] > 45:
            builder.add(
                stage="pre_render",
                severity="warning",
                blocking=False,
                deterministic=True,
                rule_id="LONG_CONTINUOUS_VOICEOVER",
                message="连续 VO 过长，声音声部缺少重启。",
                evidence={"longest_sec": longest_mode_run["voiceover"]},
            )
        if longest_mode_run["original"] > 60:
            builder.add(
                stage="pre_render",
                severity="warning",
                blocking=False,
                deterministic=True,
                rule_id="LONG_CONTINUOUS_ORIGINAL",
                message="连续原片过长，成片可能退化为高光回放。",
                evidence={"longest_sec": longest_mode_run["original"]},
            )

    # Planning and QC share the same spoiler/knowledge policy.
    if hook is not None:
        eligible, reason = hook_eligibility(hook, story, config)
        if not eligible and any(segment.hook_preposed for segment in storyboard.segments):
            builder.add(stage="pre_render", severity="error", blocking=True, deterministic=True,
                        rule_id="UNSAFE_HOOK_PREPOSE", message="钩子前置违反信息揭示约束。",
                        evidence={"reason": reason, "highlight_id": hook.highlight_id})

    semantic_checked = False
    if client is not None and visual_evidence_valid:
        try:
            builder.findings.extend(
                _semantic_qc(
                    story=story,
                    highlights=highlights,
                    plan=plan,
                    storyboard=storyboard,
                    config=config,
                    client=client,
                )
            )
            semantic_checked = True
        except Exception as exc:
            builder.add(
                stage="pre_render",
                severity="warning",
                blocking=not config.qc.allow_semantic_qc_failure,
                deterministic=True,
                rule_id="SEMANTIC_QC_UNAVAILABLE",
                message=f"语义 QC 不可用：{exc}",
                next_action="检查模型 Provider，或由人工审查故事与解说一致性。",
            )
    else:
        builder.add(stage="pre_render", severity="warning", blocking=False, deterministic=True,
                    rule_id="SEMANTIC_QC_NOT_RUN", message="未执行语义复核；结构通过不代表剧情与解说已验收。")

    metrics = {
        "segment_count": len(storyboard.segments),
        "timeline_duration_sec": total_duration,
        "target_duration_sec": plan.target_duration_sec,
        "original_duration_sec": original_duration,
        "original_ratio": original_duration / total_duration if total_duration else 0,
        "long_original_count": long_originals,
        "hook_start_sec": hook_start,
        "selected_highlight_count": sum(
            1 for candidate in highlights.candidates if candidate.selected
        ),
    }
    return QCReport(
        stage="pre_render",
        status=report_status(builder.findings),  # type: ignore[arg-type]
        findings=builder.findings,
        metrics=metrics,
        providers={"semantic_qc": config.models.llm_model if client else "off"},
        coverage={
            "structural": {"status": "checked", "method": "deterministic_preflight", "segment_count": len(storyboard.segments)},
            "semantic": {"status": "checked" if semantic_checked else "not_checked", "method": "model_advisory" if semantic_checked else None},
            "visual": {"status": "not_checked", "reason": "pre-render structural checks do not inspect composed pixels"},
            "audio": {"status": "not_checked", "reason": "transcript boundaries do not constitute listening"},
        },
    )


def _detect_intervals(
    video_path: Path,
    filter_name: str,
    regex_start: str,
    regex_end: str,
) -> list[tuple[float, float]]:
    if filter_name.startswith("blackdetect"):
        args = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            video_path,
            "-vf",
            filter_name,
            "-an",
            "-f",
            "null",
            "-",
        ]
    else:
        args = [
            "ffmpeg",
            "-hide_banner",
            "-i",
            video_path,
            "-af",
            filter_name,
            "-vn",
            "-f",
            "null",
            "-",
        ]
    result = run_command(args, timeout=1800)
    log = (result.stderr or "") + "\n" + (result.stdout or "")
    starts = [float(value) for value in re.findall(regex_start, log)]
    ends = [float(value) for value in re.findall(regex_end, log)]
    return [(start, end) for start, end in zip(starts, ends) if end > start]


def _codec_name(encoder: str) -> str:
    """Translate encoder selection to ffprobe's codec identity, not its library."""
    aliases = {
        "libx264": "h264", "libx264rgb": "h264", "libopenh264": "h264",
        "libx265": "hevc", "libvpx": "vp8", "libvpx-vp9": "vp9",
        "libaom-av1": "av1", "libsvtav1": "av1", "libfdk_aac": "aac",
        "libmp3lame": "mp3", "libopus": "opus", "libvorbis": "vorbis",
    }
    if encoder in aliases:
        return aliases[encoder]
    for codec in ("h264", "hevc", "av1", "vp9"):
        if encoder.startswith(codec + "_"):
            return codec
    return encoder


def _frame_rate(value: Any) -> float:
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError, TypeError):
        return 0.0


def _parse_srt(path: Path) -> list[tuple[float, float, str]]:
    text = path.read_text(encoding="utf-8-sig").strip()
    if not text:
        return []
    pattern = re.compile(r"^(\d{2,}):(\d{2}):(\d{2}),(\d{3}) --> (\d{2,}):(\d{2}):(\d{2}),(\d{3})$")
    parsed = []
    for block in re.split(r"\n\s*\n", text):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].strip().isdigit():
            raise ValueError("SRT cue lacks index, timing or text")
        match = pattern.fullmatch(lines[1].strip())
        if not match:
            raise ValueError("SRT timing is invalid")
        values = list(map(int, match.groups()))
        if any(values[index] >= 60 for index in (1, 2, 5, 6)):
            raise ValueError("SRT minutes or seconds exceed 59")
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        content = "\n".join(lines[2:]).strip()
        if end <= start or not content:
            raise ValueError("SRT cue has empty text or non-positive duration")
        parsed.append((start, end, content))
    return parsed


def _review_coverage(storyboard: Storyboard, final_hash: str, duration: float) -> dict[str, Any]:
    """Read independently supplied evidence. Never manufacture media review.

    This validates evidence identity and declared coverage, not reviewer honesty.
    The report preserves reviewer/method/references for an auditable handoff.
    """
    result = {kind: {"status": "not_checked", "reason": "no current independent review evidence"}
              for kind in ("visual", "audio")}
    review_file = storyboard.output.get("review_file")
    if not review_file or not Path(review_file).is_file():
        return result
    try:
        document = json.loads(Path(review_file).read_text(encoding="utf-8"))
        if document.get("artifact_sha256") != final_hash:
            raise ValueError("review evidence belongs to a different final artifact")
        for kind, methods in {
            "visual": {"human_frame_review", "media_model_frame_review"},
            "audio": {"human_listen", "media_model_listen"},
        }.items():
            for check in document.get("checks", []):
                if check.get("kind") != kind or check.get("result") != "passed":
                    continue
                if check.get("method") not in methods or not str(check.get("reviewer", "")).strip():
                    continue
                evidence = check.get("evidence", [])
                if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
                    continue
                ranges = sorted((float(start), float(end)) for start, end in check.get("checked_ranges", []))
                cursor = 0.0
                valid = bool(ranges)
                for start, end in ranges:
                    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start or start > cursor + 0.05 or end > duration + 0.05:
                        valid = False
                        break
                    cursor = max(cursor, end)
                if valid and cursor >= duration - 0.05:
                    result[kind] = {"status": "checked", "method": check["method"],
                                    "reviewer": check["reviewer"], "evidence": evidence,
                                    "checked_ranges": ranges, "artifact_sha256": final_hash,
                                    "provenance": "independent_review_record"}
                    break
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        for kind in result:
            result[kind] = {"status": "not_checked", "reason": str(exc)}
    return result


def _checked_realized_timeline(storyboard: Storyboard, config: AppConfig):
    """A stored output clock cannot override authored duration without bounds."""
    realized = storyboard.output.get("realized_timeline")
    if realized is None:
        return None
    actual = output_timeline(storyboard, realized_timeline=realized)
    if storyboard.output.get("timeline_policy") == "measured-segment-clock/1":
        # Default mode reports ordinary per-segment quantization separately.
        # Re-read the actual segment media: an output flag alone cannot relax QC.
        from .render_cache import verify_media
        from .render_timeline import build_realized_timeline
        contracts = {}
        evidence = storyboard.output.get("segment_clock_evidence", [])
        if not isinstance(evidence, list) or [item.get("segment_id") for item in evidence] != [s.segment_id for s in storyboard.segments]:
            raise ValueError("REALIZED_SEGMENT_EVIDENCE_MISSING")
        for segment, bound in zip(storyboard.segments, evidence):
            if not segment.rendered_file:
                raise ValueError("REALIZED_SEGMENT_MEDIA_MISSING")
            params = {name: getattr(config.render, name) for name in
                      ("fps", "width", "height", "video_codec", "audio_codec")}
            params["duration"] = segment_output_duration(segment)
            measured = verify_media(Path(segment.rendered_file), params,
                                    timeout=config.runtime.stage_timeout_sec)
            if measured["sha256"] != bound.get("sha256") or measured["size"] != bound.get("size"):
                raise ValueError("REALIZED_SEGMENT_MEDIA_CHANGED")
            contracts[segment.segment_id] = measured["media_contract"]
        measured = build_realized_timeline(storyboard, config.render.fps, contracts, strict_nominal=False)
        if measured != realized:
            raise ValueError("REALIZED_TIMELINE_DIFFERS_FROM_SEGMENT_MEDIA")
        return realized
    expected_cursor = 0.0
    tolerance = 1.0 / config.render.fps + 1e-8
    for segment, row in zip(storyboard.segments, actual):
        duration = segment_output_duration(segment)
        expected_cursor += duration
        if (abs(float(row["duration"]) - duration) > tolerance
                or abs(float(row["end"]) - expected_cursor) > tolerance):
            raise ValueError("REALIZED_TIMELINE_EXCEEDS_AUTHORED_TOLERANCE")
    return realized


def _subtitle_delivery_checks(
    builder: FindingBuilder, storyboard: Storyboard, config: AppConfig,
    duration: float, final_hash: str, *, realized_timeline=...,
) -> dict[str, Any]:
    try:
        if realized_timeline is ...:
            realized_timeline = _checked_realized_timeline(storyboard, config)
        expected = build_cues(storyboard, config, realized_timeline=realized_timeline)
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                    rule_id="INVALID_REALIZED_TIMELINE", message=f"实际时间图无效：{exc}")
        return {"status": "not_checked", "reason": str(exc)}
    for segment in storyboard.segments:
        if segment.mode == "original" and not segment.original_cues_verified:
            builder.add(stage="post_render", severity="warning", blocking=False, deterministic=True,
                        rule_id="ORIGINAL_CAPTIONS_UNVERIFIED", segment_id=segment.segment_id,
                        message="原声段字幕或无对白结论尚未绑定可信文字稿。")
        if segment.mode == "voiceover" and not segment.tts_word_boundaries:
            builder.add(stage="post_render", severity="warning", blocking=False, deterministic=True,
                        rule_id="VO_CAPTIONS_ESTIMATED", segment_id=segment.segment_id,
                        message="旁白字幕使用估算时间；未获得词级时间，不能宣称精确同步。")
    result: dict[str, Any] = {"status": "not_checked", "expected_cue_count": len(expected)}
    value = storyboard.output.get("subtitle")
    path = Path(value) if value else None
    if path is None or not path.is_file():
        builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                    rule_id="MISSING_SUBTITLE_FILE", message="交付字幕文件缺失。")
        return result
    try:
        cues = _parse_srt(path)
        if expected and not cues:
            raise ValueError("expected dialogue/narration captions are empty")
        previous_start = -1.0
        previous_end = -1.0
        for start, end, text in cues:
            if start < previous_start or end > duration + 0.05:
                raise ValueError("subtitle cue is unordered or outside final duration")
            if start < previous_end - 0.001:
                raise ValueError("subtitle cues overlap on the single caption track")
            previous_start, previous_end = start, end
            if end - start < 0.35:
                builder.add(stage="post_render", severity="warning", blocking=False, deterministic=True,
                            rule_id="SUBTITLE_READABILITY_RISK", message="字幕展示不足 0.35 秒，需人工检查可读性。",
                            evidence={"start": start, "end": end, "text": text})
            lines = text.splitlines()
            if len(lines) > config.render.subtitle_max_lines or any(len(line) > config.render.subtitle_max_chars_per_line for line in lines):
                builder.add(stage="post_render", severity="warning", blocking=False, deterministic=True,
                            rule_id="SUBTITLE_READABILITY_RISK", message="字幕超过配置行数或行长，需要按可靠词界重新分组。",
                            evidence={"start": start, "end": end, "text": text})
        if len(cues) != len(expected) or any(
            abs(actual[0] - planned.start) > 0.002 or abs(actual[1] - planned.end) > 0.002
            or actual[2] != planned.text.strip()
            for actual, planned in zip(cues, expected)
        ):
            raise ValueError("subtitle file differs from the current timed caption decisions")
        recorded_hash = storyboard.output.get("subtitle_fingerprint")
        if recorded_hash and recorded_hash != content_fingerprint(path):
            raise ValueError("subtitle artifact changed after rendering")
        result = {"status": "checked", "method": "srt_parse_and_timeline_match", "cue_count": len(cues)}
    except (OSError, UnicodeError, ValueError) as exc:
        builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                    rule_id="INVALID_SUBTITLE_FILE", message=f"字幕交付无效：{exc}")
    burn = storyboard.output.get("subtitle_burn_status")
    if config.render.subtitle_burn_in and expected:
        if burn != "applied" or storyboard.output.get("final_fingerprint") != final_hash:
            builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                        rule_id="SUBTITLE_BURN_UNVERIFIED", message="要求烧录字幕，但缺少绑定当前成片的成功烧录记录。")
    result["burn_status"] = burn
    return result


def post_render_qc(
    *,
    storyboard: Storyboard,
    config: AppConfig,
    attempts: int = 1,
) -> QCReport:
    builder = FindingBuilder("post")
    final_value = storyboard.output.get("final_video")
    if not final_value:
        builder.add(
            stage="post_render",
            severity="critical",
            blocking=True,
            deterministic=True,
            rule_id="MISSING_OUTPUT_REFERENCE",
            message="Storyboard 没有记录最终成片路径。",
        )
        return QCReport(
            stage="post_render",
            status="BLOCKED",
            findings=builder.findings,
            attempts=attempts,
        )
    final_path = Path(final_value)
    if not final_path.exists() or final_path.stat().st_size == 0:
        builder.add(
            stage="post_render",
            severity="critical",
            blocking=True,
            deterministic=True,
            rule_id="MISSING_FINAL_VIDEO",
            message="最终成片文件不存在或为空。",
            next_action="重新执行 render 阶段。",
        )
        return QCReport(
            stage="post_render",
            status="BLOCKED",
            findings=builder.findings,
            attempts=attempts,
        )

    final_hash = content_fingerprint(final_path)
    if storyboard.output.get("final_fingerprint") and storyboard.output["final_fingerprint"] != final_hash:
        builder.add(stage="post_render", severity="critical", blocking=True, deterministic=True,
                    rule_id="RENDER_ARTIFACT_MISMATCH", message="最终文件与本次渲染记录指纹不一致。")
    probe = ffprobe_json(final_path)
    streams = probe.get("streams", [])
    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), None
    )
    actual_duration = media_duration(final_path)
    try:
        checked_realized = _checked_realized_timeline(storyboard, config)
        timeline = output_timeline(storyboard, realized_timeline=checked_realized)
        expected_duration = float(timeline[-1]["end"]) if timeline else 0.0
    except (OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError) as exc:
        builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                    rule_id="INVALID_REALIZED_TIMELINE", message=f"实际时间图无效：{exc}")
        checked_realized = None
        expected_duration = sum(segment_output_duration(segment) for segment in storyboard.segments)
    if not video_stream:
        builder.add(
            stage="post_render",
            severity="critical",
            blocking=True,
            deterministic=True,
            rule_id="MISSING_VIDEO_STREAM",
            message="最终文件没有视频流。",
        )
    else:
        width = int(video_stream.get("width") or 0)
        height = int(video_stream.get("height") or 0)
        if (width, height) != (config.render.width, config.render.height):
            builder.add(
                stage="post_render",
                severity="critical",
                blocking=True,
                deterministic=True,
                rule_id="OUTPUT_DIMENSION_MISMATCH",
                message="最终分辨率与配置不一致。",
                evidence={
                    "actual": [width, height],
                    "expected": [config.render.width, config.render.height],
                },
            )
        for rate_name in ("avg_frame_rate", "r_frame_rate"):
            rate = _frame_rate(video_stream.get(rate_name))
            if abs(rate - config.render.fps) > max(0.02, config.render.fps * 0.001):
                builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                            rule_id="OUTPUT_FPS_MISMATCH", message="最终视频帧率与配置不一致或无法验证。",
                            evidence={"field": rate_name, "actual": rate, "expected": config.render.fps})
        if video_stream.get("codec_name") != _codec_name(config.render.video_codec):
            builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                        rule_id="OUTPUT_VIDEO_CODEC_MISMATCH", message="最终视频编码与配置不一致。",
                        evidence={"actual": video_stream.get("codec_name"), "expected": _codec_name(config.render.video_codec)})
    if not audio_stream:
        builder.add(
            stage="post_render",
            severity="critical",
            blocking=config.qc.fail_on_missing_audio,
            deterministic=True,
            rule_id="MISSING_AUDIO_STREAM",
            message="最终文件没有音频流。",
        )
    else:
        if audio_stream.get("codec_name") != _codec_name(config.render.audio_codec):
            builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                        rule_id="OUTPUT_AUDIO_CODEC_MISMATCH", message="最终音频编码与配置不一致。",
                        evidence={"actual": audio_stream.get("codec_name"), "expected": _codec_name(config.render.audio_codec)})
        if int(audio_stream.get("sample_rate") or 0) != 48000 or int(audio_stream.get("channels") or 0) != 2:
            builder.add(stage="post_render", severity="error", blocking=True, deterministic=True,
                        rule_id="OUTPUT_AUDIO_FORMAT_MISMATCH", message="最终音轨未满足渲染契约的 48 kHz 双声道。",
                        evidence={"sample_rate": audio_stream.get("sample_rate"), "channels": audio_stream.get("channels")})
    if abs(actual_duration - expected_duration) > config.qc.duration_tolerance_sec:
        builder.add(
            stage="post_render",
            severity="error",
            blocking=True,
            deterministic=True,
            rule_id="OUTPUT_DURATION_MISMATCH",
            message="最终时长与 Storyboard 预期不一致。",
            evidence={
                "actual": actual_duration,
                "expected": expected_duration,
                "tolerance": config.qc.duration_tolerance_sec,
            },
        )

    subtitle_coverage = _subtitle_delivery_checks(builder, storyboard, config, actual_duration, final_hash,
                                                  realized_timeline=checked_realized)
    nominal_duration = sum(segment_output_duration(segment) for segment in storyboard.segments)
    if abs(expected_duration - nominal_duration) > 1 / config.render.fps:
        builder.add(stage="post_render", severity="warning", blocking=False, deterministic=True,
                    rule_id="NOMINAL_FRAME_QUANTIZATION", message="逐段帧量化与名义计划时长存在累计差；字幕与 EDL 使用实测时间线。",
                    evidence={"nominal_duration_sec": nominal_duration,
                              "realized_duration_sec": expected_duration,
                              "delta_sec": expected_duration - nominal_duration})
    review_coverage = _review_coverage(storyboard, final_hash, actual_duration)
    for kind in ("visual", "audio"):
        if review_coverage[kind]["status"] != "checked":
            builder.add(stage="post_render", severity="warning", blocking=False, deterministic=True,
                        rule_id=f"{kind.upper()}_REVIEW_NOT_VERIFIED",
                        message=f"缺少绑定当前成片的{'画面' if kind == 'visual' else '听检'}复核证据。",
                        evidence=review_coverage[kind],
                        next_action="完成独立视听复核并写入 review_evidence.json，再重跑 post_qc；不要自动填造验收记录。")
    black_intervals: list[tuple[float, float]] = []
    silence_intervals: list[tuple[float, float]] = []
    black_checked = False
    silence_checked = False
    try:
        black_intervals = _detect_intervals(
            final_path,
            "blackdetect=d=0.20:pix_th=0.10",
            r"black_start:([0-9.]+)",
            r"black_end:([0-9.]+)",
        )
        black_checked = True
    except Exception as exc:
        builder.add(
            stage="post_render",
            severity="warning",
            blocking=False,
            deterministic=True,
            rule_id="BLACK_SCAN_UNAVAILABLE",
            message=f"黑帧检测失败：{exc}",
        )
    try:
        silence_intervals = _detect_intervals(
            final_path,
            "silencedetect=noise=-45dB:d=0.50",
            r"silence_start: ([0-9.]+)",
            r"silence_end: ([0-9.]+)",
        )
        silence_checked = True
    except Exception as exc:
        builder.add(
            stage="post_render",
            severity="warning",
            blocking=False,
            deterministic=True,
            rule_id="SILENCE_SCAN_UNAVAILABLE",
            message=f"静音检测失败：{exc}",
        )

    black_seconds = sum(end - start for start, end in black_intervals)
    silence_seconds = sum(end - start for start, end in silence_intervals)
    black_ratio = black_seconds / actual_duration if actual_duration else 1.0
    silence_ratio = silence_seconds / actual_duration if actual_duration else 1.0
    if black_ratio > config.qc.max_black_ratio:
        builder.add(
            stage="post_render",
            severity="error",
            blocking=True,
            deterministic=True,
            rule_id="EXCESSIVE_BLACK_FRAMES",
            message="成片黑帧占比超过阈值。",
            evidence={"ratio": black_ratio, "intervals": black_intervals},
        )
    if silence_ratio > config.qc.max_silence_ratio:
        builder.add(
            stage="post_render",
            severity="error",
            blocking=False,
            deterministic=True,
            rule_id="EXCESSIVE_SILENCE",
            message="成片长静音占比偏高。",
            evidence={"ratio": silence_ratio, "intervals": silence_intervals},
            next_action="检查 TTS、原声轨与音频映射。",
        )

    metrics = {
        "file_size_bytes": final_path.stat().st_size,
        "duration_sec": actual_duration,
        "expected_duration_sec": expected_duration,
        "black_ratio": black_ratio,
        "silence_ratio": silence_ratio,
        "black_intervals": black_intervals,
        "silence_intervals": silence_intervals,
        "artifact_sha256": final_hash,
    }
    return QCReport(
        stage="post_render",
        status=report_status(builder.findings),  # type: ignore[arg-type]
        findings=builder.findings,
        metrics=metrics,
        attempts=attempts,
        coverage={
            "structural": {"status": "checked", "method": "ffprobe_streams_and_duration", "artifact_sha256": final_hash},
            "black_scan": {"status": "checked" if black_checked else "not_checked", "method": "ffmpeg_blackdetect"},
            "silence_scan": {"status": "checked" if silence_checked else "not_checked", "method": "ffmpeg_silencedetect"},
            "subtitles": subtitle_coverage,
            **review_coverage,
        },
    )
