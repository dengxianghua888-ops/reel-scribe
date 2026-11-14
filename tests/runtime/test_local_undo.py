"""Three-way Work undo; fixture clocks are not listening acceptance."""
import copy
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import editing_runtime as rt
import work_ops
from test_result_preview import case, reinitialize


def state(q):
    with work_ops.connect(q['store']) as db:
        return work_ops.load(db)


def scope():
    return {'clip_ids':[], 'source_ids':[], 'caption_ids':[], 'audio_ids':['music'],
            'style_keys':[], 'note_keys':['manual'], 'output_fields':[], 'caption_style':True,
            'freeze_positions':['full'], 'freeze_duration':True}


def commit(case, change):
    q,out,tools,_=case; old=state(q);doc=copy.deepcopy(old['document']);change(doc)
    folder=out/('edit-'+str(old['sequence']));folder.mkdir()
    work_ops.timeline_revise({'operation':'timeline-revise','base_version':old['version'],
        'document':old['document'],'expected_document_sha256':old['document_sha256'],
        'candidate':doc,'scope':scope()},folder,tools)
    return work_ops.work_version({'operation':'work-version','action':'commit','store':q['store'],
        'expected_version':old['version'],'candidate':{'path':str(folder/'candidate.json'),
        'sha256':rt.sha256(folder/'candidate.json')},'message':'explicit edit','author':'human'},folder,tools)


def request(case, sequence=2):
    q,_,_,_=case
    return {'operation':'work-version','action':'prepare-local-undo','store':q['store'],
        'expected_version':state(q)['version'],'undo_sequence':sequence,
        'fields':[{'kind':'caption_style','field':'font_size'}],'scope':scope()}


def run(case, req):
    _,out,tools,_=case
    return work_ops.work_version(req,out,tools)


def test_preserves_later_manual_edit_and_requires_explicit_commit(case):
    commit(case,lambda d:d['caption_style'].update(font_size=14))
    commit(case,lambda d:d['notes'].update(manual='later human note'))
    q,out,tools,_=case;before=state(q)
    result=run(case,request(case));bundle=json.loads((out/'candidate.json').read_bytes())
    assert state(q)==before and result['status']=='CANDIDATE_PREPARED'
    assert bundle['document']['caption_style']['font_size']==12
    assert bundle['document']['notes']['manual']=='later human note'
    assert result['history']['after']['sequence']==2 and result['history']['before']['sequence']==1
    applied_dir=out/'applied';applied_dir.mkdir()
    applied=work_ops.work_version({'operation':'work-version','action':'commit','store':q['store'],
        'expected_version':before['version'],'candidate':{'path':str(out/'candidate.json'),'sha256':rt.sha256(out/'candidate.json')},
        'message':'explicit partial undo','author':'human'},applied_dir,tools)
    assert applied['sequence']==4


def test_noop_no_candidate(case):
    commit(case,lambda d:d['caption_style'].update(font_size=14))
    commit(case,lambda d:d['caption_style'].update(font_size=12))
    assert run(case,request(case))['status']=='NO_OP'
    assert not (case[1]/'candidate.json').exists()


@pytest.mark.parametrize('mutation,error',[
    (lambda q:q.update(expected_version='0'*64),'WORK_VERSION_CONFLICT'),
    (lambda q:q.update(undo_sequence=True),'UNDO_SEQUENCE_INVALID'),
    (lambda q:q.update(undo_sequence=0),'UNDO_SEQUENCE_INVALID'),
    (lambda q:q.update(undo_sequence=99),'UNDO_SEQUENCE_INVALID'),
    (lambda q:q.update(fields=[{'kind':'caption_style','field':'font'}]),'UNDO_FIELD_UNSUPPORTED'),
    (lambda q:q['fields'].append(q['fields'][0]),'UNDO_FIELD_DUPLICATE'),
    (lambda q:q['scope'].update(caption_style=False),'CAPTION_STYLE_FROZEN'),
])
def test_invalid_no_candidate(case,mutation,error):
    commit(case,lambda d:d['caption_style'].update(font_size=14));q=request(case);mutation(q)
    with pytest.raises(rt.ContractError,match=error):run(case,q)
    assert not (case[1]/'candidate.json').exists()


def test_conflicting_later_value(case):
    commit(case,lambda d:d['caption_style'].update(font_size=14))
    commit(case,lambda d:d['caption_style'].update(font_size=16))
    with pytest.raises(rt.ContractError,match='UNDO_FIELD_CONFLICT'):run(case,request(case))
    assert not (case[1]/'candidate.json').exists()


def test_binding_not_silently_reendorsed(case):
    def setup(d):
        d['style_bindings']['*']={'family':'fixture','style_id':'x','version':'1',
            'card':d['caption_style']['font'],'parameters':{'caption_style':{'font_size':12}}}
    reinitialize(case,setup)
    commit(case,lambda d:d['caption_style'].update(font_size=14))
    with pytest.raises(rt.ContractError,match='UNDO_STYLE_BINDING'):run(case,request(case))
    assert not (case[1]/'candidate.json').exists()


def audio_case(case):
    import wave
    wav=case[1]/'tone.wav'
    with wave.open(str(wav),'wb') as stream:
        stream.setnchannels(1);stream.setsampwidth(2);stream.setframerate(48000)
        stream.writeframes(b'\0\0'*48000)
    tools=case[2];original=tools.probe;real=rt.Tools()
    tools.probe=lambda p:real.probe(p) if str(p)==str(wav) else original(p)
    tools.selected_audio_clock=real.selected_audio_clock
    def setup(d):
        d['audio_tracks']['music']={'source':{'path':str(wav),'sha256':rt.sha256(wav)},'start':0,'end':1,
            'anchor_clip_id':'full','offset':0,'gain_db':0}
    reinitialize(case,setup)
    commit(case,lambda d:d['audio_tracks']['music'].update(gain_db=-6))
    q=request(case);q['fields']=[{'kind':'audio_track','id':'music','field':'gain_db'}]
    return q


def test_audio_gain_retains_later_caption(case):
    q=audio_case(case);commit(case,lambda d:d['caption_style'].update(font_size=20))
    q['expected_version']=state(q)['version'];run(case,q)
    doc=json.loads((case[1]/'candidate.json').read_bytes())['document']
    assert doc['audio_tracks']['music']['gain_db']==0 and doc['caption_style']['font_size']==20


@pytest.mark.parametrize('mutation',[
    lambda d:d['audio_tracks']['music'].update(start=.04,offset=.04),
    lambda d:d['audio_tracks']['music'].update(anchor_clip_id=None),
])
def test_same_gain_different_audio_identity_rejected(case,mutation):
    q=audio_case(case);commit(case,mutation);q['expected_version']=state(q)['version']
    with pytest.raises(rt.ContractError,match='UNDO_AUDIO_IDENTITY'):run(case,q)


@pytest.mark.parametrize('column,value,error',[
    ('parent',99,'UNDO_REQUIRES_ORDINARY_COMMIT_PARENT'),
    ('action','restore','UNDO_REQUIRES_ORDINARY_COMMIT_PARENT'),
    ('digest','0'*64,'WORK_DOCUMENT_HASH_MISMATCH'),
])
def test_history_integrity(case,column,value,error):
    commit(case,lambda d:d['caption_style'].update(font_size=14));q=request(case)
    with work_ops.connect(q['store']) as db:
        db.execute(f'UPDATE revisions SET {column}=? WHERE sequence=2',(value,));db.commit()
    with pytest.raises(rt.ContractError,match=error):run(case,q)


def test_deleted_audio_track_rejected(case):
    q=audio_case(case);commit(case,lambda d:d['audio_tracks'].clear())
    q['expected_version']=state(q)['version']
    with pytest.raises(rt.ContractError,match='UNDO_FIELD_MISSING'):run(case,q)


def test_same_gain_replaced_source_rejected(case):
    q=audio_case(case)
    replacement=case[1]/'different.wav';replacement.write_bytes((case[1]/'tone.wav').read_bytes())
    # Same media bytes at a different identity path are not the old selected object.
    tools=case[2];old_probe=tools.probe;real=rt.Tools()
    tools.probe=lambda p:real.probe(p) if str(p)==str(replacement) else old_probe(p)
    commit(case,lambda d:d['audio_tracks']['music'].update(source={'path':str(replacement),'sha256':rt.sha256(replacement)}))
    q['expected_version']=state(q)['version']
    with pytest.raises(rt.ContractError,match='UNDO_AUDIO_IDENTITY_CONFLICT'):run(case,q)


def test_field_absent_before_commit_rejected(case):
    old_style=copy.deepcopy(case[3]['caption_style'])
    reinitialize(case,lambda d:d.update(caption_style=None))
    commit(case,lambda d:d.update(caption_style=old_style))
    with pytest.raises(rt.ContractError,match='UNDO_FIELD_MISSING'):run(case,request(case))


def test_init_cannot_be_undone(case):
    with pytest.raises(rt.ContractError,match='UNDO_REQUIRES_ORDINARY_COMMIT_PARENT'):
        run(case,request(case,sequence=1))


def test_intervening_ancestry_corruption_rejected(case):
    commit(case,lambda d:d['caption_style'].update(font_size=14))
    commit(case,lambda d:d['notes'].update(manual='later'))
    q=request(case)
    with work_ops.connect(q['store']) as db:
        db.execute('UPDATE revisions SET parent=1 WHERE sequence=3');db.commit()
    with pytest.raises(rt.ContractError,match='UNDO_HISTORY_PARENT_INVALID'):run(case,q)


@pytest.mark.parametrize('field,value',[('margin_v',8),('color_rgb','FF0000')])
def test_other_caption_fields(case,field,value):
    commit(case,lambda d:d['caption_style'].update({field:value}))
    q=request(case);q['fields']=[{'kind':'caption_style','field':field}]
    run(case,q)
    doc=json.loads((case[1]/'candidate.json').read_bytes())['document']
    assert doc['caption_style'][field]==case[3]['caption_style'][field]


def test_dependency_discovery_requires_probe_without_render_tools():
    from dependency_discovery import _selected_requirements
    required, unknown, branch = _selected_requirements('work-version', {'action': 'prepare-local-undo'})
    assert set(required) == {'sqlite', 'ffprobe'}
    assert unknown == [] and branch == 'prepare-local-undo'


def bound_case(case, constraints=None, parameters=None):
    """Build actual compiler binding then commit; no invented binding envelope."""
    import style_recipe_ops
    q,out,tools,_=case;old=state(q)
    recipe={'schema':'style-recipe/1','id':'explicit','version':'1',
        'style':{'family':'test','style_id':'caption','version':'1', 'card':old['document']['caption_style']['font']},
        'parameters':{'caption_style':{'font_size':14,'color_rgb':'FFFFFF'}}}
    if parameters is not None:
        recipe['parameters']=parameters
    if constraints is not None:
        recipe['layout_constraints']=constraints
    folder=out/'recipe';folder.mkdir();allowed=scope();allowed['style_keys']=['*']
    style_recipe_ops.execute({'operation':'style-recipe-compile','base_version':old['version'],
        'document':old['document'],'expected_document_sha256':old['document_sha256'],
        'recipe':recipe,'expected_recipe_sha256':rt.fingerprint(recipe),'capabilities':['caption-style','audio-track-gain'],
        'scope':allowed},folder,tools)
    target=out/'recipe-commit';target.mkdir()
    work_ops.work_version({'operation':'work-version','action':'commit','store':q['store'],
        'expected_version':old['version'],'candidate':{'path':str(folder/'candidate.json'),'sha256':rt.sha256(folder/'candidate.json')},
        'message':'explicit recipe','author':'human'},target,tools)
    req=request(case);req['scope']['style_keys']=['*']
    req['binding_resolution']={'recipe':recipe,'expected_recipe_sha256':rt.fingerprint(recipe),
        'derived_recipe_id':'explicit-local-undo','derived_recipe_version':'1'}
    return req


def test_bound_undo_derives_truthful_recipe_preserves_later_note(case):
    req=bound_case(case);commit(case,lambda d:d['notes'].update(manual='later'))
    req['expected_version']=state(req)['version'];before=state(req)
    result=run(case,req);bundle=json.loads((case[1]/'candidate.json').read_bytes())
    derived=json.loads((case[1]/'derived-recipe.json').read_bytes())
    assert state(req)==before
    assert derived['parameters']['caption_style']=={'font_size':12,'color_rgb':'FFFFFF'}
    binding=bundle['document']['style_bindings']['*']
    assert binding['parameters']['recipe_sha256']==rt.fingerprint(derived)
    assert binding['parameters']['recipe_sha256']!=req['binding_resolution']['expected_recipe_sha256']
    assert bundle['document']['notes']['manual']=='later'
    assert result['binding_resolution']['derived_from']['recipe_id']=='explicit'


@pytest.mark.parametrize('mutate,error',[
    (lambda q:q['scope'].update(style_keys=[]),'UNDO_BINDING_SCOPE_REQUIRED'),
    (lambda q:q['binding_resolution'].update(expected_recipe_sha256='0'*64),'UNDO_RECIPE_HASH_CONFLICT'),
    (lambda q:q['binding_resolution'].update(derived_recipe_id='explicit',derived_recipe_version='1'),'UNDO_DERIVED_RECIPE_ID_MUST_CHANGE'),
    (lambda q:q['fields'].append({'kind':'caption_style','field':'margin_v'}),'UNDO_SELECTED_FIELD_NOT_RECIPE_MAPPED'),
])
def test_bound_resolution_fail_closed(case,mutate,error):
    req=bound_case(case);mutate(req)
    with pytest.raises(rt.ContractError,match=error):run(case,req)
    assert not (case[1]/'candidate.json').exists()


def test_bound_other_parameter_manually_changed_rejected(case):
    req=bound_case(case);commit(case,lambda d:d['caption_style'].update(color_rgb='FF0000'))
    req['expected_version']=state(req)['version']
    with pytest.raises(rt.ContractError,match='UNDO_BINDING_ALREADY_DIVERGED'):run(case,req)


def test_bound_noop_does_not_change_recipe(case):
    req=bound_case(case);commit(case,lambda d:d['caption_style'].update(font_size=12))
    req['expected_version']=state(req)['version'];before=state(req)
    result=run(case,req)
    assert result['status']=='NO_OP' and state(req)==before
    assert not (case[1]/'derived-recipe.json').exists() and not (case[1]/'candidate.json').exists()


def test_noncompiler_binding_still_rejected(case):
    req=bound_case(case)
    req['binding_resolution']['recipe']['parameters']['caption_style']['font_size']=15
    req['binding_resolution']['expected_recipe_sha256']=rt.fingerprint(req['binding_resolution']['recipe'])
    with pytest.raises(rt.ContractError,match='UNDO_BINDING_RECIPE_MISMATCH'):run(case,req)


def test_layout_preserved_and_both_documents_rechecked(case,monkeypatch):
    import caption_layout
    calls=[]
    def check(doc,constraints,directory,tools):
        calls.append((copy.deepcopy(doc),copy.deepcopy(constraints)))
        return {'status':'TEST_DOUBLE_NOT_REAL_LAYOUT_ACCEPTANCE'}
    monkeypatch.setattr(caption_layout,'check',check)
    constraints={'schema':'caption-layout/1','canvas':{'width':64,'height':64},
        'subtitle_band':{'x':0,'y':32,'width':64,'height':32},
        'protected_regions':[{'id':'ui','rect':{'x':0,'y':0,'width':64,'height':20}}]}
    req=bound_case(case,constraints);calls.clear();result=run(case,req)
    assert len(calls)==2 and [c[0]['caption_style']['font_size'] for c in calls]==[14,12]
    assert all(c[1]==constraints for c in calls)
    assert result['binding_resolution']['derived_recipe']['layout_constraints']==constraints


def test_failed_layout_never_emits_candidate(case,monkeypatch):
    import caption_layout
    monkeypatch.setattr(caption_layout,'check',lambda *a:{'status':'TEST_DOUBLE'})
    req=bound_case(case,{'fixture':'only verifies call rejection, not layout geometry'})
    def reject(*a):raise rt.ContractError('ACTUAL_LAYOUT_REJECTION_TEST_DOUBLE')
    monkeypatch.setattr(caption_layout,'check',reject)
    before=state(req)
    with pytest.raises(rt.ContractError,match='ACTUAL_LAYOUT_REJECTION'):run(case,req)
    assert state(req)==before and not (case[1]/'candidate.json').exists()


def test_multiple_binding_unsupported(case):
    req=bound_case(case)
    # Independently recorded additional binding makes global-only resolution unsupported.
    old=state(req);doc=copy.deepcopy(old['document']);doc['style_bindings']['full']=copy.deepcopy(doc['style_bindings']['*'])
    folder=case[1]/'extra-binding';folder.mkdir();allowed=scope();allowed['style_keys']=['full']
    work_ops.timeline_revise({'operation':'timeline-revise','base_version':old['version'],
        'document':old['document'],'expected_document_sha256':old['document_sha256'],
        'candidate':doc,'scope':allowed},folder,case[2])
    applied=case[1]/'extra-commit';applied.mkdir()
    work_ops.work_version({'operation':'work-version','action':'commit','store':req['store'],
        'expected_version':old['version'],'candidate':{'path':str(folder/'candidate.json'),'sha256':rt.sha256(folder/'candidate.json')},
        'message':'explicit extra binding','author':'human'},applied,case[2])
    req['expected_version']=state(req)['version']
    with pytest.raises(rt.ContractError,match='UNDO_BINDING_RECIPE_MISMATCH'):run(case,req)


def test_bound_audio_gain_derived_recipe(case):
    audio_case(case)
    req=bound_case(case,parameters={'audio_gain_db':{'music':-12}})
    req['undo_sequence']=3
    req['fields']=[{'kind':'audio_track','id':'music','field':'gain_db'}]
    result=run(case,req)
    doc=json.loads((case[1]/'candidate.json').read_bytes())['document']
    assert doc['audio_tracks']['music']['gain_db']==-6
    assert result['binding_resolution']['derived_recipe']['parameters']=={'audio_gain_db':{'music':-6}}


def test_bound_constraint_replacement_rejected(case):
    req=bound_case(case)
    req['binding_resolution']['recipe']['layout_constraints']={'attempt':'new less strict constraint'}
    req['binding_resolution']['expected_recipe_sha256']=rt.fingerprint(req['binding_resolution']['recipe'])
    with pytest.raises(rt.ContractError,match='UNDO_BINDING_RECIPE_MISMATCH'):run(case,req)
