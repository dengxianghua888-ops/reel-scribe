"""Prepare explicitly observed, itemwise reference mechanisms; never apply or infer style."""
import copy
import json
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
    if "composition" in request:
        return compose(request, directory, tools)
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


def compose(request, directory, tools):
    """Explicit two-reference compile; no automatic scope union or Work commit."""
    from editing_runtime import exact_keys, require, source, fingerprint, write_json
    from work_ops import connect, load, work_version, timeline_revise
    import result_preview_ops
    import style_recipe_ops
    fields=['operation','composition','store','expected_version','scene','stages',
            'selected_caption_variant_id','final_scope']
    exact_keys(request,fields,fields)
    require(request['operation']=='reference-transfer-prepare' and
            request['composition']=='result-first-then-caption', 'REFERENCE_COMPOSITION_UNSUPPORTED')
    require(request['scene']=='software','REFERENCE_COMPOSITION_SOFTWARE_ONLY')
    stages=request['stages']
    require(isinstance(stages,list) and len(stages)==2,'REFERENCE_COMPOSITION_TWO_STAGES_REQUIRED')
    for stage,mechanism,axis in zip(stages,['result-first','caption-presentation'],['narrative','audiovisual']):
        exact_keys(stage,['reference','items'],['reference','items'])
        require(isinstance(stage['items'],list) and len(stage['items'])==1,'REFERENCE_COMPOSITION_ONE_ITEM_PER_STAGE')
        item=stage['items'][0]
        require(isinstance(item,dict) and item.get('mechanism')==mechanism and
                item.get('axis')==axis and item.get('decision')=='adapt','REFERENCE_COMPOSITION_ORDER_OR_DECISION')
    refs=[source(s['reference']) for s in stages]
    require(refs[0]['sha256']!=refs[1]['sha256'],'REFERENCE_COMPOSITION_DISTINCT_MEDIA_REQUIRED')
    db=connect(request['store'])
    try:state=load(db)
    finally:db.close()
    require(state['version']==request['expected_version'],'WORK_VERSION_CONFLICT')
    original=state['document']
    require(not original.get('evidence_protection') or request['final_scope'].get('evidence_mapping') is True,
            'REFERENCE_COMPOSITION_FINAL_EVIDENCE_MAPPING_REQUIRED')
    def recheck(value, seen=None):
        if seen is None:seen=set()
        if isinstance(value,dict):
            if 'path' in value and 'sha256' in value:
                identity=(value['path'],value['sha256'])
                if identity not in seen:
                    source({k:value[k] for k in ['path','sha256']});seen.add(identity)
            for child in value.values():recheck(child,seen)
        elif isinstance(value,list):
            for child in value:recheck(child,seen)
    recheck([request,original])
    # All temporary Work versions and requests stay inside this scratch area.
    # Only immutable documents and non-executable summaries are published below.
    with tempfile.TemporaryDirectory(prefix='reference-composition-') as tmp:
        root=Path(tmp)
        def folder(name):
            path=root/name;path.mkdir();return path
        common={'operation':'reference-transfer-prepare','scene':'software'}
        a=execute({**common,'store':request['store'],'expected_version':state['version'],
                   **copy.deepcopy(stages[0])},folder('reference-a'),tools)
        a_dir=folder('narrative')
        a_result=result_preview_ops.execute(a['draft_request'],a_dir,tools)
        intermediate=json.loads((a_dir/'candidate.json').read_text())['document']
        temporary_store=root/'intermediate.sqlite'
        mid=work_version({'operation':'work-version','action':'init','store':str(temporary_store),
                         'work_id':'reference-composition-intermediate','document':intermediate,
                         'author':'agent','message':'Temporary explicit intermediate; original Work untouched'},folder('init'),tools)
        b=execute({**common,'store':str(temporary_store),'expected_version':mid['version'],
                   **copy.deepcopy(stages[1])},folder('reference-b'),tools)
        variants=b['draft_request']['variants']
        # This first composition supports global caption presentation only.
        # In particular, preserving an audio declaration is not authorization to change it.
        require(all(set(v['recipe']['parameters'])=={'caption_style'} and
                    v['capabilities']==['caption-style'] for v in variants),
                'REFERENCE_COMPOSITION_GLOBAL_CAPTION_ONLY')
        selected=[v for v in variants if v['id']==request['selected_caption_variant_id']]
        require(len(selected)==1,'REFERENCE_COMPOSITION_SELECTED_VARIANT_UNKNOWN')
        variant=selected[0];b_dir=folder('presentation')
        b_result=style_recipe_ops.execute({'operation':'style-recipe-compile',
            'base_version':state['version'],'document':intermediate,
            'expected_document_sha256':fingerprint(intermediate),
            **{k:copy.deepcopy(variant[k]) for k in ['recipe','expected_recipe_sha256','capabilities','scope']}},b_dir,tools)
        final=json.loads((b_dir/'candidate.json').read_text())['document']
        require({k:v for k,v in final.items() if k not in ['caption_style','style_bindings']}==
                {k:v for k,v in intermediate.items() if k not in ['caption_style','style_bindings']},
                'REFERENCE_COMPOSITION_CONTENT_CHANGED')
        final_dir=folder('final')
        final_diff=timeline_revise({'operation':'timeline-revise','base_version':state['version'],
            'document':original,'expected_document_sha256':state['document_sha256'],
            'candidate':final,'scope':request['final_scope']},final_dir,tools)
        bundle=json.loads((final_dir/'candidate.json').read_text())
        recheck([request,original,final])
        db=connect(request['store'])
        try:current=load(db)
        finally:db.close()
        require(current['version']==state['version'] and
                current['document_sha256']==state['document_sha256'],'WORK_VERSION_CONFLICT')
        # Preserve generated proof bytes; never expose deleted scratch references.
        import hashlib
        import os
        from editing_runtime import sha256
        def publish_ref(value):
            src=Path(value['path'])
            require(src.is_relative_to(root) and not src.is_symlink() and
                    not any(parent.is_symlink() for parent in src.parents if parent.is_relative_to(root)),
                    'REFERENCE_COMPOSITION_UNSAFE_EVIDENCE')
            if src.is_relative_to(b_dir):
                destination=directory/'stage-b-evidence'/src.relative_to(b_dir)
            else:
                require(src.is_relative_to(a_dir),'REFERENCE_COMPOSITION_TEMP_REFERENCE_UNSUPPORTED')
                destination=directory/'stage-a-evidence'/src.relative_to(a_dir)
            require(not any(parent.is_symlink() for parent in destination.parents if parent.is_relative_to(directory)),
                    'REFERENCE_COMPOSITION_UNSAFE_EVIDENCE')
            destination.parent.mkdir(parents=True,exist_ok=True)
            fd=os.open(src,os.O_RDONLY|os.O_NOFOLLOW)
            with os.fdopen(fd,'rb') as stream:payload=stream.read()
            require(hashlib.sha256(payload).hexdigest()==value['sha256'],'REFERENCE_COMPOSITION_LAYOUT_CHANGED')
            fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb') as stream:stream.write(payload)
            require(sha256(destination)==value['sha256'],'REFERENCE_COMPOSITION_EVIDENCE_COPY_CHANGED')
            value['path']=str(destination.resolve())
        layout=b_result['caption_layout']
        if layout['status']=='STATIC_GLYPH_COVERAGE_VERIFIED':
            for observation in layout['observations']:
                folder=Path(observation['mask']['path']).parent
                observation['padded_mask']={'path':str(folder/'padded.png'),'sha256':observation['padded_mask_sha256']}
                observation['padded_ass']={'path':str(folder/'padded.ass'),'sha256':sha256(folder/'padded.ass')}
            font_folder=b_dir/'layout/fonts'
            layout['font_artifacts']=[{'path':str(p),'sha256':sha256(p)} for p in sorted(font_folder.iterdir())]
        a_result['proof_artifacts']=[{'path':str(a_dir/name),'sha256':sha256(a_dir/name)}
            for name in ['base-protection-map.json','candidate-protection-map.json'] if (a_dir/name).exists()]
        def publish_evidence(value):
            if isinstance(value,dict):
                if isinstance(value.get('path'),str) and Path(value['path']).is_relative_to(root):
                    require(set(value)=={'path','sha256'},'REFERENCE_COMPOSITION_TEMP_REFERENCE_UNSUPPORTED')
                    publish_ref(value)
                for child in value.values():publish_evidence(child)
            elif isinstance(value,list):
                for child in value:publish_evidence(child)
        publish_evidence(a_result);publish_evidence(b_result)
        report={'schema':'reference-composition/1','status':'CANDIDATE_COMPILED',
            'composition':request['composition'],'request_sha256':fingerprint(request),
            'base_version':state['version'],'base_document_sha256':state['document_sha256'],
            'intermediate_document_sha256':fingerprint(intermediate),'candidate_document_sha256':fingerprint(final),
            'selected_caption_variant_id':variant['id'],
            'stage_order':['result-first','caption-presentation'],
            'stages':[{'reference':refs[0],'items':copy.deepcopy(stages[0]['items']),
                       'input_document_sha256':state['document_sha256'],'output_document_sha256':fingerprint(intermediate),
                       'result':a_result},
                      {'reference':refs[1],'items':copy.deepcopy(stages[1]['items']),
                       'input_document_sha256':fingerprint(intermediate),'output_document_sha256':fingerprint(final),
                       'result':b_result}],
            'final_scope':copy.deepcopy(request['final_scope']),'changes':final_diff,
            'intermediate_artifact':'intermediate-document.json',
            'applied_to_work':False,'committed':False,'rendered':False,
            'observation_truth':'Caller-declared observations and bound bytes; no listening, meaning or preference certification',
            'style_validation':'NOT_PERFORMED','external_reference_sources_imported':False,
            'reference_source_matches_in_target':[target_source_matches(original,ref) for ref in refs],
            'reference_source_matches_in_candidate':[target_source_matches(final,ref) for ref in refs],
            'insertion_scope':'No external reference source is imported. The result preview repeats an existing target source window; a target source may itself match either reference. Source identity matches are not actual output consumption proof.',
            'reference_output_presence':'NOT_EVALUATED',
            'execution_guard':'Final candidate binds original Work; adoption must recheck current version, sources and scope. No temporary store dependency.'}
    write_json(directory/'intermediate-document.json',intermediate)
    write_json(directory/'candidate.json',bundle)
    write_json(directory/'revision-diff.json',final_diff)
    write_json(directory/'reference-composition.json',report)
    return report
