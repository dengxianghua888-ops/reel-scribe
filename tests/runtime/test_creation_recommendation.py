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


def refinement(case,problem='too-small',dimension='readability',verdict='avoid'):
    _,out,tools,_=case;r,ref=recommend(case)
    item=r['options'][1]
    rating={'id':item['id'],'option_sha256':item['option_sha256'],'dimension':dimension,'verdict':verdict,'reason':'Explicit finite observation'}
    folder=out.parent/'feedback';folder.mkdir()
    mod.execute({'operation':'creation-recommendation','action':'feedback','recommendation':ref,'actor_kind':'agent-observation','ratings':[rating]},folder,tools)
    evidence=out.parent/'frame.txt';evidence.write_text('test evidence, not real rendered image')
    q={'operation':'creation-recommendation','action':'refine','recommendation':ref,'feedback':{'path':str(folder/'feedback.json'),'sha256':rt.sha256(folder/'feedback.json')},
       'observations':[{'id':item['id'],'evidence':{'path':str(evidence),'sha256':rt.sha256(evidence)},'statement':'Explicit attributed observation only','problem':problem}]}
    dest=out.parent/'refine';dest.mkdir()
    return q,dest,tools

@pytest.mark.parametrize('problem,dimension,verdict,sizes',[
 ('too-small','readability','avoid',[33,29]),
 ('too-large','readability','avoid',[25,29]),
 ('occludes-ui','occlusion','avoid',[25,29]),
 ('prefer-current','style-fit','prefer',[29,25,33]),
])
def test_refine_explicit_problem_and_select(case,problem,dimension,verdict,sizes):
    q,out,tools=refinement(case,problem,dimension,verdict);r=mod.execute(q,out,tools)
    assert [x['recipe']['parameters']['caption_style']['font_size'] for x in r['options']]==sizes
    dest=out.parent/'refine-select';dest.mkdir()
    result=mod.execute({'operation':'creation-recommendation','action':'select','recommendation':{'path':str(out/'recommendation.json'),'sha256':rt.sha256(out/'recommendation.json')},'selections':selected(r)},dest,tools)
    assert result['prepared_request']['operation']=='style-recipe-preview'
    assert not result['committed'] and not r['refinement']['identity_verified']
    assert all(x['scope']['freeze_duration'] for x in result['prepared_request']['variants'])

@pytest.mark.parametrize('problem,dimension,verdict',[
 ('unknown','readability','avoid'),('too-small','occlusion','avoid'),('prefer-current','style-fit','undecided')])
def test_refine_ambiguous_no_options(case,problem,dimension,verdict):
    q,out,tools=refinement(case,problem,dimension,verdict);r=mod.execute(q,out,tools)
    assert not r['options'] and r['issues'][0]['code']=='FEEDBACK_AMBIGUOUS_OR_UNSUPPORTED'

@pytest.mark.parametrize('target',['feedback','evidence'])
def test_refine_changed_input_bytes_rejected(case,target):
    q,out,tools=refinement(case)
    ref=q['feedback'] if target=='feedback' else q['observations'][0]['evidence']
    Path(ref['path']).write_text('{}')
    with pytest.raises(rt.ContractError):mod.execute(q,out,tools)
    assert not (out/'recommendation.json').exists()

def test_refine_feedback_wrong_option_even_rehashed(case):
    q,out,tools=refinement(case);path=Path(q['feedback']['path']);doc=json.loads(path.read_text());doc['ratings'][0]['option_sha256']='0'*64
    path.write_text(json.dumps(doc));q['feedback']['sha256']=rt.sha256(path)
    with pytest.raises(rt.ContractError,match='RECIPE_BINDING'):mod.execute(q,out,tools)

def test_refine_stale_and_no_writes(case,monkeypatch):
    q,out,tools=refinement(case);original=mod._state
    def stale(store):
        result=original(store);result['version']='stale';return result
    monkeypatch.setattr(mod,'_state',stale)
    with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):mod.execute(q,out,tools)
    assert not (out/'recommendation.json').exists()

def test_refine_bound_never_relaxed(case):
    case[0]['brief']['constraints']['max_font_size']=29
    q,out,tools=refinement(case)
    # Select largest constrained anchor and request growth.
    report=json.loads(Path(q['recommendation']['path']).read_text());item=report['options'][0]
    path=Path(q['feedback']['path']);feedback=json.loads(path.read_text());feedback['ratings'][0].update(id=item['id'],option_sha256=item['option_sha256'])
    path.write_text(json.dumps(feedback));q['feedback']['sha256']=rt.sha256(path);q['observations'][0]['id']=item['id']
    result=mod.execute(q,out,tools)
    assert not result['options'] and result['issues'][0]['code']=='REFINEMENT_BOUND_REACHED'

def test_refine_second_round_rejected(case):
    q,out,tools=refinement(case);r=mod.execute(q,out,tools)
    q['recommendation']={'path':str(out/'recommendation.json'),'sha256':rt.sha256(out/'recommendation.json')}
    dest=out.parent/'round2';dest.mkdir()
    with pytest.raises(rt.ContractError,match='DEPTH_EXCEEDED'):mod.execute(q,dest,tools)

def test_refine_conflicting_direction_no_options(case):
    q,out,tools=refinement(case)
    report=json.loads(Path(q['recommendation']['path']).read_text());item=report['options'][0]
    path=Path(q['feedback']['path']);feedback=json.loads(path.read_text());feedback['ratings'].append({'id':item['id'],'option_sha256':item['option_sha256'],'dimension':'occlusion','verdict':'avoid','reason':'Different direction'})
    path.write_text(json.dumps(feedback));q['feedback']['sha256']=rt.sha256(path)
    observation=copy.deepcopy(q['observations'][0]);observation.update(id=item['id'],problem='occludes-ui');q['observations'].append(observation)
    assert not mod.execute(q,out,tools)['options']

def test_refine_final_evidence_recheck(case,monkeypatch):
    q,out,tools=refinement(case);original=mod._refine
    def mutate(request):
        result=original(request);Path(q['observations'][0]['evidence']['path']).write_text('changed after calculation');return result
    monkeypatch.setattr(mod,'_refine',mutate)
    with pytest.raises(rt.ContractError):mod.execute(q,out,tools)
    assert not (out/'recommendation.json').exists()
