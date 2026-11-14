"""Synthetic bound metadata; no model, real render, physical frame or semantic claim."""
from copy import deepcopy
import json

import pytest
from typer.testing import CliRunner
from douyin_film_recap.cli import app
from douyin_film_recap.models import Storyboard
from douyin_film_recap.revision import BOARD
from douyin_film_recap.revision_preview import preview_revision
from douyin_film_recap.workspace import atomic, read, sha, WorkspaceError
from test_revision_preview import workspace, inventory, rendered_evidence


def spec(root, start=0, end=2):
    source=read(root/'00_source_manifest.json')['sources'][0]
    return {'schema':'film-support-windows/1','beats':[{'beat_id':'beat','alternatives':[[
        {'id':'declared','source_id':'ep1','source_sha256':source['fingerprint'],
         'start':start,'end':end,'basis':'synthetic declared reference, not semantic gold'}]]}]}


def original(root):
    board=read(root/BOARD)
    board['segments'][0].update(mode='original',audio_owner='original_dialogue',text='',text_raw='',
        visuals=[{'source_id':'ep1','start':0,'end':2,'unit_id':'direct'}])
    atomic(root/BOARD,board)
    rendered_evidence(root)
    return root


def result(root, declaration):
    return preview_revision(root,support_windows=declaration)['support_window_diagnostics']


def test_full_recorded_window_and_no_writes(workspace):
    original(workspace);before=inventory(workspace)
    r=result(workspace,spec(workspace))
    assert r['beats'][0]['status']=='RECORDED_WINDOW_FULL'
    assert r['physical_frame_coverage']=='NOT_VERIFIED' and not r['declaration_is_semantic_gold']
    assert inventory(workspace)==before


@pytest.mark.parametrize('start,end,status',[(0,3,'PARTIAL'),(3,4,'MISSING'),(.25,1.75,'FULL')])
def test_exact_partial_missing(workspace,start,end,status):
    original(workspace)
    assert result(workspace,spec(workspace,start,end))['beats'][0]['status']=='RECORDED_WINDOW_'+status


def test_conjunction_not_satisfied_by_one_window(workspace):
    original(workspace);q=spec(workspace);second=deepcopy(q['beats'][0]['alternatives'][0][0])
    second.update(id='unconsumed',start=4,end=5);q['beats'][0]['alternatives'][0].append(second)
    r=result(workspace,q);assert r['beats'][0]['status']=='RECORDED_WINDOW_PARTIAL'
    q['beats'][0]['alternatives'].append([deepcopy(q['beats'][0]['alternatives'][0][0])])
    assert result(workspace,q)['beats'][0]['status']=='RECORDED_WINDOW_FULL'


def test_unrendered_and_vo_unknown(workspace):
    assert result(workspace,spec(workspace))['beats'][0]['status']=='UNKNOWN'
    rendered_evidence(workspace)
    assert result(workspace,spec(workspace))['beats'][0]['status']=='UNKNOWN'


@pytest.mark.parametrize('mutate',[
    lambda w:w.update(start=True),lambda w:w.update(end=float('nan')),
    lambda w:w.update(end=0),lambda w:w.update(source_sha256='0'*64),
    lambda w:w.update(basis=''),lambda w:w.update(extra='not allowed'),
])
def test_invalid_declarations(workspace,mutate):
    q=spec(workspace);mutate(q['beats'][0]['alternatives'][0][0])
    with pytest.raises((ValueError,WorkspaceError)):result(workspace,q)


def test_changed_edl_unknown(workspace):
    original(workspace);p=workspace/'output/edl.json';p.write_text('[]')
    assert result(workspace,spec(workspace))['beats'][0]['status']=='UNKNOWN'


def test_cli_optional_and_legacy_unchanged(workspace,tmp_path):
    original(workspace);q=tmp_path/'declaration.json';q.write_text(json.dumps(spec(workspace)))
    runner=CliRunner();call=runner.invoke(app,['revision-preview',str(workspace),'--support-windows',str(q)])
    assert call.exit_code==0,call.output
    assert json.loads(call.stdout)['support_window_diagnostics']['beats'][0]['status']=='RECORDED_WINDOW_FULL'
    assert 'support_window_diagnostics' not in preview_revision(workspace)


def mutate_bound_plan(root, mutate):
    path=root/'output/render_plan.json';plan=read(path);mutate(plan);atomic(path,plan)
    state=read(root/'state.json');state['stages']['render']['artifacts'][str(path)]=sha(path);atomic(root/'state.json',state)


@pytest.mark.parametrize('mutation',[
    lambda p:next(n for n in p['nodes'] if n['kind']=='assembly')['inputs'][0]['media_contract'].update(frame_count=59),
    lambda p:next(n for n in p['nodes'] if n['kind']=='assembly')['inputs'][0].update(key='0'*64),
    lambda p:next(n for n in p['nodes'] if n['kind']=='segment_av')['params']['sources'][0].update(sha256='0'*64),
])
def test_unusable_measured_contract_unknown(workspace,mutation):
    original(workspace);mutate_bound_plan(workspace,mutation)
    assert result(workspace,spec(workspace))['beats'][0]['status']=='UNKNOWN'


def test_interval_union_does_not_double_count():
    from douyin_film_recap.consumption_coverage import _coverage
    from fractions import Fraction as F
    covered,gaps=_coverage({'start':0,'end':4},[(F(0),F(1)),(F(0),F(1)),(F(1),F(2)),(F(3),F(4))])
    assert covered==[[F(0),F(2)],[F(3),F(4)]] and gaps==[[F(2),F(3)]]


def test_submillisecond_seek_is_not_full(workspace):
    board=read(workspace/BOARD)
    board['segments'][0].update(mode='original',audio_owner='original_dialogue',text='',text_raw='',
        visuals=[{'source_id':'ep1','start':.0004,'end':2.0004,'unit_id':'direct'}])
    atomic(workspace/BOARD,board);rendered_evidence(workspace)
    r=result(workspace,spec(workspace,.1,1.9))
    assert r['beats'][0]['status']=='UNKNOWN'
    assert r['beats'][0]['mapping_unknowns'][0]['reason']=='millisecond_seek_rounding_unresolved'


def test_other_beat_cannot_fill_support(workspace):
    original(workspace)
    # Pure projection receives a checked consumption fixture; no real render claim.
    from douyin_film_recap.consumption_coverage import diagnose
    from douyin_film_recap.revision import freeze_revision
    from douyin_film_recap.revision_preview import _consumption
    board=read(workspace/BOARD);parsed=Storyboard.model_validate(board);base=freeze_revision(workspace)
    consumption=_consumption(workspace,board,read(workspace/'state.json'),candidate=False,external=[],base=base)
    parsed.segments[0].beat_id='other'
    q=spec(workspace);q['beats'][0]['beat_id']='other'
    # Missing EDL row for same Beat is not licensed merely by same segment ID.
    r=diagnose(q,parsed,base,consumption,read(workspace/'output/render_plan.json'))
    assert r['beats'][0]['status']=='UNKNOWN'


def test_old_base_and_changed_source_rejected(workspace):
    from douyin_film_recap.revision import freeze_revision
    original(workspace);base=freeze_revision(workspace);q=spec(workspace)
    board=read(workspace/BOARD);board['segments'][0]['notes']='later manual edit';atomic(workspace/BOARD,board)
    with pytest.raises(WorkspaceError,match='REVISION_BASE_CONFLICT'):
        preview_revision(workspace,base=base,support_windows=q)
    (workspace.parent/'source.mp4').write_bytes(b'new source')
    with pytest.raises(WorkspaceError,match='SOURCE_BINDING_CHANGED'):
        result(workspace,q)


def test_duplicate_beats_and_window_ids_reject(workspace):
    q=spec(workspace);q['beats'].append(deepcopy(q['beats'][0]))
    with pytest.raises(WorkspaceError,match='BEAT_UNKNOWN_OR_DUPLICATE'):result(workspace,q)
    q=spec(workspace);q['beats'][0]['alternatives'][0]*=2
    with pytest.raises(WorkspaceError,match='WINDOW_ID_DUPLICATE'):result(workspace,q)


def test_candidate_never_inherits_recorded_support(workspace):
    from test_revision_preview import local_proposal
    original(workspace)
    r=preview_revision(workspace,proposal=local_proposal(workspace),support_windows=spec(workspace))
    assert r['support_window_diagnostics']['beats'][0]['status']=='UNKNOWN'
