"""Deterministic bounded presentation hypotheses, never aesthetic or authorization truth."""
import copy
import hashlib
import json
import math
from pathlib import Path


def _state(store):
    from work_ops import connect, load
    db=connect(store)
    try:return load(db)
    finally:db.close()


def _build(request):
    from editing_runtime import exact_keys, require, source, fingerprint, sha256
    fields=['operation','action','store','expected_version','brief','capabilities']
    exact_keys(request,fields+['parameters'],fields)
    require(request['operation']=='creation-recommendation' and request['action']=='recommend','RECOMMENDATION_ACTION_REQUIRED')
    state=_state(request['store'])
    require(state['version']==request['expected_version'],'WORK_VERSION_CONFLICT')
    brief=request['brief'];exact_keys(brief,['scene','goal','constraints'],['scene','goal','constraints'])
    require(brief['scene'] in ['film','speech','software'],'RECOMMENDATION_SCENE_UNSUPPORTED')
    require(brief['goal'] in ['readable-captions','preserve-original','learn-steps','narrative-impact','speech-tighten'],'RECOMMENDATION_GOAL_UNSUPPORTED')
    constraints=brief['constraints'];exact_keys(constraints,['min_font_size','max_font_size','freeze_content'],['min_font_size','max_font_size','freeze_content'])
    lo,hi=constraints['min_font_size'],constraints['max_font_size']
    require(type(lo) is int and type(hi) is int and 8<=lo<=hi<=300,'RECOMMENDATION_FONT_RANGE_INVALID')
    require(type(constraints['freeze_content']) is bool,'RECOMMENDATION_FREEZE_BOOLEAN_REQUIRED')
    capabilities=request['capabilities']
    require(isinstance(capabilities,list) and all(isinstance(x,str) for x in capabilities) and len(capabilities)==len(set(capabilities)),'RECOMMENDATION_CAPABILITIES_INVALID')
    family={'film':'film-recap','speech':'speech','software':'software'}[brief['scene']]
    card_id={'film':'causal-spine','speech':'faithful-clean','software':'guided-first-run'}[brief['scene']]
    root=Path(__file__).resolve().parents[1]
    catalog_path=root/'styles'/family/'catalog.json';raw=catalog_path.read_bytes()
    catalog=json.loads(raw.decode('utf-8'))
    matches=[x for x in catalog['styles'] if x['id']==card_id]
    require(len(matches)==1,'RECOMMENDATION_CARD_UNAVAILABLE')
    card=matches[0];card_path=root/'styles'/family/(card_id+'.md')
    card_ref={'path':str(card_path),'sha256':sha256(card_path)};source(card_ref)
    doc=state['document'];style=doc['caption_style'];issues=[];options=[]
    parameters=request.get('parameters',{});exact_keys(parameters,['tutorial','speech'],[])
    goal=brief['goal']
    if goal=='learn-steps' and brief['scene']=='software' and 'tutorial' in parameters:
        tutorial=parameters['tutorial'];exact_keys(tutorial,['steps','result_cues'],['steps','result_cues'])
        require(isinstance(tutorial['steps'],list) and tutorial['steps'] and isinstance(tutorial['result_cues'],list),'RECOMMENDATION_TUTORIAL_EVENTS_REQUIRED')
        prepared={'operation':'tutorial-plan-compile','plan':copy.deepcopy(doc['plan']),'expected_revision':fingerprint(doc['plan']),**copy.deepcopy(tutorial)}
        options.append({'id':'validate-declared-steps','score':100,'request':prepared,'reason':'Explicit tutorial steps are supplied: validate declared time windows and dependencies before editing.', 'execution':'tutorial-plan-validation-only','effect_validation':'NOT_PERFORMED'})
    if options and 'tutorial-plan-compile' not in capabilities:
        options=[];issues.append({'code':'TUTORIAL_CAPABILITY_MISSING','reason':'Explicit tutorial compiler support must be declared.'})
    if goal=='speech-tighten':
        require(brief['scene']=='speech','RECOMMENDATION_SPEECH_SCENE_REQUIRED')
        speech=parameters.get('speech',{});require(isinstance(speech,dict),'RECOMMENDATION_SPEECH_PARAMETERS_REQUIRED')
        required=['aligned_transcript','expected_transcript_revision','segments','protected_word_ids','allow_reorder','source_clip_ids']
        exact_keys(speech,required,[])
        issues.append({'code':'SPEECH_BRIEF_PREPARATION_REQUIRED','missing_fields':sorted(set(required)-set(speech)), 'reason':'Use creation-brief-prepare with fixed aligned transcript and explicit decisions. Estimated timings are not edit boundaries; this recommender never selects words.'})
    if goal in ['learn-steps','narrative-impact'] and not options:
        issues.append({'code':'EDITORIAL_MECHANISM_NOT_EXECUTABLE','reason':'Caption size cannot implement step selection, prerequisites, causal order or narrative impact.'})
    if goal in ['readable-captions','preserve-original'] and 'caption-style' not in capabilities:issues.append({'code':'CAPTION_STYLE_CAPABILITY_MISSING','reason':'Caller has not declared caption presentation support; no fallback renderer selected.'})
    if goal in ['readable-captions','preserve-original'] and (not doc['captions'] or style is None):issues.append({'code':'CAPTIONS_AND_FONT_REQUIRED','reason':'No existing captions/font to present; this recommender does not transcribe or choose a font.'})
    ceiling=min(300,int(doc['plan']['height']*.12))
    if goal in ['readable-captions','preserve-original'] and lo>ceiling:
        issues.append({'code':'FONT_RANGE_CONFLICTS_WITH_CANVAS','reason':'Minimum size exceeds conservative 12%-of-height proposal ceiling; this heuristic is not layout verification.'})
    if not issues and not options and goal in ['readable-captions','preserve-original']:
        source(style['font'])
        current=style['font_size']
        sizes=sorted(set(min(hi,ceiling,max(lo,int(math.floor(current*ratio+.5)))) for ratio in [1,1.2,1.4]))
        sizes=[n for n in sizes if n<=doc['plan']['height']]
        if len(sizes)<2:
            issues.append({'code':'INSUFFICIENT_DISTINCT_COMPARISONS','reason':'Constraints collapse font hypotheses to fewer than two distinct values; do not manufacture duplicate styles.'})
        else:
            for size in sizes:
                recipe={'schema':'style-recipe/1','id':f'{family}-caption-{size}','version':'recommendation-1',
                    'style':{'family':card['family'],'style_id':card_id,'version':card['version'],'card':card_ref},
                    'parameters':{'caption_style':{'font_size':size}}}
                score=(size-current if brief['goal']=='readable-captions' else -abs(size-current))
                options.append({'id':f'caption-{size}','score':score,'recipe':recipe,'recipe_sha256':fingerprint(recipe),
                    'reason':('Higher proposed size ranks first for the declared readability goal; not proof of legibility.' if brief['goal']=='readable-captions'
                              else 'Smallest change from current font size ranks first for the declared preservation goal.'),
                    'tradeoff':'Larger text may wrap or cover UI; current color/margins/font/text/timing unchanged. Actual preview and layout review required.',
                    'execution':'caption-presentation-only','effect_validation':'NOT_PERFORMED'})
            options.sort(key=lambda x:(-x['score'],x['id']))
    for option in options:option['option_sha256']=fingerprint(option)
    report={'schema':'creation-recommendation/1','request':copy.deepcopy(request),
        'base_document_sha256':state['document_sha256'],'base_version':state['version'],
        'catalog':{'path':str(catalog_path),'sha256':hashlib.sha256(raw).hexdigest()},
        'card':card_ref,'planning_context':{'id':card_id,'name':card['name'],'fit':card['fit'],'anti':card['anti'],'card_status':card['status'],
            'meaning':'This is a scene-related planning card, not a claim that its narrative mechanism is executed by captions.'},
        'options':options,'issues':issues,'status':'SUGGESTIONS_ONLY' if options else 'NO_EXECUTABLE_RECOMMENDATION',
        'font_proposal_ceiling_pixels':ceiling,
        'ranking_policy':'caption-hypotheses-v1; explicit goal + font range, no video/text inference, no learned preference',
        'capability_truth':'Caller-declared, not probed','constraints_interpretation':'Content stays frozen even if freeze_content=false; no broader edits implemented',
        'automatic_adoption':False,'semantic_recommendation':'NOT_PERFORMED','layout_safety':'UNKNOWN','render':'NOT_RUN'}
    source(card_ref);source({'path':str(catalog_path),'sha256':report['catalog']['sha256']})
    require(_state(request['store'])['version']==state['version'],'WORK_VERSION_CONFLICT')
    return report


def _verify_bindings(report):
    from editing_runtime import source, require
    source(report['card']);source(report['catalog'])
    state=_state(report['request']['store'])
    require(state['version']==report['base_version'] and state['document_sha256']==report['base_document_sha256'],'WORK_VERSION_CONFLICT')
    if any(x['execution']=='caption-presentation-only' for x in report['options']):
        source(state['document']['caption_style']['font'])


def _bound_report(ref):
    from editing_runtime import source, require, fingerprint
    identity=source(ref)
    require(identity['bytes']<=1024*1024,'RECOMMENDATION_REPORT_TOO_LARGE')
    with Path(identity['path']).open('rb') as handle:raw=handle.read(1024*1024+1)
    require(len(raw)<=1024*1024 and hashlib.sha256(raw).hexdigest()==identity['sha256'],'RECOMMENDATION_REPORT_BYTES_CHANGED')
    def pairs(items):
        result={}
        for key,value in items:
            require(key not in result,'RECOMMENDATION_REPORT_DUPLICATE_KEY');result[key]=value
        return result
    doc=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda _:require(False,'RECOMMENDATION_REPORT_NONFINITE'))
    require(isinstance(doc,dict) and 'request' in doc,'RECOMMENDATION_REPORT_INVALID')
    current=_build(doc['request'])
    require(fingerprint(doc)==fingerprint(current),'RECOMMENDATION_REPORT_NOT_REPRODUCIBLE')
    return doc


def execute(request,directory,tools):
    from editing_runtime import exact_keys, require, fingerprint, write_json, source
    action=request.get('action')
    if action=='recommend':
        report=_build(request);_verify_bindings(report);write_json(directory/'recommendation.json',report);return report
    require(request.get('operation')=='creation-recommendation','RECOMMENDATION_OPERATION_REQUIRED')
    if action=='select':
        fields=['operation','action','recommendation','selections']
        exact_keys(request,fields+['audio_backend','source_consumption'],fields)
    elif action=='feedback':
        fields=['operation','action','recommendation','actor_kind','ratings'];exact_keys(request,fields,fields)
    else:require(False,'RECOMMENDATION_ACTION_UNSUPPORTED')
    report=_bound_report(request['recommendation'])
    by_id={x['id']:x for x in report['options']}
    records=request['selections'] if action=='select' else request['ratings']
    require(isinstance(records,list) and records,'RECOMMENDATION_SELECTION_REQUIRED')
    require(len(records)<=3,'RECOMMENDATION_TOO_MANY_SELECTIONS')
    seen=set()
    for record in records:
        fields=['id','option_sha256']+(['dimension','verdict','reason'] if action=='feedback' else [])
        exact_keys(record,fields,fields)
        require(isinstance(record['id'],str) and record['id'] in by_id and record['id'] not in seen,'RECOMMENDATION_OPTION_UNKNOWN_OR_DUPLICATE');seen.add(record['id'])
        require(record['option_sha256']==by_id[record['id']]['option_sha256'],'RECOMMENDATION_RECIPE_BINDING_MISMATCH')
        if action=='feedback':
            require(record['dimension'] in ['readability','occlusion','style-fit','step-coverage'] and record['verdict'] in ['prefer','avoid','undecided'] and isinstance(record['reason'],str) and record['reason'].strip(),'RECOMMENDATION_FEEDBACK_INVALID')
    current=_state(report['request']['store'])
    require(current['version']==report['base_version'],'WORK_VERSION_CONFLICT')
    if action=='select':
        selected_options=[by_id[x['id']] for x in records]
        tutorial_selection=len(selected_options)==1 and selected_options[0]['execution']=='tutorial-plan-validation-only'
        require(tutorial_selection or (2<=len(records)<=3 and all(x['execution']=='caption-presentation-only' for x in selected_options)),'RECOMMENDATION_COMPARE_REQUIRES_2_TO_3_OR_ONE_TUTORIAL')
        scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],'style_keys':['*'],'note_keys':[],'output_fields':[],
            'caption_style':True,'freeze_positions':[x['id'] for x in current['document']['plan']['clips']],'freeze_duration':True}
        prepared=copy.deepcopy(selected_options[0]['request']) if tutorial_selection else {'operation':'style-recipe-preview','store':report['request']['store'],'expected_version':report['base_version'],
            'variants':[{'id':item['id'],'recipe':copy.deepcopy(by_id[item['id']]['recipe']),
                'expected_recipe_sha256':by_id[item['id']]['recipe_sha256'],'capabilities':['caption-style'],'scope':copy.deepcopy(scope)} for item in records],
            **{k:copy.deepcopy(request[k]) for k in ['audio_backend','source_consumption'] if k in request}}
        source(request['recommendation']);_verify_bindings(report)
        require(_state(report['request']['store'])['version']==report['base_version'],'WORK_VERSION_CONFLICT')
        write_json(directory/'prepared-request.json',prepared)
        result={'schema':'creation-recommendation-selection/1','base_version':report['base_version'],
            'recommendation':request['recommendation'],'selections':records,'prepared_request':prepared,
            'prepared_request_fingerprint':fingerprint(prepared),'execution_guard':{'store':report['request']['store'],'expected_version':report['base_version'],'require_fresh_head_read':True,'adoption':'Independent tutorial plan has no Work CAS; apply only through timeline-revise with scope and dependent mappings'},'executed':False,'committed':False,'status':'READY_FOR_DOWNSTREAM_VALIDATION'}
        write_json(directory/'selection.json',result);return result
    require(request['actor_kind'] in ['agent-observation','user-reported'],'RECOMMENDATION_FEEDBACK_ACTOR_INVALID')
    result={'schema':'creation-recommendation-feedback/1','recommendation':request['recommendation'],
        'base_version':report['base_version'],'base_document_sha256':report['base_document_sha256'],
        'actor_kind':request['actor_kind'],'ratings':copy.deepcopy(records),'identity_verified':False,
        'scope':'Unverified attributed feedback, not proof a preview was watched, not user authorization or learned preference',
        'adopted':False,'ranking_updated':False}
    source(request['recommendation']);_verify_bindings(report);require(_state(report['request']['store'])['version']==report['base_version'],'WORK_VERSION_CONFLICT');write_json(directory/'feedback.json',result);return result
