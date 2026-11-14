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


@pytest.fixture
def speech_integration(case):
    """Real media plumbing with synthetic tone and declared fixture word clocks."""
    import shutil
    import subprocess
    from test_creation_brief import speech_case, replace_speech_work
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/ffprobe unavailable')
    q,out,_,doc=speech_case(case)
    media=out.parent/'integration-tone.mov'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=64x64:r=25:d=1',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1',
        '-c:v','libx264','-pix_fmt','yuv420p','-c:a','pcm_s16le',str(media)],check=True)
    tools=rt.Tools();doc=copy.deepcopy(doc)
    ref={'path':str(media),'sha256':rt.sha256(media)}
    doc['plan']['sources']['s']=ref
    doc['captions']={'manual':{'clip_id':'full','start':0,'end':1,'text':'保留不能'}}
    replace_speech_work(case,q,doc,tools)
    path=Path(q['parameters']['aligned_transcript']['path'])
    transcript=json.loads(path.read_bytes());transcript['source']=ref
    path.write_text(json.dumps(transcript,ensure_ascii=False))
    q['parameters']['aligned_transcript']['sha256']=rt.sha256(path)
    q['parameters']['expected_transcript_revision']=rt.fingerprint(transcript)
    return q,out,tools,doc


def test_speech_prepared_actual_downstream_is_independent_not_work_edit(speech_integration):
    q,out,tools,doc=speech_integration;before=state(q)
    r=brief.execute(q,out,tools)
    request=json.loads((out/'prepared-request.json').read_bytes())
    assert rt.fingerprint(request)==r['prepared_request_sha256']
    assert state(q)['version']==r['execution_guard']['expected_version']
    target=out/'downstream';target.mkdir();result=rt.execute(request,target,tools)
    compiled=json.loads((target/'execution-plan.json').read_bytes())
    assert compiled['clips'][0]['id']=='kept' and doc['plan']['clips'][0]['id']=='full'
    assert result['kept_word_ids']==['w1','w2','w3']
    assert result['semantic_review']==result['acoustic_review']=='NOT_RUN'
    assert r['speech_binding']['dependent_resources']['captions']==['manual']
    assert r['speech_binding']['dependent_mapping_validation']=='NOT_RUN'
    assert r['speech_binding']['adoption_state']=='REQUIRES_TIMELINE_REVISE_AND_DEPENDENT_MAPPING'
    assert r['speech_binding']['apply_authorized_by_preparation'] is False
    assert state(q)==before


def test_speech_prepared_protection_enforced_by_actual_compiler(speech_integration):
    q,out,tools,_=speech_integration;before=state(q)
    brief.execute(q,out,tools)
    request=json.loads((out/'prepared-request.json').read_bytes())
    request['segments'][0].update(word_ids=['w2','w3'],start=.4)
    target=out/'rejected';target.mkdir()
    with pytest.raises(rt.ContractError,match='PROTECTED_WORD_DELETED'):
        rt.execute(request,target,tools)
    assert not (target/'execution-plan.json').exists() and state(q)==before


def test_speech_estimated_rejected_before_prepared_artifact(speech_integration):
    q,out,tools,_=speech_integration;before=state(q)
    path=Path(q['parameters']['aligned_transcript']['path']);transcript=json.loads(path.read_bytes())
    transcript['timing']='estimated';path.write_text(json.dumps(transcript))
    q['parameters']['aligned_transcript']['sha256']=rt.sha256(path)
    q['parameters']['expected_transcript_revision']=rt.fingerprint(transcript)
    with pytest.raises(rt.ContractError,match='ESTIMATED_OR_UNKNOWN'):
        brief.execute(q,out,tools)
    assert not (out/'prepared-request.json').exists() and state(q)==before


def test_speech_prepared_stale_guard_after_real_work_commit(speech_integration):
    q,out,tools,doc=speech_integration;before=state(q)
    r=brief.execute(q,out,tools)
    candidate=copy.deepcopy(doc);candidate['notes']['manual']='newer manual note'
    scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],
           'style_keys':[],'note_keys':['manual'],'output_fields':[],
           'caption_style':False,'freeze_positions':['full'],'freeze_duration':True}
    bundle={'schema':'work-candidate/1','base_version':before['version'],
            'base_document_sha256':before['document_sha256'],'document':candidate,'scope':scope}
    path=out/'note-candidate.json';path.write_text(json.dumps(bundle))
    target=out/'commit';target.mkdir()
    committed=work_ops.work_version({'operation':'work-version','action':'commit','store':q['store'],
        'expected_version':before['version'],'candidate':{'path':str(path),'sha256':rt.sha256(path)},
        'message':'simulated concurrent note','author':'agent'},target,tools)
    assert committed['version']!=r['execution_guard']['expected_version']
    assert r['execution_guard']['require_fresh_work_read_before_execution']
    reject=out/'stale';reject.mkdir()
    with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):
        brief.execute(q,reject,tools)
    assert not (reject/'prepared-request.json').exists()
    assert state(q)['document']==candidate
    # No stale independent plan is adopted; standalone compiler success is not CAS.
