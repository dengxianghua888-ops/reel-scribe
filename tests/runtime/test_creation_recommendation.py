"""Deterministic suggestions, not user preference or narrative validation."""
import copy,json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import editing_runtime as rt
import creation_recommendation_ops as mod
import work_ops
from test_result_preview import case as work_case

@pytest.fixture
def case(work_case):
    old,out,tools,doc=work_case
    doc=copy.deepcopy(doc);doc['plan'].update(width=960,height=540)
    doc['caption_style']['font_size']=24
    doc['captions']={'manual':{'clip_id':'full','start':0,'end':1,'text':'保留否定'}}
    store=out.parent/'recommend.sqlite';folder=out.parent/'init-recommend';folder.mkdir()
    state=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),'work_id':'recommend','document':doc,'author':'agent','message':'fixture'},folder,tools)
    q={'operation':'creation-recommendation','action':'recommend','store':str(store),'expected_version':state['version'],
       'brief':{'scene':'speech','goal':'readable-captions','constraints':{'min_font_size':16,'max_font_size':48,'freeze_content':True}},'capabilities':['caption-style']}
    return q,out,tools,old['tutorial']

def recommend(case):
    q,out,tools,_=case;r=mod.execute(q,out,tools)
    ref={'path':str(out/'recommendation.json'),'sha256':rt.sha256(out/'recommendation.json')}
    return r,ref

def selected(r):return [{'id':x['id'],'option_sha256':x['option_sha256']} for x in r['options'][:2]]

def test_ranking_explained_and_select_prepares_only(case):
    q,out,tools,_=case;r,ref=recommend(case)
    assert [x['recipe']['parameters']['caption_style']['font_size'] for x in r['options']]==[34,29,24]
    dest=out.parent/'select';dest.mkdir()
    result=mod.execute({'operation':'creation-recommendation','action':'select','recommendation':ref,'selections':selected(r)},dest,tools)
    assert result['prepared_request']['operation']=='style-recipe-preview'
    assert all(x['scope']['freeze_duration'] for x in result['prepared_request']['variants'])
    assert not result['executed'] and r['layout_safety']=='UNKNOWN'
    with work_ops.connect(q['store']) as db:assert work_ops.load(db)['version']==q['expected_version']

def test_preserve_prefers_current_size(case):
    q,_,_,_=case;q['brief']['goal']='preserve-original';r,_=recommend(case)
    assert r['options'][0]['recipe']['parameters']['caption_style']['font_size']==24

@pytest.mark.parametrize('mutate,code',[
 (lambda q:q.update(capabilities=[]),'CAPTION_STYLE_CAPABILITY_MISSING'),
 (lambda q:q['brief']['constraints'].update(min_font_size=90,max_font_size=100),'FONT_RANGE_CONFLICTS_WITH_CANVAS'),
 (lambda q:q['brief']['constraints'].update(min_font_size=24,max_font_size=24),'INSUFFICIENT_DISTINCT_COMPARISONS'),
 (lambda q:q['brief'].update(goal='narrative-impact'),'EDITORIAL_MECHANISM_NOT_EXECUTABLE'),
 (lambda q:q['brief'].update(goal='speech-tighten'),'SPEECH_BRIEF_PREPARATION_REQUIRED'),
])
def test_no_unsupported_execution(case,mutate,code):
    q,_,_,_=case;mutate(q);r,_=recommend(case)
    assert not r['options'] and code in [x['code'] for x in r['issues']]

def test_tutorial_recommend_select_existing_request(case):
    q,out,tools,tutorial=case;q['brief'].update(scene='software',goal='learn-steps')
    q['parameters']={'tutorial':tutorial};q['capabilities']=['tutorial-plan-compile']
    r,ref=recommend(case);dest=out.parent/'select';dest.mkdir()
    rr=mod.execute({'operation':'creation-recommendation','action':'select','recommendation':ref,'selections':selected(r)},dest,tools)
    assert rr['prepared_request']['operation']=='tutorial-plan-compile'
    assert rr['execution_guard']['require_fresh_head_read']
    import tutorial_ops
    compiled=out.parent/'compiled';compiled.mkdir()
    result=tutorial_ops.execute(rr['prepared_request'],compiled,tools)
    assert result['ui_fact_review']=='NOT_RUN'

def test_tampered_report_even_with_new_file_hash_rejected(case):
    _,out,tools,_=case;r,ref=recommend(case)
    r['options'][0]['recipe']['parameters']['caption_style']['font_size']=299
    Path(ref['path']).write_text(json.dumps(r));ref['sha256']=rt.sha256(ref['path'])
    dest=out.parent/'select';dest.mkdir()
    with pytest.raises(rt.ContractError,match='NOT_REPRODUCIBLE'):
        mod.execute({'operation':'creation-recommendation','action':'select','recommendation':ref,'selections':selected(r)},dest,tools)
    assert not (dest/'prepared-request.json').exists()

def test_false_recipe_feedback_rejected(case):
    _,out,tools,_=case;r,ref=recommend(case);dest=out.parent/'feedback';dest.mkdir()
    rating={**selected(r)[0],'option_sha256':'0'*64,'dimension':'occlusion','verdict':'avoid','reason':'example'}
    with pytest.raises(rt.ContractError,match='BINDING_MISMATCH'):
        mod.execute({'operation':'creation-recommendation','action':'feedback','recommendation':ref,'actor_kind':'user-reported','ratings':[rating]},dest,tools)
    assert not (dest/'feedback.json').exists()

def test_feedback_does_not_authenticate_user_or_learn(case):
    _,out,tools,_=case;r,ref=recommend(case);dest=out.parent/'feedback';dest.mkdir()
    rating={**selected(r)[0],'dimension':'readability','verdict':'prefer','reason':'attributed report, not authenticated'}
    result=mod.execute({'operation':'creation-recommendation','action':'feedback','recommendation':ref,'actor_kind':'user-reported','ratings':[rating]},dest,tools)
    assert not result['identity_verified'] and not result['ranking_updated'] and not result['adopted']

@pytest.mark.parametrize('action',['select','feedback'])
def test_stale_head_rejected(case,monkeypatch,action):
    q,out,tools,_=case;r,ref=recommend(case);original=mod._state
    def stale(store):
        v=original(store);v['version']='0'*64;return v
    monkeypatch.setattr(mod,'_state',stale);dest=out.parent/'stale';dest.mkdir()
    req={'operation':'creation-recommendation','action':action,'recommendation':ref}
    if action=='select':req['selections']=selected(r)
    else:req.update(actor_kind='agent-observation',ratings=[{**selected(r)[0],'dimension':'style-fit','verdict':'undecided','reason':'not watched'}])
    with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):mod.execute(req,dest,tools)

def test_duplicate_selection_rejected(case):
    _,out,tools,_=case;r,ref=recommend(case);dest=out.parent/'duplicates';dest.mkdir()
    with pytest.raises(rt.ContractError,match='DUPLICATE'):
        mod.execute({'operation':'creation-recommendation','action':'select','recommendation':ref,'selections':[selected(r)[0]]*2},dest,tools)


def test_card_mutates_after_reproduction_is_rechecked(case,monkeypatch):
    _,out,tools,_=case;r,ref=recommend(case)
    original=rt.source;calls=[]
    def changed(identity,*args,**kwargs):
        if identity['path']==r['card']['path']:
            calls.append(1)
            if len(calls)==3:raise rt.ContractError('SOURCE_HASH_MISMATCH: card changed before publication')
        return original(identity,*args,**kwargs)
    monkeypatch.setattr(rt,'source',changed);dest=out.parent/'race';dest.mkdir()
    with pytest.raises(rt.ContractError,match='SOURCE_HASH_MISMATCH'):
        mod.execute({'operation':'creation-recommendation','action':'select','recommendation':ref,'selections':selected(r)},dest,tools)
    assert not (dest/'prepared-request.json').exists()


def test_tutorial_capability_missing(case):
    q,_,_,tutorial=case;q['brief'].update(scene='software',goal='learn-steps');q['parameters']={'tutorial':tutorial}
    r,_=recommend(case)
    assert not r['options'] and 'TUTORIAL_CAPABILITY_MISSING' in [x['code'] for x in r['issues']]


def test_report_unknown_added_field_rejected(case):
    _,out,tools,_=case;r,ref=recommend(case)
    r['approved_by_user']=True;Path(ref['path']).write_text(json.dumps(r));ref['sha256']=rt.sha256(ref['path'])
    dest=out.parent/'forged';dest.mkdir()
    with pytest.raises(rt.ContractError,match='NOT_REPRODUCIBLE'):
        mod.execute({'operation':'creation-recommendation','action':'select','recommendation':ref,'selections':selected(r)},dest,tools)
