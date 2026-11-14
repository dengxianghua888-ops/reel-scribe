#!/usr/bin/env python3
"""Read-only case/evidence verification; never assigns semantic acceptance."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re


def require(value,message):
    if not value:raise ValueError(message)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def validate(data):
    require(isinstance(data,dict),'MANIFEST_OBJECT_REQUIRED')
    require(data.get('schema')=='evaluation-cases/1','SCHEMA_INVALID')
    require(all(isinstance(data.get(k),dict) for k in ['sources','evidence','work_receipt_keys']),'MANIFEST_DICTIONARIES_REQUIRED')
    require(isinstance(data.get('cases'),list) and all(isinstance(c,dict) and isinstance(c.get('id'),str) for c in data['cases']),'CASE_OBJECTS_REQUIRED')
    cases=data['cases'];sources=data['sources'];evidence=data['evidence']
    require(not (sources.keys() & evidence.keys()),'SOURCE_EVIDENCE_KEY_CONFLICT')
    require(len(cases)==9 and len({c['id'] for c in cases})==9,'NINE_UNIQUE_CASES_REQUIRED')
    require({(c['category'],c['difficulty']) for c in cases}=={
        (a,b) for a in ['narrative','speech','software'] for b in ['normal','complex','misleading']},'GRID_INCOMPLETE')
    for collection in [sources,evidence]:
        for ref in collection.values():
            path=Path(ref['asset_path'])
            require(not path.is_absolute() and '..' not in path.parts,'RELATIVE_ASSET_REQUIRED')
            require(re.fullmatch('[0-9a-f]{64}',ref['sha256']) is not None,'HASH_INVALID')
            require(type(ref['bytes']) is int and ref['bytes']>0,'SIZE_INVALID')
    for case in cases:
        source=sources[case['source_id']];a,b=case['window_seconds']
        require(all(type(x) in (int,float) and math.isfinite(x) for x in [a,b,source['duration_seconds']])
                and 0<=a<b<=source['duration_seconds'],'WINDOW_INVALID')
        require(case['semantic_acceptance']=='NOT_RUN' and case['listening_review']=='NOT_RUN'
                and case['word_timing_gold'] is False,'UNSUPPORTED_SEMANTIC_CLAIM')
        require(case['status'] in {'TECHNICAL_ONLY','NEEDS_SEMANTIC_REVIEW','OBSERVED_FAILURE'},'STATUS_INVALID')
        for field in ['text','evidence_basis','dependencies','expected','runnable_mechanism','unknown']:
            require(bool(case.get(field)),'MISSING_CASE_CONTEXT: '+field)
        require(all(x in evidence for x in case['evidence_refs']),'UNKNOWN_EVIDENCE')
    require(set(data['work_receipt_keys'])=={'init','apply','restore','stale'},'WORK_RECEIPTS_REQUIRED')
    require(all(v in evidence for v in data['work_receipt_keys'].values()),'UNKNOWN_WORK_EVIDENCE')
    return {'schema':'PASS','case_count':9,'semantic_acceptance':'NOT_RUN'}


def verify_work(receipts):
    for key in ['init','apply','restore']:
        require(receipts[key]['status']=='SUCCEEDED','WORK_RECEIPT_NOT_SUCCEEDED')
    initial,applied,restored=[receipts[k]['result'] for k in ['init','apply','restore']]
    require(receipts['stale']['status']=='FAILED' and receipts['stale']['error']=='WORK_VERSION_CONFLICT','STALE_CAS_NOT_REJECTED')
    for key in ['plan','captions','audio_tracks','notes']:
        require(initial['document'][key]==applied['document'][key],'PROTECTED_CONTENT_CHANGED: '+key)
    require(initial['document']==restored['document'],'RESTORE_NOT_EXACT')
    require(len({x['version'] for x in [initial,applied,restored]})==3,'RESTORE_HISTORY_NOT_NEW')
    return {'status':'VERIFIED_EXISTING_TECHNICAL_EVIDENCE','protected_fields':['plan','captions','audio_tracks','notes'],
            'restore_exact':True,'stale_cas_rejected':True,'new_render':'NOT_RUN','semantic_acceptance':'NOT_RUN'}


def verify_local(data,root):
    root=Path(root).resolve();missing=[];parsed={}
    require(not (data['sources'].keys() & data['evidence'].keys()),'SOURCE_EVIDENCE_KEY_CONFLICT')
    receipt_keys=set(data['work_receipt_keys'].values())
    # Media are stream-hashed. Evidence is read exactly once, and any receipt
    # is decoded from those same size/hash-verified bytes, never a later read.
    for kind,collection in [('source',data['sources']),('evidence',data['evidence'])]:
        for key,ref in collection.items():
            path=(root/ref['asset_path']).resolve()
            require(path.is_relative_to(root),'ASSET_ESCAPES_ROOT')
            if not path.is_file():missing.append(ref['asset_path']);continue
            if kind=='source':
                require(path.stat().st_size==ref['bytes'] and digest(path)==ref['sha256'],
                        'ASSET_IDENTITY_MISMATCH: '+key)
            else:
                raw=path.read_bytes()
                require(len(raw)==ref['bytes'] and hashlib.sha256(raw).hexdigest()==ref['sha256'],
                        'ASSET_IDENTITY_MISMATCH: '+key)
                if key in receipt_keys:parsed[key]=json.loads(raw)
    if missing:return {'status':'NOT_RUN_MISSING_ASSETS','missing':missing,'semantic_acceptance':'NOT_RUN'}
    receipts={key:parsed[ref] for key,ref in data['work_receipt_keys'].items()}
    return {'status':'LOCAL_IDENTITIES_VERIFIED','work':verify_work(receipts),'semantic_acceptance':'NOT_RUN'}


def load_manifest(path):
    def unique_pairs(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'DUPLICATE_JSON_KEY: '+key)
            result[key]=value
        return result
    return json.loads(Path(path).read_bytes(),object_pairs_hook=unique_pairs)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest');parser.add_argument('--asset-root')
    args=parser.parse_args();data=load_manifest(args.manifest)
    result=validate(data)
    if args.asset_root:result['local']=verify_local(data,args.asset_root)
    else:result['local']={'status':'NOT_RUN_NO_ASSET_ROOT'}
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 2 if result['local']['status'].startswith('NOT_RUN') else 0

if __name__=='__main__':raise SystemExit(main())
