"""Prepare explicitly observed, itemwise reference mechanisms; never apply or infer style."""
import copy
import tempfile
from pathlib import Path


def target_source_matches(document, reference):
    """Compare declared SHA identities, not paths, rendered use or derived content."""
    matches=[]
    groups=[('plan.sources',document['plan']['sources'])]
    groups.extend((key,{ident:item['source'] for ident,item in document.get(key,{}).items()})
                  for key in ['audio_tracks','visual_layers'])
    for group,sources in groups:
        for ident,asset in sorted(sources.items()):
            if asset['sha256']==reference['sha256']:
                matches.append({'collection':group,'id':ident,'source':copy.deepcopy(asset)})
    return matches


def result_first_draft(request, item, state, refs, tools):
    """Preflight only. Full proof/scope validation remains the existing compiler's job."""
    from editing_runtime import exact_keys, require, source, span
    require(request['scene']=='software' and item['decision']=='adapt','REFERENCE_RESULT_FIRST_ADAPT_SOFTWARE_ONLY')
    obs=item['observation'];sequence=obs.get('sequence')
    require(isinstance(sequence,list) and 2<=len(sequence)<=8,'REFERENCE_ORDER_OBSERVATIONS_REQUIRED')
    require(isinstance(obs.get('unknowns'),list) and all(isinstance(x,str) and x.strip() for x in obs['unknowns']),
            'REFERENCE_UNKNOWNS_REQUIRED')
    last=obs['start'];roles=[]
    for event in sequence:
        fields=['role','start','end','evidence','description']
        exact_keys(event,fields,fields)
        require(event['role'] in ['result-preview','process'],'REFERENCE_ORDER_ROLE_INVALID')
        a,b=span(event['start'],event['end'],obs['end'])
        require(a>=last,'REFERENCE_ORDER_INTERVALS_INVALID');last=b;roles.append(event['role'])
        require(isinstance(event['description'],str) and event['description'].strip(),'REFERENCE_ORDER_DESCRIPTION_REQUIRED')
        source(event['evidence']);refs.append(event['evidence'])
    require(roles[0]=='result-preview' and all(x=='process' for x in roles[1:]),'REFERENCE_RESULT_BEFORE_PROCESS_REQUIRED')
    params=item['parameters'];fields=['mechanism_card','tutorial','preview','shift_clip_ids','scope']
    exact_keys(params,fields,fields)
    draft={'operation':'result-preview-compile','store':request['store'],'expected_version':state['version'],**copy.deepcopy(params)}
    # The authoritative compiler validates target source, original clips, labels,
    # scope and protection. Temporary candidate/proof files are not published.
    import result_preview_ops
    with tempfile.TemporaryDirectory(prefix='reference-result-first-') as tmp:
        validation=result_preview_ops.execute(draft,Path(tmp),tools)
    refs.append(params['mechanism_card'])
    for step in params['tutorial']['steps']:
        for role in ['before','action','result']:refs.append(step[role]['evidence'])
    doc=state['document'];refs.extend(doc['plan']['sources'].values())
    if doc['caption_style']:refs.append(doc['caption_style']['font'])
    if 'evidence_protection' in doc:
        for unit in doc['evidence_protection']['units']:refs.extend([unit['source'],unit['evidence']])
    return draft,validation



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
            exact_keys(obs,keys+(['sequence','unknowns'] if item['axis']=='narrative' and item['mechanism']=='result-first' else []),keys)
            require(obs['status']=='observed' and obs['method'] in ['visual-review','audiovisual-review'],
                    'REFERENCE_OBSERVATION_METHOD_REQUIRED')
            span(obs['start'],obs['end'],media['duration'])
            require(isinstance(obs['description'],str) and obs['description'].strip(),'REFERENCE_OBSERVATION_DESCRIPTION_REQUIRED')
            source(obs['evidence']);refs.append(obs['evidence'])
        require(isinstance(item['parameters'],dict),'REFERENCE_PARAMETERS_REQUIRED')
        if item['decision']=='omit':
            require(item['parameters']=={},'REFERENCE_OMITTED_PARAMETERS_FORBIDDEN')
        else:
            require((item['axis']=='audiovisual' and item['mechanism']=='caption-presentation') or (item['axis']=='narrative' and item['mechanism']=='result-first'),
                    'REFERENCE_TRANSFER_MECHANISM_UNSUPPORTED')
            selected.append(item)
    require(len(selected)<=1,'REFERENCE_MULTIPLE_TRANSFERS_UNSUPPORTED')
    draft=None; narrative_validation=None
    if selected and selected[0]['mechanism']=='result-first':
        draft,narrative_validation=result_first_draft(request,selected[0],state,refs,tools)
    elif selected:
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
    matches=target_source_matches(state['document'],ref)
    refs.extend(match['source'] for match in matches)
    for identity in refs:source(identity)
    db=connect(request['store'])
    try:require(load(db)['version']==state['version'],'WORK_VERSION_CONFLICT')
    finally:db.close()
    report={'schema':'reference-transfer/2','scene':request['scene'],'reference':ref,'items':copy.deepcopy(items),
            'base_version':state['version'],'base_document_sha256':state['document_sha256'],
            'request_sha256':fingerprint(request),'status':'READY_FOR_DOWNSTREAM_VALIDATION' if draft else 'NO_TRANSFER_SELECTED',
            'draft_request':draft,'executed':narrative_validation is not None,'execution_kind':'TEMPORARY_COMPILER_VALIDATION_ONLY' if narrative_validation is not None else 'PREPARATION_ONLY',
            'rendered':False,'applied_to_work':False,'committed':False,'downstream_validation':'COMPILER_VALIDATED_RECHECK_BEFORE_USE' if narrative_validation is not None else 'NOT_RUN',
            'temporary_compiler_result':narrative_validation,
            'observation_truth':'Caller-declared intervals and artifact identity only; content, watching and listening not certified',
            'style_validation':'NOT_PERFORMED','narrative_transfer':'EXPLICIT_RESULT_FIRST_DRAFT_ONLY' if draft and draft['operation']=='result-preview-compile' else 'NOT_SUPPORTED',
            'reference_media_inserted_by_transfer':False,
            'reference_target_source_matches':matches,
            'reference_output_presence':'NOT_EVALUATED',
            'source_match_meaning':'Same SHA256 among current Work plan/audio/visual source identities, rechecked before publication; not actual consumption or derived-content detection. No match does not prove absence from a future output.','execution_guard':{'store':request['store'],'expected_version':state['version'],
            'require_fresh_identity_and_work_check':True,'note':'Prepared request is one explicit supported mechanism; downstream compiler and scope checks remain required. Reference order observations never prove target causality. Selection is not user authorization, aesthetic acceptance or whole-style transfer.'}}
    if draft is not None:
        report['prepared_request_sha256']=fingerprint(draft)
        write_json(directory/'prepared-request.json',draft)
    write_json(directory/'reference-transfer.json',report)
    return report
