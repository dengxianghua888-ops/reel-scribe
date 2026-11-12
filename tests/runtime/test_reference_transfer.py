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

@pytest.fixture
def narrative(work_case):
 q,out,tools,doc=work_case
 ref=copy.deepcopy(doc['plan']['sources']['s'])
 event=lambda role,a,b:{'role':role,'start':a,'end':b,'evidence':ref,'description':'Synthetic declared sequence, not real observation'}
 item={'id':'order','axis':'narrative','mechanism':'result-first','decision':'adapt','reason':'Explicit target preview, not target causality',
 'observation':{'status':'observed','start':0,'end':1,'method':'visual-review','evidence':ref,'description':'Synthetic two-window declaration',
 'sequence':[event('result-preview',0,.2),event('process',.3,.8)],'unknowns':['No listening or semantic certification']},
 'parameters':{k:copy.deepcopy(q[k]) for k in ['mechanism_card','tutorial','preview','shift_clip_ids','scope']}}
 return {'operation':'reference-transfer-prepare','scene':'software','store':q['store'],'expected_version':q['expected_version'],'reference':ref,'items':[item]},out,tools,doc


def test_result_first_uses_existing_compiler_without_publishing_candidate(narrative):
 q,out,tools,doc=narrative;r=mod.execute(q,out,tools)
 assert r['draft_request']['operation']=='result-preview-compile'
 assert r['executed'] and r['execution_kind']=='TEMPORARY_COMPILER_VALIDATION_ONLY'
 assert not r['rendered'] and not r['applied_to_work']
 assert r['temporary_compiler_result']['preserved_clip_ids']==['full']
 assert not (out/'candidate.json').exists()
 with work_ops.connect(q['store']) as db:state=work_ops.load(db)
 assert state['document']==doc and state['version']==q['expected_version']

@pytest.mark.parametrize('mutate,error',[
 (lambda q:q.update(scene='film'),'ADAPT_SOFTWARE_ONLY'),
 (lambda q:q['items'][0].update(decision='adopt'),'ADAPT_SOFTWARE_ONLY'),
 (lambda q:q['items'][0]['observation'].pop('sequence'),'ORDER_OBSERVATIONS_REQUIRED'),
 (lambda q:q['items'][0]['observation']['sequence'].pop(),'ORDER_OBSERVATIONS_REQUIRED'),
 (lambda q:q['items'][0]['observation']['sequence'][0].update(end=0),'SOURCE_RANGE_INVALID'),
 (lambda q:q['items'][0]['observation']['sequence'][1].update(start=.1),'ORDER_INTERVALS_INVALID'),
 (lambda q:q['items'][0]['observation']['sequence'][0].update(role='process'),'RESULT_BEFORE_PROCESS_REQUIRED'),
 (lambda q:q['items'][0]['observation'].pop('unknowns'),'UNKNOWNS_REQUIRED'),
 (lambda q:q['items'][0]['parameters']['preview'].update(label='操作成功'),'VISIBLE_LABEL_REQUIRED'),
 (lambda q:q['items'][0]['parameters']['preview'].update(start=.4),'OUTSIDE_RESULT'),
 (lambda q:q['items'][0]['parameters'].update(shift_clip_ids=[]),'EXPLICIT_SHIFT_REQUIRED'),
 (lambda q:q['items'][0]['parameters']['scope'].update(freeze_duration=True),'WORK_DURATION_FROZEN'),
])
def test_result_first_rejects_invalid_sequence_or_target(narrative,mutate,error):
 q,out,tools,_=narrative;mutate(q)
 with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
 assert not (out/'prepared-request.json').exists() and not (out/'candidate.json').exists()


def test_result_first_preserves_persistent_protection(narrative,work_case):
 from test_result_preview import protected_case
 doc=protected_case(work_case)
 q,out,tools,_=narrative;q['expected_version']=work_case[0]['expected_version'];q['store']=work_case[0]['store']
 q['items'][0]['parameters']['scope']['evidence_mapping']=True
 r=mod.execute(q,out,tools)
 assert r['temporary_compiler_result']['protection_shift']['original_carriers_preserved']
 with work_ops.connect(q['store']) as db:assert work_ops.load(db)['document']==doc


def test_result_first_cannot_disable_protection(narrative,work_case):
 from test_result_preview import protected_case
 protected_case(work_case)
 q,out,tools,_=narrative;q['expected_version']=work_case[0]['expected_version'];q['store']=work_case[0]['store']
 with pytest.raises(rt.ContractError,match='PROTECTION_SHIFT_SCOPE_REQUIRED'):mod.execute(q,out,tools)
 assert not (out/'prepared-request.json').exists()


def test_result_first_reference_change_after_compile_no_publication(narrative,monkeypatch):
 import result_preview_ops
 q,out,tools,_=narrative;original=result_preview_ops.execute
 def changed(*a,**k):
  result=original(*a,**k);Path(q['reference']['path']).write_bytes(b'changed');return result
 monkeypatch.setattr(result_preview_ops,'execute',changed)
 with pytest.raises(rt.ContractError,match='SOURCE_HASH_MISMATCH'):mod.execute(q,out,tools)
 assert list(out.iterdir())==[]


def test_result_first_final_head_change_no_publication(narrative,monkeypatch):
 import result_preview_ops
 q,out,tools,_=narrative;original=result_preview_ops.execute;load=work_ops.load;armed=[]
 def compiled(*a,**k):
  result=original(*a,**k);armed.append(True);return result
 def stale(db):
  state=load(db)
  if armed:state['version']='0'*64
  return state
 monkeypatch.setattr(result_preview_ops,'execute',compiled);monkeypatch.setattr(work_ops,'load',stale)
 with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):mod.execute(q,out,tools)
 assert list(out.iterdir())==[]
