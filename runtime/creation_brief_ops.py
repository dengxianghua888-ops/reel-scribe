"""Prepare explicit Agent-parsed briefs. No language inference, authorization or execution."""
import copy
import re
import json
import hashlib
from pathlib import Path
from fractions import Fraction


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
    issues=[]; draft=None; speech_binding=None; recheck_refs=[]
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
                require(isinstance(rp,dict),'BRIEF_CAPTION_ONLY_PARAMETERS_REQUIRED')
                local='caption_overrides' in rp
                if local:
                    require(set(rp)<= {'caption_style','caption_overrides','audio_gain_db'},'BRIEF_CAPTION_ONLY_PARAMETERS_REQUIRED')
                    from style_recipe_ops import cue_recipe_guard
                    cue_recipe_guard(state['document'],recipe,v['scope'])
                    from caption_style import validate_override
                    for values in rp['caption_overrides'].values():validate_override(values,state['document']['plan']['height'])
                    require(v['capabilities']==['caption-cue-style'],'BRIEF_CAPTION_ONLY_CAPABILITY_REQUIRED')
                else:
                    require(set(rp)=={'caption_style'},'BRIEF_CAPTION_ONLY_PARAMETERS_REQUIRED')
                    require(isinstance(rp['caption_style'],dict) and rp['caption_style'] and
                            set(rp['caption_style'])<= {'font_size','margin_v','color_rgb'},'BRIEF_CAPTION_PARAMETERS_UNSUPPORTED')
                    require(v['capabilities']==['caption-style'],'BRIEF_CAPTION_ONLY_CAPABILITY_REQUIRED')
                style=recipe.get('style');require(isinstance(style,dict) and 'card' in style,'BRIEF_STYLE_CARD_REQUIRED')
                source(style['card'])
                scope=v['scope']
                required=['clip_ids','source_ids','caption_ids','audio_ids','style_keys','note_keys','output_fields','caption_style','freeze_positions','freeze_duration']
                exact_keys(scope,required+['visual_ids','evidence_mapping'],required)
                require(all(scope[k]==[] for k in (['clip_ids','source_ids','audio_ids','note_keys','output_fields'] if local else ['clip_ids','source_ids','caption_ids','audio_ids','note_keys','output_fields'])) and
                        scope.get('visual_ids',[])==[] and scope.get('evidence_mapping',False) is False and
                        scope['style_keys']==['*'] and scope['caption_style'] is (not local) and scope['freeze_duration'] is True,
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
        fields=['aligned_transcript','expected_transcript_revision','segments','protected_word_ids','allow_reorder','source_clip_ids']
        exact_keys(parameters,fields,[])
        if 'aligned_transcript' not in parameters:
            issues.append({'code':'REVIEWED_WORD_ALIGNMENT_REQUIRED','detail':'A readable transcript alone cannot authorize word-level cuts; provide timing provenance and explicit decisions.'})
        elif set(fields)-set(parameters):
            issues.append({'code':'SPEECH_EXPLICIT_DECISIONS_REQUIRED','missing_fields':sorted(set(fields)-set(parameters)),
                           'detail':'No word selections, protection IDs, reordering or source scope are inferred.'})
        else:
            require(brief['scene']=='speech','BRIEF_SPEECH_SCENE_REQUIRED')
            ref=parameters['aligned_transcript']; identity=source(ref)
            require(identity['bytes']<=4*1024*1024,'BRIEF_TRANSCRIPT_TOO_LARGE')
            with Path(identity['path']).open('rb') as handle:raw=handle.read(4*1024*1024+1)
            require(len(raw)<=4*1024*1024,'BRIEF_TRANSCRIPT_TOO_LARGE')
            require(hashlib.sha256(raw).hexdigest()==identity['sha256'],'BRIEF_TRANSCRIPT_BYTES_CHANGED')
            def unique_pairs(pairs):
                obj={}
                for key,value in pairs:
                    require(key not in obj,'BRIEF_TRANSCRIPT_DUPLICATE_KEY');obj[key]=value
                return obj
            transcript=json.loads(raw.decode('utf-8'),object_pairs_hook=unique_pairs,
                parse_constant=lambda _:require(False,'BRIEF_TRANSCRIPT_NONFINITE'))
            require(isinstance(transcript,dict) and transcript.get('schema')=='word-transcript/1','TRANSCRIPT_SCHEMA_UNSUPPORTED')
            require(transcript.get('timing') in ['model-aligned','human-checked'],
                    'ESTIMATED_OR_UNKNOWN_WORD_TIMES_NOT_EDIT_BOUNDARIES')
            require(fingerprint(transcript)==parameters['expected_transcript_revision'],'TRANSCRIPT_REVISION_CONFLICT')
            require(parameters['allow_reorder'] is False,'BRIEF_SPEECH_REORDER_UNSUPPORTED')
            require(isinstance(parameters['protected_word_ids'],list) and
                    all(isinstance(x,str) and x for x in parameters['protected_word_ids']) and
                    len(set(parameters['protected_word_ids']))==len(parameters['protected_word_ids']),
                    'PROTECTED_WORD_IDS_REQUIRED')
            selected=parameters['source_clip_ids'];plan=state['document']['plan'];clips=plan['clips']
            require(isinstance(selected,list) and selected and all(isinstance(x,str) for x in selected) and
                    len(set(selected))==len(selected),'BRIEF_SPEECH_SOURCE_SCOPE_REQUIRED')
            positions={c['id']:i for i,c in enumerate(clips)}
            require(set(selected)<=set(positions),'BRIEF_SPEECH_CLIP_UNKNOWN')
            indices=[positions[x] for x in selected]
            require(indices==list(range(indices[0],indices[-1]+1)),'BRIEF_SPEECH_CONTIGUOUS_CLIPS_REQUIRED')
            chosen=[clips[i] for i in indices];sid=chosen[0]['source_id']
            require(all(c['source_id']==sid and Fraction(str(c.get('speed',1)))==1 and
                        not c.get('mute',False) and c['gain_db']>-120 for c in chosen),
                    'BRIEF_SPEECH_SINGLE_SOURCE_1X_AUDIBLE_REQUIRED')
            asset=source(transcript['source']);current_asset=source(plan['sources'][sid])
            require(asset['sha256']==current_asset['sha256'] and
                    Path(asset['path']).resolve()==Path(current_asset['path']).resolve(),
                    'BRIEF_SPEECH_SOURCE_MISMATCH')
            fps=Fraction(str(plan['fps']));windows=[]
            for clip in chosen:
                start,end=Fraction(str(clip['start'])),Fraction(str(clip['end']))
                effective=min(end,start+round((end-start)*fps)/fps)
                require(effective>start,'BRIEF_SPEECH_EMPTY_SOURCE_WINDOW')
                if windows:require(start==windows[-1][1],'BRIEF_SPEECH_CONTIGUOUS_SOURCE_REQUIRED')
                windows.append((start,effective))
            segments=parameters['segments']
            require(isinstance(segments,list) and segments,'SEGMENTS_REQUIRED')
            from editing_runtime import number
            boundary_refs=[]
            for segment in segments:
                segment_fields=['id','word_ids','start','end','gain_db','boundary_evidence']
                exact_keys(segment,segment_fields,segment_fields)
                boundary=segment['boundary_evidence']
                exact_keys(boundary,['method','artifact'],['method','artifact'])
                require(boundary['method'] in ['waveform-review','listening-review','alignment-review'],'BOUNDARY_METHOD_REQUIRED')
                source(boundary['artifact']);boundary_refs.append(boundary['artifact'])
                a=Fraction(str(number(segment['start'],'start',0)));b=Fraction(str(number(segment['end'],'end',0)))
                require(windows[0][0]<=a<b<=windows[-1][1],'BRIEF_SPEECH_SEGMENT_OUTSIDE_WORK_SCOPE')
            draft={'operation':'speech-plan-compile','transcript':transcript,
                   'expected_revision':parameters['expected_transcript_revision'],
                   'output':{k:copy.deepcopy(plan[k]) for k in ['fps','width','height','fit']},
                   **{k:copy.deepcopy(parameters[k]) for k in ['segments','protected_word_ids','allow_reorder']}}
            recheck_refs=[ref,transcript['source'],plan['sources'][sid],*boundary_refs]
            speech_binding={'transcript_file':identity,'timing':transcript['timing'],
                'source_clip_ids':selected,'source_id':sid,'source':current_asset,
                'source_window':[float(windows[0][0]),float(windows[-1][1])],
                'persistent_protection_sha256':fingerprint(state['document'].get('evidence_protection')),
                'adoption_state':'REQUIRES_TIMELINE_REVISE_AND_DEPENDENT_MAPPING',
                'apply_authorized_by_preparation':False,
                'dependent_resources':{k:list(state['document'].get(k,{})) for k in ['captions','audio_tracks','visual_layers','style_bindings']},
                'persistent_protection_present':'evidence_protection' in state['document'],
                'dependent_mapping_validation':'NOT_RUN',
                'timing_truth':'Upstream declaration, not word-boundary certification by this helper',
                'adoption':'Compiler creates an independent plan only. Merge by timeline-revise with explicit scope, remap captions/audio/protection, and preserve current Work protections; do not replace plan directly.'}
    else:
        exact_keys(parameters,[],[])
        issues.append({'code':'EDITORIAL_DECISION_REQUIRED','detail':'Choose supported source beats, order and reveal limits through the scene workflow; no narrative inferred from a style name.'})
    for ref in recheck_refs:source(ref)
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
                           'note':'tutorial/speech compilers validate independent plans, not current Work CAS; adoption requires timeline-revise and explicit scope, never direct plan replacement'},
        'semantic_recommendation':'NOT_PERFORMED','downstream_validation':'NOT_RUN'}
    if speech_binding is not None:report['speech_binding']=speech_binding
    if draft is not None and not planning:
        write_json(directory/'prepared-request.json',draft)
        report['prepared_request_sha256']=fingerprint(draft)
    write_json(directory/'creation-brief.json',report)
    return report
