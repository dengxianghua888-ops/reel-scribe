"""Cross-operation contract checks. Synthetic clocks are not real-media acceptance."""
import copy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import editing_runtime as rt
import work_ops
import creation_brief_ops as brief
import style_recipe_ops
import style_preview_ops
from test_creation_brief import case
from test_result_preview import case as work_case


def state(q):
    with work_ops.connect(q['store']) as db:return work_ops.load(db)


def test_prepared_tutorial_runs_readonly_same_plan(case):
    q,out,tools,doc=case; before=state(q)
    r=brief.execute(q,out,tools);request=json.loads((out/'prepared-request.json').read_bytes())
    assert rt.fingerprint(request)==r['prepared_request_sha256']
    assert state(q)['version']==r['execution_guard']['expected_version']
    target=out/'downstream';target.mkdir();result=rt.execute(request,target,tools)
    assert result and state(q)==before and request['plan']==doc['plan']


def test_caption_brief_compiles_real_downstream_candidates_without_commit(case,tmp_path):
    q,out,tools,doc=case
    doc=copy.deepcopy(doc);doc['captions']={'one':{'clip_id':'full','start':0,'end':.8,'text':'fixture'}}
    store=tmp_path/'caption.sqlite';init=tmp_path/'caption-init';init.mkdir()
    initial=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),'work_id':'caption','document':doc,'author':'agent','message':'fixture'},init,tools)
    q['store']=str(store);q['expected_version']=initial['version'];q['brief']['scene']='speech';q['brief']['intent']='caption-presentation'
    card=tmp_path/'card.md';card.write_text('Explicit synthetic card')
    scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],'style_keys':['*'],'note_keys':[],'output_fields':[],'caption_style':True,'freeze_positions':['full'],'freeze_duration':True}
    variants=[]
    for i,size in enumerate([10,14]):
        recipe={'schema':'style-recipe/1','id':str(i),'version':'1','style':{'family':'fixture','style_id':'test','version':'1','card':{'path':str(card),'sha256':rt.sha256(card)}},'parameters':{'caption_style':{'font_size':size}}}
        variants.append({'id':'v'+str(i),'recipe':recipe,'expected_recipe_sha256':rt.fingerprint(recipe),'capabilities':['caption-style'],'scope':copy.deepcopy(scope)})
    q['parameters']={'variants':variants};before=state(q)
    r=brief.execute(q,out,tools);request=json.loads((out/'prepared-request.json').read_bytes())
    assert request['operation']=='style-recipe-preview' and r['status']=='READY_FOR_DOWNSTREAM_VALIDATION'
    for v in request['variants']:
        target=out/v['id'];target.mkdir()
        cq={'operation':'style-recipe-compile','document':doc,'expected_document_sha256':before['document_sha256'],'base_version':before['version'],**{k:v[k] for k in ['recipe','expected_recipe_sha256','scope','capabilities']}}
        style_recipe_ops.execute(cq,target,tools)
        candidate=json.loads((target/'candidate.json').read_bytes())['document']
        assert candidate['plan']==doc['plan'] and candidate['captions']==doc['captions']
    assert state(q)==before
    request['expected_version']='0'*64;reject=out/'reject';reject.mkdir()
    with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):style_preview_ops.execute(request,reject,tools)


def test_prepared_plan_not_authority_after_work_moves(case):
    q,out,tools,_=case;r=brief.execute(q,out,tools)
    # A consumer must compare fresh Work head, not regard tutorial-plan success as CAS.
    assert r['execution_guard']['require_fresh_work_read_before_execution']
    stale=copy.deepcopy(q);stale['expected_version']='0'*64;target=out/'stale';target.mkdir()
    with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):brief.execute(stale,target,tools)
    assert not (target/'prepared-request.json').exists()
