"""Synthetic HTML/CLI checks, not real media acceptance."""
import copy
import json
import socket
from html.parser import HTMLParser

import pytest
from typer.testing import CliRunner
from douyin_film_recap.cli import app
from douyin_film_recap.revision import BOARD, freeze_revision
from douyin_film_recap.revision_preview import preview_revision
from douyin_film_recap.revision_report import render_preview_html
from douyin_film_recap.workspace import atomic, read
from test_revision_preview import workspace, inventory, local_proposal, rendered_evidence


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.text = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    def handle_data(self, text):
        self.text.append(text)


def test_offline_html_escapes_all_dynamic_content_and_preserves_input(workspace):
    value = preview_revision(workspace)
    poison = '<script>alert("你好")</script><img src="https://evil.invalid" onerror="bad()">'
    value['beats'][0]['beat_id'] = poison
    value['beats'][0]['storyboard_references'][0]['text'] = poison + '长文本' * 10000
    value['beats'][0]['storyboard_references'][0]['unknown_fields'] = {poison: poison}
    value['base']['sources'][0]['path'] = poison
    value['scope_check']['reason'] = poison
    value['raw_evidence'] = [{'card': {'evidence_type': poison, 'notes': poison}}]
    before = copy.deepcopy(value)
    html = render_preview_html(value)
    doc = Document(html)
    assert value == before
    assert poison in ''.join(doc.text)
    assert '长文本' * 10000 in ''.join(doc.text)
    assert not any(t in {'script', 'img', 'iframe', 'object', 'embed', 'link', 'form', 'base'} for t, _ in doc.tags)
    for tag, attrs in doc.tags:
        assert not any(k.startswith('on') or k in {'src', 'srcset'} for k in attrs)
        if 'href' in attrs:
            assert attrs['href'] == '#beat-0'
    assert '候选池 ≠ 分镜引用 ≠ 成片消费' in html
    assert 'QC：NOT_RUN' in html
    assert '不会复核后来发生的变化' in html
    assert 'default-src' in html
    assert 'id="beat-0"' in html


def test_json_default_is_exactly_backward_compatible(workspace):
    expected = json.dumps(preview_revision(workspace), ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    default = CliRunner().invoke(app, ['revision-preview', str(workspace)])
    explicit = CliRunner().invoke(app, ['revision-preview', str(workspace), '--format', 'json'])
    assert default.exit_code == explicit.exit_code == 0
    assert default.stdout == explicit.stdout == expected


def test_html_cli_no_network_subprocess_or_workspace_write(workspace, monkeypatch):
    import douyin_film_recap.revision as revision
    import douyin_film_recap.workspace as workspace_module
    import douyin_film_recap.utils as utils
    import douyin_film_recap.raw_evidence as raw
    def forbidden(*a, **kw):
        pytest.fail('side effect attempted')
    monkeypatch.setattr(socket, 'socket', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(workspace_module, 'work_lock', forbidden)
    monkeypatch.setattr(revision, 'adopt_revision', forbidden)
    monkeypatch.setattr(revision, 'freeze_revision', forbidden)
    monkeypatch.setattr(utils, 'run_command', forbidden)
    monkeypatch.setattr(raw, 'verify_raw_evidence', forbidden)
    before = inventory(workspace.parent)
    result = CliRunner().invoke(app, ['revision-preview', str(workspace), '--format', 'html'])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith('<!doctype html>')
    assert inventory(workspace.parent) == before


def test_candidate_does_not_inherit_recorded_consumption(workspace):
    rendered_evidence(workspace)
    proposal = local_proposal(workspace)
    value = preview_revision(workspace, proposal=proposal)
    html = render_preview_html(value)
    assert '候选修改预览 · 尚未采用' in html
    assert 'candidate_has_not_been_rendered' in html
    assert '未知 / unknown' in html
    assert '处于现有局部范围（仅部分检查）' in html
    assert 'seg' in html
    assert '未验证 / not_validated' in html


def test_rejected_scope_and_protected_marker_are_visible(workspace):
    proposal = local_proposal(workspace)
    proposal['scope']['segment_ids'] = []
    value = preview_revision(workspace, proposal=proposal)
    value['beats'][0]['storyboard_references'][0]['protected'] = True
    html = render_preview_html(value)
    assert '拒绝 / rejected' in html
    assert value['scope_check']['reason'] in html
    assert '保护标记' in html


def test_empty_optional_data_stays_unknown(workspace):
    value = preview_revision(workspace)
    value.update(beats=[], raw_evidence=[], highlights=[], candidate_pool={'status': 'unknown', 'units': []})
    html = render_preview_html(value)
    assert '无 Beat 记录' in html
    assert '未知 / unknown' in html
    assert '无记录' in html


@pytest.mark.parametrize('format', ['html', 'json'])
def test_stale_base_refused_before_report(workspace, tmp_path, format):
    base = tmp_path / 'base.json'
    atomic(base, freeze_revision(workspace))
    board = read(workspace / BOARD)
    board['segments'][0]['notes'] = 'changed'
    atomic(workspace / BOARD, board)
    before = inventory(workspace.parent)
    result = CliRunner().invoke(app, ['revision-preview', str(workspace), '--base', str(base), '--format', format])
    assert result.exit_code == 2
    assert '<!doctype' not in result.stdout
    assert inventory(workspace.parent) == before


def test_invalid_format_rejected_without_reading_workspace(tmp_path):
    result = CliRunner().invoke(app, ['revision-preview', str(tmp_path / 'absent'), '--format', 'pdf'])
    assert result.exit_code == 2
    assert 'pdf' in result.output
    assert '只读预览失败' not in result.output


@pytest.mark.parametrize('changes', [{'schema': 'other'}, {'qc_status': 'PASSED'}, {'semantic_and_av_review_inherited': True}])
def test_renderer_refuses_incompatible_or_qc_inheriting_input(workspace, changes):
    value = preview_revision(workspace)
    value.update(changes)
    with pytest.raises(ValueError):
        render_preview_html(value)


def test_code_translation_is_contextual_and_navigation_is_early(workspace):
    value = preview_revision(workspace)
    ref = value['beats'][0]['storyboard_references'][0]
    ref.update(text='unknown', title='recorded', notes='candidate_evidence',
               unknown_fields={'status': 'unknown', 'reason': 'writer_budget'})
    html = render_preview_html(value)
    assert '<span class="value">unknown</span>' in html
    assert '<span class="value">writer_budget</span>' in html
    assert '<dt>status</dt><dd><span class="value">unknown</span>' in html
    assert '<dt>reason</dt><dd><span class="value">writer_budget</span>' in html
    assert '没有实际成片时间线记录 / realized_timeline_missing' in html
    assert '已有方案引用 / recorded_reference' in html
    assert '检索排名声明：3 条' in html
    assert html.index('href="#beat-0"') < html.index('1. 基线与源素材身份')
    assert '源素材 1 个 · Beat 1 个' in html


@pytest.mark.parametrize('rows', [None, 42, False, '<script>alert(1)</script>', {'reason': '<img src=x>'}])
def test_malformed_exclusions_preserved_without_count_or_side_effects(workspace, rows):
    board = read(workspace / BOARD)
    board['retrieval_provenance']['exclusions']['beat'] = rows
    atomic(workspace / BOARD, board)
    before = inventory(workspace.parent)
    value = preview_revision(workspace)
    original = copy.deepcopy(value)
    assert value['beats'][0]['retrieval']['exclusions'] == rows
    default = CliRunner().invoke(app, ['revision-preview', str(workspace)])
    assert default.exit_code == 0
    assert json.loads(default.stdout)['beats'][0]['retrieval']['exclusions'] == rows
    result = CliRunner().invoke(app, ['revision-preview', str(workspace), '--format', 'html'])
    assert result.exit_code == 0, result.output
    assert '排除记录：格式异常，非列表（展开查看原记录）' in result.stdout
    assert '排除记录：0 条' not in result.stdout
    assert 'QC：NOT_RUN' in result.stdout
    doc = Document(result.stdout)
    assert not any(tag in {'script', 'img', 'iframe'} for tag, _ in doc.tags)
    if isinstance(rows, str):
        assert rows in ''.join(doc.text)
    if isinstance(rows, dict):
        assert rows['reason'] in ''.join(doc.text)
    assert value == original
    assert inventory(workspace.parent) == before
