"""Brief preparation contract; never claims semantic parsing or media rendering."""
import copy
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import creation_brief_ops as mod
import editing_runtime as rt
import work_ops
from test_result_preview import case as work_case

@pytest.fixture
def case(work_case):
    q,out,tools,doc=work_case
    query='只检查这个软件教程的步骤，不要改内容。'
    p={k:{'kind':'query','start':0,'end':len(query),'quote':query} for k in ['scene','mode','intent','parameters']}
    request={'operation':'creation-brief-prepare','query':query,'brief':{'scene':'software','mode':'REVISION','intent':'tutorial-plan-validation','provenance':p},'store':q['store'],'expected_version':q['expected_version'],'parameters':copy.deepcopy(q['tutorial'])}
    return request,out,tools,doc

def test_prepares_current_plan_without_execution(case):
    q,out,tools,doc=case
    result=mod.execute(q,out,tools)
    draft=json.loads((out/'prepared-request.json').read_text())
    assert draft['operation']=='tutorial-plan-compile' and draft['plan']==doc['plan']
    assert result['status']=='READY_FOR_DOWNSTREAM_VALIDATION' and not result['executed']
    assert result['execution_guard']['require_fresh_work_read_before_execution']
    with work_ops.connect(q['store']) as db:assert work_ops.load(db)['version']==q['expected_version']

@pytest.mark.parametrize('mode',['PLAN','ANALYZE'])
def test_plan_draft_only(case,mode):
    q,out,tools,_=case;q['brief']['mode']=mode
    report=mod.execute(q,out,tools)
    assert report['status']=='PLANNING_ONLY' and report['draft_request']
    assert not (out/'prepared-request.json').exists()

@pytest.mark.parametrize('intent,params,code',[
 ('caption-presentation',{},'CAPTION_VARIANTS_REQUIRED'),
 ('tutorial-plan-validation',{},'TUTORIAL_EXPLICIT_EVENTS_REQUIRED'),
 ('speech-tighten',{},'REVIEWED_WORD_ALIGNMENT_REQUIRED'),
 ('narrative-edit',{},'EDITORIAL_DECISION_REQUIRED'),
])
def test_missing_inputs_not_fabricated(case,intent,params,code):
    q,out,tools,_=case;q['brief']['intent']=intent;q['parameters']=params
    report=mod.execute(q,out,tools)
    assert report['status']=='BLOCKED' and report['issues'][0]['code']==code
    assert not (out/'prepared-request.json').exists()

@pytest.mark.parametrize('mutate,error',[
 (lambda q:q.update(expected_version='0'*64),'WORK_VERSION_CONFLICT'),
 (lambda q:q['brief']['provenance']['intent'].update(quote='different'),'QUERY_SLICE_MISMATCH'),
 (lambda q:q['brief']['provenance']['intent'].update(start=True),'QUERY_SLICE_MISMATCH'),
 (lambda q:q['brief'].update(scene='film'),'TUTORIAL_SCENE_REQUIRED'),
 (lambda q:q['brief'].update(mode='AUTO'),'MODE_UNSUPPORTED'),
])
def test_invalid_brief_fails(case,mutate,error):
    q,out,tools,_=case;mutate(q)
    with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
    assert not (out/'prepared-request.json').exists()

def test_context_is_not_user_confirmation(case):
    q,out,tools,_=case
    q['brief']['provenance']['scene']={'kind':'context','description':'Agent observed existing Work category'}
    r=mod.execute(q,out,tools)
    assert r['brief']['provenance']['scene']['kind']=='context'
    assert 'not semantic interpretation or authorization' in r['provenance_semantics']

def caption_case(case):
    q,out,tools,doc=case
    doc=copy.deepcopy(doc);doc['captions']={'old':{'clip_id':'full','start':0,'end':1,'text':'不要删除'}}
    init=out.parent/'caption-init';init.mkdir();store=out.parent/'caption.sqlite'
    state=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),'work_id':'cap','document':doc,'author':'agent','message':'fixture'},init,tools)
    q['store']=str(store);q['expected_version']=state['version'];q['brief']['intent']='caption-presentation'
    card=Path(__file__).resolve().parents[2]/'styles/speech/faithful-clean.md'
    scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],'style_keys':['*'],'note_keys':[],'output_fields':[],'caption_style':True,'freeze_positions':['full'],'freeze_duration':True}
    variants=[]
    for i in [12,14]:
        recipe={'schema':'style-recipe/1','id':str(i),'version':'1','style':{'family':'speech','style_id':'faithful-clean','version':'0.1.0','card':{'path':str(card),'sha256':rt.sha256(card)}},'parameters':{'caption_style':{'font_size':i}}}
        variants.append({'id':str(i),'recipe':recipe,'expected_recipe_sha256':rt.fingerprint(recipe),'capabilities':['caption-style'],'scope':copy.deepcopy(scope)})
    q['parameters']={'variants':variants}
    return q,out,tools

def test_caption_only_prepares_existing_operation(case):
    q,out,tools=caption_case(case);r=mod.execute(q,out,tools)
    assert r['draft_request']['operation']=='style-recipe-preview'
    assert r['draft_request']['expected_version']==q['expected_version']
    assert not list(out.glob('*.mp4'))

@pytest.mark.parametrize('mutation,error',[
 (lambda v:v['scope']['clip_ids'].append('full'),'SCOPE_TOO_BROAD'),
 (lambda v:v['scope']['caption_ids'].append('old'),'SCOPE_TOO_BROAD'),
 (lambda v:v['scope'].update(freeze_positions=[]),'POSITIONS_NOT_FROZEN'),
 (lambda v:v['capabilities'].append('audio-track-gain'),'CAPTION_ONLY_CAPABILITY'),
])
def test_caption_cannot_broaden_edit(case,mutation,error):
    q,out,tools=caption_case(case);mutation(q['parameters']['variants'][0])
    with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
    assert not (out/'prepared-request.json').exists()

def test_race_before_publication(case,monkeypatch):
    q,out,tools,_=case;orig=work_ops.load;calls=[]
    def changed(db):
        r=orig(db);calls.append(1)
        if len(calls)>1:r['version']='0'*64
        return r
    monkeypatch.setattr(work_ops,'load',changed)
    with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):mod.execute(q,out,tools)
    assert not (out/'prepared-request.json').exists()

def test_dispatch_without_media_tool_calls(case):
    q,out,_,_=case
    class NoMedia:
        def probe(self,*a):raise AssertionError('preparation must not probe or render')
        def ff(self,*a,**k):raise AssertionError('preparation must not render')
    report=rt.execute(q,out,NoMedia())
    assert report['status']=='READY_FOR_DOWNSTREAM_VALIDATION'


def test_no_caption_data_is_gap_not_asr(case):
    q,out,tools,_=case
    q['brief']['intent']='caption-presentation';q['parameters']={'variants':[{},{}]}
    report=mod.execute(q,out,tools)
    assert report['issues'][0]['code']=='EXISTING_CAPTIONS_AND_FONT_REQUIRED'
    assert not (out/'prepared-request.json').exists()
