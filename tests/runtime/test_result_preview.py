"""Explicit preview compilation; synthetic clocks are not real-media validation."""
import copy
import json
import sys
from pathlib import Path
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import editing_runtime as rt
import work_ops
import result_preview_ops as mod
from test_generation_intents import SyntheticMediaTools

@pytest.fixture
def case(tmp_path):
    tools = SyntheticMediaTools()
    asset = tmp_path/'source.bin'; asset.write_bytes(b'contract fixture only')
    font = tmp_path/'font.ttf'; font.write_bytes(b'contract font only')
    ref=lambda p:{'path':str(p.resolve()),'sha256':rt.sha256(p)}
    doc={'schema':'work-document/1','plan':{'schema':'execution-plan/1','fps':'25','width':64,'height':64,'fit':'contain','sources':{'s':ref(asset)},'clips':[{'id':'full','source_id':'s','start':0,'end':1,'gain_db':0}]},'captions':{},'caption_style':{'font':ref(font),'font_family':'fixture','font_size':12,'margin_v':2,'color_rgb':'FFFFFF'},'audio_tracks':{},'style_bindings':{},'notes':{'manual':'retain this'}}
    store=tmp_path/'work.sqlite'; init=tmp_path/'init';init.mkdir()
    state=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),'work_id':'test','document':doc,'author':'agent','message':'fixture'},init,tools)
    event=lambda a,b:{'clip_id':'full','start':a,'end':b,'min_visible_seconds':.1,'evidence':ref(asset)}
    step={'id':'step','label':'declared states only','context_id':'capture','requires':[],'before':event(0,.2),'action':event(.2,.6),'result':event(.6,1)}
    q={'operation':'result-preview-compile','store':str(store),'expected_version':state['version'],'mechanism_card':ref(Path(__file__).resolve().parents[2]/'styles/reference/consequence-first.md'),'tutorial':{'steps':[step],'result_cues':[{'id':'result','step_id':'step','start':.6,'end':1,'text':'declared result'}]},'preview':{'id':'peek','step_id':'step','start':.6,'end':1,'label':'后段画面预览 · 非当前操作已成功','return_label':'回到原流程','return_label_seconds':.2},'shift_clip_ids':['full'],'scope':{'clip_ids':['peek'],'source_ids':[],'caption_ids':['peek-label','peek-return-label'],'audio_ids':[],'style_keys':[],'note_keys':['result_preview'],'output_fields':['allow_source_reuse'],'caption_style':False,'freeze_positions':[],'freeze_duration':False}}
    output=tmp_path/'output';output.mkdir()
    return q,output,tools,doc

def test_preserves_content_and_does_not_commit(case):
    q,out,tools,doc=case
    result=mod.execute(q,out,tools)
    candidate=json.loads((out/'candidate.json').read_text())['document']
    assert candidate['plan']['clips'][1:]==doc['plan']['clips']
    assert candidate['notes']['manual']=='retain this'
    assert candidate['notes']['result_preview']['candidate_tutorial']['result_cues'][0]['start']==1.0
    assert result['shift_seconds']==.4 and not result['committed']
    with work_ops.connect(q['store']) as db: assert work_ops.load(db)['version']==q['expected_version']

@pytest.mark.parametrize('change,error',[
 (lambda q:q.update(expected_version='0'*64),'WORK_VERSION_CONFLICT'),
 (lambda q:q.update(shift_clip_ids=[]),'EXPLICIT_SHIFT_REQUIRED'),
 (lambda q:q.update(shift_clip_ids=['full','full']),'EXPLICIT_SHIFT_REQUIRED'),
 (lambda q:q['preview'].update(start=.4),'OUTSIDE_RESULT'),
 (lambda q:q['preview'].update(start=.61),'FRAME_GRID_REQUIRED'),
 (lambda q:q['preview'].update(id='full'),'CLIP_ID_CONFLICT'),
 (lambda q:q['preview'].update(label='操作成功'),'VISIBLE_LABEL_REQUIRED'),
 (lambda q:q['scope'].update(output_fields=[]),'OUTPUT_OUTSIDE_SCOPE'),
 (lambda q:q['scope'].update(freeze_positions=['full']),'FROZEN_POSITION_CHANGED'),
 (lambda q:q['scope'].update(freeze_duration=True),'WORK_DURATION_FROZEN'),
 (lambda q:q['scope'].update(note_keys=[]),'OUTSIDE_SCOPE'),
 (lambda q:q['tutorial']['result_cues'][0].update(start=0),'RESULT_CUE_OUTSIDE_EVIDENCE_WINDOW'),
 (lambda q:q['mechanism_card'].update(sha256='0'*64),'SOURCE_HASH_MISMATCH'),
])
def test_fail_closed(case,change,error):
    q,out,tools,_=case;change(q)
    with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()

@pytest.mark.parametrize('field,value,error',[
 ('audio_tracks',{'future':{}},'DEPENDENT_MAPPING_UNSUPPORTED'),
 ('visual_layers',{'future':{}},'DEPENDENT_MAPPING_UNSUPPORTED'),
 ('notes',{'result_preview':{'user':'owned'}},'NOTE_EXISTS'),
])
def test_does_not_remove_unsupported_existing_data(case,monkeypatch,field,value,error):
    q,out,tools,doc=case
    # Inject already-loaded state to isolate admission guard, not claim invalid payload is a valid Work.
    original=work_ops.load
    def loaded(db):
        state=original(db);state['document'][field]=value;return state
    monkeypatch.setattr(work_ops,'load',loaded)
    monkeypatch.setattr(work_ops,'validate_document',lambda *a:({'fps':'25'},[],[]))
    with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()

def reinitialize(case, update):
    q,out,tools,doc=case
    doc=copy.deepcopy(doc);update(doc)
    folder=out.parent/'replacement';folder.mkdir();store=out.parent/'replacement.sqlite'
    state=work_ops.work_version({'operation':'work-version','action':'init','store':str(store),'work_id':'new-fixture','document':doc,'author':'agent','message':'fixture'},folder,tools)
    q['store']=str(store);q['expected_version']=state['version']
    return doc

def test_existing_caption_and_notes_preserved(case):
    q,out,tools,_=case
    doc=reinitialize(case,lambda d:d['captions'].update(manual={'clip_id':'full','start':.2,'end':.6,'text':'不要删除我的限定'}))
    mod.execute(q,out,tools)
    candidate=json.loads((out/'candidate.json').read_text())['document']
    assert candidate['captions']['manual']==doc['captions']['manual']
    assert candidate['notes']['manual']==doc['notes']['manual']

def test_existing_caption_overlap_not_silently_removed(case):
    q,out,tools,_=case
    reinitialize(case,lambda d:d['captions'].update(manual={'clip_id':'full','start':0,'end':.4,'text':'必须保留'}))
    with pytest.raises(rt.ContractError,match='OVERLAPPING_CAPTIONS'):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()

def test_changed_head_at_finish_no_success_report(case,monkeypatch):
    q,out,tools,_=case
    original=work_ops.load;calls=[]
    def changed(db):
        state=original(db);calls.append(1)
        if len(calls)>1:state['version']='0'*64
        return state
    monkeypatch.setattr(work_ops,'load',changed)
    with pytest.raises(rt.ContractError,match='WORK_VERSION_CONFLICT'):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()

def test_changed_evidence_after_compile_rejected(case,monkeypatch):
    q,out,tools,_=case
    evidence=out.parent/'evidence.txt';evidence.write_text('observation')
    for step in q['tutorial']['steps']:
        for role in ['before','action','result']:step[role]['evidence']={'path':str(evidence),'sha256':rt.sha256(evidence)}
    original=work_ops.timeline_revise
    def changed(*a,**k):
        result=original(*a,**k);evidence.write_text('different');return result
    monkeypatch.setattr(work_ops,'timeline_revise',changed)
    with pytest.raises(rt.ContractError,match='SOURCE_HASH_MISMATCH'):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()


def protected_case(case):
    q, out, tools, doc = case
    ref = doc['plan']['sources']['s']
    def update(d):
        units = []
        occurrences = []
        for uid, start, end, deps in [('action', .2, .6, []), ('result', .6, 1, [{'unit_id':'action','relation':'prerequisite'}])]:
            units.append({'id':uid,'label':uid,'kind':'claim','speaker':'declared','modality':'video',
                          'source':ref,'start':start,'end':end,'evidence':ref,'requires':deps})
            occurrences.append({'id':uid+'-original','unit_id':uid,'carriers':[{'type':'clip-video','id':'full'}],
                                'dependencies':{'action':'action-original'} if deps else {}})
        d['evidence_protection']={'schema':'work-evidence-protection/1','units':units,
            'required_units':['action','result'],'occurrences':occurrences,
            'chapters':[{'id':'chapter','title':'Original evidence','occurrence_ids':['action-original','result-original']}]}
    doc = reinitialize(case, update)
    q['scope']['evidence_mapping'] = True
    return doc


def test_protected_original_units_carriers_dependencies_and_chapter_shift(case):
    q,out,tools,_=case;doc=protected_case(case)
    result=mod.execute(q,out,tools)
    candidate=json.loads((out/'candidate.json').read_text())['document']
    assert candidate['evidence_protection']==doc['evidence_protection']
    proof=json.loads((out/'candidate-protection-map.json').read_text())
    assert proof['validation_mode']=='ordinary_protection'
    assert proof['declared_coverage']=='DECLARED_SOURCE_RANGES_PRESERVED'
    assert proof['occurrences'][0]['parts'][0]['clock_rational']['output_start']=='3/5'
    assert proof['occurrences'][1]['parts'][0]['clock_rational']['output_start']=='1'
    assert proof['chapters'][0]['start']==.6
    assert not result['protection_shift']['preview_registered_as_evidence']
    with work_ops.connect(q['store']) as db:assert work_ops.load(db)['document']==doc


def test_protected_shift_requires_explicit_mapping_authorization(case):
    q,out,tools,_=case;protected_case(case);q['scope'].pop('evidence_mapping')
    with pytest.raises(rt.ContractError,match='PROTECTION_SHIFT_SCOPE_REQUIRED'):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()


@pytest.mark.parametrize('mutation', ['drop-unit','drop-required','redirect-preview','drop-original','change-source'])
def test_protection_guard_rejects_changed_declaration_or_original(case, monkeypatch, mutation):
    q,out,tools,_=case;protected_case(case)
    original=work_ops.timeline_revise
    def changed(request,*args,**kwargs):
        result=original(request,*args,**kwargs)
        c=request['candidate']
        if mutation=='drop-unit':c['evidence_protection']['units'].pop()
        elif mutation=='drop-required':c['evidence_protection']['required_units'].pop()
        elif mutation=='redirect-preview':c['evidence_protection']['occurrences'][1]['carriers'][0]['id']='peek'
        elif mutation=='drop-original':c['plan']['clips'].pop()
        else:c['plan']['sources']['s']['sha256']='0'*64
        return result
    monkeypatch.setattr(work_ops,'timeline_revise',changed)
    with pytest.raises(rt.ContractError,match='PROTECTION_CHANGED|ORIGINAL_CONTENT_CHANGED'):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()


def test_protected_evidence_change_after_proof_no_success(case, monkeypatch):
    q,out,tools,_=case;doc=protected_case(case)
    original=mod.protection_shift
    def changed(*a,**k):
        result=original(*a,**k)
        Path(doc['evidence_protection']['units'][0]['evidence']['path']).write_bytes(b'changed')
        return result
    monkeypatch.setattr(mod,'protection_shift',changed)
    with pytest.raises(rt.ContractError,match='SOURCE_HASH_MISMATCH'):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()


@pytest.mark.parametrize('field,value,error', [
    ('freeze_positions',['full'],'FROZEN_POSITION_CHANGED'),
    ('freeze_duration',True,'WORK_DURATION_FROZEN'),
    ('output_fields',[],'OUTPUT_OUTSIDE_SCOPE'),
])
def test_protected_preview_still_honors_existing_scope(case,field,value,error):
    q,out,tools,_=case;protected_case(case);q['scope'][field]=value
    with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,tools)
    assert not (out/'result-preview.json').exists()


def test_proof_failure_precedes_candidate_publication(case,monkeypatch):
    q,out,tools,_=case;protected_case(case)
    def fail(*a,**k):raise rt.ContractError('INJECTED_PROTECTION_PROOF_FAILURE')
    monkeypatch.setattr(mod,'protection_shift',fail)
    with pytest.raises(rt.ContractError,match='INJECTED'):mod.execute(q,out,tools)
    assert not (out/'candidate.json').exists() and not (out/'result-preview.json').exists()
