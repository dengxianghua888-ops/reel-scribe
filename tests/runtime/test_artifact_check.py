"""Declared linkage is not artifact production, screenshot provenance or saved state."""
import copy,json,sys
from pathlib import Path
import pytest
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'runtime'),str(Path(__file__).resolve().parent)]
import editing_runtime as rt
import artifact_check_ops as mod
from test_result_preview import case as work_case

@pytest.fixture
def case(work_case):
    prior,out,tools,doc=work_case
    tutorial=copy.deepcopy(prior['tutorial']);tutorial['steps'][0]['result']['end']=.8;tutorial['result_cues'][0]['end']=.8
    result=out.parent/'artifact.txt';result.write_text('local fixture output, not a saved backend document')
    evidence=out.parent/'observation.txt';evidence.write_text('fixture observation declaration, no extracted frame')
    ref=lambda p:{'path':str(p),'sha256':rt.sha256(p)}
    q={'operation':'tutorial-artifact-check','plan':copy.deepcopy(doc['plan']),'expected_revision':rt.fingerprint(doc['plan']),
       'tutorial':tutorial,'checks':[{'id':'inspect','step_id':'step','input_artifacts':[], 'result_artifact':ref(result),
       'inspection':{'clip_id':'full','start':.8,'end':1,'min_visible_seconds':.1,'evidence':ref(evidence)},
       'observation':{'actor_kind':'agent-observation','statement':'Declared local observation, not independently verified'}}],
       'artifact_cues':[{'id':'cue','check_id':'inspect','start':.8,'end':1,'text':'Inspection declared'}]}
    return q,out,tools

def test_valid_linkage_not_semantic_success(case):
    q,out,t=case;before=copy.deepcopy(q);r=mod.execute(q,out,t)
    assert q==before and r['status']=='LINKAGE_VALIDATED'
    assert r['frame_derivation']=='FRAME_DERIVATION_NOT_VERIFIED' and r['backend_persistence']=='NOT_VERIFIED'
    assert r['checks'][0]['result_artifact']['sha256']==q['checks'][0]['result_artifact']['sha256']
    assert not r['work_changed'] and not r['publication_gate']

def test_missing_result_is_incomplete_not_backend_failure(case):
    q,out,t=case;q['checks'][0]['result_artifact']=None;q['artifact_cues']=[]
    r=mod.execute(q,out,t);assert r['status']=='INCOMPLETE'
    assert r['checks'][0]['status']=='MISSING_ARTIFACT' and r['backend_persistence']=='NOT_VERIFIED'

@pytest.mark.parametrize('change,error',[
 (lambda q:q.update(expected_revision='0'*64),'PLAN_REVISION_CONFLICT'),
 (lambda q:q['checks'][0].update(step_id='other'),'ARTIFACT_STEP_UNKNOWN'),
 (lambda q:q['checks'].append(copy.deepcopy(q['checks'][0])),'CHECK_ID_INVALID'),
 (lambda q:q['checks'][0]['inspection'].update(start=.7),'INSPECTION_PRECEDES_RESULT'),
 (lambda q:q['checks'][0]['inspection'].update(end=1.1),'SOURCE_RANGE_INVALID'),
 (lambda q:q['checks'][0]['inspection'].update(min_visible_seconds=.3),'READING_WINDOW_TOO_SHORT'),
 (lambda q:q['checks'][0]['inspection'].update(clip_id='missing'),'INSPECTION_CLIP_UNKNOWN'),
 (lambda q:q['artifact_cues'][0].update(start=.7),'CUE_OUTSIDE_INSPECTION'),
 (lambda q:q['checks'][0].update(result_artifact=None),'CUE_WITHOUT_RESULT_FILE'),
 (lambda q:q['checks'][0]['observation'].update(actor_kind='authenticated-user'),'OBSERVER_INVALID'),
 (lambda q:q['checks'][0]['observation'].update(verified=True),'UNKNOWN_FIELDS'),
 (lambda q:q['checks'][0]['result_artifact'].update(sha256='0'*64),'SOURCE_HASH_MISMATCH'),
 (lambda q:q['checks'][0]['result_artifact'].update(path='https://example.com/result'),'LOCAL_ABSOLUTE_FILE'),
])
def test_adversarial_no_report(case,change,error):
    q,out,t=case;change(q)
    with pytest.raises(rt.ContractError,match=error):mod.execute(q,out,t)
    assert not (out/'artifact-check.json').exists()

@pytest.mark.parametrize('kind',['directory','symlink','parent-symlink'])
def test_nonregular_or_alias_rejected(case,kind):
    q,out,t=case;ref=q['checks'][0]['result_artifact'];p=Path(ref['path'])
    if kind=='directory':ref['path']=str(out)
    elif kind=='symlink':link=out.parent/'alias';link.symlink_to(p);ref['path']=str(link)
    else:link=out.parent/'alias-dir';link.symlink_to(p.parent,target_is_directory=True);ref['path']=str(link/p.name)
    with pytest.raises(rt.ContractError,match='REGULAR_FILE|SYMLINK'):mod.execute(q,out,t)
    assert not (out/'artifact-check.json').exists()

def test_other_capture_rejected(case):
    q,out,t=case;q['plan']['sources']['second']=q['plan']['sources']['s'].copy()
    q['plan']['clips'][0]['end']=.8;q['plan']['clips'].append({'id':'other','source_id':'second','start':.8,'end':1,'gain_db':0})
    q['expected_revision']=rt.fingerprint(q['plan']);q['checks'][0]['inspection']['clip_id']='other'
    with pytest.raises(rt.ContractError,match='CAPTURE_MISMATCH'):mod.execute(q,out,t)

def test_frame_rounding_tail_rejected(case):
    q,out,t=case;q['plan']['clips'][0]['end']=.99;q['expected_revision']=rt.fingerprint(q['plan']);q['checks'][0]['inspection']['end']=.99
    # At25fps .99 rounds to1, actual contractual end .99 remains usable; make .97 round .96.
    q['plan']['clips'][0]['end']=.97;q['expected_revision']=rt.fingerprint(q['plan']);q['checks'][0]['inspection']['end']=.97
    with pytest.raises(rt.ContractError,match='INSPECTION_NOT_VISIBLE'):mod.execute(q,out,t)

@pytest.mark.parametrize('target',['result_artifact','evidence','capture','tutorial'])
def test_changed_file_before_final_pass_rejected(case,monkeypatch,target):
    q,out,t=case
    if target=='result_artifact':ref=q['checks'][0]['result_artifact']
    elif target=='evidence':ref=q['checks'][0]['inspection']['evidence']
    elif target=='capture':ref=q['plan']['sources']['s']
    else:ref=q['tutorial']['steps'][0]['before']['evidence']
    original=mod._file;seen={}
    def mutate(reference):
        result=original(reference);key=reference['path'];seen[key]=seen.get(key,0)+1
        # Mutate after first successful consumption, before final revalidation.
        if key==ref['path'] and seen[key]==1:Path(key).write_bytes(b'changed after first binding')
        return result
    monkeypatch.setattr(mod,'_file',mutate)
    with pytest.raises(rt.ContractError,match='HASH'):mod.execute(q,out,t)
    assert not (out/'artifact-check.json').exists()

def test_later_source_inspection_reordered_early_in_output_rejected(case):
    q,out,t=case
    q['plan']['clips']=[{'id':'inspection-first','source_id':'s','start':.8,'end':1,'gain_db':0},{'id':'full','source_id':'s','start':0,'end':.8,'gain_db':0}]
    q['expected_revision']=rt.fingerprint(q['plan']);q['tutorial']['result_cues']=[]
    q['checks'][0]['inspection']['clip_id']='inspection-first';q['artifact_cues']=[]
    with pytest.raises(rt.ContractError,match='INSPECTION_PRECEDES_RESULT'):mod.execute(q,out,t)
    assert not (out/'artifact-check.json').exists()

def test_claiming_saved_and_reopened_does_not_certify_it(case):
    q,out,t=case;q['checks'][0]['observation']['statement']='This was saved and reopened successfully'
    r=mod.execute(q,out,t)
    assert r['checks'][0]['observation_truth']=='NOT_VERIFIED'
    assert r['checks'][0]['backend_persistence']=='NOT_VERIFIED'
    assert r['checks'][0]['artifact_production_link']=='DECLARED_ONLY'

def test_mixed_missing_artifact_keeps_available_item(case):
    q,out,t=case;other=copy.deepcopy(q['checks'][0]);other.update(id='missing',result_artifact=None);q['checks'].append(other)
    r=mod.execute(q,out,t)
    assert r['status']=='INCOMPLETE'
    assert [x['status'] for x in r['checks']]==['ARTIFACT_BYTES_AVAILABLE','MISSING_ARTIFACT']
