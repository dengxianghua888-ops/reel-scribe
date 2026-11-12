"""Finite cue overrides: no synthetic-clock test is visual/listening acceptance."""
import copy
import json
import pytest
from test_local_undo import case, reinitialize, state, request, run
import test_local_undo as helper
import editing_runtime as rt
import shared_timeline
import revision_impact

@pytest.fixture
def cue_case(case,monkeypatch):
    def initialize(doc):
        doc['captions']={'a':{'clip_id':'full','start':0,'end':.4,'text':'first'},
                         'b':{'clip_id':'full','start':.4,'end':.8,'text':'second'}}
    reinitialize(case,initialize)
    original=helper.scope
    def scoped():
        value=original();value['caption_ids']=['a','b'];return value
    monkeypatch.setattr(helper,'scope',scoped)
    return case


def undo_request(case):
    q=request(case);q['fields']=[{'kind':'caption_override','id':'a','field':'font_size'}]
    return q


def test_remove_new_override_inherits_current_global_preserves_later(cue_case):
    c=cue_case
    helper.commit(c,lambda d:d['captions']['a'].update(style_override={'font_size':14}))
    helper.commit(c,lambda d:(d['caption_style'].update(font_size=16),d['notes'].update(manual='later'),
                               d['captions']['b'].update(style_override={'color_rgb':'FF0000'})))
    q=undo_request(c);before=state(q);r=run(c,q)
    doc=json.loads((c[1]/'candidate.json').read_bytes())['document']
    assert 'style_override' not in doc['captions']['a']
    assert doc['captions']['b']==before['document']['captions']['b'] and doc['notes']==before['document']['notes']
    assert r['fields'][0]['restored_effective_value']==16 and not r['fields'][0]['presence']['before']
    assert state(q)==before


def test_partial_override_keeps_other_keys(cue_case):
    helper.commit(cue_case,lambda d:d['captions']['a'].update(style_override={'color_rgb':'FF0000'}))
    helper.commit(cue_case,lambda d:d['captions']['a']['style_override'].update(font_size=14))
    q=undo_request(cue_case);q['undo_sequence']=3;run(cue_case,q)
    doc=json.loads((cue_case[1]/'candidate.json').read_bytes())['document']
    assert doc['captions']['a']['style_override']=={'color_rgb':'FF0000'}


@pytest.mark.parametrize('change,error',[
    (lambda d:d['captions']['a']['style_override'].update(font_size=18),'UNDO_FIELD_CONFLICT'),
    (lambda d:d['captions']['a'].update(text='different words'),'UNDO_CAPTION_IDENTITY_CONFLICT'),
    (lambda d:d['captions'].pop('a'),'UNDO_FIELD_MISSING'),
])
def test_later_change_not_overwritten(cue_case,change,error):
    helper.commit(cue_case,lambda d:d['captions']['a'].update(style_override={'font_size':14}))
    helper.commit(cue_case,change)
    with pytest.raises(rt.ContractError,match=error):run(cue_case,undo_request(cue_case))
    assert not (cue_case[1]/'candidate.json').exists()


def test_local_scope_required(cue_case):
    helper.commit(cue_case,lambda d:d['captions']['a'].update(style_override={'font_size':14}))
    q=undo_request(cue_case);q['scope']['caption_ids']=[];q['scope']['caption_style']=True
    with pytest.raises(rt.ContractError,match='OUTSIDE_SCOPE'):run(cue_case,q)


def test_shared_and_impact_only_ignore_finite_presentation(cue_case):
    base=state(cue_case[0])['document'];candidate=copy.deepcopy(base)
    candidate['captions']['a']['style_override']={'font_size':14}
    assert shared_timeline.compatible(base,candidate)
    report=revision_impact.analyze(base,candidate,helper.scope(),cue_case[2],
        expected_base_sha256=rt.fingerprint(base),expected_candidate_sha256=rt.fingerprint(candidate))
    assert 'caption-local-presentation' in report['classification']
    assert report['required_stages']==['caption-layout','visual-composition','render']
    assert report['cache_reuse']=='NOT_AUTHORIZED'
    candidate['captions']['a']['text']='new';assert not shared_timeline.compatible(base,candidate)


@pytest.mark.parametrize('value',[{}, {'font':'arbitrary'}, {'font_size':True},{'font_size':400}, {'margin_v':64},{'color_rgb':'red'}])
def test_shared_does_not_swallow_unknown_or_invalid_overrides(cue_case,value):
    base=state(cue_case[0])['document'];candidate=copy.deepcopy(base)
    candidate['captions']['a']['style_override']=value
    assert not shared_timeline.compatible(base,candidate)


def bound_override(case,monkeypatch,keep_other):
    original=helper.scope
    def scoped():
        value=original();value['style_keys']=['*'];return value
    monkeypatch.setattr(helper,'scope',scoped)
    doc=state(case[0])['document']
    recipe={'schema':'style-recipe/1','id':'local','version':'1',
        'style':{'family':'fixture','style_id':'local','version':'1','card':doc['caption_style']['font']},
        'parameters':{'caption_overrides':{'a':{'font_size':14}}}}
    if keep_other:recipe['parameters']['caption_style']={'color_rgb':'FFFFFF'}
    def edit(d):
        d['captions']['a']['style_override']={'font_size':14}
        d['style_bindings']['*']={**copy.deepcopy(recipe['style']),'parameters':{
            'recipe_id':'local','recipe_version':'1','recipe_sha256':rt.fingerprint(recipe),
            'presentation':copy.deepcopy(recipe['parameters'])}}
    helper.commit(case,edit)
    q=undo_request(case);q['binding_resolution']={'recipe':recipe,'expected_recipe_sha256':rt.fingerprint(recipe),
        'derived_recipe_id':'local-undo','derived_recipe_version':'1'}
    return q


def test_bound_override_removal_keeps_nonempty_recipe(cue_case,monkeypatch):
    q=bound_override(cue_case,monkeypatch,True)
    r=run(cue_case,q)
    derived=r['binding_resolution']['derived_recipe']
    assert derived['parameters']=={'caption_style':{'color_rgb':'FFFFFF'}}
    doc=json.loads((cue_case[1]/'candidate.json').read_bytes())['document']
    assert 'style_override' not in doc['captions']['a'] and doc['style_bindings']['*']['parameters']['recipe_sha256']==rt.fingerprint(derived)


def test_undo_cannot_silently_clear_last_binding(cue_case,monkeypatch):
    q=bound_override(cue_case,monkeypatch,False)
    with pytest.raises(rt.ContractError,match='UNDO_EMPTY_DERIVED_RECIPE_UNSUPPORTED'):run(cue_case,q)
    assert not (cue_case[1]/'candidate.json').exists()


@pytest.mark.parametrize('reverse',[False,True])
def test_effective_undo_value_uses_final_candidate_not_field_order(cue_case,reverse):
    def edit(d):
        d['caption_style']['font_size']=14
        d['captions']['a']['style_override']={'font_size':18}
    helper.commit(cue_case,edit)
    q=undo_request(cue_case);q['fields'].append({'kind':'caption_style','field':'font_size'})
    if reverse:q['fields'].reverse()
    r=run(cue_case,q)
    local=next(v for v in r['fields'] if v['selection']['kind']=='caption_override')
    assert local['restored_effective_value']==12


@pytest.mark.parametrize('mutate',[
    lambda d:d.pop('plan'),lambda d:d['plan'].pop('height'),
    lambda d:d['plan'].update(height=True),lambda d:d['plan'].update(height=0),
])
def test_shared_invalid_canvas_does_not_strip_override(cue_case,mutate):
    base=state(cue_case[0])['document'];candidate=copy.deepcopy(base)
    candidate['captions']['a']['style_override']={'color_rgb':'FF0000'}
    mutate(base);mutate(candidate)
    assert not shared_timeline.compatible(base,candidate)


# Real generated-tone media plumbing; not real speech/semantic acceptance.
from test_shared_timeline_cache import case as shared_case
from test_shared_timeline_cache import base_case, tools, media


def test_local_override_shared_render_matches_unshared(shared_case):
    from test_shared_timeline_cache import test_two_candidates_share_once_and_match_unshared_decoded_output
    c=shared_case
    refs=[]
    for i,size in enumerate([14,16]):
        original=json.loads(__import__('pathlib').Path(c['candidates'][i]['path']).read_bytes())
        original['document']['caption_style']=copy.deepcopy(c['document']['caption_style'])
        original['document']['captions']['label']['style_override']={'font_size':size}
        original['scope']['caption_style']=False;original['scope']['caption_ids']=['label']
        path=c['root']/f'local-override-{i}.json';rt.write_json(path,original)
        refs.append({'path':str(path),'sha256':rt.sha256(path)})
    c['candidates']=refs
    test_two_candidates_share_once_and_match_unshared_decoded_output(c)
