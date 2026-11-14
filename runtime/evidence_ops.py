"""Map caller-declared evidence onto a work. No semantic classification or selection."""
from pathlib import Path
from fractions import Fraction


def compile_evidence(request, directory, tools, *, normalized_document=None, validation_mode='strict'):
    from editing_runtime import exact_keys, require, source, span, fingerprint, write_json, require_video_coverage, audio_intersection, windowed_mix_clock
    from work_ops import validate_document
    fields=['operation','document','expected_document_sha256','units','occurrences','required_units','chapters']
    exact_keys(request,fields,fields)
    require(validation_mode in ('strict','ordinary_protection'),'EVIDENCE_VALIDATION_MODE_INVALID')
    ordinary=validation_mode=='ordinary_protection'
    doc=request['document']
    require(fingerprint(doc)==request['expected_document_sha256'],'WORK_DOCUMENT_REVISION_CONFLICT')
    # Internal document validation supplies its already-normalized values so
    # embedded protection uses this same coverage algorithm without recursion.
    # This keyword is never accepted in the public request schema above.
    norm,_,tracks=validate_document(doc,tools) if normalized_document is None else normalized_document
    carriers={}
    for clip in norm['clips']:
        asset=norm['sources'][clip['source_id']]
        end=clip['effective_source_end']
        carrier={'source':asset,'start':clip['start'],'end':end,'output_start':clip['output_start'],
                 'source_seconds_per_output_second':float(Fraction(clip['speed'])),
                 'speed_rational':str(Fraction(clip['speed'])),'gain_db':clip['gain_db']}
        if ordinary:
            speed=Fraction(clip['speed']);fps=Fraction(norm['fps'])
            carrier['mapping_clock']=(Fraction(str(clip['start'])),
                min(Fraction(str(clip['end'])),Fraction(str(clip['start']))+Fraction(clip['frames'])/fps*speed),
                Fraction(clip['output_start_frame'])/fps,speed)
        carriers[('clip-video',clip['id'])]=carrier
        if not clip.get('mute',False) and clip['gain_db']>-120 and any(s['codec_type']=='audio' for s in asset['media']['streams']):
            carriers[('clip-audio',clip['id'])]=carrier
    for aid,track in zip(doc['audio_tracks'],tracks):
        if track['gain_db']>-120:
            carriers[('audio-track',aid)]={**track,'source':source(track['source']),
                                           'source_seconds_per_output_second':1.0,'speed_rational':'1'}
            if ordinary:
                declared=doc['audio_tracks'][aid];anchor=declared['anchor_clip_id']
                anchor_time=(Fraction(next(c['output_start_frame'] for c in norm['clips'] if c['id']==anchor))/Fraction(norm['fps'])
                             if anchor is not None else Fraction(0))
                carriers[('audio-track',aid)]['mapping_clock']=(Fraction(str(track['start'])),
                    Fraction(str(track['end'])),anchor_time+Fraction(str(declared['offset'])),Fraction(1))
    require(isinstance(request['units'],list) and request['units'],'UNITS_REQUIRED')
    units={}
    audio_unit_clock_precision={}
    audio_unit_coverage_basis={}
    video_unit_coverage_basis={}
    for unit in request['units']:
        fields=['id','label','kind','speaker','modality','source','start','end','evidence','requires']
        exact_keys(unit,fields,fields)
        uid=unit['id'];require(isinstance(uid,str) and uid and uid not in units,'UNIT_ID_DUPLICATE_OR_EMPTY')
        require(all(isinstance(unit[k],str) and unit[k].strip() for k in ['label','kind','speaker']),'UNIT_METADATA_REQUIRED')
        require(unit['modality'] in ['audio','video'],'EVIDENCE_MODALITY_REQUIRED')
        asset=source(unit['source']);media=tools.probe(asset['path'])
        require(any(s['codec_type']==unit['modality'] for s in media['streams']),'EVIDENCE_STREAM_MISSING')
        a,b=span(unit['start'],unit['end'],media['duration'])
        if unit['modality']=='video':
            clock=windowed_mix_clock(tools,asset['path'],media,b,kind='video',start=a)
            require_video_coverage(clock,a,b,playback=validation_mode=='ordinary_protection')
            observed_complete=any(Fraction(x)<=Fraction(str(a)) and Fraction(str(b))<=Fraction(y)
                                  for x,y in clock['observed_intervals'])
            video_unit_coverage_basis[uid]='OBSERVED_FRAMES' if observed_complete else 'PLAYBACK_QUANTIZED_UNCERTAIN'
        else:
            clock=windowed_mix_clock(tools,asset['path'],media,b,kind='audio',start=a,
                                     playback=validation_mode=='ordinary_protection')
            audio_unit_clock_precision[uid]=clock['source_time_precision']
            audio_intersection(clock,a,b,require_full=True,require_precise=validation_mode=='strict',
                               playback=validation_mode=='ordinary_protection')
            observed_complete=any(Fraction(x)<=Fraction(str(a)) and Fraction(str(b))<=Fraction(y)
                                  for x,y in clock['observed_intervals'])
            audio_unit_coverage_basis[uid]={'basis':'OBSERVED_SAMPLES' if observed_complete else 'PLAYBACK_GROUP_QUANTIZED_UNCERTAIN',
                'clock_basis':clock.get('playback_basis') if not observed_complete else None}
        evidence=source(unit['evidence'])
        require(isinstance(unit['requires'],list),'DEPENDENCIES_ARRAY_REQUIRED')
        deps=set()
        for dep in unit['requires']:
            exact_keys(dep,['unit_id','relation'],['unit_id','relation'])
            require(isinstance(dep['unit_id'],str) and dep['unit_id'] and dep['unit_id'] not in deps,'DEPENDENCY_DUPLICATE_OR_EMPTY')
            require(dep['relation'] in ['prerequisite','context'],'DEPENDENCY_RELATION_UNKNOWN')
            deps.add(dep['unit_id'])
        units[uid]={**unit,'source':asset,'evidence':evidence,'start':a,'end':b}
    for uid,u in units.items():
        require(all(d['unit_id'] in units and d['unit_id']!=uid for d in u['requires']),'DEPENDENCY_UNIT_UNKNOWN_OR_SELF')
    require(isinstance(request['occurrences'],list) and request['occurrences'],'OCCURRENCES_REQUIRED')
    occurrences={};occurrence_clocks={};retimed_carriers=[]
    for item in request['occurrences']:
        exact_keys(item,['id','unit_id','carriers','dependencies'],['id','unit_id','carriers','dependencies'])
        oid=item['id'];require(isinstance(oid,str) and oid and oid not in occurrences,'OCCURRENCE_ID_DUPLICATE_OR_EMPTY')
        require(item['unit_id'] in units,'OCCURRENCE_UNIT_UNKNOWN');u=units[item['unit_id']]
        require(isinstance(item['carriers'],list) and item['carriers'],'CARRIERS_REQUIRED')
        parts=[];seen=set()
        for ref in item['carriers']:
            exact_keys(ref,['type','id'],['type','id'])
            require(isinstance(ref['type'],str) and isinstance(ref['id'],str),'CARRIER_ID_REQUIRED')
            key=(ref['type'],ref['id'])
            require(key not in seen,'DUPLICATE_CARRIER');seen.add(key)
            require(key in carriers,'CARRIER_MISSING_OR_MUTED')
            require((u['modality']=='video' and key[0]=='clip-video') or
                    (u['modality']=='audio' and key[0] in ['clip-audio','audio-track']),'CARRIER_MODALITY_MISMATCH')
            c=carriers[key]
            # Ordinary protection preserves declared source ranges and order.
            # It cannot grant strict sampled evidence or a listening verdict.
            require(ordinary or Fraction(c['speed_rational'])==1,
                    'EVIDENCE_RETIMED_CARRIER_UNSUPPORTED: '+oid)
            require(c['source']['sha256']==u['source']['sha256'] and
                    Path(c['source']['path']).resolve()==Path(u['source']['path']).resolve(),'EVIDENCE_SOURCE_MISMATCH')
            if ordinary:
                source_start,source_end,output_start,speed=c['mapping_clock']
                require(Fraction(1,2)<=speed<=2,'EVIDENCE_SPEED_OUT_OF_RANGE')
                a=max(Fraction(str(u['start'])),source_start);b=min(Fraction(str(u['end'])),source_end)
            else:
                a=max(u['start'],c['start']);b=min(u['end'],c['end'])
                source_start=c['start'];output_start=c['output_start'];speed=c['source_seconds_per_output_second']
            require(b>a,'CARRIER_DOES_NOT_COVER_UNIT')
            if key[0]=='audio-track' and 'envelope' in c:
                env=c['envelope'];lo=Fraction(str(c['start']));hi=Fraction(str(c['end']))
                fi=Fraction(env['fade_in_samples'],48000);fo=Fraction(env['fade_out_samples'],48000)
                require(not ((fi and Fraction(str(a))<lo+fi) or (fo and Fraction(str(b))>hi-fo)),
                        'EVIDENCE_AUDIO_ENVELOPE_OVERLAP: '+oid)
            start=output_start+(a-source_start)/speed;end=start+(b-a)/speed
            part={'carrier':ref,'source_start':float(a),'source_end':float(b),'output_start':float(start),
                  'output_end':float(end),'source_seconds_per_output_second':float(speed)}
            if ordinary:
                part['clock_rational']={k:str(v) for k,v in
                    [('source_start',a),('source_end',b),('output_start',start),('output_end',end),('speed',speed)]}
                if speed!=1:
                    retimed_carriers.append({'occurrence_id':oid,'carrier':ref,'speed':str(speed)})
            parts.append(part)
        parts.sort(key=lambda p:Fraction(p['clock_rational']['output_start']) if ordinary else p['output_start'])
        cursor=Fraction(str(u['start'])) if ordinary else u['start'];previous=None
        for part in parts:
            values={k:Fraction(v) for k,v in part['clock_rational'].items()} if ordinary else part
            require(values['source_start']==cursor if ordinary else abs(values['source_start']-cursor)<1e-7,
                    'EVIDENCE_TRUNCATED_REORDERED_OR_REPEATED: '+oid)
            if previous is not None:
                require(values['output_start']==previous if ordinary else abs(values['output_start']-previous)<1e-7,
                        'EVIDENCE_OUTPUT_DISCONTINUITY: '+oid)
            cursor=values['source_end'];previous=values['output_end']
        require(cursor==Fraction(str(u['end'])) if ordinary else abs(cursor-u['end'])<1e-7,
                'EVIDENCE_TRUNCATED_REORDERED_OR_REPEATED: '+oid)
        if ordinary:
            occurrence_clocks[oid]=(Fraction(parts[0]['clock_rational']['output_start']),previous)
        deps=item['dependencies'];require(isinstance(deps,dict),'OCCURRENCE_DEPENDENCIES_REQUIRED')
        require(set(deps)=={d['unit_id'] for d in u['requires']},'DEPENDENCY_BINDING_MISMATCH')
        require(all(isinstance(x,str) and x for x in deps.values()),'DEPENDENCY_OCCURRENCE_ID_REQUIRED')
        occurrences[oid]={'id':oid,'unit_id':u['id'],'label':u['label'],'kind':u['kind'],'speaker':u['speaker'],
            'modality':u['modality'],'parts':parts,'output_start':parts[0]['output_start'],'output_end':parts[-1]['output_end'],
            'dependencies':deps,'semantic_status':'caller-declared, not verified'}
    for oid,o in occurrences.items():
        for dep in units[o['unit_id']]['requires']:
            target=o['dependencies'][dep['unit_id']]
            require(target in occurrences and target!=oid,'DEPENDENCY_OCCURRENCE_MISSING_OR_SELF')
            parent=occurrences[target]
            require(parent['unit_id']==dep['unit_id'],'DEPENDENCY_OCCURRENCE_WRONG_UNIT')
            if dep['relation']=='prerequisite':
                require(occurrence_clocks[target][1]<=occurrence_clocks[oid][0] if ordinary else
                        parent['output_end']<=o['output_start']+1e-7,'PREREQUISITE_NOT_BEFORE_UNIT')
    required=request['required_units']
    require(isinstance(required,list) and all(isinstance(x,str) for x in required) and len(set(required))==len(required),'REQUIRED_UNIT_IDS_INVALID')
    require(set(required)<=set(units),'REQUIRED_UNIT_UNKNOWN')
    require(set(required)<={o['unit_id'] for o in occurrences.values()},'REQUIRED_UNIT_OMITTED')
    require(isinstance(request['chapters'],list),'CHAPTERS_ARRAY_REQUIRED')
    chapters=[];seen_chapters=set();assigned=set();previous_start=-1
    for ch in request['chapters']:
        exact_keys(ch,['id','title','occurrence_ids'],['id','title','occurrence_ids'])
        require(isinstance(ch['id'],str) and ch['id'] and ch['id'] not in seen_chapters,'CHAPTER_ID_DUPLICATE_OR_EMPTY')
        seen_chapters.add(ch['id'])
        require(isinstance(ch['title'],str) and ch['title'].strip(),'CHAPTER_TITLE_REQUIRED')
        ids=ch['occurrence_ids'];require(isinstance(ids,list) and ids and all(isinstance(x,str) for x in ids),'CHAPTER_OCCURRENCES_REQUIRED')
        require(len(set(ids))==len(ids) and not assigned.intersection(ids),'CHAPTER_DUPLICATE_OCCURRENCE')
        require(set(ids)<=set(occurrences),'CHAPTER_OCCURRENCE_UNKNOWN');assigned.update(ids)
        items=sorted([occurrences[x] for x in ids],key=lambda o:o['output_start'])
        start=items[0]['output_start'];require(start>=previous_start,'CHAPTER_ORDER_INVALID');previous_start=start
        # Keep exact disjoint intervals: a chapter span does not certify intervening material.
        chapters.append({'id':ch['id'],'title':ch['title'],'start':start,'end':max(x['output_end'] for x in items),
            'evidence_intervals':[{'occurrence_id':x['id'],'start':x['output_start'],'end':x['output_end']} for x in items]})
    require(not chapters or assigned==set(occurrences),'UNCHAPTERED_OCCURRENCE')
    from overlay_ops import work_layers
    overlays=work_layers(doc,norm,tools);fps=float(Fraction(norm['fps']))
    overlay_intersections=[{'occurrence_id':oid,'layer_ids':[layer['id'] for layer in overlays
        if layer['opacity']>0 and layer['start_frame']/fps<o['output_end'] and layer['end_frame']/fps>o['output_start']]}
        for oid,o in occurrences.items() if o['modality']=='video']
    report={'schema':'evidence-map/1','document_sha256':fingerprint(doc),'units':list(units.values()),
        'occurrences':list(occurrences.values()),'required_units':required,'chapters':chapters,
        'validation_mode':validation_mode,
        'declared_coverage':'COMPLETE' if validation_mode=='strict' else 'DECLARED_SOURCE_RANGES_PRESERVED',
        'audio_unit_clock_precision':audio_unit_clock_precision,
        'audio_unit_coverage_basis':audio_unit_coverage_basis,
        'video_unit_coverage_basis':video_unit_coverage_basis,
        'source_audio_clock_requirement':'SAMPLE_RESOLVING' if validation_mode=='strict' else 'NOT_REQUIRED',
        'semantic_review':'NOT_RUN','audibility_legibility':'NOT_RUN',
        'visual_layer_intersections':overlay_intersections,'layer_occlusion_review':'NOT_RUN',
        'scope':'Only caller-declared units, identities, dependencies and source-time coverage. No inference of importance, truth, approval, missing context or pedagogical completeness.'}
    if ordinary:
        report['retiming']={'policy':'explicit-constant-speed-source-mapping-only',
            'carriers':retimed_carriers,'mapping_clock':'exact rational source/output coordinates',
            'sample_or_pixel_freeze':'NOT_CERTIFIED','source_complete':'NOT_GRANTED',
            'speed_or_scope_authorization':'caller declaration; revisions also require work scope checks'}
    if directory is not None:
        write_json(directory/'evidence-map.json',report)
    return report
