from __future__ import annotations

import shutil
import hashlib
import json
import stat
import os
import uuid
from urllib.parse import urlsplit
from pathlib import Path
from typing import Callable

from .analysis import build_story, load_story_bundle, analyze_scenes, read_story_context
from .asr import build_transcript
from .config import AppConfig
from .highlight import build_highlights
from .media import build_manifest, build_scene_index, find_sidecar_subtitle
from .models import (
    CharacterRegistry,
    HighlightDocument,
    KnowledgeTimeline,
    OriginalCue,
    QCReport,
    RecapPlan,
    SceneAnalysisDocument,
    SceneIndex,
    SourceManifest,
    StoryGraph,
    Storyboard,
    TranscriptDocument,
)
from .narrative_contracts import get_plan_constraints
from .planning import build_plan, build_storyboard, write_human_script
from .providers import OpenAICompatibleClient
from .qc import post_render_qc, preflight_qc
from .render import render_storyboard
from .state import STAGES, StateStore
from .send_guard import send_session
from .workspace import WorkspaceError, atomic, canonical, inventory, now, preflight, prepare, read, work_lock
from .tts import synthesize_storyboard
from .visual_evidence import VisualEvidenceError, validate_storyboard_visual_evidence
from .utils import (
    content_fingerprint,
    content_identity,
    discover_videos,
    fingerprint_json,
    read_json,
    safe_slug,
    write_json,
)


class StageBlocked(RuntimeError):
    def __init__(self, stage: str, report: QCReport):
        super().__init__(f"{stage} blocked with {len(report.findings)} finding(s)")
        self.stage = stage
        self.report = report


PIPELINE_REVISION = "0.3.0-workspace-2-cfr-1"


class FilmRecapPipeline:
    def __init__(
        self,
        *,
        input_path: str | Path,
        work_dir: str | Path,
        config: AppConfig,
        on_update: Callable[[str], None] | None = None,
        migrate_legacy: bool = False,
        recovery_bundle: str | Path | None = None,
        recovery_bundle_sha256: str | None = None,
    ):
        self.task_root, _ = preflight(work_dir, allow_legacy=migrate_legacy)
        self.input_path = Path(input_path).expanduser().resolve()
        self.work_dir = self.task_root
        if self.input_path.is_dir() and self.work_dir.is_relative_to(self.input_path):
            raise ValueError("work_dir must be outside the input media directory to prevent importing generated videos")
        if self.input_path.is_relative_to(self.work_dir):
            raise ValueError("Input media must be outside work_dir to protect source files from generated outputs")
        self.config = config.model_copy(deep=True)
        config = self.config  # All constructor bindings use the same frozen copy.
        self._config_fingerprint = self.config.fingerprint()
        self._endpoint = self._resolved_endpoint()
        self.on_update = on_update or (lambda _: None)
        self.project_name = safe_slug(
            self.input_path.stem if self.input_path.is_file() else self.input_path.name
        )
        self._client = None
        current_inputs = discover_videos(self.input_path)
        identities = [self._source_input_identity(path) for path in current_inputs]
        input_fingerprint = fingerprint_json(identities)
        context_fingerprint = None
        if config.story.allow_external_context and config.project.context_file:
            context_path = Path(config.project.context_file).expanduser()
            if context_path.exists():
                context_fingerprint = content_identity(context_path)
        runtime_fingerprint = fingerprint_json(
            {
                "config": config.fingerprint(),
                "pipeline_revision": PIPELINE_REVISION,
                "context_fingerprint": context_fingerprint,
                "remote_endpoint": self._endpoint,
            }
        )
        self.binding = {"schema": "film-input-binding/2", "input_paths": [str(self.input_path)],
                        "input_fingerprint": input_fingerprint,
                        "config_fingerprint": runtime_fingerprint, "sources": identities,
                        "context_identity": context_fingerprint}
        self.remote_policy = {"endpoint": self._endpoint,
            "models": [self.config.models.llm_model, self.config.models.vlm_model],
            "edge_tts": {key: getattr(self.config.tts, key) for key in ("voice", "rate", "pitch", "volume")}}
        with work_lock(self.task_root):
            _, previous_active = preflight(self.task_root, allow_legacy=migrate_legacy)
            revision_path = previous_active / ".receipts/revision-adoption.json"
            if revision_path.exists():
                if revision_path.is_symlink() or read(revision_path).get("schema") != "film-revision-adoption/1":
                    raise WorkspaceError("REVISION_RECEIPT_INVALID")
                previous_state = read(previous_active / "state.json")
                if (previous_state.get("input_fingerprint") != self.binding["input_fingerprint"] or
                        previous_state.get("config_fingerprint") != self.binding["config_fingerprint"]):
                    raise WorkspaceError("PROTECTED_REVISION_BINDING_CHANGED_USE_RENDER_CURRENT")
            self.task_root, self.work_dir, self.migration = prepare(
                self.task_root, self.binding, allow_legacy=migrate_legacy,
                recovery_bundle=recovery_bundle,
                recovery_bundle_sha256=recovery_bundle_sha256,
            )
        self.store = StateStore(self.work_dir)
        with work_lock(self.task_root):
            _, active = preflight(self.task_root)
            if active != self.work_dir:
                raise WorkspaceError("STALE_WORKSPACE_INSTANCE")
            self.state = self.store.load_or_create(
                project_name=self.project_name,
                input_paths=[str(self.input_path)],
                input_fingerprint=input_fingerprint,
                config_fingerprint=runtime_fingerprint,
            )
            atomic(self.work_dir / ".receipts/config-binding.json", self._config_receipt())

    def _config_receipt(self):
        return {"schema": "film-config-binding/1", "pipeline_revision": PIPELINE_REVISION,
                "config": self.config.model_dump(mode="json"),
                "explicit_format_fields": sorted(self.config.format.model_fields_set),
                "binding": self.binding, "remote_policy": self.remote_policy}

    @classmethod
    def from_current(cls, *, work_dir, config, on_update=None):
        """Open the current authored generation without prepare()/upstream stages.

        Older projects lacking the new config receipt require the exact original
        config. A verified receipt permits render-only config changes, published
        atomically as a new generation before rendering starts.
        """
        from .revision import BOARD, assert_revision_base, freeze_revision
        from .workspace import commit_generation

        root, _ = preflight(work_dir)
        with work_lock(root):
            _, active = preflight(root)
            base = freeze_revision(root)
            old = read(active / "state.json")
            if len(old.get("input_paths", [])) != 1:
                raise WorkspaceError("RENDER_CURRENT_SINGLE_INPUT_BINDING_REQUIRED")
            self = cls.__new__(cls)
            self.task_root, self.work_dir = root, active
            self.input_path = Path(old["input_paths"][0]).expanduser().resolve()
            self.config = config.model_copy(deep=True)
            self._config_fingerprint = self.config.fingerprint()
            self._endpoint = self._resolved_endpoint()
            self._client = None
            self.on_update = on_update or (lambda _: None)
            self.project_name = old.get("project_name", "film")
            self.migration = None
            identities = [self._source_input_identity(p) for p in discover_videos(self.input_path)]
            input_fingerprint = fingerprint_json(identities)
            if input_fingerprint != old.get("input_fingerprint"):
                raise WorkspaceError("SOURCE_BINDING_CHANGED")
            context = None
            if self.config.story.allow_external_context and self.config.project.context_file:
                context_path = Path(self.config.project.context_file).expanduser()
                if context_path.exists():
                    context = content_identity(context_path)
            runtime_fingerprint = fingerprint_json({"config": self.config.fingerprint(),
                "pipeline_revision": PIPELINE_REVISION, "context_fingerprint": context,
                "remote_endpoint": self._endpoint})
            self.binding = {"schema": "film-input-binding/2", "input_paths": [str(self.input_path)],
                "input_fingerprint": input_fingerprint, "config_fingerprint": runtime_fingerprint,
                "sources": identities, "context_identity": context}
            self.remote_policy = {"endpoint": self._endpoint,
                "models": [self.config.models.llm_model, self.config.models.vlm_model],
                "edge_tts": {key: getattr(self.config.tts, key)
                             for key in ("voice", "rate", "pitch", "volume")}}
            receipt_path = active / ".receipts/config-binding.json"
            if runtime_fingerprint != old.get("config_fingerprint"):
                if not receipt_path.is_file():
                    raise WorkspaceError("RENDER_CURRENT_ORIGINAL_CONFIG_REQUIRED")
                previous = read(receipt_path)
                prior_config = AppConfig.model_validate(previous.get("config", {}))
                prior_config.format.__pydantic_fields_set__ = set(previous.get("explicit_format_fields", []))
                prior_binding = previous.get("binding", {})
                verified_fingerprint = fingerprint_json({"config": prior_config.fingerprint(),
                    "pipeline_revision": previous.get("pipeline_revision"),
                    "context_fingerprint": prior_binding.get("context_identity"),
                    "remote_endpoint": previous.get("remote_policy", {}).get("endpoint")})
                comparable = self.config.model_copy(deep=True)
                comparable.render = prior_config.render.model_copy(deep=True)
                if (previous.get("schema") != "film-config-binding/1"
                        or verified_fingerprint != old.get("config_fingerprint")
                        or prior_binding.get("config_fingerprint") != old.get("config_fingerprint")
                        or previous.get("pipeline_revision") != PIPELINE_REVISION
                        or comparable.fingerprint() != prior_config.fingerprint()
                        or prior_binding.get("context_identity") != context
                        or previous.get("remote_policy") != self.remote_policy):
                    raise WorkspaceError("RENDER_CURRENT_NON_RENDER_CONFIG_CHANGED")
                board = read(active / BOARD)
                board["output"] = {}
                for segment in board["segments"]:
                    segment.pop("rendered_file", None)
                    segment.pop("rendered_duration_sec", None)
                    segment["status"] = "audio_ready" if segment.get("audio_file") else "planned"
                result = commit_generation(root,
                    replacements={BOARD: board, ".receipts/config-binding.json": self._config_receipt(),
                        ".receipts/revision-adoption.json": {"schema": "film-revision-adoption/1",
                            "kind": "render_config", "base": base, "qc_status": "NOT_RUN",
                            "semantic_and_av_review_inherited": False}},
                    expected_generation=base["generation"], expected_pointer_sha256=base["pointer_sha256"],
                    validate=lambda _: assert_revision_base(root, base), binding=self.binding,
                    reason="render-only configuration change")
                self.work_dir = Path(result["active_dir"])
            else:
                # Safe bootstrap: exact full runtime fingerprint was independently matched.
                atomic(receipt_path, self._config_receipt())
            self.store = StateStore(self.work_dir)
            self.state = self.store.load_or_create(project_name=self.project_name,
                input_paths=self.binding["input_paths"], input_fingerprint=input_fingerprint,
                config_fingerprint=runtime_fingerprint)
            self._render_current = True
            return self

    def render_only(self) -> Path:
        """Always run both QC gates and final composition; never rebuild model/TTS stages.

        No persisted remote grant is reused here. Exact send-intent results may
        replay; new or UNKNOWN requests cannot be sent by this entry.
        """
        from .revision import freeze_revision

        with work_lock(self.task_root):
            _, active = preflight(self.task_root)
            if active != self.work_dir:
                raise WorkspaceError("STALE_WORKSPACE_INSTANCE")
            self._assert_bound_sources()
            self.state = self.store.load_or_create(project_name=self.project_name,
                input_paths=self.binding["input_paths"],
                input_fingerprint=self.binding["input_fingerprint"],
                config_fingerprint=self.binding["config_fingerprint"])
            if (self.state.input_fingerprint != self.binding["input_fingerprint"] or
                    self.state.config_fingerprint != self.binding["config_fingerprint"]):
                raise WorkspaceError("STATE_BINDING_CHANGED")
            frozen = freeze_revision(self.task_root)
            self._validate_visual_evidence(self._storyboard())
            atomic(self.work_dir / ".receipts/render-current.json", {
                "schema": "film-render-current/1", "base": frozen,
                "stages": ["pre_qc", "render", "post_qc", "delivery"],
                "new_remote_requests_allowed": False, "tts_regenerated": False})
            self.store.invalidate_from(self.state, "pre_qc")
            self._render_current = True
            editorial = None
            for stage in ("pre_qc", "render", "post_qc", "delivery"):
                self._assert_bound_sources()
                if editorial is not None and self._storyboard_identity() != editorial:
                    raise WorkspaceError("RENDER_CURRENT_STORYBOARD_CHANGED")
                try:
                    self._prepare_stage(stage)
                except BaseException as exc:
                    self._record_stage_failure(stage, exc)
                    raise
                if editorial is None:
                    editorial = self._storyboard_identity()
                scope = {"binding": self.binding, "stage": stage,
                         "stage_inputs": self._stage_inputs(stage), "remote_policy": self.remote_policy}
                with send_session(self.task_root, scope, authorized=False, max_requests=0):
                    self._run_stage(stage)
                if self._storyboard_identity() != editorial:
                    raise WorkspaceError("RENDER_CURRENT_STORYBOARD_CHANGED")
            return self.paths["delivery"]

    @property
    def client(self):
        if self._client is None:
            self._client = OpenAICompatibleClient(self.config.models)
        return self._client

    @client.setter
    def client(self, value):
        self._client = value

    def _assert_bound_sources(self):
        if self.config.fingerprint() != self._config_fingerprint or self._resolved_endpoint() != self._endpoint:
            raise WorkspaceError("CONFIG_OR_ENDPOINT_BINDING_CHANGED")
        current = fingerprint_json([self._source_input_identity(p) for p in discover_videos(self.input_path)])
        if current != self.binding["input_fingerprint"]:
            raise WorkspaceError("SOURCE_BINDING_CHANGED: create a new generation before recomputing")
        context = None
        if self.config.story.allow_external_context and self.config.project.context_file:
            path = Path(self.config.project.context_file).expanduser()
            if path.exists():
                context = content_identity(path)
        if context != self.binding["context_identity"]:
            raise WorkspaceError("CONTEXT_BINDING_CHANGED")

    def _resolved_endpoint(self):
        value = os.getenv(self.config.models.base_url_env, "").strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise WorkspaceError("MODEL_ENDPOINT_MUST_NOT_CONTAIN_CREDENTIALS_OR_QUERY")
        return value or None

    @property
    def paths(self) -> dict[str, Path]:
        return {
            "manifest": self.work_dir / "00_source_manifest.json",
            "transcript": self.work_dir / "01_transcript.json",
            "scene_index": self.work_dir / "02_scene_index.json",
            "scene_analysis": self.work_dir / "03_scene_analysis.json",
            "characters": self.work_dir / "04_character_registry.json",
            "story": self.work_dir / "05_story_graph.json",
            "knowledge": self.work_dir / "06_knowledge_timeline.json",
            "highlights": self.work_dir / "07_highlight_candidates.json",
            "plan": self.work_dir / "08_recap_plan.json",
            "storyboard": self.work_dir / "09_storyboard.json",
            "pre_qc": self.work_dir / "10_preflight_qc.json",
            "post_qc": self.work_dir / "11_post_render_qc.json",
            "script": self.work_dir / "scripts" / "final_script.md",
            "delivery": self.work_dir / "output" / "delivery_report.md",
        }

    def _say(self, message: str) -> None:
        self.on_update(message)

    def _source_input_identity(self, path: Path) -> dict:
        subtitle = find_sidecar_subtitle(path) if self.config.asr.prefer_sidecar_subtitle else None
        return {
            "path": str(path), "identity": content_identity(path),
            "subtitle": {"path": str(subtitle), "identity": content_identity(subtitle)}
                        if subtitle else None,
        }

    def _snapshot_path(self, stage: str) -> Path:
        return self.work_dir / ".receipts" / f"{stage}_storyboard.json"

    def _storyboard_identity(self) -> dict:
        data = read_json(self.paths["storyboard"])
        data.pop("output", None)
        for segment in data.get("segments", []):
            for key in ("status", "rendered_file", "rendered_duration_sec"):
                segment.pop(key, None)
        return data

    def _stage_inputs(self, stage: str) -> str:
        dependencies = {
            "ingest": [], "transcript": ["manifest"], "scenes": ["manifest", "transcript"],
            "scene_analysis": ["scene_index"], "story": ["scene_index", "scene_analysis"],
            "highlights": ["manifest", "transcript", "scene_index", "scene_analysis", "characters", "story", "knowledge"],
            "plan": ["manifest", "transcript", "characters", "story", "knowledge", "highlights"],
            "storyboard": ["manifest", "characters", "story", "knowledge", "highlights", "plan", "scene_index", "scene_analysis"],
            "tts": ["manifest", "highlights", "plan", "scene_index", "scene_analysis"],
            "pre_qc": ["manifest", "transcript", "characters", "story", "knowledge", "highlights", "plan", "scene_index", "scene_analysis"],
            "render": ["pre_qc"], "post_qc": ["pre_qc"], "delivery": ["pre_qc", "post_qc", "highlights", "plan"],
        }
        payload: dict = {"config": self.state.config_fingerprint, "inputs": self.state.input_fingerprint}
        payload["files"] = {
            name: content_fingerprint(self.paths[name]) if self.paths[name].is_file() else "MISSING"
            for name in dependencies[stage]
        }
        if stage == "tts":
            board = self._storyboard_identity()
            payload["voiceover"] = [
                {key: segment.get(key) for key in ("segment_id", "text", "planned_duration_sec", "visuals", "narration_job")}
                for segment in board.get("segments", []) if segment.get("mode") == "voiceover"
            ]
        if stage in {"pre_qc", "render", "post_qc", "delivery"}:
            payload["storyboard"] = self._storyboard_identity()
            payload["audio"] = {
                segment["audio_file"]: content_fingerprint(segment["audio_file"])
                if Path(segment["audio_file"]).is_file() else "MISSING"
                for segment in payload["storyboard"].get("segments", [])
                if segment.get("mode") == "voiceover" and segment.get("audio_file")
            }
        if stage in {"post_qc", "delivery"}:
            output = read_json(self.paths["storyboard"]).get("output", {})
            payload["output"] = output
            payload["output_files"] = {
                key: content_fingerprint(output[key]) if Path(output[key]).is_file() else "MISSING"
                for key in ("final_video", "subtitle", "edl", "preview_video") if output.get(key)
            }
            evidence = Path(output.get("review_file") or self.work_dir / "output" / "review_evidence.json")
            payload["review_evidence"] = content_fingerprint(evidence) if evidence.is_file() else None
        return fingerprint_json(payload)

    def _required_artifacts(self, stage: str, artifact: Path | None) -> list[Path]:
        if stage in {"storyboard", "tts"}:
            paths = [self._snapshot_path(stage)]
            if stage == "tts":
                paths.append(self.paths["script"])
                paths.extend(Path(segment.audio_file) for segment in self._storyboard().segments
                             if segment.mode == "voiceover" and segment.audio_file)
            return paths
        paths = [artifact] if artifact else []
        if stage == "story":
            paths.extend([self.paths["characters"], self.paths["knowledge"]])
        elif stage == "ingest":
            paths.extend(Path(source.subtitle_path) for source in self._manifest().sources if source.subtitle_path)
        elif stage == "scenes":
            for unit in self._scene_index().units:
                paths.extend(Path(path) for path in unit.frame_paths)
                if unit.contact_sheet_path:
                    paths.append(Path(unit.contact_sheet_path))
        elif stage == "render":
            output = self._storyboard().output
            paths.extend(Path(output[key]) for key in ("preview_video", "subtitle", "edl") if output.get(key))
            if not all(output.get(key) for key in ("final_video", "preview_video", "subtitle", "edl")):
                raise ValueError("Render did not provide the complete delivery artifact set")
            paths.extend(Path(output[key]) for key in ("render_plan", "render_receipt") if output.get(key))
        elif stage == "delivery":
            paths.append(self.work_dir / "output" / "master.srt")
        return list(dict.fromkeys(paths))

    def _artifact_exists(self, stage: str) -> bool:
        record = self.state.stages[stage]
        artifacts = getattr(record, "artifacts", {})
        if not artifacts:
            return False
        if stage in {"storyboard", "tts"} and not self.paths["storyboard"].is_file():
            return False
        for name, expected in artifacts.items():
            path = Path(name)
            optional_debug = (stage == "scenes" and not self.config.runtime.keep_debug_frames
                              and self.state.stages["scene_analysis"].status == "passed"
                              and self.state.stages["highlights"].status == "passed"
                              and (path.is_relative_to(self.work_dir / "frames")
                                   or path.is_relative_to(self.work_dir / "contact_sheets")))
            if optional_debug and not path.exists():
                continue
            if not path.is_file() or content_fingerprint(path) != expected:
                return False
        try:
            return record.input_fingerprint == self._stage_inputs(stage)
        except (OSError, ValueError, KeyError):
            return False

    def _adopt_manual_artifacts(self, from_stage: str) -> None:
        # --from-stage is the explicit handoff: preserve edits to preceding authored JSONs.
        for stage in STAGES[:min(STAGES.index(from_stage), STAGES.index("tts"))]:
            record = self.state.stages[stage]
            if record.status != "passed":
                continue
            artifacts = getattr(record, "artifacts", {})
            if artifacts and all(Path(path).is_file() for path in artifacts):
                try:
                    input_fingerprint = self._stage_inputs(stage)
                except (OSError, ValueError, KeyError):
                    continue  # Missing dependencies must be rebuilt by the normal stage loop.
                record.artifacts = {path: content_fingerprint(path) for path in artifacts}
                record.input_fingerprint = input_fingerprint
        self.store.save(self.state)

    def run(self, *, until: str | None = None, from_stage: str | None = None,
            allow_remote: bool = False, max_remote_requests: int | None = None) -> Path:
        if until and until not in STAGES:
            raise ValueError(f"Unknown stage: {until}")
        if from_stage and from_stage not in STAGES:
            raise ValueError(f"Unknown stage: {from_stage}")
        if max_remote_requests is not None and max_remote_requests < 0:
            raise ValueError("max_remote_requests must be non-negative")
        # Unknown versions are rejected before even creating the cooperating lock.
        _, active = preflight(self.task_root)
        with work_lock(self.task_root):
            _, active = preflight(self.task_root)
            if active != self.work_dir:
                raise WorkspaceError("STALE_WORKSPACE_INSTANCE")
            self._assert_bound_sources()
            self.state = self.store.load_or_create(project_name=self.project_name,
                input_paths=self.binding["input_paths"],
                input_fingerprint=self.binding["input_fingerprint"],
                config_fingerprint=self.binding["config_fingerprint"])
            if (self.state.input_fingerprint != self.binding["input_fingerprint"] or
                    self.state.config_fingerprint != self.binding["config_fingerprint"]):
                raise WorkspaceError("STATE_BINDING_CHANGED")
            revision_path = self.work_dir / ".receipts/revision-adoption.json"
            protected_revision = revision_path.exists()
            if protected_revision:
                if revision_path.is_symlink() or read(revision_path).get("schema") != "film-revision-adoption/1":
                    raise WorkspaceError("REVISION_RECEIPT_INVALID")
                if not from_stage:
                    raise WorkspaceError("PROTECTED_REVISION_REQUIRES_RENDER_CURRENT_OR_EXPLICIT_FROM_STAGE")
            if not self.config.runtime.cache and not protected_revision:
                self.store.invalidate_from(self.state, "ingest")
            effective_from = from_stage
            if protected_revision and STAGES.index(from_stage) > STAGES.index("pre_qc"):
                effective_from = "pre_qc"  # Explicit resume still cannot bypass either QC gate.
            if effective_from:
                self._adopt_manual_artifacts(effective_from)
                self.store.invalidate_from(self.state, effective_from)
            selected = list(self.store.selected_stages(until))
            if protected_revision:
                selected = [stage for stage in selected if STAGES.index(stage) >= STAGES.index(effective_from)]
                if not selected:
                    raise WorkspaceError("REVISION_UNTIL_PRECEDES_FROM_STAGE")
            grant_path = self.task_root / ".remote-authorization.json"
            grant = None
            if allow_remote:
                grant = {"schema": "film-remote-authorization/1", "id": uuid.uuid4().hex,
                    "binding": self.binding, "remote_policy": self.remote_policy,
                    "stages": selected, "max_requests": max_remote_requests,
                    "request_limit_is_billing_cap": False}
                atomic(grant_path, grant)
            elif grant_path.is_file():
                previous = read(grant_path)
                if (previous.get("schema") == "film-remote-authorization/1"
                        and previous.get("binding") == self.binding
                        and previous.get("remote_policy") == self.remote_policy
                        and set(selected) <= set(previous.get("stages", []))):
                    grant = previous
            atomic(self.work_dir / ".receipts" / "recompute-plan.json", {
                "schema": "film-recompute-plan/1", "binding": self.binding,
                "selected_stages": selected, "from_stage": from_stage,
                "allow_remote": allow_remote, "max_remote_requests": max_remote_requests,
                "existing_authorization_reused": bool(grant and not allow_remote),
                "request_limit_is_billing_cap": False})
            remaining = max_remote_requests
            for stage in selected:
                self._assert_bound_sources()
                if self.state.stages[stage].status == "passed" and self._artifact_exists(stage):
                    self._say(f"[cache] {stage}")
                    continue
                self.store.invalidate_from(self.state, stage)
                try:
                    self._prepare_stage(stage)
                except BaseException as exc:
                    self._record_stage_failure(stage, exc)
                    raise
                scope = {"binding": self.binding, "stage": stage,
                         "stage_inputs": self._stage_inputs(stage), "remote_policy": self.remote_policy}
                with send_session(self.task_root, scope, authorized=bool(grant),
                                  max_requests=remaining, grant=grant) as sends:
                    self._run_stage(stage)
                if remaining is not None:
                    remaining -= sends.sent
        return (self.paths["delivery"] if self.state.stages["delivery"].status == "passed"
                and self.paths["delivery"].is_file() else self.work_dir)

    def _prepare_stage(self, stage):
        if stage == "pre_qc":
            storyboard, snapshot = self._render_storyboard_snapshot()
            self._attach_original_cues(storyboard)
            self._publish_render_storyboard(storyboard, snapshot)

    def _record_stage_failure(self, stage: str, error: BaseException) -> None:
        try:
            self.store.fail(self.state, stage, error)
        except BaseException as persistence_error:
            # Disk/receipt failures must not disguise the original interruption.
            error.add_note(
                f"Could not persist {stage} failure: {type(persistence_error).__name__}: {persistence_error}"
            )

    def _run_stage(self, stage: str) -> None:
        handler = getattr(self, f"_stage_{stage}")
        self._say(f"[start] {stage}")
        try:
            self.store.start(self.state, stage)
            artifact = handler()
            self._assert_bound_sources()
            if stage in {"storyboard", "tts"}:
                write_json(self._snapshot_path(stage), read_json(self.paths["storyboard"]))
            required = self._required_artifacts(stage, artifact)
            fingerprints = {str(path): content_fingerprint(path) for path in required}
            self.store.pass_stage(
                self.state, stage, artifact=str(artifact) if artifact else None,
                fingerprint=content_fingerprint(artifact) if artifact and artifact.is_file() else None,
                artifacts=fingerprints, input_fingerprint=self._stage_inputs(stage),
            )
            self._say(f"[done] {stage}")
        except BaseException as exc:
            self._record_stage_failure(stage, exc)
            try:
                self._say(f"[failed] {stage}: {exc}")
            except BaseException as update_error:
                exc.add_note(f"Failure update could not be delivered: {update_error}")
            raise

    def _manifest(self) -> SourceManifest:
        return SourceManifest.model_validate(read_json(self.paths["manifest"]))

    def _transcript(self) -> TranscriptDocument:
        return TranscriptDocument.model_validate(read_json(self.paths["transcript"]))

    def _scene_index(self) -> SceneIndex:
        return SceneIndex.model_validate(read_json(self.paths["scene_index"]))

    def _scene_analysis(self) -> SceneAnalysisDocument:
        return SceneAnalysisDocument.model_validate(read_json(self.paths["scene_analysis"]))

    def _story_bundle(self):
        return load_story_bundle(
            CharacterRegistry.model_validate(read_json(self.paths["characters"])),
            StoryGraph.model_validate(read_json(self.paths["story"])),
            KnowledgeTimeline.model_validate(read_json(self.paths["knowledge"])),
        )

    def _highlights(self) -> HighlightDocument:
        return HighlightDocument.model_validate(read_json(self.paths["highlights"]))

    def _plan(self) -> RecapPlan:
        return RecapPlan.model_validate(read_json(self.paths["plan"]))

    def _storyboard(self) -> Storyboard:
        return Storyboard.model_validate(read_json(self.paths["storyboard"]))

    def _render_storyboard_snapshot(self):
        """Parse and bind the same bytes before validation/repair callbacks run."""
        if not getattr(self, "_render_current", False):
            return self._storyboard(), None
        path = self.paths["storyboard"]
        with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise WorkspaceError("RENDER_CURRENT_STORYBOARD_NOT_REGULAR")
            raw = stream.read()
            after = os.fstat(stream.fileno())
        current = path.stat()
        fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if any(getattr(before, field) != getattr(after, field)
               or getattr(after, field) != getattr(current, field) for field in fields):
            raise WorkspaceError("RENDER_CURRENT_STORYBOARD_CHANGED")
        snapshot = hashlib.sha256(raw).hexdigest()
        return Storyboard.model_validate(json.loads(raw)), snapshot

    def _assert_render_storyboard_snapshot(self, snapshot):
        if snapshot is not None and content_fingerprint(self.paths["storyboard"]) != snapshot:
            raise WorkspaceError("RENDER_CURRENT_STORYBOARD_CHANGED")

    def _publish_render_storyboard(self, storyboard, snapshot):
        if snapshot is None:
            write_json(self.paths["storyboard"], storyboard)
            return None
        value = storyboard.model_dump(mode="json")
        # Derive the next token from exactly our published bytes, never a later
        # disk read that could silently adopt another manual save as our base.
        next_snapshot = hashlib.sha256(canonical(value) + b"\n").hexdigest()
        self._assert_render_storyboard_snapshot(snapshot)
        atomic(self.paths["storyboard"], value)
        return next_snapshot

    def _stage_ingest(self) -> Path:
        manifest = build_manifest(self.input_path, self.config, self.work_dir)
        write_json(self.paths["manifest"], manifest)
        return self.paths["manifest"]

    def _stage_transcript(self) -> Path:
        transcript = build_transcript(self._manifest(), self.config)
        write_json(self.paths["transcript"], transcript)
        return self.paths["transcript"]

    def _stage_scenes(self) -> Path:
        scene_index = build_scene_index(
            self._manifest(), self._transcript(), self.config, self.work_dir
        )
        write_json(self.paths["scene_index"], scene_index)
        return self.paths["scene_index"]

    def _stage_scene_analysis(self) -> Path:
        analysis = analyze_scenes(self._scene_index(), self.config, self.client)
        write_json(self.paths["scene_analysis"], analysis)
        return self.paths["scene_analysis"]

    def _stage_story(self) -> Path:
        bundle = build_story(
            self._scene_index(), self._scene_analysis(), self.config, self.client,
            context=read_story_context(self.config, self.binding["context_identity"], bound=True),
        )
        write_json(self.paths["characters"], bundle.character_registry)
        write_json(self.paths["story"], bundle.story_graph)
        write_json(self.paths["knowledge"], bundle.knowledge_timeline)
        return self.paths["story"]

    def _stage_highlights(self) -> Path:
        highlights = build_highlights(
            self._manifest(),
            self._transcript(),
            self._scene_index(),
            self._scene_analysis(),
            self._story_bundle(),
            self.config,
            self.client,
            self.work_dir,
        )
        write_json(self.paths["highlights"], highlights)
        return self.paths["highlights"]

    def _stage_plan(self) -> Path:
        plan = build_plan(
            self._manifest(),
            self._transcript(),
            self._story_bundle(),
            self._highlights(),
            self.config,
            self.client,
        )
        write_json(self.paths["plan"], plan)
        return self.paths["plan"]

    def _stage_storyboard(self) -> Path:
        storyboard = build_storyboard(
            project_name=self.project_name,
            manifest=self._manifest(),
            story=self._story_bundle(),
            highlights=self._highlights(),
            plan=self._plan(),
            config=self.config,
            client=self.client,
            scene_index=self._scene_index(),
            scene_analysis=self._scene_analysis(),
        )
        self._attach_original_cues(storyboard)
        write_json(self.paths["storyboard"], storyboard)
        write_human_script(storyboard, self.paths["script"])
        return self.paths["storyboard"]

    def _attach_original_cues(self, storyboard: Storyboard) -> None:
        transcript = self._transcript()
        manifest_fingerprints = {source.source_id: source.fingerprint for source in self._manifest().sources}
        for segment in storyboard.segments:
            if segment.mode != "original":
                continue
            segment.original_cues = [
                OriginalCue.model_validate(cue.model_dump(mode="json")) for cue in transcript.segments
                if any(cue.source_id == visual.source_id and cue.end > visual.start
                       and cue.start < visual.end for visual in segment.visuals)
            ]
            segment.original_cues_verified = bool(segment.visuals) and all(
                visual.source_id in transcript.source_fingerprints
                and transcript.source_fingerprints[visual.source_id] == manifest_fingerprints.get(visual.source_id)
                for visual in segment.visuals
            )

    def _effective_tts_config(self) -> AppConfig:
        effective = self.config.model_copy(deep=True)
        effective.format.vo_chars_per_sec = tuple(get_plan_constraints(self._plan(), self.config)["vo_chars_per_sec"])
        return effective

    def _validate_visual_evidence(self, storyboard: Storyboard) -> None:
        validate_storyboard_visual_evidence(
            storyboard, self._manifest(), self._highlights(),
            self._scene_index(), self._scene_analysis(),
        )

    def _stage_tts(self) -> Path:
        storyboard = self._storyboard()
        self._validate_visual_evidence(storyboard)
        storyboard = synthesize_storyboard(
            storyboard, self._effective_tts_config(), self.client, self.work_dir
        )
        self._attach_original_cues(storyboard)
        write_json(self.paths["storyboard"], storyboard)
        write_human_script(storyboard, self.paths["script"])
        return self.paths["storyboard"]

    def _stage_pre_qc(self) -> Path:
        storyboard, snapshot = self._render_storyboard_snapshot()
        try:
            self._validate_visual_evidence(storyboard)
        except VisualEvidenceError:
            client = None  # Persist deterministic findings without opening a provider.
        else:
            if getattr(self, "_render_current", False):
                pipeline = self

                class ReplayOnlyClient:
                    def chat_json(self, **kwargs):
                        return pipeline.client.chat_json(**kwargs)

                client = ReplayOnlyClient()
            else:
                client = self.client
        self._assert_render_storyboard_snapshot(snapshot)
        report = preflight_qc(
            manifest=self._manifest(),
            transcript=self._transcript(),
            story=self._story_bundle(),
            highlights=self._highlights(),
            plan=self._plan(),
            storyboard=storyboard,
            config=self.config,
            client=client,
            scene_index=self._scene_index(),
            scene_analysis=self._scene_analysis(),
        )
        self._assert_render_storyboard_snapshot(snapshot)
        write_json(self.paths["pre_qc"], report)
        if report.status == "BLOCKED":
            raise StageBlocked("pre_qc", report)
        return self.paths["pre_qc"]

    def _stage_render(self) -> Path:
        storyboard, snapshot = self._render_storyboard_snapshot()
        self._validate_visual_evidence(storyboard)
        self._assert_render_storyboard_snapshot(snapshot)
        storyboard = render_storyboard(storyboard, self.config, self.work_dir)
        self._publish_render_storyboard(storyboard, snapshot)
        final = Path(storyboard.output["final_video"])
        return final

    def _clear_render_outputs(self) -> None:
        # Renderer allocates a fresh attempt; preserve successful and failed outputs.
        return None

    def _stage_post_qc(self) -> Path:
        storyboard, snapshot = self._render_storyboard_snapshot()
        auto_repairable = {
            "MISSING_OUTPUT_REFERENCE",
            "MISSING_FINAL_VIDEO",
            "MISSING_VIDEO_STREAM",
            "MISSING_AUDIO_STREAM",
            "OUTPUT_DIMENSION_MISMATCH",
            "OUTPUT_DURATION_MISMATCH",
        }
        report: QCReport | None = None
        attempts = 1
        while attempts <= self.config.qc.self_repair_rounds + 1:
            report = post_render_qc(
                storyboard=storyboard,
                config=self.config,
                attempts=attempts,
            )
            self._assert_render_storyboard_snapshot(snapshot)
            # Persist the current finding before a repair that might itself fail.
            write_json(self.paths["post_qc"], report)
            if report.status != "BLOCKED":
                break
            blocking_ids = {item.rule_id for item in report.findings if item.blocking}
            if attempts > self.config.qc.self_repair_rounds or not blocking_ids <= auto_repairable:
                break
            self._say(f"[repair] render pass {attempts + 1}")
            self._clear_render_outputs()
            self._validate_visual_evidence(storyboard)
            self._assert_render_storyboard_snapshot(snapshot)
            storyboard = render_storyboard(storyboard, self.config, self.work_dir)
            snapshot = self._publish_render_storyboard(storyboard, snapshot)
            final = Path(storyboard.output["final_video"])
            self.store.pass_stage(
                self.state, "render", artifact=str(final), fingerprint=content_fingerprint(final),
                artifacts={str(path): content_fingerprint(path) for path in self._required_artifacts("render", final)},
                input_fingerprint=self._stage_inputs("render"),
            )
            attempts += 1
        assert report is not None
        self._assert_render_storyboard_snapshot(snapshot)
        write_json(self.paths["post_qc"], report)
        if report.status == "BLOCKED":
            raise StageBlocked("post_qc", report)
        return self.paths["post_qc"]

    def _cleanup_debug_artifacts(self) -> None:
        # Persist cleanup intent before deletion so an interruption is recoverable.
        # Required media and authored artifacts are never covered by this receipt.
        files = {}
        recorded = {}
        for name, sha256 in self.state.stages["scenes"].artifacts.items():
            path = Path(name)
            path = (path if path.is_absolute() else self.work_dir / path).resolve()
            recorded[str(path)] = sha256
            if any(path.is_relative_to(self.work_dir / directory)
                   for directory in ("frames", "contact_sheets")):
                files[str(path)] = sha256
        if not files:
            # Copied scenes can reference only old generations. An empty receipt
            # would erase their cleanup proof (or poison legacy absence facts).
            # No registered local target also means no local directory deletion.
            return
        _, _, unavailable = inventory(self.work_dir)
        if any(row["reason"] == "missing_regenerable_debug_after_delivery" for row in unavailable):
            # The v1 receipt cannot represent legacy absence separately from
            # observed cleanup. Keep current debug files instead of upgrading
            # historical uncertainty or invalidating its recovery evidence.
            return
        for row in unavailable:
            if row["reason"] == "recorded_regenerable_debug_cleanup":
                path = str(Path(row["original_path"]).resolve())
                files[path] = recorded[path]  # inventory verified path/hash/history.
        atomic(self.work_dir / ".receipts/debug-cleanup.json", {
            "schema": "film-debug-cleanup/1", "requested_at": now(),
            "files": [{"path": path, "sha256": files[path]} for path in sorted(files)],
            "reason": "runtime.keep_debug_frames=false",
        })
        shutil.rmtree(self.work_dir / "frames", ignore_errors=True)
        shutil.rmtree(self.work_dir / "contact_sheets", ignore_errors=True)

    def _stage_delivery(self) -> Path:
        storyboard = self._storyboard()
        pre_report = QCReport.model_validate(read_json(self.paths["pre_qc"]))
        post_report = QCReport.model_validate(read_json(self.paths["post_qc"]))
        final_status = (
            "DEGRADED"
            if "DEGRADED" in {pre_report.status, post_report.status}
            else "PASSED"
        )
        output_dir = self.work_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)
        source_srt = Path(storyboard.output.get("subtitle", ""))
        if source_srt.exists():
            shutil.copy2(source_srt, output_dir / "master.srt")
        selected_highlights = [
            candidate
            for candidate in self._highlights().candidates
            if candidate.selected
        ]
        lines = [
            f"# {self.project_name} · 影视解说交付报告",
            "",
            f"- 最终状态：**{final_status}**",
            f"- 最终成片：`{storyboard.output.get('final_video')}`",
            f"- 预览：`{storyboard.output.get('preview_video')}`",
            f"- 字幕：`{output_dir / 'master.srt'}`",
            f"- EDL：`{storyboard.output.get('edl')}`",
            f"- Storyboard：`{self.paths['storyboard']}`",
            f"- 目标时长：{self._plan().target_duration_sec:.1f}s",
            f"- 实际时长：{float(storyboard.output.get('duration_sec', 0)):.1f}s",
            f"- 入选高光：{len(selected_highlights)} 个",
            f"- LLM：`{self.config.models.llm_model}`",
            f"- VLM：`{self.config.models.vlm_model}`",
            f"- ASR：`{self._transcript().provider}`",
            f"- TTS：`{self.config.tts.provider}` / `{self.config.tts.voice}`",
            "- 云端上传：模型分析会上传压缩 contact sheet 与对应文本；默认不上传完整影片文件",
            "",
            "## 主线",
            "",
            self._story_bundle().story_graph.main_plot,
            "",
            "## 高光清单",
            "",
        ]
        for candidate in selected_highlights:
            lines.append(
                f"- `{candidate.highlight_id}` {candidate.source_id} "
                f"{candidate.start:.2f}-{candidate.end:.2f}s · "
                f"{', '.join(candidate.types)} · {candidate.selection_reason}"
            )
        lines.extend(
            [
                "",
                "## QC 摘要",
                "",
                f"- 渲染前：{pre_report.status}，{len(pre_report.findings)} 项发现",
                f"- 渲染后：{post_report.status}，{len(post_report.findings)} 项发现",
                "",
                "### 未阻断问题",
                "",
            ]
        )
        non_blocking = [
            item
            for item in pre_report.findings + post_report.findings
            if not item.blocking
        ]
        if non_blocking:
            for item in non_blocking:
                lines.append(f"- `{item.rule_id}` {item.message}")
        else:
            lines.append("- 无")
        lines.extend(
            [
                "",
                "## 发布边界",
                "",
                "本工具只生成草稿或成片文件，不自动发布，不规避版权检测。",
                "发布者仍需确认影视素材、音乐、配音与平台规则所需权利。",
                "",
            ]
        )
        if self.config.format.duration_mode == "series":
            lines.extend(
                [
                    "## Series 提示",
                    "",
                    "当前运行时每次只生成一个 Part。对于多集或超长素材，建议按故事阶段分别运行，",
                    "并让每个 Part 拥有独立钩子、阶段回报和下一段问题。",
                    "",
                ]
            )
        self.paths["delivery"].write_text("\n".join(lines), encoding="utf-8")
        if not self.config.runtime.keep_debug_frames:
            self._cleanup_debug_artifacts()
        return self.paths["delivery"]
