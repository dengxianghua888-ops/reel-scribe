"""Objective signal measurements and caller-declared event assembly checks."""
import math
import re
from pathlib import Path


def metadata_rows(path,max_rows):
    from editing_runtime import require
    rows=[];current=None
    for line in Path(path).read_text(encoding='utf-8').splitlines():
        if line.startswith('frame:'):
            match=re.search(r'pts_time:([^\s]+)',line);require(match is not None,'MEASUREMENT_TIMESTAMP_MISSING')
            t=float(match.group(1));require(math.isfinite(t),'MEASUREMENT_TIMESTAMP_NONFINITE')
            current={'time':t};rows.append(current)
            require(len(rows)<=max_rows,'MEASUREMENT_ROW_LIMIT: split the requested interval')
        elif current is not None and '=' in line:
            key,value=line.split('=',1)
            try:value=float(value)
            except ValueError:continue
            current[key]=value if math.isfinite(value) else None
    require(all(a['time']<b['time'] for a,b in zip(rows,rows[1:])),'MEASUREMENT_TIME_NOT_INCREASING')
    return rows


def signal_scan(request,directory,tools):
    from editing_runtime import exact_keys,require,source,span,number,write_json
    fields=['operation','source','start','end','video','audio','max_rows']
    exact_keys(request,fields,fields)
    asset=source(request['source']);media=tools.probe(asset['path']);a,b=span(request['start'],request['end'],media['duration'])
    limit=request['max_rows'];require(type(limit) is int and limit>0,'POSITIVE_ROW_LIMIT_REQUIRED')
    require(request['video'] is not None or request['audio'] is not None,'MEASUREMENT_REQUIRED')
    result={'schema':'media-signals/1','source':asset,'requested_interval':[a,b],
        'time_basis':'FFmpeg input presentation seconds, rebased by demuxer; measured pts retained',
        'video':None,'audio':None,'editorial_selection':'NOT_RUN','event_recall':'NOT_MEASURED'}
    if request['video'] is not None:
        cfg=request['video'];exact_keys(cfg,['width','height','delta_threshold'],['width','height','delta_threshold'])
        require(any(s['codec_type']=='video' for s in media['streams']),'VIDEO_STREAM_REQUIRED')
        require(all(type(cfg[k]) is int and 8<=cfg[k]<=1024 and cfg[k]%2==0 for k in ['width','height']),'MEASUREMENT_DIMENSIONS_INVALID')
        threshold=number(cfg['delta_threshold'],'delta_threshold',0);require(threshold<=255,'DELTA_THRESHOLD_INVALID')
        vf=f"trim=start={a}:end={b},scale={cfg['width']}:{cfg['height']},format=yuv420p,signalstats,metadata=mode=print:file=video-metadata.txt"
        tools.ff(['-i',asset['path'],'-map','0:v:0','-vf',vf,'-an','-fps_mode','passthrough','-f','null','-'],cwd=directory)
        raw=metadata_rows(directory/'video-metadata.txt',limit);require(raw,'NO_VIDEO_MEASUREMENTS')
        rows=[]
        for i,row in enumerate(raw):
            require('lavfi.signalstats.YAVG' in row and 'lavfi.signalstats.YDIF' in row,'VIDEO_MEASUREMENT_MISSING')
            rows.append({'time':row['time'],'mean_luma':row['lavfi.signalstats.YAVG'],
                         'mean_absolute_luma_delta':None if i==0 else row['lavfi.signalstats.YDIF']})
        result['video']={'config':cfg,'frames':rows,'frame_count':len(rows),'all_decoded_frames_in_requested_interval':True,
            'threshold_crossings':[r['time'] for r in rows if r['mean_absolute_luma_delta'] is not None and r['mean_absolute_luma_delta']>=threshold],
            'first_pts':rows[0]['time'],'last_pts':rows[-1]['time'],
            'max_pts_gap':max((y['time']-x['time'] for x,y in zip(rows,rows[1:])),default=None),
            'scope':'Every decoded frame measured after spatial downscale. Not object detection, motion tracking, highlight ranking or proof of no missed event. First frame has no cross-boundary delta.'}
    if request['audio'] is not None:
        cfg=request['audio'];exact_keys(cfg,['sample_rate','window_samples','rms_threshold_db'],['sample_rate','window_samples','rms_threshold_db'])
        require(type(cfg['sample_rate']) is int and 8000<=cfg['sample_rate']<=96000,'SAMPLE_RATE_INVALID')
        require(type(cfg['window_samples']) is int and cfg['window_samples']>0,'WINDOW_SAMPLES_INVALID')
        threshold=number(cfg['rms_threshold_db'],'rms_threshold_db');require(-160<=threshold<=0,'RMS_THRESHOLD_INVALID')
        if not any(s['codec_type']=='audio' for s in media['streams']):
            result['audio']={'status':'NO_AUDIO','windows':[],'threshold_crossings':[]}
        else:
            af=f"atrim=start={a}:end={b},aresample={cfg['sample_rate']},aformat=channel_layouts=mono,asetnsamples=n={cfg['window_samples']}:p=0,astats=metadata=1:reset=1,ametadata=mode=print:file=audio-metadata.txt"
            tools.ff(['-i',asset['path'],'-map','0:a:0','-af',af,'-vn','-f','null','-'],cwd=directory)
            raw=metadata_rows(directory/'audio-metadata.txt',limit);require(raw,'NO_AUDIO_MEASUREMENTS')
            rows=[]
            for row in raw:
                keys=['lavfi.astats.Overall.RMS_level','lavfi.astats.Overall.Peak_level','lavfi.astats.Overall.Number_of_samples']
                require(all(k in row for k in keys),'AUDIO_MEASUREMENT_MISSING')
                count=row[keys[2]];require(count is not None and count>0,'AUDIO_SAMPLE_COUNT_INVALID')
                rows.append({'start':row['time'],'end':row['time']+count/cfg['sample_rate'],
                    'samples':int(count),'rms_dbfs':row[keys[0]],'peak_dbfs':row[keys[1]]})
            result['audio']={'status':'MEASURED','config':cfg,'windows':rows,
                'threshold_crossings':[r['start'] for r in rows if r['rms_dbfs'] is not None and r['rms_dbfs']>=threshold],
                'scope':'Mono resampled energy only; null dB is digital silence/nonfinite FFmpeg level. No excitement, speaker, semantic or sound-quality inference. Windows do not overlap.'}
    write_json(directory/'media-signals.json',result)
    return result


def event_compile(request,directory,tools):
    from editing_runtime import exact_keys,require,write_json,fingerprint
    from evidence_ops import compile_evidence
    from work_ops import validate_document
    fields=['operation','document','expected_document_sha256','units','occurrences','required_units','chapters','events']
    exact_keys(request,fields,fields)
    folder=directory/'evidence';folder.mkdir()
    base={k:v for k,v in request.items() if k!='events'};base['operation']='evidence-plan-compile'
    proof=compile_evidence(base,folder,tools)
    _,cues,_=validate_document(request['document'],tools);cues={c['id']:c for c in cues}
    occurrences={o['id']:o for o in proof['occurrences']}
    require(isinstance(request['events'],list) and request['events'],'EVENTS_REQUIRED')
    events={};assigned=set()
    for event in request['events']:
        keys=['id','label','mode','setup','action','outcome','replay_of','replay_caption_ids']
        exact_keys(event,keys,keys)
        eid=event['id'];require(isinstance(eid,str) and eid and eid not in events,'EVENT_ID_DUPLICATE_OR_EMPTY')
        require(isinstance(event['label'],str) and event['label'].strip(),'EVENT_LABEL_REQUIRED')
        mode=event['mode'];require(mode in ['complete','open','replay'],'EVENT_MODE_UNKNOWN')
        roles={}
        for role in ['setup','action','outcome']:
            ids=event[role];require(isinstance(ids,list) and all(isinstance(x,str) for x in ids),'EVENT_OCCURRENCE_IDS_REQUIRED')
            require(len(set(ids))==len(ids),'EVENT_OCCURRENCE_DUPLICATE')
            require(set(ids)<=set(occurrences),'EVENT_OCCURRENCE_UNKNOWN')
            require(not assigned.intersection(ids),'EVENT_OCCURRENCE_ALREADY_ASSIGNED');assigned.update(ids)
            items=sorted([occurrences[x] for x in ids],key=lambda x:x['output_start']);roles[role]=items
        require(roles['action'],'EVENT_ACTION_REQUIRED')
        if mode=='complete':require(roles['setup'] and roles['outcome'],'COMPLETE_EVENT_NEEDS_SETUP_AND_OUTCOME')
        previous=None
        for role in ['setup','action','outcome']:
            if not roles[role]:continue
            start=min(x['output_start'] for x in roles[role]);end=max(x['output_end'] for x in roles[role])
            require(previous is None or start>=previous-1e-7,'EVENT_PHASE_ORDER_VIOLATION');previous=end
        if mode=='replay':
            target=event['replay_of'];require(isinstance(target,str) and target in events and events[target]['mode']!='replay','REPLAY_ORIGINAL_MISSING_OR_NOT_PRIOR')
            require(roles['action'][0]['output_start']>=events[target]['output_end']-1e-7,'REPLAY_PRECEDES_ORIGINAL_END')
            ids=event['replay_caption_ids'];require(isinstance(ids,list) and ids and all(isinstance(x,str) and x in cues for x in ids),'REPLAY_CAPTION_REQUIRED')
            # Caller authors the words; verify a visible explicit Replay/重放/回放 label over all action intervals.
            labels=[cues[x] for x in ids]
            require(all(re.search(r'(?i)(\breplay\b|重放|回放)',c['text']) for c in labels),'EXPLICIT_REPLAY_TEXT_REQUIRED')
            for action in roles['action']:
                cursor=action['output_start']
                for c in sorted(labels,key=lambda x:x['start']):
                    if c['start']>cursor+1e-7:break
                    cursor=max(cursor,c['end'])
                require(cursor>=action['output_end']-1e-7,'REPLAY_LABEL_NOT_COVERING_ACTION')
        else:
            require(event['replay_of'] is None and event['replay_caption_ids']==[],'PRIMARY_EVENT_CANNOT_DECLARE_REPLAY')
        items=sum(roles.values(),[])
        events[eid]={**event,'output_start':min(x['output_start'] for x in items),'output_end':max(x['output_end'] for x in items),
            'canonical_event_id':event['replay_of'] if mode=='replay' else eid,'semantic_identity':'caller-declared, not independently verified'}
    require(assigned==set(occurrences),'UNASSIGNED_EVENT_OCCURRENCE')
    result={'schema':'event-map/1','document_sha256':fingerprint(request['document']),'events':list(events.values()),
        'primary_event_count':sum(e['mode']!='replay' for e in events.values()),'replay_count':sum(e['mode']=='replay' for e in events.values()),
        'open_event_count':sum(e['mode']=='open' for e in events.values()),'semantic_review':'NOT_RUN',
        'scope':'Declared phase timing and visible replay labels only. No event detection, true outcome judgment or semantic duplicate discovery.'}
    write_json(directory/'event-map.json',result);return result


def execute(request,directory,tools):
    if request['operation']=='media-signal-scan':return signal_scan(request,directory,tools)
    return event_compile(request,directory,tools)
