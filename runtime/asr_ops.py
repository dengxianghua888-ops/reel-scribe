"""Pinned local speech recognition observations; no editorial deletion or rewriting."""
import importlib.metadata
import json
import math
from pathlib import Path
import sys


def json_safe_metadata(value, path='$'):
    """Preserve backend metadata shape while making non-finite floats explicit."""
    from dataclasses import asdict,is_dataclass
    if is_dataclass(value):value=asdict(value)
    elif hasattr(value,'_asdict'):value=value._asdict()
    elif hasattr(value,'__dict__'):value=vars(value)
    if isinstance(value,dict):
        result={};nonfinite=[]
        for key,item in value.items():
            if not isinstance(key,str):raise ValueError('ASR_INFO_KEY_NOT_STRING: '+path)
            result[key],found=json_safe_metadata(item,f'{path}.{key}');nonfinite.extend(found)
        return result,nonfinite
    if isinstance(value,(list,tuple)):
        result=[];nonfinite=[]
        for index,item in enumerate(value):
            clean,found=json_safe_metadata(item,f'{path}[{index}]');result.append(clean);nonfinite.extend(found)
        return result,nonfinite
    if isinstance(value,float) and not math.isfinite(value):return None,[path]
    if value is None or isinstance(value,(bool,int,float,str)):return value,[]
    raise ValueError(f'ASR_INFO_UNSERIALIZABLE: {path}: {type(value).__name__}')


def verify_model(reference):
    from editing_runtime import source, require
    lock_ref=source(reference); lock=json.loads(Path(lock_ref['path']).read_text())
    require(lock.get('schema')=='local-asr-model/1' and lock.get('provider')=='faster-whisper','ASR_MODEL_LOCK_INVALID')
    root=Path(lock_ref['path']).parent; names=set()
    for row in lock['files']:
        require(row['name'] not in names,'ASR_MODEL_FILE_DUPLICATE'); names.add(row['name'])
        p=Path(row['path']); require(p.resolve()==(root/row['name']).resolve() and p.parent.resolve()==root,'ASR_MODEL_PATH_INVALID')
        bound=source({'path':str(p),'sha256':row['sha256']}); require(bound['bytes']==row['bytes'],'ASR_MODEL_SIZE_MISMATCH')
    require({'config.json','model.bin','tokenizer.json'}<=names and bool({'vocabulary.txt','vocabulary.json'}&names),'ASR_MODEL_FILES_MISSING')
    # CT2 accepts text or JSON vocabularies; faster-whisper also reads an optional
    # preprocessor file. Every present loader input must belong to the lock.
    loader_names={'config.json','model.bin','tokenizer.json','vocabulary.txt','vocabulary.json','preprocessor_config.json'}
    unbound={name for name in loader_names if (root/name).exists() and name not in names}
    require(not unbound,'ASR_UNBOUND_MODEL_FILE: '+','.join(sorted(unbound)))
    return lock_ref,lock,root


def verify_environment(reference):
    from editing_runtime import source,require
    ref=source(reference); lock=json.loads(Path(ref['path']).read_text())
    require(lock.get('schema')=='asr-environment/1','ASR_ENVIRONMENT_LOCK_INVALID')
    require(lock.get('python')==sys.version,'ASR_PYTHON_VERSION_MISMATCH')
    names=set()
    for row in lock['packages']:
        name=row['name'].lower().replace('_','-');require(name not in names,'ASR_PACKAGE_DUPLICATE');names.add(name)
        try:dist=importlib.metadata.distribution(row['name'])
        except importlib.metadata.PackageNotFoundError as exc:raise ValueError('ASR_DEPENDENCY_UNAVAILABLE: '+row['name']) from exc
        require(dist.version==row['version'],'ASR_PACKAGE_VERSION_MISMATCH: '+name)
        actual={str(Path(dist.locate_file(f)).resolve()) for f in dist.files or [] if Path(dist.locate_file(f)).is_file() and Path(f).suffix!='.pyc' and '__pycache__' not in Path(f).parts}
        expected={f['path'] for f in row['files']};require(actual==expected and len(expected)==len(row['files']),'ASR_PACKAGE_FILES_CHANGED: '+name)
        for f in row['files']:
            item=source({'path':f['path'],'sha256':f['sha256']});require(item['bytes']==f['bytes'],'ASR_PACKAGE_SIZE_MISMATCH')
    require({'faster-whisper','ctranslate2','av','tokenizers','numpy','onnxruntime','huggingface-hub'}<=names,'ASR_ENVIRONMENT_INCOMPLETE')
    require(importlib.metadata.version('faster-whisper')=='1.2.1','ASR_BACKEND_VERSION_UNSUPPORTED')
    return ref,lock


def normalize_observation(raw,asset,language,start,end,origin):
    """Keep raw text intact. Do not invent nonzero spans or export a partial editable transcript."""
    issues=[];words=[];last_start=-1
    for si,segment in enumerate(raw['segments']):
        items=segment.get('words') or []
        if segment.get('text','').strip() and not items:issues.append({'segment':si,'reason':'TEXT_WITHOUT_WORD_TIMES'})
        joined=''.join(w.get('word','') for w in items)
        # Whitespace is layout only; do not normalize punctuation or Chinese characters.
        if ''.join(joined.split())!=''.join(segment.get('text','').split()):issues.append({'segment':si,'reason':'SEGMENT_WORD_TEXT_MISMATCH'})
        for wi,w in enumerate(items):
            a=w.get('start');b=w.get('end');c=w.get('probability');txt=w.get('word')
            valid=all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in (a,b,c))
            valid=valid and 0<=a<b<=end-start+1e-8 and a>=last_start and 0<=c<=1 and isinstance(txt,str) and bool(txt.strip())
            if not valid:
                issues.append({'segment':si,'word':wi,'reason':'INVALID_OR_ZERO_WORD_SPAN_PROBABILITY_OR_TEXT'});continue
            last_start=a
            words.append({'id':f'w{si:05d}-{wi:04d}','text':txt,'start':start+a,'end':start+b,'speaker':'unknown','confidence':c})
    if issues:return None,issues
    if not words:return None,[]
    return {'schema':'word-transcript/1','source':asset,'language':language,'timing':'model-aligned',
            'origin':{'method':'faster-whisper 1.2.1 internal word alignment; no separate forced alignment, diarization or human hearing check','reference':origin},'words':words},[]


def recognition_pcm(reference):
    """Read only our bound 16k mono PCM16 WAV; never invoke a second decoder."""
    import hashlib
    import io
    import wave
    import numpy as np
    from editing_runtime import source,require
    bound=source(reference)
    data=Path(bound['path']).read_bytes()
    require(hashlib.sha256(data).hexdigest()==reference['sha256'],'ASR_PCM_IDENTITY_CHANGED')
    require(len(data)>=12 and data[:4]==b'RIFF' and data[8:12]==b'WAVE'
            and int.from_bytes(data[4:8],'little')+8==len(data),'ASR_PCM_CONTAINER_INVALID')
    # wave.readframes alone ignores trailing chunks and inconsistent PCM headers.
    # Validate the entire bounded RIFF, while retaining opaque metadata chunks.
    import struct
    offset=12;seen=set();data_size=None
    while offset<len(data):
        require(offset+8<=len(data),'ASR_PCM_CONTAINER_INVALID')
        kind=data[offset:offset+4];size=int.from_bytes(data[offset+4:offset+8],'little')
        start=offset+8;end=start+size;padded=end+(size%2)
        require(padded<=len(data),'ASR_PCM_FRAMES_INCOMPLETE' if kind==b'data' else 'ASR_PCM_CONTAINER_INVALID')
        if size%2:require(data[end]==0,'ASR_PCM_PADDING_INVALID')
        if kind in (b'fmt ',b'data'):
            require(kind not in seen,'ASR_PCM_DUPLICATE_CHUNK')
            seen.add(kind)
        if kind==b'fmt ':
            require(size==16 and struct.unpack('<HHIIHH',data[start:end])==(1,1,16000,32000,2,16),
                    'ASR_PCM_FORMAT_INVALID')
        if kind==b'data':
            require(b'fmt ' in seen and size>0 and size%2==0,'ASR_PCM_FRAMES_INCOMPLETE')
            data_size=size
        offset=padded
    require(seen=={b'fmt ',b'data'} and offset==len(data),'ASR_PCM_CONTAINER_INVALID')
    try:
        with wave.open(io.BytesIO(data),'rb') as stream:
            require(stream.getnchannels()==1 and stream.getframerate()==16000 and
                    stream.getsampwidth()==2 and stream.getcomptype()=='NONE','ASR_PCM_FORMAT_INVALID')
            count=stream.getnframes()
            pcm=stream.readframes(count+1)
            require(count>0 and len(pcm)==count*2==data_size,'ASR_PCM_FRAMES_INCOMPLETE')
    except (wave.Error,EOFError) as exc:
        raise ValueError('ASR_PCM_FORMAT_INVALID: '+str(exc)) from exc
    source(reference)
    return np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768.0


def transcribe(request,directory,tools):
    from editing_runtime import exact_keys,require,source,span,write_json,sha256
    keys=['operation','source','audio_stream','start','end','model_lock','environment_lock','language','beam_size','vad_filter','condition_on_previous_text','cpu_threads']
    exact_keys(request,keys,keys)
    asset=source(request['source']);media=tools.probe(asset['path']);a,b=span(request['start'],request['end'],media['duration'])
    idx=request['audio_stream'];require(type(idx) is int and any(s['index']==idx and s['codec_type']=='audio' for s in media['streams']),'ASR_AUDIO_STREAM_REQUIRED')
    require(isinstance(request['language'],str) and len(request['language']) in (2,3) and request['language'].isascii() and request['language'].islower(),'ASR_LANGUAGE_CODE_REQUIRED')
    for k,hi in [('beam_size',10),('cpu_threads',32)]:require(type(request[k]) is int and 1<=request[k]<=hi,'ASR_INTEGER_RANGE: '+k)
    for k in ['vad_filter','condition_on_previous_text']:require(type(request[k]) is bool,'ASR_BOOLEAN_REQUIRED: '+k)
    ml,model,root=verify_model(request['model_lock']);el,environment=verify_environment(request['environment_lock'])
    try:from faster_whisper import WhisperModel
    except ImportError as exc:raise ValueError('ASR_DEPENDENCY_UNAVAILABLE: faster-whisper') from exc
    wav=directory/'recognition-input.wav'
    # Explicit input PTS window and absolute audio-stream index; retain initial silence if audio begins later.
    tools.ff(['-copyts','-i',asset['path'],'-map',f'0:{idx}','-af',f'atrim=start={a}:end={b},asetpts=PTS-{a}/TB,aresample=16000:async=1:first_pts=0,apad,atrim=duration={b-a}',
              '-ac','1','-c:a','pcm_s16le',str(wav)])
    audio_ref={'path':str(wav),'sha256':sha256(wav)}
    audio=recognition_pcm(audio_ref)
    write_json(directory/'input-binding.json',{'source':request['source'],'window':[a,b],'audio_stream':idx,'audio':audio_ref,'model_lock':request['model_lock'],'environment_lock':request['environment_lock'],'model_revision':model['revision'],'network':'local_files_only; no media upload or implicit model download','clock':'source PTS trimmed; resampled to16k mono with source-window-relative zero'})
    try:
        engine=WhisperModel(str(root),device='cpu',compute_type='int8',cpu_threads=request['cpu_threads'],local_files_only=True)
        segments,info=engine.transcribe(audio,language=request['language'],task='transcribe',beam_size=request['beam_size'],word_timestamps=True,
             vad_filter=request['vad_filter'],condition_on_previous_text=request['condition_on_previous_text'],temperature=0.0)
        rows=[s._asdict() for s in segments]
        for row in rows:row['words']=[w._asdict() if hasattr(w,'_asdict') else w for w in row.get('words') or []]
    except (RuntimeError,ValueError) as exc:raise ValueError('ASR_BACKEND_FAILED: '+str(exc)) from exc
    info_value,nonfinite_info=json_safe_metadata(info)
    raw={'schema':'asr-observation/1','segments':rows,'info':info_value,'info_nonfinite_fields':nonfinite_info,
         'speaker_status':'NOT_DIARIZED','recognition_accuracy':'NOT_VERIFIED','acoustic_alignment':'MODEL_ONLY'}
    write_json(directory/'raw-observation.json',raw)
    # Inputs or dependency bytes changing during inference invalidate the observation.
    source(audio_ref)
    source(request['source']);verify_model(request['model_lock']);verify_environment(request['environment_lock'])
    transcript,issues=normalize_observation(raw,request['source'],request['language'],a,b,str(directory/'raw-observation.json')+'#sha256='+sha256(directory/'raw-observation.json'))
    if transcript:
        from speech_ops import validate_transcript
        validate_transcript(transcript,tools);write_json(directory/'transcript.json',transcript)
    result={'state':'REVIEW_REQUIRED' if issues else ('MODEL_TRANSCRIPT_READY' if transcript else 'NO_WORDS_DETECTED'),
            'transcript':{'path':str(directory/'transcript.json'),'sha256':sha256(directory/'transcript.json')} if transcript else None,
            'raw_observation':{'path':str(directory/'raw-observation.json'),'sha256':sha256(directory/'raw-observation.json')},
            'issues':issues,'word_count':len(transcript['words']) if transcript else 0,'source_window':[a,b],
            'coverage_limit':'Recognition may omit actual speech/fillers; unrecognized spans are not proven silence. No partial transcript exported when invalid words occur.',
            'recognition_accuracy':'NOT_VERIFIED','acoustic_alignment':'MODEL_ONLY','speaker_identity':'UNKNOWN','editorial_decisions':'NONE'}
    write_json(directory/'asr-result.json',result)
    return result
