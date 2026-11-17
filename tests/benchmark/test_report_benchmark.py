import hashlib
import importlib.util
import json
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[2]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'scripts'/f'{name}.py')
    obj=importlib.util.module_from_spec(spec);spec.loader.exec_module(obj);return obj
b=module('report_benchmark');runner=module('run_local_benchmark')

def fixture(tmp_path, attempts=None):
    p=tmp_path/'receipt.json'
    for a in attempts or []: a.setdefault('path', str(tmp_path))
    p.write_text(json.dumps({'schema':'operation-receipt/1','operation':'work-batch-render','status':'SUCCEEDED','artifacts':[],
        'result':{'schema':'batch-state/1','batch_id':'x','jobs':[], 'attempts':attempts or [],'events':[]}}))
    return {'path':str(p),'sha256':b.sha(p)}

def test_missing_metrics_are_unknown(tmp_path):
    r=b.report(tmp_path,[fixture(tmp_path)])
    for k in ['elapsed_seconds','ffmpeg_invocations','model_calls','cost','human_time_saved']:assert r[k]=='NOT_RECORDED'

def test_duplicate_reference_not_double_counted(tmp_path):
    a={'job_id':'a','number':1,'status':'FAILED'};ref=fixture(tmp_path,[a]);r=b.report(tmp_path,[ref,ref])
    assert r['attempt_count']==r['failed_attempt_count']==1 and len(r['evidence'])==1

def test_duplicate_attempt_rejected(tmp_path):
    a={'job_id':'a','number':1,'status':'RENDERED'}
    with pytest.raises(ValueError,match='DUPLICATE_ATTEMPT'):b.report(tmp_path,[fixture(tmp_path,[a,a])])

def test_changed_receipt_rejected(tmp_path):
    ref=fixture(tmp_path);Path(ref['path']).write_text('{}')
    with pytest.raises(ValueError,match='HASH_MISMATCH'):b.report(tmp_path,[ref])

def test_outside_root_rejected(tmp_path):
    ref=fixture(tmp_path); child=tmp_path/'child';child.mkdir()
    with pytest.raises(ValueError,match='OUTSIDE'):b.report(child,[ref])

def test_duplicate_json_rejected(tmp_path):
    p=tmp_path/'receipt.json';p.write_text('{"schema":1,"schema":2}')
    with pytest.raises(ValueError,match='DUPLICATE_JSON'):b.report(tmp_path,[{'path':str(p),'sha256':b.sha(p)}])

def test_changed_artifact_rejected(tmp_path):
    ref=fixture(tmp_path);p=Path(ref['path']);d=json.loads(p.read_text());a=tmp_path/'a';a.write_bytes(b'old')
    d['artifacts']=[{'path':'a','sha256':b.sha(a),'bytes':3}];p.write_text(json.dumps(d));ref['sha256']=b.sha(p);a.write_bytes(b'new')
    with pytest.raises(ValueError,match='HASH_MISMATCH'):b.report(tmp_path,[ref])

def fake_run(request,out):
    out.mkdir(parents=True)
    if request['action']=='prepare':
        batch=Path(request['batch_dir']);batch.mkdir();(batch/'manifest.json').write_text('{}');r={'status':'SUCCEEDED','result':{}}
    else:
        assert request['manifest_sha256']==hashlib.sha256(b'{}').hexdigest()
        assert 'job_ids' in request and request['retry_failed'] is False
        action='RENDER_ATTEMPT' if out.name=='cold' else 'REUSED_VERIFIED'
        r={'status':'SUCCEEDED','result':{'events':[{'action':action,'status':'SUCCEEDED'}]}}
    (out/'receipt.json').write_text(json.dumps(r));return r

def test_measured_runner_scoped_and_no_invented_commands(tmp_path):
    ticks=iter([0,1,2,7,8,10]);r=runner.measure({'operation':'work-batch-render','action':'prepare'},tmp_path/'run',fake_run,lambda:next(ticks))
    assert [p['elapsed_seconds'] for p in r['phases']]==[1,5,2]
    assert r['status']=='MEASURED_LOCAL_BATCH_ONLY' and r['ffmpeg_invocations']=='NOT_RECORDED'

def test_runner_preserves_existing_output(tmp_path):
    with pytest.raises(FileExistsError):runner.measure({'operation':'work-batch-render','action':'prepare'},tmp_path,fake_run)

def test_runner_rejects_other_operation(tmp_path):
    with pytest.raises(ValueError,match='ONLY_BATCH'):runner.measure({'operation':'generate'},tmp_path/'out',fake_run)

def test_failure_not_success(tmp_path):
    def failed(req,out):
        r=fake_run(req,out)
        if out.name=='reuse':r['result']['events'][0]['action']='RENDER_ATTEMPT'
        return r
    r=runner.measure({'operation':'work-batch-render','action':'prepare'},tmp_path/'out',failed)
    assert r['status']=='FAILED:NOT_VERIFIED_REUSE'

def test_receipt_replacement_after_read_not_reendorsed(tmp_path, monkeypatch):
    ref=fixture(tmp_path); original=Path.read_bytes
    def swapped(p):
        data=original(p)
        if p==Path(ref['path']):p.write_text('{}')
        return data
    monkeypatch.setattr(Path,'read_bytes',swapped)
    r=b.report(tmp_path,[ref])
    assert r['evidence'][0]['operation']=='work-batch-render'
    assert b.sha(Path(ref['path']))!=r['evidence'][0]['sha256']

def test_plan_replaced_after_artifact_check_rejected(tmp_path, monkeypatch):
    plan=tmp_path/'normalized-plan.json';plan.write_text(json.dumps({'clips':[], 'sources':{}}))
    p=tmp_path/'receipt.json';d={'schema':'operation-receipt/1','operation':'timeline-render','status':'SUCCEEDED',
        'result':{'normalized_plan':plan.name,'media':{'duration':6}},
        'artifacts':[{'path':plan.name,'sha256':b.sha(plan),'bytes':plan.stat().st_size}]}
    p.write_text(json.dumps(d));ref={'path':str(p),'sha256':b.sha(p)};old=b.sha
    def swapped(path):
        h=old(path)
        if path==plan:plan.write_text(plan.read_text().replace('clips', 'clops'))
        return h
    monkeypatch.setattr(b,'sha',swapped)
    with pytest.raises(ValueError,match='ARTIFACT_SIZE|HASH_MISMATCH'):b.report(tmp_path,[ref])
