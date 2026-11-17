"""Compile explicit translated cues and whole dub assets; never translate or rewrite."""
import math
import re


def compile_localization(request, directory, tools):
    from editing_runtime import exact_keys, require, fingerprint, source, span, number, write_json, audio_intersection, windowed_mix_clock, verified_json
    from work_ops import validate_document
    fields=['operation','document','expected_document_sha256','source_script','translation','reading_profile']
    exact_keys(request,fields,fields)
    doc=request['document'];document_hash=fingerprint(doc)
    require(document_hash==request['expected_document_sha256'],'DOCUMENT_REVISION_CONFLICT')
    norm,_,_=validate_document(doc,tools)
    clips={c['id']:c for c in norm['clips']}
    script_ref,script=verified_json(request['source_script'],'LOCALIZATION_SOURCE')
    sk=['schema','document_sha256','provenance','units']
    exact_keys(script,sk,sk)
    require(script['schema']=='localization-source/1','LOCALIZATION_SOURCE_SCHEMA')
    require(script['document_sha256']==document_hash,'SOURCE_SCRIPT_REVISION_CONFLICT')
    require(script['provenance'] in ['authored','human-transcript','asr','supplied-subtitle'],'TEXT_PROVENANCE_REQUIRED')
    require(isinstance(script['units'],list) and script['units'],'SOURCE_UNITS_REQUIRED')
    def text(v,label):
        require(isinstance(v,str) and v.strip() and all(ord(c)>=32 or c=='\n' for c in v),label)
        return v
    def ids(v,label,nonempty=True):
        require(isinstance(v,list) and (bool(v) or not nonempty),'IDS_REQUIRED: '+label)
        require(all(isinstance(x,str) and x.strip() for x in v),'ID_INVALID: '+label)
        require(len(v)==len(set(v)),'ID_DUPLICATE: '+label)
        return v
    def window(row):
        cid=row['clip_id'];require(isinstance(cid,str) and cid in clips,'LOCALIZATION_ANCHOR_MISSING')
        offset=clips[cid]['output_start']
        a,b=span(row['start'],row['end'],norm['duration']-offset)
        return a,b,offset+a,offset+b
    units={}
    for u in script['units']:
        keys=['id','clip_id','start','end','text','speaker_id','language']
        exact_keys(u,keys,keys);uid=text(u['id'],'SOURCE_ID_INVALID')
        require(uid not in units,'SOURCE_ID_DUPLICATE')
        text(u['text'],'SOURCE_TEXT_EMPTY');text(u['speaker_id'],'SOURCE_SPEAKER_REQUIRED');text(u['language'],'SOURCE_LANGUAGE_REQUIRED')
        window(u);units[uid]=u
    tr=request['translation']
    tk=['source_script_sha256','target_locale','mode','protected_source_ids','omissions','cues','literal_locks']
    exact_keys(tr,tk,tk)
    require(tr['source_script_sha256']==script_ref['sha256'],'TRANSLATION_SOURCE_REVISION_CONFLICT')
    require(isinstance(tr['target_locale'],str) and re.fullmatch(r'[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*',tr['target_locale']),'TARGET_LOCALE_INVALID')
    require(tr['mode'] in ['captions','dub'],'LOCALIZATION_MODE_UNSUPPORTED')
    protected=ids(tr['protected_source_ids'],'protected',False)
    require(set(protected)<=set(units),'PROTECTED_SOURCE_UNKNOWN')
    require(isinstance(tr['omissions'],list),'OMISSIONS_REQUIRED')
    omitted={}
    for item in tr['omissions']:
        exact_keys(item,['source_id','reason'],['source_id','reason'])
        sid=item['source_id'];require(isinstance(sid,str) and sid in units and sid not in omitted,'OMISSION_SOURCE_INVALID')
        text(item['reason'],'OMISSION_REASON_REQUIRED');omitted[sid]=item['reason']
    require(not set(protected)&set(omitted),'PROTECTED_SOURCE_OMITTED')
    profile=request['reading_profile']
    pk=['max_lines','max_codepoints_per_line','max_codepoints_per_second','count_spaces','overflow_action']
    exact_keys(profile,pk,pk)
    for key in pk[:2]:require(type(profile[key]) is int and profile[key]>0,'READING_LIMIT_INVALID')
    rate=number(profile['max_codepoints_per_second'],'reading_rate',0);require(rate>0,'READING_LIMIT_INVALID')
    require(type(profile['count_spaces']) is bool,'COUNT_SPACES_BOOLEAN_REQUIRED')
    require(profile['overflow_action'] in ['report','reject'],'OVERFLOW_ACTION_INVALID')
    require(isinstance(tr['cues'],list) and tr['cues'],'TARGET_CUES_REQUIRED')
    captions={};audio_tracks={};mapping=[];covered=set();warnings=[]
    for cue in tr['cues']:
        ck=['id','source_ids','speaker_ids','clip_id','start','end','text']
        extra=['audio','gain_db'] if tr['mode']=='dub' else []
        exact_keys(cue,ck+extra,ck+extra)
        cid=text(cue['id'],'TARGET_CUE_ID_INVALID');require(cid not in captions,'TARGET_CUE_ID_DUPLICATE')
        uids=ids(cue['source_ids'],'cue source');require(set(uids)<=set(units),'CUE_SOURCE_UNKNOWN')
        require(not set(uids)&set(omitted),'SOURCE_BOTH_USED_AND_OMITTED')
        speakers=ids(cue['speaker_ids'],'speakers')
        require(set(speakers)=={units[x]['speaker_id'] for x in uids},'SPEAKER_MAPPING_MISMATCH')
        body=text(cue['text'],'TARGET_TEXT_EMPTY');lines=body.split('\n')
        require(all(x.strip() for x in lines),'EMPTY_CAPTION_LINE')
        a,b,out_a,out_b=window(cue)
        count=lambda value:len(value if profile['count_spaces'] else ''.join(value.split()))
        chars=sum(count(line) for line in lines);cps=chars/(b-a)
        excess=[]
        if len(lines)>profile['max_lines']:excess.append('LINE_COUNT')
        if any(count(line)>profile['max_codepoints_per_line'] for line in lines):excess.append('LINE_LENGTH')
        if cps>rate+1e-8:excess.append('READING_RATE')
        if excess:warnings.append({'cue_id':cid,'exceeded':excess,'codepoints_per_second':cps})
        captions[cid]={k:cue[k] for k in ['clip_id','start','end','text']}
        row={'cue_id':cid,'source_ids':uids,'speaker_ids':speakers,'source_windows':[{'source_id':uid,'output_window':list(window(units[uid])[2:])} for uid in uids],'output_window':[out_a,out_b],'codepoints':chars,'codepoints_per_second':cps}
        if tr['mode']=='dub':
            audio=source(cue['audio']);probe=tools.probe(audio['path']);streams=probe['streams']
            require(sum(x.get('codec_type')=='audio' for x in streams)==1 and not any(x.get('codec_type')=='video' for x in streams),'DUB_SINGLE_AUDIO_ASSET_REQUIRED')
            stream=next(x for x in streams if x.get('codec_type')=='audio')
            # Some valid WAV streams omit start_time; the selected decoded
            # sample clock below still has to cover [0, duration].
            if 'start_time' in stream:
                try:
                    origin=float(stream['start_time'])
                except (TypeError, ValueError, OverflowError):
                    require(False,'DUB_ORIGIN_UNVERIFIED')
                require(math.isfinite(origin),'DUB_ORIGIN_UNVERIFIED')
                require(abs(origin)<1e-8,'DUB_NONZERO_ORIGIN')
            duration=probe['duration'];require(duration<=b-a+1e-8,'DUB_EXCEEDS_SLOT: '+cid)
            audio_clock=windowed_mix_clock(tools,audio['path'],probe,duration,kind='audio',playback=True)
            audio_intersection(audio_clock,0,duration,require_full=True,playback=True)
            gain=number(cue['gain_db'],'gain_db');require(-120<=gain<=24,'GAIN_OUT_OF_RANGE')
            audio_tracks[cid]={'source':cue['audio'],'start':0,'end':duration,'anchor_clip_id':cue['clip_id'],'offset':a,'gain_db':gain}
            row.update(audio_duration=duration,slot_duration=b-a,audio_text_alignment='DECLARED_NOT_VERIFIED',
                       audio_clock_basis=audio_clock.get('playback_basis', {'status':'OBSERVED_ONLY'}))
        mapping.append(row);covered.update(uids)
    require(covered|set(omitted)==set(units),'SOURCE_COVERAGE_INCOMPLETE')
    ordered=sorted(mapping,key=lambda x:(x['output_window'][0],x['output_window'][1]))
    require(all(a['output_window'][1]<=b['output_window'][0] for a,b in zip(ordered,ordered[1:])),'OVERLAPPING_TARGET_CUES')
    # Repeated unit IDs permit split translation. They do not assert semantic completeness.
    require(isinstance(tr['literal_locks'],list),'LITERAL_LOCKS_REQUIRED')
    lock_ids=set()
    for lock in tr['literal_locks']:
        lk=['id','cue_ids','text','match'];exact_keys(lock,lk,lk)
        lid=text(lock['id'],'LOCK_ID_INVALID');require(lid not in lock_ids,'LOCK_ID_DUPLICATE');lock_ids.add(lid)
        cids=ids(lock['cue_ids'],'lock cues');require(set(cids)<=set(captions),'LOCK_CUE_UNKNOWN')
        literal=text(lock['text'],'LOCK_TEXT_REQUIRED');require(lock['match'] in ['exact','contains'],'LOCK_MATCH_INVALID')
        for cid in cids:
            value=captions[cid]['text']
            require(value==literal if lock['match']=='exact' else literal in value,'TARGET_LITERAL_MISMATCH: '+cid)
    require(not warnings or profile['overflow_action']=='report','READING_PROFILE_EXCEEDED')
    # Recheck bound text input after inspection; do not modify the work or source packet.
    source(request['source_script'])
    result={'schema':'localization-plan/1','status':'COMPILED_WITH_READING_WARNINGS' if warnings else 'COMPILED','document_sha256':document_hash,'source_script':request['source_script'],'source_provenance':script['provenance'],'target_locale':tr['target_locale'],'mode':tr['mode'],'captions':captions,'audio_tracks':audio_tracks,'mapping':mapping,'omissions':tr['omissions'],'reading_profile':profile,'reading_warnings':warnings,'counting':'Unicode codepoints, excluding line breaks; not glyph width, grapheme count or a universal language readability standard','semantic_review':'NOT_RUN','voice_and_lip_sync':'NOT_RUN','source_coverage':'declared source unit IDs only; not proof that all meaning was translated','scope':'Explicit text/time/audio compilation only. No translation, compression, voice choice, source audio removal or WorkDocument mutation.'}
    write_json(directory/'localization-plan.json',result)
    return result
