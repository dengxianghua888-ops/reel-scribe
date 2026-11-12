"""Reference preparation contracts, synthetic observation declarations, not style QA."""
import copy
from pathlib import Path
import sys
import pytest
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'runtime'),str(Path(__file__).resolve().parent)]
from test_creation_brief import case,work_case,caption_case
import reference_transfer_ops as mod
import editing_runtime as rt
import work_ops

@pytest.fixture
def reference(case):
 q,out,tools=caption_case(case)
 with work_ops.connect(q['store']) as db:doc=work_ops.load(db)['document']
 ref=doc['plan']['sources']['s']
 request={'operation':'reference-transfer-prepare','scene':'speech','store':q['store'],'expected_version':q['expected_version'],
 'reference':ref,'items':[{'id':'caption','axis':'audiovisual','mechanism':'caption-presentation',
 'decision':'adapt','reason':'Explicitly choose readable subtitle presentation, not whole style.',
 'observation':{'status':'observed','start':0,'end':1,'method':'visual-review','evidence':ref,'description':'Synthetic declared visual observation; not watched media'},
 'parameters':q['parameters']}]}
 return request,out,tools,doc

def test_prepare_preserves_work_and_binds_recipe(reference):
 q,out,tools,doc=reference;r=mod.execute(q,out,tools)
 assert r['status']=='READY_FOR_DOWNSTREAM_VALIDATION'
 assert r['draft_request']['operation']=='style-recipe-preview'
 assert r['draft_request']['variants']==q['items'][0]['parameters']['variants']
 assert r['draft_request']['expected_version']==q['expected_version']
 assert not r['executed'] and not r['committed'] and not r['reference_media_in_output']
 assert r['style_validation']=='NOT_PERFORMED' and r['downstream_validation']=='NOT_RUN'
 with work_ops.connect(q['store']) as db:s=work_ops.load(db)
 assert s['document']==doc and s['version']==q['expected_version']

@pytest.mark.parametrize('mutate,error',[
 (lambda q:q['items'][0].update(observation={'status':'unobserved'}),'UNOBSERVED_TRANSFER_FORBIDDEN'),
 (lambda q:q['items'][0].update(axis='narrative'),'MECHANISM_UNSUPPORTED'),
 (lambda q:q['items'][0].update(mechanism='music-transfer'),'MECHANISM_UNSUPPORTED'),
 (lambda q:q['items'][0]['observation'].update(method='listening-review'),'OBSERVATION_METHOD_REQUIRED'),
 (lambda q:q['items'][0]['observation'].update(end=2),'SOURCE_RANGE_INVALID'),
 (lambda q:q['items'][0]['parameters']['variants'][0]['recipe']['parameters']['caption_style'].update(font_size=99),'RECIPE_REVISION_CONFLICT'),
 (lambda q:q['items'][0]['parameters']['variants'][0]['scope']['clip_ids'].append('full'),'SCOPE_TOO_BROAD'),
 (lambda q:q.update(expected_version='0'*64),'WORK_VERSION_CONFLICT'),
 (lambda q:q['reference'].update(sha256='0'*64),'SOURCE_HASH_MISMATCH'),
 (lambda q:q['items'].append(copy.deepcopy(q['items'][0])),'ITEM_ID_INVALID'),
])
def test_rejects_unsafe_preparation(reference,mutate,error):
 q,out,tools,_=reference;mutate(q)
 with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
 assert not (out/'prepared-request.json').exists()

def test_unobserved_narrative_omission_keeps_explicit_gap(reference):
 q,out,tools,_=reference;q['items']=[{'id':'narrative','axis':'narrative','mechanism':'result-first','decision':'omit',
 'reason':'Not observed; do not infer causality.','observation':{'status':'unobserved'},'parameters':{}}]
 r=mod.execute(q,out,tools)
 assert r['status']=='NO_TRANSFER_SELECTED' and r['items']==q['items'] and r['draft_request'] is None
 assert not (out/'prepared-request.json').exists()

def test_reference_changed_after_probe(reference,monkeypatch):
 q,out,tools,_=reference;orig=tools.probe
 def changed(path):
  result=orig(path);Path(path).write_bytes(b'changed');return result
 monkeypatch.setattr(tools,'probe',changed)
 with pytest.raises(rt.ContractError,match='SOURCE_HASH_MISMATCH'):mod.execute(q,out,tools)
 assert not (out/'prepared-request.json').exists()

def test_final_work_race(reference,monkeypatch):
 q,out,tools,_=reference;orig=work_ops.load;calls=[]
 def changed(db):
  result=orig(db);calls.append(1)
  if len(calls)>=4:result['version']='0'*64
  return result
 monkeypatch.setattr(work_ops,'load',changed)
 with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):mod.execute(q,out,tools)
 assert not (out/'prepared-request.json').exists()

def test_two_selected_mechanisms_are_not_implicitly_composed(reference):
 q,out,tools,_=reference;other=copy.deepcopy(q['items'][0]);other['id']='another';q['items'].append(other)
 with pytest.raises(rt.ContractError,match='MULTIPLE_TRANSFERS_UNSUPPORTED'):mod.execute(q,out,tools)
 assert not (out/'prepared-request.json').exists()

def test_omitted_parameters_cannot_smuggle_execution(reference):
 q,out,tools,_=reference;q['items'][0]['decision']='omit'
 with pytest.raises(rt.ContractError,match='OMITTED_PARAMETERS_FORBIDDEN'):mod.execute(q,out,tools)


def test_omitted_narrative_and_adopt_caption_axes_stay_separate(reference):
 q,out,tools,_=reference;q['items'][0]['decision']='adopt'
 q['items'].append({'id':'story','axis':'narrative','mechanism':'result-first','decision':'omit','reason':'No target narrative inference',
 'observation':{'status':'unobserved'},'parameters':{}})
 r=mod.execute(q,out,tools)
 assert r['draft_request']['operation']=='style-recipe-preview'
 assert len(r['items'])==2 and r['narrative_transfer']=='NOT_SUPPORTED'
 assert 'reference' not in r['draft_request']


@pytest.mark.parametrize('scene',['speech','film','software'])
def test_explicit_scene_preserved(reference,scene):
 q,out,tools,_=reference;q['scene']=scene
 r=mod.execute(q,out,tools)
 assert r['scene']==scene


def test_changed_card_does_not_publish(reference,monkeypatch):
 q,out,tools,_=reference
 q['items'][0]['parameters']['variants'][0]['recipe']['style']['card']['sha256']='0'*64
 recipe=q['items'][0]['parameters']['variants'][0]
 recipe['expected_recipe_sha256']=rt.fingerprint(recipe['recipe'])
 with pytest.raises(rt.ContractError,match='SOURCE_HASH_MISMATCH'):mod.execute(q,out,tools)
 assert not (out/'prepared-request.json').exists() and not (out/'reference-transfer.json').exists()
