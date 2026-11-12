import copy
import importlib.util
import json
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('cases',ROOT/'scripts/validate_evaluation_cases.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


def data():return json.loads((ROOT/'examples/evaluation-cases/nine-cases.json').read_text())


def test_manifest_has_nine_non_gold_cases():assert m.validate(data())['case_count']==9


@pytest.mark.parametrize('field,value',[('semantic_acceptance','PASS'),('word_timing_gold',True),('window_seconds',[0,1e9]),('dependencies',[])])
def test_reject_unsupported_claims(field,value):
    d=data();d['cases'][0][field]=value
    with pytest.raises(ValueError):m.validate(d)


def test_missing_assets_not_success(tmp_path):assert m.verify_local(data(),tmp_path)['status']=='NOT_RUN_MISSING_ASSETS'


def test_grid_must_be_complete():
    d=data();d['cases'][0]['difficulty']='complex'
    with pytest.raises(ValueError,match='GRID_INCOMPLETE'):m.validate(d)


def receipts():
    doc={'plan':{'source':'real'},'captions':{'a':'do not remove'},'audio_tracks':{},'notes':{},'caption_style':1}
    r={k:{'status':'SUCCEEDED','result':{'document':copy.deepcopy(doc),'version':k}} for k in ['init','apply','restore']}
    r['apply']['result']['document']['caption_style']=2
    r['stale']={'status':'FAILED','error':'WORK_VERSION_CONFLICT'};return r


def test_existing_work_checks_protected_content_and_restore():
    r=receipts();assert m.verify_work(r)['restore_exact']
    r['apply']['result']['document']['captions']['a']='remove'
    with pytest.raises(ValueError,match='PROTECTED_CONTENT_CHANGED'):m.verify_work(r)


def test_existing_work_checks_failed_cas():
    r=receipts();r['stale']['status']='SUCCEEDED'
    with pytest.raises(ValueError,match='STALE_CAS_NOT_REJECTED'):m.verify_work(r)


def test_asset_identity_mismatch_is_failure(tmp_path):
    d=data();ref=next(iter(d['sources'].values()));path=tmp_path/ref['asset_path'];path.parent.mkdir(parents=True);path.write_text('wrong')
    with pytest.raises(ValueError,match='ASSET_IDENTITY_MISMATCH'):m.verify_local(d,tmp_path)


def test_manifest_cannot_escape_asset_root():
    d=data();next(iter(d['sources'].values()))['asset_path']='../outside.mov'
    with pytest.raises(ValueError,match='RELATIVE_ASSET_REQUIRED'):m.validate(d)


def test_source_evidence_name_collision_rejected(tmp_path):
    d=data();d['evidence']['film']=copy.deepcopy(d['sources']['film'])
    with pytest.raises(ValueError,match='SOURCE_EVIDENCE_KEY_CONFLICT'):m.validate(d)
    with pytest.raises(ValueError,match='SOURCE_EVIDENCE_KEY_CONFLICT'):m.verify_local(d,tmp_path)


def local_receipt_fixture(tmp_path):
    import hashlib
    rs=receipts();d={'sources':{},'evidence':{},'work_receipt_keys':{k:k for k in rs}}
    for key,r in rs.items():
        raw=json.dumps(r).encode();(tmp_path/(key+'.json')).write_bytes(raw)
        d['evidence'][key]={'asset_path':key+'.json','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    return d


def test_parsed_receipts_are_same_verified_bytes(tmp_path,monkeypatch):
    d=local_receipt_fixture(tmp_path)
    def denied(*a,**kw):raise AssertionError('do not reopen verified evidence as text')
    monkeypatch.setattr(Path,'read_text',denied)
    assert m.verify_local(d,tmp_path)['work']['restore_exact']


def test_changed_receipt_bytes_rejected(tmp_path,monkeypatch):
    d=local_receipt_fixture(tmp_path);read=Path.read_bytes
    def tampered(p):
        raw=read(p)
        return raw.replace(b'do not remove',b'DO NOT REMOVE') if p.name=='apply.json' else raw
    monkeypatch.setattr(Path,'read_bytes',tampered)
    with pytest.raises(ValueError,match='ASSET_IDENTITY_MISMATCH'):m.verify_local(d,tmp_path)
