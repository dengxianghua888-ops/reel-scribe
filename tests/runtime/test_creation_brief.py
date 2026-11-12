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


def speech_case(case, *, timing='model-aligned'):
    q,out,tools,doc=case
    q['brief'].update(scene='speech',intent='speech-tighten')
    source=copy.deepcopy(doc['plan']['sources']['s'])
    evidence=out.parent/'boundaries.json';evidence.write_text('{"basis":"synthetic boundary fixture, not listening"}')
    boundary={'method':'alignment-review','artifact':{'path':str(evidence),'sha256':rt.sha256(evidence)}}
    transcript={'schema':'word-transcript/1','source':source,'language':'zh-CN','timing':timing,
        'origin':{'method':'synthetic declared boundaries, not real alignment','reference':'contract test'},
        'words':[{'id':w,'text':text,'start':a,'end':b,'speaker':'s','confidence':.5}
                 for w,text,a,b in [('w1','不能',0,.4),('w2','删',.4,.6),('w3','限定',.6,1)]]}
    path=out.parent/'transcript.json';path.write_text(json.dumps(transcript,ensure_ascii=False))
    q['parameters']={'aligned_transcript':{'path':str(path),'sha256':rt.sha256(path)},
       'expected_transcript_revision':rt.fingerprint(transcript),
       'segments':[{'id':'kept','word_ids':['w1','w2','w3'],'start':0,'end':1,'gain_db':0,'boundary_evidence':boundary}],
       'protected_word_ids':['w1'],'allow_reorder':False,'source_clip_ids':['full']}
    return q,out,tools,doc


def test_speech_prepares_fixed_transcript_and_does_not_apply(case):
    q,out,tools,doc=speech_case(case)
    report=mod.execute(q,out,tools);draft=report['draft_request']
    assert draft['operation']=='speech-plan-compile'
    assert draft['transcript']['words'][0]['text']=='不能'
    assert draft['output']=={k:doc['plan'][k] for k in ['fps','width','height','fit']}
    assert report['speech_binding']['adoption_state']=='REQUIRES_TIMELINE_REVISE_AND_DEPENDENT_MAPPING'
    assert not report['speech_binding']['apply_authorized_by_preparation']
    with work_ops.connect(q['store']) as db:
        current=work_ops.load(db)
    assert current['document']==doc and current['version']==q['expected_version']


@pytest.mark.parametrize('mutation,error',[
 (lambda q:q['parameters'].update(expected_transcript_revision='0'*64),'TRANSCRIPT_REVISION_CONFLICT'),
 (lambda q:q['parameters'].update(allow_reorder=True),'REORDER_UNSUPPORTED'),
 (lambda q:q['parameters'].update(source_clip_ids=['unknown']),'CLIP_UNKNOWN'),
 (lambda q:q['parameters']['segments'][0].update(end=1.04),'OUTSIDE_WORK_SCOPE'),
 (lambda q:q['parameters']['segments'][0]['boundary_evidence']['artifact'].update(sha256='0'*64),'SOURCE_HASH_MISMATCH'),
 (lambda q:q['parameters'].update(protected_word_ids=['w1','w1']),'PROTECTED_WORD_IDS_REQUIRED'),
])
def test_speech_bad_preparation(case,mutation,error):
    q,out,tools,_=speech_case(case);mutation(q)
    with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
    assert not (out/'prepared-request.json').exists()


def test_speech_estimated_not_promoted_by_review_file(case):
    q,out,tools,_=speech_case(case,timing='estimated')
    with pytest.raises(rt.ContractError,match='ESTIMATED_OR_UNKNOWN'):mod.execute(q,out,tools)
    assert not (out/'prepared-request.json').exists()


def test_speech_plan_only_no_ready_file(case):
    q,out,tools,_=speech_case(case);q['brief']['mode']='PLAN'
    report=mod.execute(q,out,tools)
    assert report['draft_request']['operation']=='speech-plan-compile'
    assert report['status']=='PLANNING_ONLY' and not (out/'prepared-request.json').exists()


def test_speech_wrong_source_rejected(case):
    q,out,tools,_=speech_case(case)
    path=Path(q['parameters']['aligned_transcript']['path']);transcript=json.loads(path.read_text())
    other=out.parent/'other.bin';other.write_bytes(b'other content')
    transcript['source']={'path':str(other),'sha256':rt.sha256(other)}
    path.write_text(json.dumps(transcript));q['parameters']['aligned_transcript']['sha256']=rt.sha256(path)
    q['parameters']['expected_transcript_revision']=rt.fingerprint(transcript)
    with pytest.raises(rt.ContractError,match='SOURCE_MISMATCH'):mod.execute(q,out,tools)


def test_speech_current_caption_remains_dependency_not_implicit_apply(case):
    q,out,tools,doc=speech_case(case)
    doc=copy.deepcopy(doc);doc['captions']={'manual':{'clip_id':'full','start':0,'end':1,'text':'保留不能'}}
    init=out.parent/'speech-layer-init';init.mkdir();store=out.parent/'speech-layer.sqlite'
    state=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),'work_id':'layer','document':doc,'author':'agent','message':'fixture'},init,tools)
    q['store']=str(store);q['expected_version']=state['version']
    report=mod.execute(q,out,tools)
    assert report['speech_binding']['dependent_resources']['captions']==['manual']
    assert report['speech_binding']['dependent_mapping_validation']=='NOT_RUN'
    with work_ops.connect(store) as db:assert work_ops.load(db)['document']==doc


def test_speech_existing_compiler_rejects_deleting_protected_word(case,monkeypatch):
    import speech_ops
    q,out,tools,_=speech_case(case)
    report=mod.execute(q,out,tools);draft=report['draft_request']
    # Real compiler guards with declared synthetic media metadata; no real voice acceptance.
    monkeypatch.setattr(tools,'probe',lambda path:{'duration':1,'streams':[{'codec_type':'audio'}]})
    draft['segments'][0].update(word_ids=['w2','w3'],start=.4)
    folder=out.parent/'compile-negative';folder.mkdir()
    with pytest.raises(rt.ContractError,match='PROTECTED_WORD_DELETED'):speech_ops.execute(draft,folder,tools)


def test_speech_transcript_bytes_race(case,monkeypatch):
    q,out,tools,_=speech_case(case)
    import io
    original=Path.open;target=Path(q['parameters']['aligned_transcript']['path']);calls=[]
    def changed(path,*args,**kwargs):
        handle=original(path,*args,**kwargs)
        if path==target and args and args[0]=='rb':
            calls.append(1)
            if len(calls)==2:
                with handle:data=handle.read()
                return io.BytesIO(data+b' ')
        return handle
    monkeypatch.setattr(Path,'open',changed)
    # Change only second open: hashed source identity and parser consumption must agree.
    with pytest.raises(rt.ContractError,match='BRIEF_TRANSCRIPT_BYTES_CHANGED'):mod.execute(q,out,tools)


def replace_speech_work(case,q,doc,tools):
    out=case[1];folder=out.parent/'scope-init';folder.mkdir();store=out.parent/'scope.sqlite'
    state=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),'work_id':'scope','document':doc,'author':'agent','message':'fixture'},folder,tools)
    q['store']=str(store);q['expected_version']=state['version']


@pytest.mark.parametrize('clips,ids,error',[
 ([{'id':'a','source_id':'s','start':0,'end':.4,'gain_db':0},{'id':'b','source_id':'s','start':.6,'end':1,'gain_db':0}],['a','b'],'CONTIGUOUS_SOURCE_REQUIRED'),
 ([{'id':'full','source_id':'s','start':0,'end':1,'gain_db':0,'speed':2}],['full'],'SINGLE_SOURCE_1X_AUDIBLE_REQUIRED'),
 ([{'id':'full','source_id':'s','start':0,'end':.98,'gain_db':0}],['full'],'OUTSIDE_WORK_SCOPE'),
])
def test_speech_respects_existing_clip_mapping(case,clips,ids,error):
    q,out,tools,doc=speech_case(case);doc=copy.deepcopy(doc);doc['plan']['clips']=clips
    replace_speech_work(case,q,doc,tools);q['parameters']['source_clip_ids']=ids
    if error=='OUTSIDE_WORK_SCOPE':q['parameters']['segments'][0]['end']=.98
    with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)


def test_speech_prepared_request_real_compiler_on_synthetic_media(case):
    import subprocess,shutil
    import speech_ops
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('FFmpeg/ffprobe unavailable')
    q,out,_,doc=speech_case(case)
    media=out.parent/'synthetic.mov'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=c=black:s=64x64:r=25:d=1',
        '-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','pcm_s16le',str(media)],check=True)
    tools=rt.Tools();doc=copy.deepcopy(doc);ref={'path':str(media),'sha256':rt.sha256(media)}
    doc['plan']['sources']['s']=ref
    replace_speech_work(case,q,doc,tools)
    path=Path(q['parameters']['aligned_transcript']['path']);transcript=json.loads(path.read_text());transcript['source']=ref
    path.write_text(json.dumps(transcript));q['parameters']['aligned_transcript']['sha256']=rt.sha256(path);q['parameters']['expected_transcript_revision']=rt.fingerprint(transcript)
    report=mod.execute(q,out,tools);compiled=out.parent/'actual-compiler';compiled.mkdir()
    result=speech_ops.execute(report['draft_request'],compiled,tools)
    assert result['kept_word_ids']==['w1','w2','w3'] and result['semantic_review']=='NOT_RUN'
    assert (compiled/'execution-plan.json').exists()
    with work_ops.connect(q['store']) as db:assert work_ops.load(db)['version']==q['expected_version']
