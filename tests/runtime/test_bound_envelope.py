"""Bound envelopes: contract tests, not listening or style certification."""
import copy
import json
import pytest
from test_local_undo import case, audio_case, state, scope, reinitialize, commit, request, run
from test_work_envelope import ENV
import editing_runtime as rt
import style_recipe_ops as recipes
import work_ops


def recipe_for(doc, card):
    return {'schema':'style-recipe/1','id':'bound','version':'1',
        'style':{'family':'fixture','style_id':'x','version':'1','card':card},
        'parameters':{'caption_style':{'font_size':doc['caption_style']['font_size']}}}


def bind(doc, recipe):
    doc['style_bindings']={'*':{**copy.deepcopy(recipe['style']),'parameters':{
        'recipe_id':recipe['id'],'recipe_version':recipe['version'],'recipe_sha256':rt.fingerprint(recipe),
        'presentation':copy.deepcopy(recipe['parameters'])}}}


def setup(case):
    audio_case(case);q,out,tools,_=case
    card=out/'card.md';card.write_text('fixture')
    rec=recipe_for(state(q)['document'],{'path':str(card),'sha256':rt.sha256(card)})
    out=out/'initial-bind';out.mkdir()
    r=compile_request(case,rec);recipes.execute(r,out,tools)
    work_ops.work_version({'operation':'work-version','action':'commit','store':q['store'],
        'expected_version':state(q)['version'],'candidate':{'path':str(out/'candidate.json'),'sha256':rt.sha256(out/'candidate.json')},
        'message':'bind caption','author':'human'},out,tools)
    return rec


def compile_request(case,rec):
    old=state(case[0]);sc=scope();sc['style_keys']=['*']
    return {'operation':'style-recipe-compile','base_version':old['version'],'document':old['document'],
        'expected_document_sha256':old['document_sha256'],'recipe':rec,'expected_recipe_sha256':rt.fingerprint(rec),
        'capabilities':['caption-style','audio-track-envelope'],'scope':sc}


def prepare(case):
    rec=setup(case);rec['id']='fade';rec['parameters']['audio_envelope']={'music':ENV}
    return rec,compile_request(case,rec)


def test_bound_compile_and_undo(case):
    rec,req=prepare(case);q,out,tools,_=case
    render=out/'envelope';render.mkdir()
    recipes.execute(req,render,tools)
    work_ops.work_version({'operation':'work-version','action':'commit','store':q['store'],
        'expected_version':state(q)['version'],'candidate':{'path':str(render/'candidate.json'),'sha256':rt.sha256(render/'candidate.json')},
        'message':'explicit fade','author':'human'},render,tools)
    seq=state(q)['sequence']
    commit(case,lambda d:(d['audio_tracks']['music'].update(gain_db=-9),d['notes'].update(manual='keep')))
    r=request(case,seq);r['fields']=[{'kind':'audio_track','id':'music','field':'envelope'}];r['scope']['style_keys']=['*']
    r['binding_resolution']={'recipe':rec,'expected_recipe_sha256':rt.fingerprint(rec),'derived_recipe_id':'undo','derived_recipe_version':'1'}
    result=run(case,r);doc=json.loads((out/'candidate.json').read_text())['document']
    assert 'envelope' not in doc['audio_tracks']['music']
    assert doc['audio_tracks']['music']['gain_db']==-9 and doc['notes']['manual']=='keep'
    assert result['binding_resolution']['derived_recipe']['parameters']=={'caption_style':{'font_size':12}}


@pytest.mark.parametrize('mutation,error',[
    (lambda r:r['recipe']['parameters'].pop('caption_style'),'PARAMETERS_DROPPED'),
    (lambda r:r['recipe']['parameters']['caption_style'].update(font_size=13),'UNSELECTED_PARAMETER_CHANGED'),
    (lambda r:r['scope'].update(audio_ids=[]),'OUTSIDE_SCOPE: audio_tracks'),
    (lambda r:r['capabilities'].remove('audio-track-envelope'),'CAPABILITY_UNAVAILABLE'),
    (lambda r:r['recipe'].update(layout_constraints={}), 'CONSTRAINTS_MUST_PERSIST'),
])
def test_reject_recipe_changes(case,mutation,error):
    rec,r=prepare(case);mutation(r);r['expected_recipe_sha256']=rt.fingerprint(r['recipe'])
    with pytest.raises(ValueError,match=error):recipes.execute(r,case[1],case[2])


@pytest.mark.parametrize('mutation,error',[
    (lambda d:d['style_bindings']['*']['parameters'].update(recipe_sha256='0'*64),'HASH_CONFLICT'),
    (lambda d:d['caption_style'].update(font_size=19),'BINDING_DIVERGED'),
    (lambda d:d['style_bindings'].update(extra=copy.deepcopy(d['style_bindings']['*'])),'BINDING_UNSUPPORTED'),
])
def test_reject_unverified_binding(case,mutation,error):
    rec,r=prepare(case);recipes.execute(r,case[1],case[2]);doc=json.loads((case[1]/'candidate.json').read_text())['document']
    mutation(doc)
    with pytest.raises(ValueError,match=error):work_ops.validate_document(doc,case[2])


def test_deleted_last_envelope_keeps_stale_binding_rejected(case):
    rec,r=prepare(case);recipes.execute(r,case[1],case[2])
    doc=json.loads((case[1]/'candidate.json').read_text())['document']
    doc['audio_tracks']['music'].pop('envelope')
    with pytest.raises(ValueError,match='BINDING_DIVERGED'):work_ops.validate_document(doc,case[2])


def test_cue_guard_carries_envelope_unchanged(case):
    rec,r=prepare(case);recipes.execute(r,case[1],case[2])
    doc=json.loads((case[1]/'candidate.json').read_text())['document']
    doc['captions']['c']={'clip_id':'full','start':0,'end':.5,'text':'test'}
    rec['parameters']['caption_overrides']={'c':{'font_size':12}}
    doc['captions']['c']['style_override']={'font_size':12}
    bind(doc,rec)
    proposal=copy.deepcopy(rec);proposal['parameters']['caption_overrides']={'c':{'font_size':14}}
    sc=scope();sc.update(caption_ids=['c'],caption_style=False)
    recipes.envelope_recipe_guard(doc,proposal,sc)
    assert recipes.cue_recipe_guard(doc,proposal,sc)==['c']
    sc['style_keys']=['*']
    compiled=case[1]/'cue-update';compiled.mkdir()
    req={**r,'document':doc,'expected_document_sha256':rt.fingerprint(doc),'recipe':proposal,
         'expected_recipe_sha256':rt.fingerprint(proposal),'scope':sc,'capabilities':['caption-cue-style']}
    recipes.execute(req,compiled,case[2])
    candidate=json.loads((compiled/'candidate.json').read_text())['document']
    assert candidate['captions']['c']['style_override']['font_size']==14
    assert candidate['audio_tracks']==doc['audio_tracks']
    proposal['parameters']['audio_envelope']['music']={**ENV,'curve':'qsin'}
    with pytest.raises(ValueError,match='GLOBAL_CHANGE_FORBIDDEN'):recipes.cue_recipe_guard(doc,proposal,sc)


@pytest.mark.parametrize('change_cue',[False,True])
def test_audio_only_carries_existing_cue_mapping(case,change_cue):
    rec,r=prepare(case)
    doc=copy.deepcopy(r['document'])
    doc['captions']['c']={'clip_id':'full','start':0,'end':.5,'text':'test','style_override':{'font_size':12}}
    old=copy.deepcopy(rec);old['parameters'].pop('audio_envelope')
    old['parameters']['caption_overrides']={'c':{'font_size':12}}
    bind(doc,old)
    rec['parameters']['caption_overrides']={'c':{'font_size':14 if change_cue else 12}}
    r.update(document=doc,expected_document_sha256=rt.fingerprint(doc),expected_recipe_sha256=rt.fingerprint(rec))
    if change_cue:
        with pytest.raises(ValueError,match='UNSELECTED_PARAMETER_CHANGED|UNSELECTED_OVERRIDE_CHANGED'):
            recipes.execute(r,case[1],case[2])
    else:
        recipes.execute(r,case[1],case[2])
        result=json.loads((case[1]/'candidate.json').read_text())['document']
        assert result['captions']==doc['captions']
        assert result['audio_tracks']['music']['envelope']==ENV


@pytest.mark.parametrize('group,value',[
    ('audio_gain_db',{'missing':None}),('caption_style',{'unknown':None}),
    ('caption_overrides',{'missing':{}}),('audio_gain_db',{'music':None}),
])
def test_forged_but_rehashed_mapping_rejected(case,group,value):
    rec,r=prepare(case);recipes.execute(r,case[1],case[2])
    doc=json.loads((case[1]/'candidate.json').read_text())['document']
    rec['parameters'][group]=value;bind(doc,rec)
    with pytest.raises((ValueError,TypeError)):work_ops.validate_document(doc,case[2])


@pytest.mark.parametrize('existing',[False,True])
def test_integer_gain_mapping_accepts_normalized_float(case,existing):
    rec,r=prepare(case)
    rec['parameters']['audio_gain_db']={'music':-6}
    r['document']['audio_tracks']['music']['gain_db']=-6.0
    if existing:
        old=copy.deepcopy(rec);old['parameters'].pop('audio_envelope');bind(r['document'],old)
    r.update(expected_document_sha256=rt.fingerprint(r['document']),expected_recipe_sha256=rt.fingerprint(rec))
    r['capabilities'].append('audio-track-gain')
    recipes.execute(r,case[1],case[2])
    doc=json.loads((case[1]/'candidate.json').read_text())['document']
    work_ops.validate_document(doc,case[2])
    assert doc['audio_tracks']['music']['gain_db']==-6.0


@pytest.mark.parametrize('malformed',[{},None,{'parameters':None},{'parameters':[]},
    {'family':'x','style_id':'x','version':'1','card':{},'parameters':None},
    {'family':'x','style_id':'x','version':'1','card':{},'parameters':{}},
    {'family':'x','style_id':'x','version':'1','card':{},'parameters':{'recipe_id':'x','recipe_version':'1','recipe_sha256':'0'*64,'presentation':None}}])
def test_malformed_binding_has_explainable_error(case,malformed):
    rec,r=prepare(case);doc=copy.deepcopy(r['document'])
    doc['audio_tracks']['music']['envelope']=ENV
    doc['style_bindings']['*']=malformed
    with pytest.raises(ValueError,match='AUDIO_ENVELOPE_STYLE_BINDING_UNSUPPORTED'):
        work_ops.validate_document(doc,case[2])


@pytest.mark.parametrize('malformed',[None,{'family':'x','style_id':'x','version':'1','card':{},'parameters':None}])
def test_malformed_binding_without_envelope_not_attribute_error(case,malformed):
    rec,r=prepare(case);doc=copy.deepcopy(r['document'])
    doc['style_bindings']['*']=malformed
    with pytest.raises(ValueError):work_ops.validate_document(doc,case[2])
