"""Measured constant offsets and explicit multicamera picture/program-audio mapping."""
from fractions import Fraction
import statistics
import subprocess
import sys


def declare_clock(request,directory,tools):
    """Import explicit external clock metadata without inventing measured markers."""
    from editing_runtime import exact_keys,require,source,number,span,write_json
    fields=['operation','method','reference','follower','clock_id','reference_origin_seconds',
            'follower_origin_seconds','coverage_session','clock_evidence','uncertainty_seconds']
    exact_keys(request,fields,fields)
    require(isinstance(request['clock_id'],str) and request['clock_id'].strip(),'CLOCK_ID_REQUIRED')
    refs={k:source(request[k]) for k in ['reference','follower']}
    media={k:tools.probe(v['path']) for k,v in refs.items()}
    evidence=source(request['clock_evidence'])
    ref_origin=number(request['reference_origin_seconds'],'reference_origin_seconds')
    follower_origin=number(request['follower_origin_seconds'],'follower_origin_seconds')
    offset=follower_origin-ref_origin
    coverage=request['coverage_session']
    require(isinstance(coverage,list) and len(coverage)==2,'CLOCK_COVERAGE_REQUIRED')
    a,b=[number(t,'coverage_session') for t in coverage];require(a<b,'CLOCK_COVERAGE_INVALID')
    span(a,b,media['reference']['duration']);span(a-offset,b-offset,media['follower']['duration'])
    uncertainty=request['uncertainty_seconds']
    if uncertainty is not None:number(uncertainty,'uncertainty_seconds',0)
    report={'schema':'sync-measurement/1','method':'declared-clock','reference':request['reference'],
        'follower':request['follower'],'clock_id':request['clock_id'],'clock_evidence':request['clock_evidence'],
        'reference_origin_seconds':ref_origin,'follower_origin_seconds':follower_origin,
        'candidate_offset_seconds':offset,'coverage_session':[a,b],'uncertainty_seconds':uncertainty,
        'measurement_state':'DECLARED','issues':[],'measurements':[],
        'convention':'session_time = source_time + offset_seconds; reference source starts at session 0',
        'automatically_applied':False,'physical_sync_review':'NOT_RUN',
        'trust_limit':'Caller imports clock metadata; evidence bytes and coverage checked, content/physical alignment not independently validated'}
    write_json(directory/'sync-measurement.json',report);return report


def sync_measure(request,directory,tools):
    from editing_runtime import exact_keys,require,source,number,span,write_json,ContractError,sha256
    if request.get('method')=='declared-clock':return declare_clock(request,directory,tools)
    common=['operation','method','reference','follower','max_spread_seconds','min_span_seconds']
    method=request.get('method');require(method in ['audio-correlation','declared-markers'],'SYNC_METHOD_UNSUPPORTED')
    extra=['windows','sample_rate','min_score','min_peak_margin','peak_exclusion_seconds'] if method=='audio-correlation' else ['markers','marker_evidence']
    feature_keys=['correlation_feature','envelope_window_ms','envelope_hop_ms'] if method=='audio-correlation' else []
    exact_keys(request,common+extra+feature_keys,common+extra)
    refs={k:source(request[k]) for k in ['reference','follower']};media={k:tools.probe(v['path']) for k,v in refs.items()}
    tolerance=number(request['max_spread_seconds'],'max_spread_seconds',0)
    min_span=number(request['min_span_seconds'],'min_span_seconds',0);require(min_span>0,'POSITIVE_SPAN_REQUIRED')
    measurements=[];issues=[];extra_report={}
    if method=='declared-markers':
        evidence=source(request['marker_evidence']);markers=request['markers']
        require(isinstance(markers,list) and len(markers)>=3,'THREE_MARKERS_REQUIRED')
        previous=[-1,-1]
        for m in markers:
            exact_keys(m,['reference_time','follower_time'],['reference_time','follower_time'])
            times=[number(m[k+'_time'],k+'_time',0) for k in ['reference','follower']]
            require(all(t<media[k]['duration'] for t,k in zip(times,['reference','follower'])),'MARKER_OUT_OF_RANGE')
            require(all(a>b for a,b in zip(times,previous)),'MARKERS_NOT_STRICTLY_CHRONOLOGICAL');previous=times
            measurements.append({**m,'offset_seconds':times[0]-times[1]})
        extra_report={'marker_evidence':evidence,'marker_truth':'caller-declared correspondences; not independently observed'}
    else:
        try:import numpy as np
        except ImportError as exc:raise ContractError('DEPENDENCY_UNAVAILABLE: numpy; run with the declared analysis environment') from exc
        require(all(any(s['codec_type']=='audio' for s in m['streams']) for m in media.values()),'SYNC_AUDIO_REQUIRED')
        rate=request['sample_rate'];require(type(rate) is int and rate in [8000,16000],'SYNC_SAMPLE_RATE_UNSUPPORTED')
        feature=request.get('correlation_feature','waveform')
        require(feature in ['waveform','log-rms-envelope'],'SYNC_FEATURE_UNSUPPORTED')
        correlation_rate=rate;feature_parameters={}
        if feature=='log-rms-envelope':
            win_ms=request.get('envelope_window_ms');hop_ms=request.get('envelope_hop_ms')
            require(type(win_ms) is int and type(hop_ms) is int and 5<=hop_ms<=100 and hop_ms<=win_ms<=200,'ENVELOPE_WINDOW_INVALID')
            win=rate*win_ms//1000;hop=rate*hop_ms//1000;correlation_rate=rate/hop
            feature_parameters={'window_ms':win_ms,'hop_ms':hop_ms,'energy_floor':1e-12}
        else:require(not any(k in request for k in ['envelope_window_ms','envelope_hop_ms']),'ENVELOPE_FIELDS_WITH_WAVEFORM')
        score_min=number(request['min_score'],'min_score',0);margin_min=number(request['min_peak_margin'],'min_peak_margin',0)
        require(score_min<=1 and margin_min<=1,'CORRELATION_THRESHOLD_INVALID')
        exclusion=number(request['peak_exclusion_seconds'],'peak_exclusion_seconds',1/rate)
        windows=request['windows'];require(isinstance(windows,list) and len(windows)>=2,'TWO_SYNC_WINDOWS_REQUIRED')
        def decode(asset,start,duration):
            r=subprocess.run([tools.binary('ffmpeg'),'-nostdin','-v','error','-i',asset['path'],'-ss',str(start),'-t',str(duration),
                '-map','0:a:0','-ac','1','-ar',str(rate),'-f','f32le','-'],capture_output=True,timeout=300)
            require(r.returncode==0,'SYNC_DECODE_FAILED: '+r.stderr.decode(errors='replace')[-1000:])
            data=np.frombuffer(r.stdout,dtype='<f4').astype(np.float64)
            require(np.all(np.isfinite(data)),'NONFINITE_AUDIO_SAMPLES');return data
        previous_end=-1
        for i,w in enumerate(windows):
            exact_keys(w,['follower_start','duration','reference_start','reference_end'],['follower_start','duration','reference_start','reference_end'])
            f=number(w['follower_start'],'follower_start',0);duration=number(w['duration'],'duration',0.5)
            require(duration<=30,'SYNC_WINDOW_TOO_LONG');span(f,f+duration,media['follower']['duration'])
            a,b=span(w['reference_start'],w['reference_end'],media['reference']['duration'])
            require(duration+2*exclusion<b-a<=120,'REFERENCE_SEARCH_WINDOW_INVALID')
            require(f>=previous_end,'FOLLOWER_WINDOWS_OVERLAP');previous_end=f+duration
            x=decode(refs['reference'],a,b-a);y=decode(refs['follower'],f,duration)
            require(len(x)>len(y)>0,'SYNC_DECODE_WINDOW_TOO_SHORT')
            silent=float(np.mean(y*y))<=1e-12
            if feature=='log-rms-envelope':
                def envelope(samples):
                    cumulative=np.concatenate(([0.],np.cumsum(samples*samples)))
                    starts=np.arange(0,len(samples)-win+1,hop)
                    return .5*np.log(np.maximum((cumulative[starts+win]-cumulative[starts])/win,1e-12))
                x=envelope(x);y=envelope(y)
            m=len(y);y=y-y.mean();energy=float(np.dot(y,y))
            local=[]
            if silent or energy<=1e-12:
                issue='SILENT_FOLLOWER_WINDOW' if silent else 'UNINFORMATIVE_FOLLOWER_WINDOW'
                measurements.append({'follower_time':f,'offset_seconds':None,'issues':[issue]});issues.append('window%d:%s'%(i,issue));continue
            n=1 << (len(x)+m-2).bit_length()
            dots=np.fft.irfft(np.fft.rfft(x,n)*np.fft.rfft(y[::-1],n),n)[m-1:len(x)]
            sums=np.concatenate(([0.],np.cumsum(x)));squares=np.concatenate(([0.],np.cumsum(x*x)))
            var=(squares[m:]-squares[:-m])-(sums[m:]-sums[:-m])**2/m
            denom=np.sqrt(np.maximum(var,0)*energy)
            scores=np.divide(dots,denom,out=np.zeros_like(dots),where=denom>1e-12)
            scores=np.clip(scores,-1,1)
            # Envelope anticorrelation is not polarity inversion; only positive dynamics can match.
            magnitudes=np.abs(scores) if feature=='waveform' else scores
            best=int(np.argmax(magnitudes))
            exclusion_samples=max(1,round(exclusion*correlation_rate));others=magnitudes.copy()
            others[max(0,best-exclusion_samples):min(len(others),best+exclusion_samples+1)]=-1
            runner=float(others.max());peak=float(magnitudes[best]);margin=peak-max(0,runner)
            if peak<score_min:local.append('LOW_CORRELATION')
            if runner<0:local.append('SEARCH_TOO_NARROW')
            elif margin<margin_min:local.append('AMBIGUOUS_PEAK')
            if best==0 or best==len(scores)-1:local.append('PEAK_AT_SEARCH_EDGE')
            reference_time=a+best/correlation_rate
            measurements.append({'follower_time':f,'reference_time':reference_time,'offset_seconds':reference_time-f,
                                 'correlation':float(scores[best]),'peak_margin':margin,'issues':local})
            issues.extend('window%d:%s'%(i,item) for item in local)
        extra_report={'sample_rate':rate,'correlation_feature':feature,'feature_parameters':feature_parameters,
                      'precision_seconds':1/correlation_rate,'precision_scope':'lag grid spacing, not guaranteed alignment accuracy',
                      'alignment_scope':'coarse-envelope-candidate' if feature=='log-rms-envelope' else 'waveform-candidate',
                      'numpy_version':np.__version__,
                      'python':{'executable':sys.executable,'version':sys.version,'sha256':sha256(sys.executable)},
                      'acceptance_thresholds':{k:request[k] for k in ['min_score','min_peak_margin','peak_exclusion_seconds']},
                      'method_limits':'mono correlation; envelope is coarse only; neither identifies speakers, establishes same take, or proves lip sync'}
    usable=[m for m in measurements if m['offset_seconds'] is not None]
    offsets=[m['offset_seconds'] for m in usable]
    offset=statistics.median(offsets) if offsets else None
    spread=max(offsets)-min(offsets) if offsets else None
    measured_span=measurements[-1]['follower_time']-measurements[0]['follower_time']
    if measured_span<min_span:issues.append('INSUFFICIENT_TIME_COVERAGE')
    if spread is not None and spread>tolerance+1e-10:issues.append('NONCONSTANT_OFFSET_OR_BAD_MATCH')
    if len(usable)!=len(measurements):issues.append('INCOMPLETE_MEASUREMENTS')
    report={'schema':'sync-measurement/1','method':method,'reference':request['reference'],'follower':request['follower'],
        'convention':'session_time = source_time + offset_seconds; reference source starts at session 0',
        'candidate_offset_seconds':offset,'spread_seconds':spread,'measured_span_seconds':measured_span,
        'max_spread_seconds':tolerance,'min_span_seconds':min_span,'measurements':measurements,'issues':issues,
        'measurement_state':'REVIEW_NEEDED' if issues else 'CONSISTENT','automatically_applied':False,
        'physical_sync_review':'NOT_RUN',**extra_report}
    write_json(directory/'sync-measurement.json',report);return report


def compile_multicam(request,directory,tools):
    from editing_runtime import exact_keys,require,source,number,span,fingerprint,normalize_plan,write_json,ContractError,verified_json
    from work_ops import validate_document
    exact_keys(request,['operation','master','expected_revision','output','segments','allow_reorder','allow_session_reuse','allow_declared_clock'],
               ['operation','master','expected_revision','output','segments','allow_reorder','allow_session_reuse'])
    allow_declared=request.get('allow_declared_clock',False)
    require(type(allow_declared) is bool,'BOOLEAN_POLICY_REQUIRED')
    master=request['master'];require(fingerprint(master)==request['expected_revision'],'SYNC_MASTER_REVISION_CONFLICT')
    exact_keys(master,['schema','reference_id','sources','placements'],['schema','reference_id','sources','placements'])
    require(master['schema']=='multicam-master/1','SYNC_MASTER_SCHEMA_UNSUPPORTED')
    require(isinstance(master['sources'],dict) and master['sources'],'SOURCES_REQUIRED')
    require(isinstance(master['placements'],dict) and set(master['placements'])==set(master['sources']),'PLACEMENT_SOURCES_MISMATCH')
    reference=master['reference_id'];require(reference in master['sources'],'REFERENCE_UNKNOWN')
    media={};offsets={};evidence={};declared={}
    for sid,ref in master['sources'].items():
        require(isinstance(sid,str) and sid,'SOURCE_ID_REQUIRED');asset=source(ref);media[sid]=tools.probe(asset['path'])
        place=master['placements'][sid];exact_keys(place,['offset_seconds','evidence'],['offset_seconds','evidence'])
        offsets[sid]=number(place['offset_seconds'],'offset_seconds')
        if sid==reference:
            require(offsets[sid]==0 and place['evidence'] is None,'REFERENCE_OFFSET_MUST_BE_ZERO');continue
        record,measurement=verified_json(place['evidence'],'SYNC_EVIDENCE')
        require(measurement.get('schema')=='sync-measurement/1','SYNC_EVIDENCE_SCHEMA_UNSUPPORTED')
        require(measurement.get('reference')==master['sources'][reference] and measurement.get('follower')==ref,'SYNC_EVIDENCE_SOURCE_MISMATCH')
        if measurement.get('method')=='declared-clock':
            require(allow_declared,'DECLARED_CLOCK_NOT_ALLOWED')
            require(measurement.get('measurement_state')=='DECLARED' and not measurement.get('issues'),'CLOCK_DECLARATION_INVALID')
            source(measurement['clock_evidence'])  # Revalidate underlying declaration, not just its wrapper.
            coverage=measurement.get('coverage_session')
            require(isinstance(coverage,list) and len(coverage)==2,'CLOCK_COVERAGE_REQUIRED')
            ca,cb=[number(t,'coverage_session') for t in coverage];require(ca<cb,'CLOCK_COVERAGE_INVALID')
            declared[sid]={'coverage_session':[ca,cb],'uncertainty_seconds':measurement.get('uncertainty_seconds'),'physical_sync_review':'NOT_RUN'}
        else:require(measurement.get('measurement_state')=='CONSISTENT' and not measurement.get('issues'),'SYNC_MEASUREMENT_NOT_CONSISTENT')
        require(measurement.get('candidate_offset_seconds')==offsets[sid],'SYNC_OFFSET_EVIDENCE_MISMATCH')
        evidence[sid]=record
    output=request['output'];exact_keys(output,['fps','width','height','fit'],['fps','width','height','fit'])
    try:fps=Fraction(str(output['fps']))
    except (ValueError,ZeroDivisionError) as exc:raise ContractError('INVALID_FPS') from exc
    require(1<=fps<=120,'FPS_OUT_OF_RANGE')
    require(type(request['allow_reorder']) is bool and type(request['allow_session_reuse']) is bool,'BOOLEAN_POLICY_REQUIRED')
    segments=request['segments'];require(isinstance(segments,list) and segments,'SEGMENTS_REQUIRED')
    clips=[];tracks={};seen=set();used=[];mapping=[];previous_end=None
    for segment in segments:
        exact_keys(segment,['id','start','end','shots','program_audio'],['id','start','end','shots','program_audio'])
        sid=segment['id'];require(isinstance(sid,str) and sid and sid not in seen,'SEGMENT_ID_DUPLICATE_OR_EMPTY');seen.add(sid)
        a=number(segment['start'],'start');b=number(segment['end'],'end');require(a<b,'SESSION_RANGE_INVALID')
        if not request['allow_reorder'] and previous_end is not None:require(a>=previous_end,'SESSION_REORDER_NOT_AUTHORIZED')
        previous_end=b
        if not request['allow_session_reuse']:require(not any(a<y and b>x for x,y in used),'SESSION_REUSE_NOT_AUTHORIZED')
        used.append((a,b))
        frames=int((Fraction(str(b))-Fraction(str(a)))*fps);require(frames>0,'SUBFRAME_SEGMENT')
        require(isinstance(segment['shots'],list) and segment['shots'],'SHOTS_REQUIRED')
        require(isinstance(segment['program_audio'],list) and segment['program_audio'],'PROGRAM_AUDIO_REQUIRED')
        cursor=a;previous_frame=0;first_clip=None
        for index,shot in enumerate(segment['shots']):
            exact_keys(shot,['id','angle_id','start','end'],['id','angle_id','start','end'])
            angle=shot['angle_id'];require(angle in media,'ANGLE_UNKNOWN')
            require(any(s['codec_type']=='video' for s in media[angle]['streams']),'ANGLE_VIDEO_REQUIRED')
            left=number(shot['start'],'shot.start');right=number(shot['end'],'shot.end')
            require(abs(left-cursor)<1e-8 and left<right<=b+1e-8,'SHOT_GAP_OR_OVERLAP')
            last=index==len(segment['shots'])-1
            if last:require(abs(right-b)<1e-8,'PICTURE_DOES_NOT_COVER_SEGMENT')
            end_frame=frames if last else round((Fraction(str(right))-Fraction(str(a)))*fps)
            require(previous_frame<end_frame<=frames,'SUBFRAME_OR_OVERRUN_SHOT')
            session_start=a+float(previous_frame/fps);session_end=a+float(end_frame/fps)
            source_a=session_start-offsets[angle];source_b=session_end-offsets[angle]
            span(source_a,source_b,media[angle]['duration'])
            if angle in declared:
                ca,cb=declared[angle]['coverage_session'];require(ca<=session_start and session_end<=cb,'OUTSIDE_DECLARED_CLOCK_COVERAGE')
            require(isinstance(shot['id'],str) and shot['id'],'SHOT_ID_REQUIRED')
            cid=shot['id'];first_clip=first_clip or cid
            clips.append({'id':cid,'source_id':angle,'start':source_a,'end':source_b,'gain_db':0,'mute':True})
            mapping.append({'segment_id':sid,'clip_id':cid,'angle_id':angle,'requested_session_range':[left,right],
                'actual_session_range':[session_start,session_end],'source_range':[source_a,source_b],'offset_seconds':offsets[angle],
                'quantization_delta_seconds':[session_start-left,session_end-right]})
            previous_frame=end_frame;cursor=right
        for index,audio in enumerate(segment['program_audio']):
            exact_keys(audio,['source_id','gain_db'],['source_id','gain_db']);aid=audio['source_id']
            require(aid in media and any(s['codec_type']=='audio' for s in media[aid]['streams']),'PROGRAM_AUDIO_STREAM_REQUIRED')
            require(sum(x['source_id']==aid for x in segment['program_audio'])==1,'DUPLICATE_PROGRAM_SOURCE')
            sa=a-offsets[aid];sb=sa+float(frames/fps);span(sa,sb,media[aid]['duration'])
            if aid in declared:
                ca,cb=declared[aid]['coverage_session'];require(ca<=a and a+float(frames/fps)<=cb,'OUTSIDE_DECLARED_CLOCK_COVERAGE')
            tracks[f'{sid}-audio-{index}']={'source':master['sources'][aid],'start':sa,'end':sb,'anchor_clip_id':first_clip,'offset':0,'gain_db':audio['gain_db']}
    plan={'schema':'execution-plan/1',**output,'sources':{sid:master['sources'][sid] for sid in {c['source_id'] for c in clips}},
          'clips':clips,'allow_source_reuse':request['allow_session_reuse']}
    norm=normalize_plan(plan,tools)
    # Every shot boundary was quantized once on a shared section clock; never sum independent rounded durations.
    for m,c in zip(mapping,norm['clips']):
        m['output_range']=[c['output_start'],c['output_end']]
        require(abs((c['output_end']-c['output_start'])-(m['actual_session_range'][1]-m['actual_session_range'][0]))<1e-7,'SYNC_FRAME_QUANTIZATION_MISMATCH')
    doc={'schema':'work-document/1','plan':plan,'captions':{},'caption_style':None,'audio_tracks':tracks,'style_bindings':{},
         'notes':{'sync_master_revision':fingerprint(master),'director_choice':'caller-supplied; not validated by compiler',
                  'declared_clock_sources':declared,'physical_sync_review':'NOT_RUN'}}
    validate_document(doc,tools)
    report={'schema':'multicam-map/1','master_revision':fingerprint(master),'placements':master['placements'],'evidence':evidence,
            'picture_mapping':mapping,'audio_tracks':tracks,'duration':norm['duration'],
            'camera_embedded_audio':'muted explicitly; program sources continue across picture switches',
            'declared_clock_sources':declared,'physical_sync_review':'NOT_RUN','director_quality':'NOT_RUN','native_multitrack_master':'NOT_CREATED'}
    write_json(directory/'work-document.json',doc);write_json(directory/'multicam-map.json',report);return report


def execute(request,directory,tools):
    if request['operation']=='sync-offset-measure':return sync_measure(request,directory,tools)
    return compile_multicam(request,directory,tools)
