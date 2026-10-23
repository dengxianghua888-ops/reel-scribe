from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from .config import load_config
from .doctor import run_doctor
from .pipeline import FilmRecapPipeline, StageBlocked
from .state import STAGES
from .workspace import preflight
from .send_guard import reconcile

app = typer.Typer(
    name="douyin-film-recap",
    help="将电影或电视剧自动制作成抖音影视解说成片。",
    no_args_is_help=True,
)
console = Console()


@app.command()
def doctor(
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="YAML 配置文件"),
    ] = Path("config.yaml"),
) -> None:
    """检查 FFmpeg、模型、ASR、TTS 与发布边界。"""
    try:
        resolved = config.expanduser().resolve()
        app_config = load_config(resolved)
        checks = run_doctor(app_config, resolved)
    except Exception as exc:
        console.print(f"[bold red]配置加载失败：[/bold red] {exc}")
        raise typer.Exit(code=2) from exc
    table = Table(title="Douyin Film Recap Doctor")
    table.add_column("检查项")
    table.add_column("状态")
    table.add_column("详情")
    for check in checks:
        style = {"PASS": "green", "WARN": "yellow", "FAIL": "red"}.get(
            check.status, "white"
        )
        table.add_row(check.name, f"[{style}]{check.status}[/{style}]", check.detail)
    console.print(table)
    if any(check.critical for check in checks):
        raise typer.Exit(code=1)


@app.command("run")
def run_pipeline(
    input_path: Annotated[Path, typer.Argument(help="视频文件或素材目录")],
    work_dir: Annotated[
        Path,
        typer.Option("--work-dir", "-w", help="项目工作目录"),
    ],
    config: Annotated[
        Path,
        typer.Option("--config", "-c", help="YAML 配置文件"),
    ] = Path("config.yaml"),
    until: Annotated[
        str | None,
        typer.Option("--until", help="运行到指定阶段后停止"),
    ] = None,
    from_stage: Annotated[
        str | None,
        typer.Option("--from-stage", help="从指定阶段强制重算"),
    ] = None,
    migrate_legacy: Annotated[bool, typer.Option("--migrate-legacy", help="保全旧字节后迁移 Schema 1")] = False,
    recovery_bundle: Annotated[Path | None, typer.Option("--recovery-bundle", help="已独立验证的只读 B 包目录")] = None,
    recovery_bundle_sha256: Annotated[str | None, typer.Option("--recovery-bundle-sha256", help="固定 B 包 manifest SHA256")] = None,
    allow_remote: Annotated[bool, typer.Option("--allow-remote", help="授权本次选定阶段产生新的模型/TTS请求")] = False,
    max_remote_requests: Annotated[int | None, typer.Option("--max-remote-requests", min=0, help="本次本地新发请求上限；不代表服务计费封顶")] = None,
) -> None:
    """执行完整或分阶段的影视解说生产管线。"""
    if until and until not in STAGES:
        console.print(f"[red]未知阶段：{until}[/red]\n可用阶段：{', '.join(STAGES)}")
        raise typer.Exit(code=2)
    if from_stage and from_stage not in STAGES:
        console.print(
            f"[red]未知阶段：{from_stage}[/red]\n可用阶段：{', '.join(STAGES)}"
        )
        raise typer.Exit(code=2)
    try:
        preflight(work_dir, allow_legacy=migrate_legacy)
        app_config = load_config(config)
        pipeline = FilmRecapPipeline(
            input_path=input_path,
            work_dir=work_dir,
            config=app_config,
            on_update=lambda message: console.print(f"[cyan]{message}[/cyan]"),
            migrate_legacy=migrate_legacy, recovery_bundle=recovery_bundle,
            recovery_bundle_sha256=recovery_bundle_sha256,
        )
        result = pipeline.run(until=until, from_stage=from_stage,
                              allow_remote=allow_remote, max_remote_requests=max_remote_requests)
        console.print(f"\n[bold green]完成[/bold green]：{result}")
    except StageBlocked as exc:
        console.print(f"\n[bold red]{exc.stage} 被质量门禁阻断[/bold red]")
        for finding in exc.report.findings:
            marker = "BLOCK" if finding.blocking else finding.severity.upper()
            console.print(f"- [{marker}] {finding.rule_id}: {finding.message}")
        raise typer.Exit(code=3) from exc
    except Exception as exc:
        console.print(f"\n[bold red]执行失败：[/bold red] {exc}")
        raise typer.Exit(code=1) from exc


@app.command()
def status(
    work_dir: Annotated[Path, typer.Argument(help="项目工作目录")],
) -> None:
    """查看断点续跑状态。"""
    try:
        _, active = preflight(work_dir, allow_legacy=True)
    except (ValueError, OSError) as exc:
        console.print(f"[red]状态读取被拒绝：{exc}[/red]")
        raise typer.Exit(code=2) from exc
    state_path = active / "state.json"
    if not state_path.exists():
        console.print(f"[red]未找到状态文件：{state_path}[/red]")
        raise typer.Exit(code=1)
    data = json.loads(state_path.read_text(encoding="utf-8"))
    table = Table(title=data.get("project_name", "Film Recap Project"))
    table.add_column("阶段")
    table.add_column("状态")
    table.add_column("产物")
    table.add_column("错误")
    for stage in STAGES:
        record = data.get("stages", {}).get(stage, {})
        status_value = record.get("status", "pending")
        style = {
            "passed": "green",
            "running": "cyan",
            "failed": "red",
            "skipped": "yellow",
            "pending": "dim",
        }.get(status_value, "white")
        error = record.get("error") or {}
        table.add_row(
            stage,
            f"[{style}]{status_value}[/{style}]",
            str(record.get("artifact") or ""),
            str(error.get("message") or ""),
        )
    console.print(table)


@app.command("reconcile-send")
def reconcile_send(
    work_dir: Annotated[Path, typer.Argument(help="原任务根目录")],
    intent: Annotated[str, typer.Option("--intent", help="UNKNOWN 请求的 intent SHA")],
    evidence: Annotated[str, typer.Option("--confirmed-not-submitted", help="人工确认服务未接收的证据；不能仅凭本地超时断言")],
) -> None:
    """记录人工核对结果；下次实际重发仍须 --allow-remote。"""
    try:
        root, _ = preflight(work_dir)
        result = reconcile(root, intent, evidence)
        console.print(json.dumps(result, ensure_ascii=False))
    except (ValueError, OSError) as exc:
        console.print(f"[red]核对失败：{exc}[/red]")
        raise typer.Exit(code=2) from exc


@app.command("stages")
def list_stages() -> None:
    """列出可断点运行的阶段。"""
    for index, stage in enumerate(STAGES, start=1):
        console.print(f"{index:02d}. {stage}")


@app.command("render-plan")
def render_plan_command(
    work_dir: Annotated[Path, typer.Argument(help="已有工作区（只读）")],
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml"),
    dry_run: Annotated[bool, typer.Option("--dry-run", help="只读派生计划，不渲染或写入作品")] = True,
) -> None:
    """输出派生渲染计划；候选复用不等于验证命中或 QC 通过。"""
    from .models import Storyboard
    from .render_plan import collect_render_inputs, compile_render_plan
    from .workspace import sha

    if not dry_run:
        console.print("render-plan only supports --dry-run")
        raise typer.Exit(code=2)
    try:
        _, active = preflight(work_dir)
        board_path = active / "09_storyboard.json"
        before = sha(board_path)
        board = Storyboard.model_validate_json(board_path.read_text(encoding="utf-8"))
        plan = compile_render_plan(
            board, load_config(config), **collect_render_inputs(board),
            authority_sha256=before, workspace_generation=str(active),
        )
        _, current = preflight(work_dir)
        if current != active or sha(board_path) != before:
            raise ValueError("STALE_AUTHORITY")
        typer.echo(json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError) as exc:
        console.print(f"派生计划失败：{exc}")
        raise typer.Exit(code=2) from exc


@app.command("revision-snapshot")
def revision_snapshot_command(
    work_dir: Annotated[Path, typer.Argument(help="读取当前 Storyboard/generation 身份")],
) -> None:
    """输出局部提案所需基线，不改变作品。"""
    from .revision import freeze_revision
    try:
        typer.echo(json.dumps(freeze_revision(work_dir), ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError) as exc:
        console.print(f"快照读取失败：{exc}")
        raise typer.Exit(code=2) from exc


@app.command("revision-preview")
def revision_preview_command(
    work_dir: Annotated[Path, typer.Argument(help="已有作品；只读，不初始化工作区")],
    proposal: Annotated[Path | None, typer.Option("--proposal", help="既有 revise 局部候选 JSON")] = None,
    base: Annotated[Path | None, typer.Option("--base", help="既有 revision-snapshot，拒绝过期引用")] = None,
    beat_id: Annotated[list[str] | None, typer.Option("--beat-id", help="只查看指定 beat，可重复")] = None,
    raw_cards: Annotated[Path | None, typer.Option("--raw-cards", help="已有 RawEvidenceCard 数组；仅投影声明")] = None,
) -> None:
    """定位选材、分镜引用与已绑定的渲染消费；预览不表示验证或采用通过。"""
    from .revision_preview import preview_revision
    from .workspace import sha

    try:
        paths = [path for path in (proposal, base, raw_cards) if path is not None]
        identities = {path: sha(path) for path in paths}
        documents = {path: json.loads(path.read_text(encoding="utf-8")) for path in paths}
        if raw_cards is not None and not isinstance(documents[raw_cards], list):
            raise ValueError("RAW_CARDS_MUST_BE_A_LIST")
        result = preview_revision(work_dir,
            proposal=documents[proposal] if proposal is not None else None,
            base=documents[base] if base is not None else None, beat_ids=beat_id,
            raw_cards=documents[raw_cards] if raw_cards is not None else None)
        if any(sha(path) != value for path, value in identities.items()):
            raise ValueError("PREVIEW_INPUT_DOCUMENT_CHANGED")
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError, KeyError, TypeError) as exc:
        console.print(f"只读预览失败：{exc}", markup=False)
        raise typer.Exit(code=2) from exc


@app.command("revise")
def revise_command(
    work_dir: Annotated[Path, typer.Argument(help="已有工作区")],
    proposal: Annotated[Path, typer.Option("--proposal", help="含 base/artifacts/scope 的局部修订 JSON")],
) -> None:
    """按明确范围采用局部候选；不会生成配音、调用模型或自动渲染。"""
    from .revision import adopt_revision
    try:
        request = json.loads(proposal.read_text(encoding="utf-8"))
        if not isinstance(request, dict) or set(request) - {"base", "artifacts", "scope", "kind", "reason"}:
            raise ValueError("INVALID_LOCAL_PROPOSAL")
        if request.get("kind", "local") != "local":
            raise ValueError("DOMAIN_PROPOSAL_REQUIRES_DEDICATED_VALIDATOR")
        result = adopt_revision(work_dir, base=request["base"], artifacts=request["artifacts"],
                                scope=request["scope"], kind="local", reason=request.get("reason", ""))
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=str))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        console.print(f"局部修订失败：{exc}")
        raise typer.Exit(code=2) from exc


@app.command("render-current")
def render_current_command(
    work_dir: Annotated[Path, typer.Argument(help="当前已准备 Storyboard 的工作区")],
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml"),
) -> None:
    """只从当前作品执行 pre-QC/render/post-QC/delivery，不重跑模型或 TTS。"""
    try:
        pipeline = FilmRecapPipeline.from_current(work_dir=work_dir, config=load_config(config),
            on_update=lambda message: console.print(message))
        result = pipeline.render_only()
        typer.echo(json.dumps({"result": str(result)}, ensure_ascii=False))
    except StageBlocked as exc:
        console.print(f"{exc.stage} 被质量门禁阻断")
        for finding in exc.report.findings:
            console.print(f"- {finding.rule_id}: {finding.message}")
        raise typer.Exit(code=3) from exc
    except (ValueError, OSError, RuntimeError) as exc:
        console.print(f"当前作品渲染失败：{exc}")
        raise typer.Exit(code=2) from exc


@app.command("apply-boundary")
def apply_boundary_command(
    work_dir: Annotated[Path, typer.Argument(help="当前已冻结的工作区")],
    proposal: Annotated[Path, typer.Option("--proposal", help="包含 proposal 与 base 的边界采用请求")],
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml"),
) -> None:
    """重新核对独立来源时钟后，一次采用对应 07/08/09；不自动渲染。"""
    from .boundary import BoundaryProposal
    from .boundary_apply import apply_boundary_proposal, collect_boundary_timebases
    from .models import SourceManifest
    from .workspace import read, work_lock
    try:
        request = json.loads(proposal.read_text(encoding="utf-8"))
        if (not isinstance(request, dict) or not {"proposal", "base"} <= set(request)
                or set(request) - {"proposal", "base", "raw_cards", "evidence_root"}):
            raise ValueError("INVALID_BOUNDARY_APPLICATION_REQUEST")
        raw_cards = None
        if "raw_cards" in request:
            from .raw_evidence import RawEvidenceCard
            if not isinstance(request["raw_cards"], list):
                raise ValueError("RAW_CARDS_MUST_BE_A_LIST")
            raw_cards = [RawEvidenceCard.model_validate(row) for row in request["raw_cards"]]
        root, _ = preflight(work_dir)
        with work_lock(root):
            _, active = preflight(root)
            manifest = SourceManifest.model_validate(read(active / "00_source_manifest.json"))
            current_timebases = collect_boundary_timebases(manifest)
            result = apply_boundary_proposal(root,
                proposal=BoundaryProposal.model_validate(request["proposal"]), base=request["base"],
                config=load_config(config), timebases=current_timebases,
                raw_cards=raw_cards, evidence_root=request.get("evidence_root"))
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=str))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        console.print(f"边界采用失败：{exc}")
        raise typer.Exit(code=2) from exc


@app.command("narration-revise-plan")
def narration_revision_plan_command(
    work_dir: Annotated[Path, typer.Argument(help="当前作品工作区")],
    request: Annotated[Path, typer.Option("--request", help="含 base/edits/reason 的精确旁白修改请求")],
) -> None:
    """只读输出待执行计划；edits 为 segment_id 到完整新文字的映射。"""
    from .narration_revision import prepare_narration_revision
    try:
        data = json.loads(request.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) - {"base", "edits", "reason"}:
            raise ValueError("INVALID_NARRATION_REVISION_REQUEST")
        result = prepare_narration_revision(work_dir, base=data["base"], edits=data["edits"],
                                             reason=data.get("reason", ""))
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        console.print(f"旁白修订计划失败：{exc}")
        raise typer.Exit(code=2) from exc


@app.command("narration-revise-apply")
def narration_revision_apply_command(
    work_dir: Annotated[Path, typer.Argument(help="当前作品工作区")],
    plan: Annotated[Path, typer.Option("--plan", help="完整未改动的待执行计划")],
    config: Annotated[Path, typer.Option("--config", "-c")] = Path("config.yaml"),
    allow_remote: Annotated[bool, typer.Option("--allow-remote", help="授权本计划需要的新TTS/语义检查请求")] = False,
    max_remote_requests: Annotated[int | None, typer.Option("--max-remote-requests", min=0)] = None,
    render: Annotated[bool, typer.Option("--render", help="采用后继续原有pre-QC/render/post-QC/delivery")] = False,
) -> None:
    """仅重做目标旁白；UNKNOWN不重发，视觉不足不自动改稿或补画。"""
    from .narration_revision import execute_narration_revision
    try:
        result = execute_narration_revision(work_dir,
            plan=json.loads(plan.read_text(encoding="utf-8")), config=load_config(config),
            allow_remote=allow_remote, max_remote_requests=max_remote_requests, render=render,
            on_update=lambda message: console.print(message))
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False, default=str))
    except StageBlocked as exc:
        console.print(f"{exc.stage} 被质量门禁阻断")
        for finding in exc.report.findings:
            console.print(f"- {finding.rule_id}: {finding.message}")
        raise typer.Exit(code=3) from exc
    except (ValueError, OSError, RuntimeError, KeyError) as exc:
        console.print(f"旁白修订执行失败：{exc}")
        raise typer.Exit(code=2) from exc


@app.command("validate-alignment")
def validate_alignment(
    manifest: Annotated[Path, typer.Option("--manifest")],
    result: Annotated[Path, typer.Option("--result")],
    source_id: Annotated[str, typer.Option("--source-id")],
) -> None:
    """离线核验已有对齐结果与字幕/音频身份，不加载模型或执行ASR。"""
    from .alignment import import_alignment
    from .asr import parse_subtitle
    from .models import SourceManifest
    try:
        sources = SourceManifest.model_validate_json(manifest.read_bytes()).sources
        source = next((item for item in sources if item.source_id == source_id), None)
        if source is None or not source.subtitle_path:
            raise ValueError("Source with existing subtitles required")
        segments = import_alignment(result, source, parse_subtitle(source.subtitle_path, source_id))
    except Exception as exc:
        console.print(f"Alignment rejected: {exc}", markup=False)
        raise typer.Exit(2) from exc
    aligned = sum(bool(s.alignment and s.alignment["status"] == "aligned") for s in segments)
    estimated = sum(bool(s.alignment and s.alignment["status"] == "estimated") for s in segments)
    console.print(f"Validated: {aligned} aligned cues, {estimated} estimated fallback cues. "
                  "Producer provenance is declared, not independently verified.", markup=False)


@app.command("convert-whisperx-alignment")
def convert_whisperx_alignment(
    receipt: Annotated[Path, typer.Option("--receipt")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """转换带运行时身份声明的原生字符结果；不运行WhisperX，不下载资源。"""
    from .alignment import convert_whisperx
    try:
        converted = convert_whisperx(json.loads(receipt.read_text(encoding="utf-8")))
        # Exclusive creation protects existing artifacts and source files.
        with output.open("x", encoding="utf-8") as handle:
            handle.write(converted.model_dump_json(indent=2))
            handle.write("\n")
    except Exception as exc:
        console.print(f"Conversion rejected: {exc}", markup=False)
        raise typer.Exit(2) from exc
    console.print("Converted declared native character evidence. Run validate-alignment before use.")


@app.command("run-local-alignment")
def run_local_alignment_command(
    manifest: Annotated[Path, typer.Option("--manifest")],
    source_id: Annotated[str, typer.Option("--source-id")],
    cue_index: Annotated[list[int], typer.Option("--cue-index")],
    model_dir: Annotated[Path, typer.Option("--model-dir")],
    model_sha256: Annotated[str, typer.Option("--model-sha256")],
    output: Annotated[Path, typer.Option("--output")],
    cache_dir: Annotated[Path | None, typer.Option("--cache-dir")] = None,
) -> None:
    """显式本地 CPU CTC 对齐，仅处理所选字幕窗；不下载模型，不自动采用。"""
    from .local_alignment import run_local_alignment
    from .models import SourceManifest
    try:
        sources = SourceManifest.model_validate_json(manifest.read_bytes()).sources
        source = next((item for item in sources if item.source_id == source_id), None)
        if source is None:
            raise ValueError("Unknown source_id")
        result = run_local_alignment(source=source, cue_indices=cue_index, model_dir=model_dir,
            model_sha256=model_sha256, output=output, cache_dir=cache_dir)
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        console.print(f"Local alignment rejected: {exc}", markup=False)
        raise typer.Exit(2) from exc
