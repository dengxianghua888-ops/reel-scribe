"""Prepare explicitly observed, itemwise reference mechanisms; never apply or infer style."""
import copy
import tempfile
from pathlib import Path


def execute(request, directory, tools):
    from editing_runtime import exact_keys, require, source, span, fingerprint, write_json
    from work_ops import connect, load
    import creation_brief_ops
    fields=['operation','store','expected_version','scene','reference','items']
    exact_keys(request,fields,fields)
    require(request['operation']=='reference-transfer-prepare','REFERENCE_OPERATION_UNSUPPORTED')
    require(request['scene'] in ['film','speech','software'],'REFERENCE_SCENE_UNSUPPORTED')
    db=connect(request['store'])
    try:state=load(db)
    finally:db.close()
    require(state['version']==request['expected_version'],'WORK_VERSION_CONFLICT')
    ref=source(request['reference']);media=tools.probe(ref['path'])
    require(any(s['codec_type']=='video' for s in media['streams']),'REFERENCE_VIDEO_REQUIRED')
    items=request['items'];require(isinstance(items,list) and 1<=len(items)<=32,'REFERENCE_ITEMS_REQUIRED')
    ids=set();selected=[];refs=[request['reference']]
    for item in items:
        keys=['id','axis','mechanism','decision','reason','observation','parameters']
        exact_keys(item,keys,keys)
        require(isinstance(item['id'],str) and item['id'].strip() and item['id'] not in ids,'REFERENCE_ITEM_ID_INVALID')
        ids.add(item['id'])
        require(item['axis'] in ['narrative','audiovisual'],'REFERENCE_AXIS_INVALID')
        require(isinstance(item['mechanism'],str) and item['mechanism'].strip(),'REFERENCE_MECHANISM_REQUIRED')
        require(item['decision'] in ['adopt','adapt','omit'],'REFERENCE_DECISION_REQUIRED')
        require(isinstance(item['reason'],str) and item['reason'].strip(),'REFERENCE_REASON_REQUIRED')
        obs=item['observation'];require(isinstance(obs,dict),'REFERENCE_OBSERVATION_REQUIRED')
        if obs.get('status')=='unobserved':
            exact_keys(obs,['status'],['status'])
            require(item['decision']=='omit','REFERENCE_UNOBSERVED_TRANSFER_FORBIDDEN')
        else:
            keys=['status','start','end','method','evidence','description']
            exact_keys(obs,keys,keys)
            require(obs['status']=='observed' and obs['method'] in ['visual-review','audiovisual-review'],
                    'REFERENCE_OBSERVATION_METHOD_REQUIRED')
            span(obs['start'],obs['end'],media['duration'])
            require(isinstance(obs['description'],str) and obs['description'].strip(),'REFERENCE_OBSERVATION_DESCRIPTION_REQUIRED')
            source(obs['evidence']);refs.append(obs['evidence'])
        require(isinstance(item['parameters'],dict),'REFERENCE_PARAMETERS_REQUIRED')
        if item['decision']=='omit':
            require(item['parameters']=={},'REFERENCE_OMITTED_PARAMETERS_FORBIDDEN')
        else:
            require(item['axis']=='audiovisual' and item['mechanism']=='caption-presentation',
                    'REFERENCE_TRANSFER_MECHANISM_UNSUPPORTED')
            selected.append(item)
    require(len(selected)<=1,'REFERENCE_MULTIPLE_TRANSFERS_UNSUPPORTED')
    draft=None
    if selected:
        item=selected[0]
        # Reuse the existing caption-only preparation boundary, not the renderer.
        params=item['parameters']
        exact_keys(params,['variants'],['variants'])
        query='Explicit reference mechanism selection; not an authorization or observation certificate.'
        brief={'operation':'creation-brief-prepare','query':query,'store':request['store'],
               'expected_version':state['version'],'brief':{'scene':request['scene'],'mode':'REVISION',
               'intent':'caption-presentation','provenance':{k:{'kind':'context','description':'Explicit reference item '+item['id']}
               for k in ['scene','mode','intent','parameters']}},'parameters':copy.deepcopy(params)}
        with tempfile.TemporaryDirectory(prefix='reference-caption-') as tmp:
            prepared=creation_brief_ops.execute(brief,Path(tmp),tools)
        require(prepared['status']=='READY_FOR_DOWNSTREAM_VALIDATION','REFERENCE_CAPTION_PREPARATION_BLOCKED')
        draft=prepared['draft_request']
        for v in params['variants']:refs.append(v['recipe']['style']['card'])
    for identity in refs:source(identity)
    db=connect(request['store'])
    try:require(load(db)['version']==state['version'],'WORK_VERSION_CONFLICT')
    finally:db.close()
    report={'schema':'reference-transfer/1','scene':request['scene'],'reference':ref,'items':copy.deepcopy(items),
            'base_version':state['version'],'base_document_sha256':state['document_sha256'],
            'request_sha256':fingerprint(request),'status':'READY_FOR_DOWNSTREAM_VALIDATION' if draft else 'NO_TRANSFER_SELECTED',
            'draft_request':draft,'executed':False,'committed':False,'downstream_validation':'NOT_RUN',
            'observation_truth':'Caller-declared intervals and artifact identity only; content, watching and listening not certified',
            'style_validation':'NOT_PERFORMED','narrative_transfer':'NOT_SUPPORTED',
            'reference_media_in_output':False,'execution_guard':{'store':request['store'],'expected_version':state['version'],
            'require_fresh_identity_and_work_check':True,'note':'Prepared request is only caption presentation. Selection is not user authorization, aesthetic acceptance or whole-style transfer.'}}
    if draft is not None:
        report['prepared_request_sha256']=fingerprint(draft)
        write_json(directory/'prepared-request.json',draft)
    write_json(directory/'reference-transfer.json',report)
    return report
