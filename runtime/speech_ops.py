"""Validate source-bound words and compile explicit speech-edit decisions.

This module does not transcribe, detect fillers, rank takes, or rewrite speech.
"""
import copy


def validate_transcript(document, tools):
    from editing_runtime import exact_keys, require, source, span, number, fingerprint
    exact_keys(document, ['schema','source','language','timing','origin','words'],
               ['schema','source','language','timing','origin','words'])
    require(document['schema']=='word-transcript/1','TRANSCRIPT_SCHEMA_UNSUPPORTED')
    require(document['timing'] in ['estimated','model-aligned','human-checked'],'TIMING_PROVENANCE_REQUIRED')
    require(isinstance(document['language'],str) and bool(document['language']),'LANGUAGE_REQUIRED')
    exact_keys(document['origin'],['method','reference'],['method','reference'])
    require(all(isinstance(v,str) and v.strip() for v in document['origin'].values()),'ORIGIN_REQUIRED')
    asset=source(document['source']);media=tools.probe(asset['path'])
    require(any(s['codec_type']=='audio' for s in media['streams']),'TRANSCRIPT_REQUIRES_AUDIO')
    require(isinstance(document['words'],list) and document['words'],'WORDS_REQUIRED')
    ids=set();last_start=-1
    for word in document['words']:
        exact_keys(word,['id','text','start','end','speaker','confidence'],['id','text','start','end','speaker','confidence'])
        require(isinstance(word['id'],str) and word['id'] and word['id'] not in ids,'WORD_ID_DUPLICATE_OR_EMPTY')
        ids.add(word['id'])
        require(isinstance(word['text'],str) and word['text'].strip(),'WORD_TEXT_REQUIRED')
        require(isinstance(word['speaker'],str) and word['speaker'],'SPEAKER_REQUIRED')
        a,b=span(word['start'],word['end'],media['duration'])
        require(a>=last_start,'WORDS_NOT_CHRONOLOGICAL');last_start=a
        confidence=number(word['confidence'],'confidence',0);require(confidence<=1,'CONFIDENCE_OUT_OF_RANGE')
    return {'source':asset,'duration':media['duration'],'revision':fingerprint(document),
            'word_count':len(document['words']),'timing':document['timing'],
            'timing_truth':'declared by upstream; not acoustically revalidated by this operation'}


def execute(request,directory,tools):
    from editing_runtime import exact_keys, require, fingerprint, span, normalize_plan, write_json, source
    op=request['operation']
    if op=='transcript-import':
        exact_keys(request,['operation','transcript'],['operation','transcript'])
        result=validate_transcript(request['transcript'],tools)
        write_json(directory/'transcript.json',copy.deepcopy(request['transcript']))
        return {**result,'recognition_accuracy':'NOT_VERIFIED','acoustic_alignment':'NOT_VERIFIED'}
    exact_keys(request,['operation','transcript','expected_revision','output','segments','protected_word_ids','allow_reorder'],
               ['operation','transcript','expected_revision','output','segments','protected_word_ids','allow_reorder'])
    transcript=request['transcript'];metadata=validate_transcript(transcript,tools)
    require(metadata['revision']==request['expected_revision'],'TRANSCRIPT_REVISION_CONFLICT')
    require(transcript['timing']!='estimated','ESTIMATED_WORD_TIMES_NOT_EDIT_BOUNDARIES')
    exact_keys(request['output'],['fps','width','height','fit'],['fps','width','height','fit'])
    require(type(request['allow_reorder']) is bool,'REORDER_BOOLEAN_REQUIRED')
    require(isinstance(request['segments'],list) and request['segments'],'SEGMENTS_REQUIRED')
    require(isinstance(request['protected_word_ids'],list) and all(isinstance(x,str) for x in request['protected_word_ids']),'PROTECTED_WORD_IDS_REQUIRED')
    words=transcript['words'];by_id={w['id']:w for w in words};indices={w['id']:i for i,w in enumerate(words)}
    require(set(request['protected_word_ids'])<=set(by_id),'PROTECTED_WORD_UNKNOWN')
    clips=[];used=set();seen_segments=set();previous_index=-1;decisions=[];cues=[]
    for segment in request['segments']:
        exact_keys(segment,['id','word_ids','start','end','gain_db','boundary_evidence'],
                   ['id','word_ids','start','end','gain_db','boundary_evidence'])
        sid=segment['id'];require(isinstance(sid,str) and sid and sid not in seen_segments,'SEGMENT_ID_DUPLICATE_OR_EMPTY');seen_segments.add(sid)
        selected=segment['word_ids']
        require(isinstance(selected,list) and selected and all(isinstance(x,str) for x in selected),'WORD_IDS_REQUIRED')
        require(len(selected)==len(set(selected)) and not used.intersection(selected),'DUPLICATE_WORD_USE')
        require(set(selected)<=set(by_id),'WORD_UNKNOWN')
        order=[indices[x] for x in selected]
        require(order==list(range(order[0],order[-1]+1)),'SEGMENT_WORDS_NOT_CONTIGUOUS')
        if not request['allow_reorder']:require(order[0]>previous_index,'REORDER_NOT_AUTHORIZED')
        previous_index=order[-1]
        a,b=span(segment['start'],segment['end'],metadata['duration'])
        for wid in selected:
            w=by_id[wid]
            require(a<=w['start'] and b>=w['end'],'KEPT_WORD_TRUNCATED: '+wid)
        # Margin must not bring an excluded word or overlapping speaker back into the audio.
        unlisted=[w['id'] for w in words if w['id'] not in selected and w['start']<b and w['end']>a]
        require(not unlisted,'UNLISTED_WORD_IN_AUDIO: '+','.join(unlisted))
        evidence=segment['boundary_evidence']
        exact_keys(evidence,['method','artifact'],['method','artifact'])
        require(evidence['method'] in ['waveform-review','listening-review','alignment-review'],'BOUNDARY_METHOD_REQUIRED')
        artifact=source(evidence['artifact'])
        used.update(selected)
        clips.append({'id':sid,'source_id':'speech','start':a,'end':b,'gain_db':segment['gain_db']})
        decisions.append({'segment_id':sid,'word_ids':selected,'text':' '.join(by_id[x]['text'] for x in selected),
                          'boundary_evidence':artifact,'boundary_method':evidence['method']})
        cues.extend({'id':wid,'source_id':'speech','start':by_id[wid]['start'],'end':by_id[wid]['end'],'text':by_id[wid]['text']} for wid in selected)
    require(set(request['protected_word_ids'])<=used,'PROTECTED_WORD_DELETED')
    plan={'schema':'execution-plan/1',**request['output'],'sources':{'speech':transcript['source']},'clips':clips}
    normalized=normalize_plan(plan,tools)
    # Output frame rounding must not clip the tail of a retained word.
    for clip,segment in zip(normalized['clips'],request['segments']):
        source_coverage_end=clip['start']+clip['output_end']-clip['output_start']
        require(source_coverage_end+1e-8>=max(by_id[x]['end'] for x in segment['word_ids']),'WORD_TRUNCATED_BY_FRAME_QUANTIZATION')
    write_json(directory/'execution-plan.json',plan)
    write_json(directory/'source-cues.json',{'cues':cues,'precision':transcript['timing'],'grouping':'words, not publication-ready subtitle lines'})
    report={'transcript_revision':metadata['revision'],'plan_revision':fingerprint(plan),'kept_word_ids':[x for s in request['segments'] for x in s['word_ids']],
            'removed_word_ids':[w['id'] for w in words if w['id'] not in used],'segments':decisions,
            'boundary_evidence_verified':'file identity only; content and actual listening not inferred',
            'semantic_review':'NOT_RUN','acoustic_review':'NOT_RUN'}
    write_json(directory/'speech-decisions.json',report)
    return report
