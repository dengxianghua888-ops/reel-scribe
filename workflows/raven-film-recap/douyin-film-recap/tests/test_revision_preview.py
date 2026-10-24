"""Synthetic inspection regressions; no media/provider/narrative acceptance."""
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from douyin_film_recap.cli import app
from douyin_film_recap.models import SourceInfo, SourceManifest, Storyboard, StoryboardSegment
from douyin_film_recap.revision import BOARD, PLAN, freeze_revision
from douyin_film_recap.revision_preview import preview_revision
from douyin_film_recap.workspace import WorkspaceError, atomic, digest, read, sha


@pytest.fixture
def workspace(tmp_path):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"self-created source identity; never decoded")
    info = SourceInfo(source_id="ep1", path=str(source), filename=source.name,
        fingerprint=sha(source), duration=12, width=640, height=360, fps=30)
    root = tmp_path / "work"
    root.mkdir()
    board = Storyboard(project_name="synthetic", sources=[info], plan_fingerprint="plan",
        target_duration_sec=2, segments=[StoryboardSegment(segment_id="seg", beat_id="beat",
            mode="voiceover", title="title", text="words", notes="note", audio_owner="narration",
            planned_duration_sec=2, visuals=[
                {"source_id": "ep1", "start": 0, "end": 4, "unit_id": "direct",
                 "visual_role": "direct_evidence"},
                {"source_id": "ep1", "start": 4, "end": 8, "unit_id": "context"}])]).model_dump(mode="json")
    board["retrieval_provenance"] = {"method": "r1-lexical/1", "pool_unit_ids": ["direct", "context"],
        "per_beat_rankings": {"beat": [
            {"unit_id": "direct", "in_event_span": True, "role": "direct_evidence"},
            {"unit_id": "context", "in_event_span": False, "role": "context"},
            {"unit_id": "unused", "in_event_span": True, "role": "direct_evidence"}]},
        "coverage": {"beat": {"status": "candidate_evidence", "direct_unit_ids": ["direct"]}},
        "exclusions": {"beat": [{"unit_id": "hidden", "reason": "knowledge_constraint"}]},
        "budget_exclusions": [{"beat_id": "beat", "unit_id": "unused", "reason": "writer_budget"}]}
    atomic(root / "state.json", {"schema_version": 2, "stages": {}})
    atomic(root / "00_source_manifest.json", SourceManifest(sources=[info], config_fingerprint="test").model_dump(mode="json"))
    atomic(root / "02_scene_index.json", {"units": [
        {"unit_id": "direct", "source_id": "ep1", "start": 0, "end": 4},
        {"unit_id": "context", "source_id": "ep1", "start": 4, "end": 8}]})
    atomic(root / PLAN, {"beats": [{"beat_id": "beat", "event_ids": ["event-ep1", "event-ep2"],
                                   "character_focus": ["person"], "change": "change"}]})
    atomic(root / "07_highlight_candidates.json", {"candidates": [{"highlight_id": "highlight",
        "source_id": "ep1", "start": 8, "end": 10, "selected": True}]})
    atomic(root / BOARD, board)
    return root


def inventory(root):
    return {str(p.relative_to(root)): (p.read_bytes() if p.is_file() else None,
            p.stat().st_mtime_ns) for p in root.rglob("*")}


def local_proposal(root):
    candidate = read(root / BOARD)
    candidate["segments"][0]["notes"] = "new note"
    return {"base": freeze_revision(root), "artifacts": {BOARD: candidate},
            "scope": {"segment_ids": ["seg"], "fields": ["notes"]}}


def rendered_evidence(root):
    """Self-created recorded metadata/bytes; no real render or quality claim."""
    from douyin_film_recap.render import build_edl
    from douyin_film_recap.config import AppConfig
    from douyin_film_recap.render_plan import compile_render_plan

    board = read(root / BOARD)
    board["segments"][0]["status"] = "rendered"
    voice = root / "voice.wav"
    voice.write_bytes(b"synthetic narration identity; never decoded")
    board["segments"][0]["audio_file"] = str(voice)
    parsed = Storyboard.model_validate(board)
    inputs = {"source_identities": {source.source_id: {"sha256": source.fingerprint,
        "size": Path(source.path).stat().st_size} for source in parsed.sources},
        "audio_identities": {"seg": {"sha256": sha(voice), "size": voice.stat().st_size}},
        "toolchain": {"verified": True, "ffmpeg_sha256": "f" * 64, "ffprobe_sha256": "f" * 64,
                      "version": "synthetic", "implementation_digest": "e" * 64}}
    config = AppConfig(models={"llm_model": "unused", "vlm_model": "unused"})
    compiled = compile_render_plan(parsed, config, **inputs)
    segment_node = next(node for node in compiled["nodes"] if node["kind"] == "segment_av")
    compiled = compile_render_plan(parsed, config, **inputs, realized_artifacts={"segment_av:seg": {
        "semantic_key": segment_node["semantic_key"], "sha256": "1" * 64, "size": 123,
        "media_contract": {"frame_count": 60, "fps": {"num": 30, "den": 1}, "sample_count": 96000,
            "sample_rate": 48000, "decoded_sample_count": 96128, "padding": 128,
            "encoder_delay": 1024, "padding_policy": "decoded-minus-packet-end/1"},
        "verification": {"hash_checked": True, "probe_checked": True, "decode_checked": True}}})
    timeline = compiled["timeline"]["realized"]
    outputs = {"realized_timeline": timeline}
    for key in ("final_video", "preview_video", "subtitle"):
        path = root / "output" / key
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(b"synthetic recorded output, not playable media")
        outputs[key] = str(path)
    plan_path = root / "output/render_plan.json"
    atomic(plan_path, compiled)
    outputs["render_plan"] = str(plan_path)
    edl_path = root / "output/edl.json"
    atomic(edl_path, build_edl(Storyboard.model_validate(board), realized_timeline=timeline))
    outputs["edl"] = str(edl_path)
    board["output"] = outputs
    atomic(root / BOARD, board)
    atomic(root / "state.json", {"schema_version": 2, "stages": {"render": {"status": "passed",
        "artifacts": {str(path): sha(path) for path in (root / "output").iterdir()}}}})


def test_current_preview_cli_makes_no_writes_or_provider_calls(workspace, monkeypatch):
    import douyin_film_recap.workspace as workspace_module
    import douyin_film_recap.revision as revision
    import douyin_film_recap.raw_evidence as raw
    import douyin_film_recap.utils as utils
    monkeypatch.setattr(workspace_module, "work_lock", lambda *a: pytest.fail("write lock requested"))
    monkeypatch.setattr(revision, "freeze_revision", lambda *a: pytest.fail("mutating freeze requested"))
    monkeypatch.setattr(revision, "adopt_revision", lambda *a, **kw: pytest.fail("adoption requested"))
    monkeypatch.setattr(raw, "verify_raw_evidence", lambda *a, **kw: pytest.fail("raw verification requested"))
    monkeypatch.setattr(utils, "run_command", lambda *a, **kw: pytest.fail("media/model subprocess requested"))
    before = inventory(workspace.parent)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace), "--beat-id", "beat"])
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    assert inventory(workspace.parent) == before
    assert not (workspace / ".film-write.lock").exists()
    assert value["qc_status"] == "NOT_RUN"
    assert value["adoption"]["status"] == "not_validated"


def test_preview_keeps_pool_references_and_actual_use_distinct(workspace):
    value = preview_revision(workspace)
    beat = value["beats"][0]
    assert [row["unit_id"] for row in value["candidate_pool"]["units"]] == ["direct", "context"]
    rankings = beat["retrieval"]["rankings"]
    assert [(r["beat_role"], r["entered_candidate_pool"]) for r in rankings] == [
        ("direct", True), ("context_only", True), ("direct", False)]
    assert beat["retrieval"]["exclusions"][0]["reason"] == "knowledge_constraint"
    assert beat["retrieval"]["budget_exclusions"][0]["reason"] == "writer_budget"
    assert len(beat["storyboard_references"][0]["visuals"]) == 2
    assert beat["render_consumption"] == {
        "status": "unknown", "reason": "realized_timeline_missing", "segments": []}
    assert beat["retrieval"]["coverage"]["status"] == "candidate_evidence"
    assert beat["retrieval"]["support_complete"] == "unknown"
    assert beat["plan"]["event_ids"] == ["event-ep1", "event-ep2"]


def test_direct_for_another_beat_stays_context_here_and_missing_coverage_unknown(workspace):
    board = read(workspace / BOARD)
    board["retrieval_provenance"]["per_beat_rankings"]["other"] = [
        {"unit_id": "context", "in_event_span": True}]
    plan = read(workspace / PLAN)
    plan["beats"].append({"beat_id": "other"})
    atomic(workspace / BOARD, board)
    atomic(workspace / PLAN, plan)
    value = preview_revision(workspace)
    assert value["beats"][0]["retrieval"]["rankings"][1]["beat_role"] == "context_only"
    assert value["beats"][1]["retrieval"]["coverage"]["status"] == "unknown"


@pytest.mark.parametrize("method,status", [("r0-beat-stratified/1", "not_applicable"), (None, "unknown")])
def test_r0_and_missing_r1_are_explicit(workspace, method, status):
    board = read(workspace / BOARD)
    board["retrieval_provenance"] = {"method": method} if method else {}
    atomic(workspace / BOARD, board)
    value = preview_revision(workspace)
    assert value["beats"][0]["retrieval"]["status"] == status
    assert value["candidate_pool"]["status"] == "unknown"


def test_only_bound_completed_recorded_render_can_describe_actual_consumption(workspace):
    rendered_evidence(workspace)
    before = inventory(workspace)
    value = preview_revision(workspace)
    consumption = value["beats"][0]["render_consumption"]
    assert consumption["status"] == "recorded"
    spans = consumption["segments"][0]["source_spans"]
    assert [(span["unit_id"], span["start"], span["end"]) for span in spans] == [("direct", 0, 2)]
    assert not consumption["media_reverified"] and not consumption["qc_inherited"]
    assert len(value["beats"][0]["storyboard_references"][0]["visuals"]) == 2
    assert inventory(workspace) == before


@pytest.mark.parametrize("mutation", ["no_stage", "pending", "artifact", "content", "edl", "timeline"])
def test_stale_or_unexecuted_render_metadata_stays_unknown(workspace, mutation):
    rendered_evidence(workspace)
    state = read(workspace / "state.json")
    board = read(workspace / BOARD)
    if mutation == "no_stage":
        state["stages"] = {}
    elif mutation == "pending":
        state["stages"]["render"]["status"] = "pending"
    elif mutation == "artifact":
        Path(board["output"]["final_video"]).write_bytes(b"changed")
    elif mutation == "content":
        board["segments"][0]["visuals"][0]["start"] = 1
    elif mutation == "edl":
        path = Path(board["output"]["edl"])
        atomic(path, [])
        state["stages"]["render"]["artifacts"][str(path)] = sha(path)
    elif mutation == "timeline":
        board["output"]["realized_timeline"][0]["end"] = "3"
    atomic(workspace / BOARD, board)
    atomic(workspace / "state.json", state)
    assert preview_revision(workspace)["beats"][0]["render_consumption"]["status"] == "unknown"


def test_candidate_never_inherits_old_output_or_qc(workspace):
    rendered_evidence(workspace)
    atomic(workspace / "10_preflight_qc.json", {"status": "PASSED"})
    atomic(workspace / "11_post_render_qc.json", {"status": "PASSED"})
    proposal = local_proposal(workspace)
    before = inventory(workspace)
    value = preview_revision(workspace, proposal=proposal)
    assert value["scope_check"]["status"] == "within_existing_local_scope"
    assert value["binding"]["proposal_sha256"] == digest(proposal)
    assert value["binding"]["target_content_sha256"] == digest(proposal["artifacts"][BOARD])
    assert value["beats"][0]["render_consumption"]["reason"] == "candidate_has_not_been_rendered"
    assert value["qc_status"] == "NOT_RUN" and not value["semantic_and_av_review_inherited"]
    assert inventory(workspace) == before


def test_updated_source_and_manifest_do_not_rebind_old_storyboard_render(workspace):
    rendered_evidence(workspace)
    manifest = read(workspace / "00_source_manifest.json")
    source = Path(manifest["sources"][0]["path"])
    source.write_bytes(b"new source and manifest, old board and render")
    manifest["sources"][0]["fingerprint"] = sha(source)
    atomic(workspace / "00_source_manifest.json", manifest)
    consumption = preview_revision(workspace)["beats"][0]["render_consumption"]
    assert consumption["status"] == "unknown"
    assert consumption["reason"] == "render_storyboard_source_binding_mismatch"


@pytest.mark.parametrize("mutation,error", [
    ("protected", "REVISION_PROTECTED_SEGMENT"), ("unknown", "REVISION_UNKNOWN_FIELD_CHANGED"),
    ("text", "REVISION_FIELD_UNSUPPORTED"), ("scope", "REVISION_OUTSIDE_SEGMENT_SCOPE")])
def test_scope_diagnostics_reuse_existing_protections(workspace, mutation, error):
    board = read(workspace / BOARD)
    if mutation == "protected":
        board["segments"][0]["protected"] = True
    elif mutation == "unknown":
        board["segments"][0]["opaque"] = {"anchor": "preserve"}
    atomic(workspace / BOARD, board)
    proposal = local_proposal(workspace)
    if mutation == "unknown":
        proposal["artifacts"][BOARD]["segments"][0].pop("opaque")
    elif mutation == "text":
        proposal["artifacts"][BOARD]["segments"][0]["text"] = "unauthorized text"
    elif mutation == "scope":
        proposal["scope"]["segment_ids"] = []
        error = "REVISION_EXPLICIT_SEGMENT_SCOPE_REQUIRED"
    before = inventory(workspace)
    value = preview_revision(workspace, proposal=proposal)
    assert value["scope_check"]["status"] == "rejected"
    assert error in value["scope_check"]["reason"]
    assert value["adoption"]["status"] == "not_validated"
    assert inventory(workspace) == before


@pytest.mark.parametrize("change,error", [("source", "SOURCE_BINDING_CHANGED"),
    ("manual", "BASE_CONFLICT"), ("state", "BASE_CONFLICT")])
def test_old_snapshot_reference_is_rejected(workspace, change, error):
    value = preview_revision(workspace)
    if change == "source":
        source = Path(value["base"]["sources"][0]["path"])
        source.write_bytes(b"source changed after preview")
    elif change == "manual":
        board = read(workspace / BOARD)
        board["segments"][0]["notes"] = "later manual save"
        atomic(workspace / BOARD, board)
    else:
        atomic(workspace / "state.json", {"schema_version": 2, "stages": {}, "new_version": True})
    with pytest.raises(WorkspaceError, match=error):
        preview_revision(workspace, base=value["base"])


def test_mutation_during_projection_rejects_read(workspace, monkeypatch):
    import douyin_film_recap.revision_preview as module
    original = module._retrieval
    def concurrent(*args):
        atomic(workspace / PLAN, {"beats": []})
        return original(*args)
    monkeypatch.setattr(module, "_retrieval", concurrent)
    with pytest.raises(WorkspaceError, match="BASE_CONFLICT"):
        preview_revision(workspace)


def test_generation_change_rejects_preview_snapshot(workspace):
    from douyin_film_recap.workspace import commit_generation
    before = preview_revision(workspace)
    commit_generation(workspace, replacements={BOARD: read(workspace / BOARD)},
        expected_generation=before["base"]["generation"],
        expected_pointer_sha256=before["base"]["pointer_sha256"],
        validate=lambda active: Storyboard.model_validate(read(active / BOARD)), reason="synthetic generation")
    with pytest.raises(WorkspaceError, match="BASE_CONFLICT"):
        preview_revision(workspace, base=before["base"])


def test_raw_cards_are_bound_declarations_with_unknown_coverage(workspace):
    value = preview_revision(workspace)
    card = {"evidence_id": "raw", "source_id": "ep1", "source_sha256": value["base"]["sources"][0]["sha256"],
        "timebase": {"mapping_version": "test", "numerator": 1, "denominator": 30},
        "requested_range": {"start": 0, "end": 4}, "assets": [],
        "coverage_gaps": [{"start": 1, "end": 4}], "budget_exhausted": True}
    result = preview_revision(workspace, raw_cards=[card])
    assert result["binding"]["raw_cards_sha256"] == digest([card])
    assert result["raw_evidence"][0]["card"] == card
    assert result["raw_evidence"][0]["coverage_status"] == "unknown"
    assert not result["raw_evidence"][0]["asset_bytes_verified"]
    assert result["beats"][0]["overlapping_raw_card_ids"] == ["raw"]
    assert result["beats"][0]["retrieval"]["support_complete"] == "unknown"
    with pytest.raises(WorkspaceError, match="RAW_SOURCE_BINDING_MISMATCH"):
        preview_revision(workspace, raw_cards=[{**card, "source_sha256": "0" * 64}])


def test_cli_candidate_and_snapshot_refs_keep_original_scope(workspace, tmp_path):
    proposal = local_proposal(workspace)
    path = tmp_path / "proposal.json"
    atomic(path, proposal)
    before = inventory(tmp_path)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace), "--proposal", str(path)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["scope"] == proposal["scope"]
    assert inventory(tmp_path) == before
    proposal["kind"] = "boundary"
    atomic(path, proposal)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace), "--proposal", str(path)])
    assert result.exit_code == 2 and "DOMAIN_PROPOSAL_REQUIRES_DEDICATED_VALIDATOR" in result.output
    atomic(path, proposal["base"])
    board = read(workspace / BOARD)
    board["segments"][0]["notes"] = "changed"
    atomic(workspace / BOARD, board)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace), "--base", str(path)])
    assert result.exit_code == 2 and "REVISION_BASE_CONFLICT" in result.output


def test_unknown_beats_and_empty_workspace_do_not_initialize(workspace, tmp_path):
    with pytest.raises(WorkspaceError, match="PREVIEW_UNKNOWN_BEAT:missing"):
        preview_revision(workspace, beat_ids=["missing"])
    absent = tmp_path / "not-created"
    result = CliRunner().invoke(app, ["revision-preview", str(absent)])
    assert result.exit_code == 2 and not absent.exists()


@pytest.mark.parametrize("method", [None, 42, [], {}])
def test_non_string_retrieval_method_is_unknown(workspace, method):
    board = read(workspace / BOARD)
    board["retrieval_provenance"]["method"] = method
    atomic(workspace / BOARD, board)
    before = inventory(workspace)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["beats"][0]["retrieval"]["status"] == "unknown"
    assert inventory(workspace) == before


def test_changed_narration_bytes_invalidate_recorded_consumption(workspace):
    rendered_evidence(workspace)
    assert preview_revision(workspace)["beats"][0]["render_consumption"]["status"] == "recorded"
    Path(read(workspace / BOARD)["segments"][0]["audio_file"]).write_bytes(b"replacement narration")
    before = inventory(workspace)
    result = preview_revision(workspace)
    assert result["beats"][0]["render_consumption"]["reason"] == "render_voice_binding_mismatch"
    assert result["beats"][0]["render_consumption"]["status"] == "unknown"
    assert inventory(workspace) == before


def test_coercible_ranges_preserve_raw_document_and_card_hashes(workspace):
    board = read(workspace / BOARD)
    board["segments"][0]["visuals"][0].update(start="0", end="4")
    atomic(workspace / BOARD, board)
    card = {"evidence_id": "raw", "source_id": "ep1", "source_sha256": board["sources"][0]["fingerprint"],
        "timebase": {"mapping_version": "test", "numerator": 1, "denominator": 30},
        "requested_range": {"start": "0", "end": "4"}, "assets": [], "coverage_gaps": []}
    before = inventory(workspace)
    result = preview_revision(workspace, raw_cards=[card])
    assert result["binding"]["target_content_sha256"] == digest(board)
    assert result["binding"]["raw_cards_sha256"] == digest([card])
    assert result["raw_evidence"][0]["card"] == card
    assert result["beats"][0]["overlapping_raw_card_ids"] == ["raw"]
    assert inventory(workspace) == before


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "changed", "malformed"])
def test_unbound_voice_dependencies_stay_unknown(workspace, mutation):
    rendered_evidence(workspace)
    board = read(workspace / BOARD)
    path = Path(board["output"]["render_plan"])
    plan = read(path)
    node = next(row for row in plan["nodes"] if row["kind"] == "segment_av")
    if mutation == "missing":
        node["inputs"] = []
    elif mutation == "duplicate":
        node["inputs"] *= 2
    elif mutation == "changed":
        node["inputs"][0]["sha256"] = "0" * 64
    else:
        node["inputs"] = [None]
    atomic(path, plan)
    state = read(workspace / "state.json")
    state["stages"]["render"]["artifacts"][str(path)] = sha(path)
    atomic(workspace / "state.json", state)
    assert preview_revision(workspace)["beats"][0]["render_consumption"]["status"] == "unknown"


@pytest.mark.parametrize("key", ["coverage", "per_beat_rankings", "exclusions", "budget_exclusions"])
def test_malformed_optional_retrieval_fields_return_cli_diagnostic(workspace, key):
    board = read(workspace / BOARD)
    board["retrieval_provenance"][key] = None
    atomic(workspace / BOARD, board)
    before = inventory(workspace)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace)])
    assert result.exit_code == 2
    assert "PREVIEW_RETRIEVAL_FIELD_MUST_BE_" in result.output
    assert inventory(workspace) == before


@pytest.mark.parametrize("pool", ["xy", [None], [1], [{}], None])
def test_r0_pool_ids_require_string_array(workspace, pool):
    board = read(workspace / BOARD)
    board["retrieval_provenance"] = {"method": "r0-beat-stratified/1", "pool_unit_ids": pool}
    atomic(workspace / BOARD, board)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace)])
    assert result.exit_code == 2
    assert "PREVIEW_RETRIEVAL_POOL_IDS_MUST_BE_STRING_LIST" in result.output


def test_null_budget_exclusion_row_has_deliberate_diagnostic(workspace):
    board = read(workspace / BOARD)
    board["retrieval_provenance"]["budget_exclusions"] = [None]
    atomic(workspace / BOARD, board)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace)])
    assert result.exit_code == 2
    assert "PREVIEW_RETRIEVAL_BUDGET_ROWS_MUST_BE_OBJECTS" in result.output


@pytest.mark.parametrize("rankings", [None, [None], [{}], [{"unit_id": []}]])
def test_malformed_ranking_rows_have_deliberate_diagnostic(workspace, rankings):
    board = read(workspace / BOARD)
    board["retrieval_provenance"]["per_beat_rankings"]["beat"] = rankings
    atomic(workspace / BOARD, board)
    result = CliRunner().invoke(app, ["revision-preview", str(workspace)])
    assert result.exit_code == 2
    assert "PREVIEW_RETRIEVAL_RANKINGS_MUST_HAVE_UNIT_IDS" in result.output
