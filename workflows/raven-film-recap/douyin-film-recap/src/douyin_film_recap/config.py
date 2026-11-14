from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .utils import content_identity, fingerprint_json


class FlexibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class EditorialBrief(FlexibleModel):
    narrative_question: str = ""
    audience_knowledge: list[str] = Field(default_factory=list)
    stance: str = ""
    preserve: list[str] = Field(default_factory=list)
    avoid_phrases: list[str] = Field(default_factory=list)
    ending_payoff: str = ""
    spoiler_policy: Literal["preserve", "allow"] = "preserve"
    spoiler_reason: str = ""


class ProjectConfig(FlexibleModel):
    language: str = "zh-CN"
    platform: str = "douyin"
    rights_confirmed: bool = False
    publish_mode: str = "draft"
    context_file: str | None = None
    editorial_brief: EditorialBrief = Field(default_factory=EditorialBrief)


class ModelConfig(FlexibleModel):
    provider: str = "openai_compatible"
    base_url_env: str = "FILM_RECAP_BASE_URL"
    api_key_env: str = "FILM_RECAP_API_KEY"
    llm_model: str
    vlm_model: str
    timeout_sec: float = 180
    max_retries: int = 3
    temperature: dict[str, float] = Field(
        default_factory=lambda: {"analysis": 0.1, "creative": 0.45, "qc": 0.0}
    )

    def base_url(self) -> str:
        value = os.getenv(self.base_url_env, "").strip()
        if not value:
            raise ValueError(f"Missing environment variable: {self.base_url_env}")
        return value.rstrip("/")

    def api_key(self) -> str:
        value = os.getenv(self.api_key_env, "").strip()
        if not value:
            raise ValueError(f"Missing environment variable: {self.api_key_env}")
        return value


class AlignmentConfig(BaseModel):
    """Explicit local result import; no model loading or network access."""
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    result_files: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_import(self) -> "AlignmentConfig":
        if self.enabled and not self.result_files:
            raise ValueError("alignment enabled requires local result_files keyed by source_id")
        return self


class ASRConfig(FlexibleModel):
    provider: str = "faster_whisper"
    model: str = "large-v3"
    device: str = "auto"
    compute_type: str = "auto"
    language: str = "zh"
    prefer_sidecar_subtitle: bool = True
    prefer_embedded_subtitle: bool = True
    word_timestamps: bool = True
    beam_size: int = 5
    alignment: AlignmentConfig = Field(default_factory=AlignmentConfig)


class SceneConfig(FlexibleModel):
    detector: str = "scenedetect"
    content_threshold: float = 27.0
    min_shot_sec: float = 0.45
    min_unit_sec: float = 4.0
    max_unit_sec: float = 16.0
    sample_frames_per_unit: int = 3
    contact_sheet_units: int = Field(default=8, gt=0)
    max_scene_analysis_workers: int = 2


class StoryConfig(FlexibleModel):
    chunk_units: int = Field(default=32, gt=0)
    character_confidence_threshold: float = 0.68
    story_confidence_threshold: float = 0.72
    allow_external_context: bool = False


class HighlightConfig(FlexibleModel):
    candidate_pool_size: int = 80
    rerank_top_k: int = 36
    final_pool_size: int = 24
    min_confidence: float = 0.62
    max_same_type_ratio: float = 0.45
    max_same_character_ratio: float = 0.65
    max_redundancy: float = 0.35
    allow_hook_reuse: bool = True
    genre_profile: str = "auto"


class FormatConfig(FlexibleModel):
    visual_retrieval: Literal["r0", "r1"] = "r0"
    visual_pool_text_budget: int | None = Field(default=None, gt=0)
    visual_exploration_fraction: float = Field(default=0.15, ge=0, le=1)
    duration_mode: Literal["auto", "highlight", "short", "standard", "deep", "series"] = "auto"
    content_unit: Literal["auto", "scene", "relationship", "episode", "film", "series"] = "auto"
    highlight_range_sec: tuple[int, int] = (30, 90)
    # Preserve v0.1 short/standard/deep meanings for existing configurations.
    short_range_sec: tuple[int, int] = (180, 360)
    standard_range_sec: tuple[int, int] = (360, 600)
    deep_range_sec: tuple[int, int] = (600, 1200)
    first_highlight_deadline_sec: float = 6
    original_ratio_range: tuple[float, float] = (0.25, 0.45)
    original_clip_range_sec: tuple[float, float] = (4.0, 12.0)
    max_original_over_15s: int = 2
    micro_cycle_sec: tuple[float, float] = (12, 25)
    reset_interval_sec: tuple[float, float] = (45, 75)
    vo_chars_per_sec: tuple[float, float] = (4.2, 5.2)
    default_ending: str = "payoff"
    allow_cta: bool = False
    visual_pool_size: int = Field(default=160, ge=12)


class TTSConfig(FlexibleModel):
    provider: str = "edge_tts"
    voice: str = "zh-CN-YunxiNeural"
    rate: str = "+10%"
    pitch: str = "+0Hz"
    volume: str = "+0%"
    max_speedup: float = Field(default=1.08, gt=0)
    min_speedup: float = Field(default=0.95, gt=0)


    @model_validator(mode="after")
    def validate_speed_range(self):
        if self.min_speedup > self.max_speedup:
            raise ValueError("min_speedup must not exceed max_speedup")
        return self


class RenderConfig(FlexibleModel):
    # Opt-in until independent media/performance acceptance is recorded.
    incremental_cache: bool = False
    width: int = Field(default=1080, gt=0)
    height: int = Field(default=1920, gt=0)
    fps: int = Field(default=30, gt=0)
    video_codec: str = "libx264"
    crf: int = 19
    preset: str = "medium"
    audio_codec: str = "aac"
    audio_bitrate: str = "192k"
    layout: str = "safe_fit_blur"
    blur_sigma: int = 28
    original_bed_db: float = -26
    target_lufs: float = -14
    true_peak_db: float = -1.5
    subtitle_burn_in: bool = True
    subtitle_font: str = "Noto Sans CJK SC"
    # An explicit file bypasses discovery; subtitle_font must match its family.
    subtitle_font_file: str | None = None
    # Additional libass font discovery directory (mutually exclusive with file).
    subtitle_fonts_dir: str | None = None
    # Output-canvas pixels; render pins ASS PlayResX/Y to width/height.
    subtitle_font_size: int = Field(default=62, gt=0)
    subtitle_margin_v: int = Field(default=250, ge=0)
    subtitle_max_chars_per_line: int = Field(default=16, gt=0)
    subtitle_max_lines: int = Field(default=2, gt=0)
    subtitle_outline: int = Field(default=3, ge=0)


class QCConfig(FlexibleModel):
    self_repair_rounds: int = 2
    fail_on_sentence_cut: bool = True
    fail_on_tts_truncation: bool = True
    fail_on_missing_audio: bool = True
    allow_semantic_qc_failure: bool = True
    max_black_ratio: float = 0.02
    max_silence_ratio: float = 0.18
    duration_tolerance_sec: float = 1.2


class RuntimeConfig(FlexibleModel):
    cache: bool = True
    keep_debug_frames: bool = True
    max_parallel_ffmpeg: int = 2
    stage_timeout_sec: int = 1800


class AppConfig(FlexibleModel):
    version: int = 1
    project: ProjectConfig = Field(default_factory=ProjectConfig)
    models: ModelConfig
    asr: ASRConfig = Field(default_factory=ASRConfig)
    scene: SceneConfig = Field(default_factory=SceneConfig)
    story: StoryConfig = Field(default_factory=StoryConfig)
    highlight: HighlightConfig = Field(default_factory=HighlightConfig)
    format: FormatConfig = Field(default_factory=FormatConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    qc: QCConfig = Field(default_factory=QCConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)

    def fingerprint(self) -> str:
        data = self.model_dump(mode="json")
        if not self.asr.alignment.enabled:
            data["asr"].pop("alignment", None)
        else:
            data["asr"]["alignment"]["implementation_digest"] = fingerprint_json({
                name: content_identity(Path(__file__).with_name(name))
                for name in ("alignment.py", "asr.py", "models.py", "config.py")
            })
            data["asr"]["alignment"]["content_identities"] = {
                source: content_identity(path)
                for source, path in sorted(self.asr.alignment.result_files.items())
            }
        # Disabled opt-in scheduling must retain pre-cache workspace identity.
        if data["render"].get("incremental_cache") is False:
            data["render"].pop("incremental_cache", None)
        explicit = set(self.format.model_fields_set)
        # Preserve historical defaults; non-default retrieval policy changes bind anew.
        for key, default in {"visual_retrieval": "r0", "visual_pool_text_budget": None,
                             "visual_exploration_fraction": 0.15}.items():
            if data["format"].get(key) == default:
                data["format"].pop(key, None)
                explicit.discard(key)
        return fingerprint_json(
            {
                "config": data,
                "explicit_format_fields": sorted(explicit),
            }
        )


def load_dotenv_near(config_path: Path) -> None:
    env_path = config_path.parent / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_config(path: str | Path) -> AppConfig:
    config_path = Path(path).expanduser().resolve()
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path}")
    load_dotenv_near(config_path)
    data: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config = AppConfig.model_validate(data)
    if config.asr.alignment.enabled:
        config.asr.alignment.result_files = {
            source: str((config_path.parent / Path(value).expanduser()).resolve())
            for source, value in config.asr.alignment.result_files.items()
        }
    return config
