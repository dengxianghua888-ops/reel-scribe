"""Prepare explicit Agent-parsed briefs. No language inference, authorization or execution."""
import copy
import re


def execute(request, directory, tools):
    from editing_runtime import exact_keys, require, fingerprint, source, write_json
    from work_ops import connect, load
    fields=['operation','query','brief','store','expected_version','parameters']
    exact_keys(request,fields,fields)
    require(request['operation']=='creation-brief-prepare','BRIEF_OPERATION_UNSUPPORTED')
    query=request['query']
    require(isinstance(query,str) and query.strip(),'BRIEF_QUERY_REQUIRED')
    brief=request['brief']; exact_keys(brief,['scene','mode','intent','provenance'],['scene','mode','intent','provenance'])
    require(brief['scene'] in ['film','speech','software'],'BRIEF_SCENE_UNSUPPORTED')
    require(brief['mode'] in ['ANALYZE','PLAN','PRODUCE','EDITABLE','REVISION'],'BRIEF_MODE_UNSUPPORTED')
    require(brief['intent'] in ['caption-presentation','tutorial-plan-validation','speech-tighten','narrative-edit'],'BRIEF_INTENT_UNSUPPORTED')
    provenance=brief['provenance']; keys=['scene','mode','intent','parameters'];exact_keys(provenance,keys,keys)
    for entry in provenance.values():
        require(isinstance(entry,dict),'BRIEF_PROVENANCE_REQUIRED')
        if entry.get('kind')=='query':
            exact_keys(entry,['kind','start','end','quote'],['kind','start','end','quote'])
            a,b=entry['start'],entry['end']
            require(type(a) is int and type(b) is int and 0<=a<b<=len(query) and
                    isinstance(entry['quote'],str) and entry['quote'].strip() and query[a:b]==entry['quote'],
                    'BRIEF_QUERY_SLICE_MISMATCH')
        else:
            exact_keys(entry,['kind','description'],['kind','description'])
            require(entry['kind']=='context' and isinstance(entry['description'],str) and entry['description'].strip(),
                    'BRIEF_CONTEXT_DESCRIPTION_REQUIRED')
    db=connect(request['store'])
    try:state=load(db)
    finally:db.close()
    require(state['version']==request['expected_version'],'WORK_VERSION_CONFLICT')
    parameters=request['parameters'];require(isinstance(parameters,dict),'BRIEF_PARAMETERS_OBJECT_REQUIRED')
    issues=[]; draft=None
    intent=brief['intent']
    if intent=='caption-presentation':
        exact_keys(parameters,['variants','audio_backend','source_consumption'],[])
        variants=parameters.get('variants')
        if not variants:issues.append({'code':'CAPTION_VARIANTS_REQUIRED','detail':'Supply 2–4 explicit caption-only recipes, capabilities and scope; no style parameters inferred.'})
        elif not state['document']['captions'] or state['document']['caption_style'] is None:
            issues.append({'code':'EXISTING_CAPTIONS_AND_FONT_REQUIRED','detail':'This path formats existing captions, not ASR, text writing or font selection.'})
        else:
            require(isinstance(variants,list) and 2<=len(variants)<=4,'BRIEF_REQUIRES_2_TO_4_VARIANTS')
            ids=[]
            for v in variants:
                exact_keys(v,['id','recipe','expected_recipe_sha256','capabilities','scope'],['id','recipe','expected_recipe_sha256','capabilities','scope'])
                require(isinstance(v['id'],str) and re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,63}',v['id']),'BRIEF_VARIANT_ID_INVALID');ids.append(v['id'])
                recipe=v['recipe'];require(isinstance(recipe,dict),'BRIEF_RECIPE_REQUIRED')
                require(fingerprint(recipe)==v['expected_recipe_sha256'],'RECIPE_REVISION_CONFLICT')
                rp=recipe.get('parameters')
                require(isinstance(rp,dict) and set(rp)=={'caption_style'},'BRIEF_CAPTION_ONLY_PARAMETERS_REQUIRED')
                require(isinstance(rp['caption_style'],dict) and rp['caption_style'] and
                        set(rp['caption_style'])<= {'font_size','margin_v','color_rgb'},'BRIEF_CAPTION_PARAMETERS_UNSUPPORTED')
                require(v['capabilities']==['caption-style'],'BRIEF_CAPTION_ONLY_CAPABILITY_REQUIRED')
                style=recipe.get('style');require(isinstance(style,dict) and 'card' in style,'BRIEF_STYLE_CARD_REQUIRED')
                source(style['card'])
                scope=v['scope']
                required=['clip_ids','source_ids','caption_ids','audio_ids','style_keys','note_keys','output_fields','caption_style','freeze_positions','freeze_duration']
                exact_keys(scope,required+['visual_ids','evidence_mapping'],required)
                require(all(scope[k]==[] for k in ['clip_ids','source_ids','caption_ids','audio_ids','note_keys','output_fields']) and
                        scope.get('visual_ids',[])==[] and scope.get('evidence_mapping',False) is False and
                        scope['style_keys']==['*'] and scope['caption_style'] is True and scope['freeze_duration'] is True,
                        'BRIEF_CAPTION_SCOPE_TOO_BROAD')
                frozen=scope['freeze_positions'];clip_ids=[c['id'] for c in state['document']['plan']['clips']]
                require(isinstance(frozen,list) and all(isinstance(x,str) for x in frozen) and
                        len(frozen)==len(set(frozen)) and set(frozen)==set(clip_ids),'BRIEF_CAPTION_POSITIONS_NOT_FROZEN')
            require(len(ids)==len(set(ids)),'BRIEF_DUPLICATE_VARIANT_ID')
            draft={'operation':'style-recipe-preview','store':request['store'],'expected_version':state['version'],**copy.deepcopy(parameters)}
    elif intent=='tutorial-plan-validation':
        require(brief['scene']=='software','BRIEF_TUTORIAL_SCENE_REQUIRED')
        exact_keys(parameters,['steps','result_cues'],[])
        if not parameters.get('steps') or 'result_cues' not in parameters:
            issues.append({'code':'TUTORIAL_EXPLICIT_EVENTS_REQUIRED','detail':'Supply explicit before/action/result windows and result_cues, not inferred UI events.'})
        else:
            require(isinstance(parameters['steps'],list) and isinstance(parameters['result_cues'],list),'BRIEF_TUTORIAL_ARRAYS_REQUIRED')
            draft={'operation':'tutorial-plan-compile','plan':copy.deepcopy(state['document']['plan']),
                   'expected_revision':fingerprint(state['document']['plan']),**copy.deepcopy(parameters)}
    elif intent=='speech-tighten':
        exact_keys(parameters,['aligned_transcript'],[])
        if 'aligned_transcript' not in parameters:
            issues.append({'code':'REVIEWED_WORD_ALIGNMENT_REQUIRED','detail':'A readable transcript alone cannot authorize word-level cuts; supply reviewed alignment and explicit keep/cut decisions to speech workflow.'})
        else:
            source(parameters['aligned_transcript'])
            issues.append({'code':'SPEECH_EDIT_DECISIONS_NOT_IMPLEMENTED','detail':'Attached alignment identity is recorded, not certified accurate; prepare reviewed word selections through raven-speech-edit.'})
    else:
        exact_keys(parameters,[],[])
        issues.append({'code':'EDITORIAL_DECISION_REQUIRED','detail':'Choose supported source beats, order and reveal limits through the scene workflow; no narrative inferred from a style name.'})
    db=connect(request['store'])
    try:require(load(db)['version']==state['version'],'WORK_VERSION_CONFLICT')
    finally:db.close()
    planning=brief['mode'] in ['ANALYZE','PLAN']
    report={'schema':'creation-brief/1','query':query,'brief':copy.deepcopy(brief),
        'provenance_semantics':'Exact text location/context description only; not semantic interpretation or authorization verification',
        'workflow':{'film':'raven-film-recap','speech':'raven-speech-edit','software':'raven-software-tutorial'}[brief['scene']],
        'base_version':state['version'],'base_document_sha256':state['document_sha256'],
        'parameters_sha256':fingerprint(parameters),'issues':issues,
        'status':'BLOCKED' if issues else ('PLANNING_ONLY' if planning else 'READY_FOR_DOWNSTREAM_VALIDATION'),
        'executed':False,'committed':False,'draft_request':draft,
        'execution_guard':{'store':request['store'],'expected_version':state['version'],
                           'require_fresh_work_read_before_execution':True,
                           'note':'tutorial-plan-compile validates an immutable plan, not current Work CAS; never treat its success as an applied edit'},
        'semantic_recommendation':'NOT_PERFORMED','downstream_validation':'NOT_RUN'}
    if draft is not None and not planning:
        write_json(directory/'prepared-request.json',draft)
        report['prepared_request_sha256']=fingerprint(draft)
    write_json(directory/'creation-brief.json',report)
    return report
