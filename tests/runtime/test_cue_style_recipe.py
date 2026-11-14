"""Cue recipe scope/identity tests; synthetic media, not visual acceptance."""
import copy,json
import pytest
from test_style_recipe import case
import editing_runtime as rt
import style_recipe_ops as mod

def local(case):
 q,out,work,owner=case
 q['document']['style_bindings']={}
 q['document']['captions']['cue'].update(end=.5)
 q['document']['captions']['untargeted']=copy.deepcopy(q['document']['captions']['cue'])
 q['document']['captions']['untargeted'].update(start=.5,end=1)
 q['recipe']['parameters']={'caption_overrides':{'cue':{'font_size':28}}}
 q['capabilities']=['caption-cue-style'];q['scope'].update(caption_ids=['cue'],caption_style=False)
 sync(q);return q,out,work['tools']

def sync(q):
 q['expected_document_sha256']=rt.fingerprint(q['document']);q['expected_recipe_sha256']=rt.fingerprint(q['recipe'])

def run(case):
 q,out,owner=local(case);return q,out,owner

def test_only_explicit_cue_changed(case):
 q,out,owner=local(case);before=copy.deepcopy(q['document']);r=mod.execute(q,out,owner)
 d=json.loads((out/'candidate.json').read_bytes())['document'];assert d['captions']['untargeted']==before['captions']['untargeted'];assert d['caption_style']==before['caption_style'];assert d['captions']['cue']['style_override']=={'font_size':28};assert r['caption_target_ids']==['cue']

@pytest.mark.parametrize('change,match',[
 (lambda q:q['scope'].update(caption_ids=[]),'SCOPE_REQUIRED'),
 (lambda q:q['scope'].update(caption_ids=['cue','untargeted']),'SCOPE_REQUIRED'),
 (lambda q:q['scope'].update(caption_style=True),'GLOBAL_SCOPE_FORBIDDEN'),
 (lambda q:q.update(capabilities=['caption-style']),'CAPABILITY_UNAVAILABLE'),
 (lambda q:q['recipe']['parameters']['caption_overrides'].update(missing={'font_size':20}),'TARGET_UNKNOWN'),
 (lambda q:q['recipe']['parameters']['caption_overrides']['cue'].update(font_size=True),'FONT_SIZE'),
 (lambda q:q['recipe']['parameters'].update(caption_style={'font_size':30}),'GLOBAL_CHANGE_FORBIDDEN'),
])
def test_local_refuses_unsafe(case,change,match):
 q,out,owner=local(case);change(q);sync(q)
 with pytest.raises(ValueError,match=match):mod.execute(q,out,owner)
 assert not (out/'candidate.json').exists()

def bound(q):
 prior={'caption_style':{'font_size':20},'caption_overrides':{'untargeted':{'color_rgb':'FF0000'}}}
 q['document']['captions']['untargeted']['style_override']={'color_rgb':'FF0000'}
 q['document']['style_bindings']={'*':{**copy.deepcopy(q['recipe']['style']),'parameters':{'recipe_id':'old','recipe_version':'1','recipe_sha256':'a'*64,'presentation':copy.deepcopy(prior)}}}
 q['recipe']['parameters'].update(copy.deepcopy(prior));q['recipe']['parameters']['caption_overrides']['cue']={'font_size':28};sync(q)

def test_old_mapping_preserved(case):
 q,out,owner=local(case);bound(q);mod.execute(q,out,owner)
 d=json.loads((out/'candidate.json').read_bytes())['document'];assert d['style_bindings']['*']['parameters']['presentation']==q['recipe']['parameters'];assert d['captions']['untargeted']==q['document']['captions']['untargeted']

@pytest.mark.parametrize('change,match',[
 (lambda q:q['recipe']['parameters'].pop('caption_style'),'PARAMETERS_DROPPED'),
 (lambda q:q['document']['caption_style'].update(font_size=21),'GLOBAL_CHANGE_FORBIDDEN|BINDING_DIVERGED'),
 (lambda q:q['recipe']['parameters']['caption_overrides'].pop('untargeted'),'PARAMETERS_DROPPED'),
 (lambda q:q['document']['style_bindings']['*']['parameters'].update(layout_constraints={'original':True}),'CONSTRAINTS_MUST_PERSIST'),
])
def test_no_silent_binding_drop(case,change,match):
 q,out,owner=local(case);bound(q);change(q);sync(q)
 with pytest.raises(ValueError,match=match):mod.execute(q,out,owner)
 assert not (out/'candidate.json').exists()

def test_whole_candidate_sent_to_layout_check(case,monkeypatch):
 import caption_layout
 q,out,owner=local(case);q['recipe']['layout_constraints']={'fixture':'declared'};sync(q);seen=[]
 def check(doc,constraints,directory,tools):
  seen.append(copy.deepcopy(doc));return {'status':'FIXTURE_ONLY_NOT_REAL_LAYOUT'}
 monkeypatch.setattr(caption_layout,'check',check);mod.execute(q,out,owner)
 assert len(seen)==1 and set(seen[0]['captions'])=={'cue','untargeted'}
 assert seen[0]['captions']['cue']['style_override']=={'font_size':28}
 assert 'style_override' not in seen[0]['captions']['untargeted']

def test_layout_failure_publishes_no_candidate(case,monkeypatch):
 import caption_layout
 q,out,owner=local(case);q['recipe']['layout_constraints']={'fixture':'declared'};sync(q)
 def fail(*args):raise rt.ContractError('LAYOUT_GLYPHS_OUTSIDE_DECLARED_BAND')
 monkeypatch.setattr(caption_layout,'check',fail)
 with pytest.raises(ValueError,match='LAYOUT_GLYPHS'):mod.execute(q,out,owner)
 assert not (out/'candidate.json').exists()

def test_global_replacement_cannot_erase_existing_cue_binding(case):
 q,out,owner=local(case);bound(q);q['recipe']['parameters'].pop('caption_overrides');q['scope'].update(caption_ids=[],caption_style=True);q['capabilities']=['caption-style'];sync(q)
 with pytest.raises(ValueError,match='OVERRIDES_MUST_PERSIST'):mod.execute(q,out,owner)
