"""Declared tutorial artifact inspections; byte linkage is not backend success."""
import copy
from fractions import Fraction
from pathlib import Path


def _file(ref):
    from editing_runtime import exact_keys, require, source
    exact_keys(ref,['path','sha256'],['path','sha256'])
    require(isinstance(ref['path'],str) and Path(ref['path']).is_absolute(),'ARTIFACT_LOCAL_ABSOLUTE_FILE_REQUIRED')
    path=Path(ref['path'])
    require(not any(p.is_symlink() for p in [path,*path.parents]),'ARTIFACT_SYMLINK_UNSUPPORTED')
    require(path.is_file(),'ARTIFACT_REGULAR_FILE_REQUIRED')
    return source(ref)


def execute(request,directory,tools):
    from editing_runtime import exact_keys, require, fingerprint, normalize_plan, span, number, write_json
    from tutorial_ops import compile_tutorial
    fields=['operation','plan','expected_revision','tutorial','checks','artifact_cues']
    exact_keys(request,fields,fields)
    require(request['operation']=='tutorial-artifact-check','ARTIFACT_CHECK_OPERATION_REQUIRED')
    plan=request['plan'];require(fingerprint(plan)==request['expected_revision'],'PLAN_REVISION_CONFLICT')
    tutorial=request['tutorial'];exact_keys(tutorial,['steps','result_cues'],['steps','result_cues'])
    checks=request['checks'];require(isinstance(checks,list) and 1<=len(checks)<=64,'ARTIFACT_CHECKS_REQUIRED')
    cues=request['artifact_cues'];require(isinstance(cues,list) and len(cues)<=128,'ARTIFACT_CUES_INVALID')
    refs=[]
    def bind(ref):
        identity=_file(ref);refs.append(copy.deepcopy(ref));return identity
    require(isinstance(plan,dict) and isinstance(plan.get('sources'),dict),'PLAN_SOURCES_REQUIRED')
    for ref in plan['sources'].values():bind(ref)
    require(isinstance(tutorial['steps'],list),'STEPS_REQUIRED')
    for step in tutorial['steps']:
        require(isinstance(step,dict),'STEP_REQUIRED')
        for role in ['before','action','result']:
            require(isinstance(step.get(role),dict) and 'evidence' in step[role],'EVENT_EVIDENCE_REQUIRED')
            bind(step[role]['evidence'])
    delegated=directory/'tutorial-validation';delegated.mkdir()
    proof=compile_tutorial({'operation':'tutorial-plan-compile','plan':plan,'expected_revision':request['expected_revision'],**tutorial},delegated,tools)
    normalized=normalize_plan(plan,tools)
    clips={c['id']:c for c in normalized['clips']};steps={s['id']:s for s in proof['steps']}
    mapped=[];ids=set()
    for check in checks:
        required=['id','step_id','input_artifacts','result_artifact','inspection','observation']
        exact_keys(check,required,required)
        ident=check['id'];require(isinstance(ident,str) and 0<len(ident)<=128 and ident not in ids,'ARTIFACT_CHECK_ID_INVALID');ids.add(ident)
        require(isinstance(check['step_id'],str) and check['step_id'] in steps,'ARTIFACT_STEP_UNKNOWN')
        inputs=check['input_artifacts'];require(isinstance(inputs,list) and len(inputs)<=16,'ARTIFACT_INPUTS_INVALID')
        input_refs=[bind(ref) for ref in inputs]
        result=bind(check['result_artifact']) if check['result_artifact'] is not None else None
        observation=check['observation'];exact_keys(observation,['actor_kind','statement'],['actor_kind','statement'])
        require(observation['actor_kind'] in ['agent-observation','user-reported'],'ARTIFACT_OBSERVER_INVALID')
        require(isinstance(observation['statement'],str) and 0<len(observation['statement'].strip())<=4096,'ARTIFACT_OBSERVATION_REQUIRED')
        event=check['inspection'];event_fields=['clip_id','start','end','min_visible_seconds','evidence']
        exact_keys(event,event_fields,event_fields)
        require(isinstance(event['clip_id'],str) and event['clip_id'] in clips,'ARTIFACT_INSPECTION_CLIP_UNKNOWN')
        clip=clips[event['clip_id']];prior=steps[check['step_id']]['result']
        require(clip['source_id']==prior['source_id'],'ARTIFACT_CAPTURE_MISMATCH')
        a,b=span(event['start'],event['end'],normalized['sources'][clip['source_id']]['media']['duration'])
        mapping=clip['source_to_output_map'];limit=min(clip['effective_source_end'],mapping['source_end'])
        require(mapping['source_start']<=a and b<=limit+1e-8,'ARTIFACT_INSPECTION_NOT_VISIBLE')
        speed=float(Fraction(mapping['source_seconds_per_output_second']))
        out_a=mapping['output_start']+(a-mapping['source_start'])/speed;out_b=mapping['output_start']+(b-mapping['source_start'])/speed
        require(out_b<=mapping['output_end']+1e-8,'ARTIFACT_INSPECTION_NOT_VISIBLE')
        require(a>=prior['source_end']-1e-8 and out_a>=prior['output_end']-1e-8,'ARTIFACT_INSPECTION_PRECEDES_RESULT')
        hold=number(event['min_visible_seconds'],'min_visible_seconds',0)
        require(hold>0 and out_b-out_a+1e-8>=hold,'ARTIFACT_READING_WINDOW_TOO_SHORT')
        evidence=bind(event['evidence'])
        mapped.append({'id':ident,'step_id':check['step_id'],'context_id':steps[check['step_id']]['context_id'],
            'input_artifacts':input_refs,'result_artifact':result,'status':'ARTIFACT_BYTES_AVAILABLE' if result is not None else 'MISSING_ARTIFACT',
            'inspection':{'clip_id':clip['id'],'source_id':clip['source_id'],'capture':copy.deepcopy(plan['sources'][clip['source_id']]),
                'source_start':a,'source_end':b,'output_start':out_a,'output_end':out_b,'min_visible_seconds':hold,'evidence':evidence},
            'observation':copy.deepcopy(observation),'observer_identity_verified':False,
            'observation_truth':'NOT_VERIFIED','frame_derivation':'FRAME_DERIVATION_NOT_VERIFIED',
            'artifact_production_link':'DECLARED_ONLY','backend_persistence':'NOT_VERIFIED'})
    by_id={item['id']:item for item in mapped};seen=set()
    for cue in cues:
        exact_keys(cue,['id','check_id','start','end','text'],['id','check_id','start','end','text'])
        require(isinstance(cue['id'],str) and cue['id'] and cue['id'] not in seen,'ARTIFACT_CUE_ID_INVALID');seen.add(cue['id'])
        require(isinstance(cue['check_id'],str) and cue['check_id'] in by_id,'ARTIFACT_CUE_CHECK_UNKNOWN')
        item=by_id[cue['check_id']];require(item['result_artifact'] is not None,'ARTIFACT_CUE_WITHOUT_RESULT_FILE')
        require(isinstance(cue['text'],str) and cue['text'].strip(),'ARTIFACT_CUE_TEXT_REQUIRED')
        a,b=span(cue['start'],cue['end'],normalized['duration'])
        require(a>=item['inspection']['output_start']-1e-8 and b<=item['inspection']['output_end']+1e-8,'ARTIFACT_CUE_OUTSIDE_INSPECTION')
    report={'schema':'tutorial-artifact-check/1','plan_revision':request['expected_revision'],
        'tutorial_proof':proof,'checks':mapped,'artifact_cues':copy.deepcopy(cues),
        'status':'INCOMPLETE' if any(x['result_artifact'] is None for x in mapped) else 'LINKAGE_VALIDATED',
        'verification_scope':'Actual local byte identities and declared visible interval/dependency linkage only; no interpretation of screenshots, files or observation text',
        'observation_truth':'NOT_VERIFIED','frame_derivation':'FRAME_DERIVATION_NOT_VERIFIED',
        'backend_persistence':'NOT_VERIFIED','artifact_production_link':'DECLARED_ONLY',
        'work_changed':False,'media_generated':False,'semantic_review':'NOT_RUN','publication_gate':False}
    for ref in refs:_file(ref)
    require(fingerprint(plan)==request['expected_revision'],'PLAN_REVISION_CONFLICT')
    write_json(directory/'artifact-check.json',report)
    return report
