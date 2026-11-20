"""Explicit frame-aligned video layers; no asset choice, timing inference or tracking."""
from fractions import Fraction


def video_info(ref, tools):
    from editing_runtime import source, require, frame_rate
    from color_ops import frame_clock
    asset=source(ref);media=tools.probe(asset['path'])
    videos=[s for s in media['streams'] if s['codec_type']=='video']
    require(len(videos)==1,'OVERLAY_SINGLE_VIDEO_REQUIRED')
    v=videos[0]
    require(v.get('pix_fmt')=='yuv420p','OVERLAY_8BIT_420_REQUIRED')
    require(v.get('sample_aspect_ratio') in [None,'1:1','0:1'],'OVERLAY_SQUARE_PIXELS_REQUIRED')
    rotations=[v.get('tags',{}).get('rotate',0)]+[s.get('rotation',0) for s in v.get('side_data_list',[])]
    require(all(float(x)%360==0 for x in rotations),'OVERLAY_ROTATION_UNSUPPORTED')
    for key,expected in {'color_space':'bt709','color_transfer':'bt709','color_primaries':'bt709','color_range':'tv'}.items():
        require(v.get(key) in [None,'unknown','unspecified',expected],'OVERLAY_COLOR_CONFLICT: '+key)
    fps=frame_rate(v.get('avg_frame_rate'))
    require(0<fps<=120 and frame_rate(v.get('r_frame_rate'))==fps,'OVERLAY_CFR_REQUIRED')
    times=frame_clock(asset['path'],tools)
    require(all(abs(t-float(Fraction(i,1)/fps))<.00001 for i,t in enumerate(times)),'OVERLAY_ZERO_ORIGIN_REQUIRED')
    return {'asset':asset,'media':media,'video':v,'fps':fps,'frames':len(times),'clock':times}


def normalize_layers(layers, canvas, fps, frames, tools):
    from editing_runtime import exact_keys,require,number
    require(isinstance(layers,list),'OVERLAY_LIST_REQUIRED')
    ids=set();zs=set();result=[];cache={}
    fields=['id','source','source_start_frame','start_frame','duration_frames','rect','opacity','z','allow_upscale','input_color']
    for layer in layers:
        exact_keys(layer,fields,fields)
        lid=layer['id'];require(isinstance(lid,str) and lid and lid not in ids,'OVERLAY_ID_DUPLICATE_OR_EMPTY');ids.add(lid)
        for k in ['source_start_frame','start_frame','duration_frames','z']:
            require(type(layer[k]) is int,'OVERLAY_INTEGER_REQUIRED: '+k)
        a=layer['start_frame'];n=layer['duration_frames'];sa=layer['source_start_frame']
        require(a>=0 and n>0 and a+n<=frames,'OVERLAY_OUTSIDE_BASE')
        require(sa>=0,'OVERLAY_SOURCE_FRAME_NEGATIVE')
        require(layer['z'] not in zs,'OVERLAY_Z_AMBIGUOUS');zs.add(layer['z'])
        require(layer['input_color']=='bt709-sdr-limited','OVERLAY_COLOR_DECLARATION_REQUIRED')
        require(type(layer['allow_upscale']) is bool,'OVERLAY_UPSCALE_BOOLEAN_REQUIRED')
        opacity=number(layer['opacity'],'opacity',0);require(opacity<=1,'OVERLAY_OPACITY_INVALID')
        rect=layer['rect']
        require(isinstance(rect,list) and len(rect)==4 and all(type(x) is int and x%2==0 for x in rect),'OVERLAY_EVEN_RECT_REQUIRED')
        x,y,w,h=rect;require(x>=0 and y>=0 and w>=2 and h>=2 and x+w<=canvas[0] and y+h<=canvas[1],'OVERLAY_RECT_OUTSIDE_CANVAS')
        # Cache only within this validation; render rechecks source identity afterwards.
        from editing_runtime import fingerprint
        key=fingerprint(layer['source'])
        info=cache.setdefault(key,video_info(layer['source'],tools)) if key not in cache else cache[key]
        require(info['fps']==fps,'OVERLAY_FPS_MISMATCH_NORMALIZE_EXPLICITLY')
        require(sa+n<=info['frames'],'OVERLAY_SOURCE_TOO_SHORT_NO_FREEZE')
        iw,ih=info['video']['width'],info['video']['height']
        require(iw*h==ih*w,'OVERLAY_ASPECT_DISTORTION')
        require(layer['allow_upscale'] or (w<=iw and h<=ih),'OVERLAY_UPSCALE_NOT_ALLOWED')
        result.append({**layer,'source_frames':info['frames'],'source_size':[iw,ih],
                       'end_frame':a+n,'source_end_frame':sa+n,'opacity':opacity})
    return sorted(result,key=lambda x:x['z'])


def work_layers(doc, norm, tools):
    from editing_runtime import exact_keys,require
    layers=doc.get('visual_layers',{});require(isinstance(layers,dict),'ID_MAP_REQUIRED: visual_layers')
    clips={c['id']:c for c in norm['clips']};out=[]
    fields=['source','source_start_frame','anchor_clip_id','offset_frames','duration_frames','rect','opacity','z','allow_upscale','input_color']
    for lid,layer in layers.items():
        require(isinstance(lid,str) and lid,'RESOURCE_ID_REQUIRED')
        exact_keys(layer,fields,fields)
        anchor=layer['anchor_clip_id'];require(anchor is None or anchor in clips,'OVERLAY_ANCHOR_MISSING: '+lid)
        require(type(layer['offset_frames']) is int,'OVERLAY_INTEGER_REQUIRED: offset_frames')
        start=(clips[anchor]['output_start_frame'] if anchor is not None else 0)+layer['offset_frames']
        out.append({'id':lid,'start_frame':start,**{k:v for k,v in layer.items() if k not in ['anchor_clip_id','offset_frames']}})
    return normalize_layers(out,[norm['width'],norm['height']],Fraction(norm['fps']),norm['total_frames'],tools)


def composite(q,directory,tools):
    from editing_runtime import exact_keys,require,source,sha256,exec_tool,write_json
    keys=['operation','source','input_color','layers'];exact_keys(q,keys,keys)
    require(q['input_color']=='bt709-sdr-limited','OVERLAY_COLOR_DECLARATION_REQUIRED')
    base=video_info(q['source'],tools);v=base['video'];fps=base['fps'];n=base['frames']
    require(q['layers'],'OVERLAY_LAYERS_REQUIRED')
    layers=normalize_layers(q['layers'],[v['width'],v['height']],fps,n,tools)
    args=['-i',base['asset']['path']];filters=[];last='0:v:0'
    for i,layer in enumerate(layers,1):
        args+=['-i',layer['source']['path']]
        x,y,w,h=layer['rect'];a=layer['start_frame'];b=layer['end_frame']
        filters.append(f'[{i}:v:0]trim=start_frame={layer["source_start_frame"]}:end_frame={layer["source_end_frame"]},'
            f'setpts=PTS-STARTPTS+{a}/({fps}*TB),scale={w}:{h}:flags=lanczos:in_color_matrix=bt709:in_range=tv:'
            f'out_color_matrix=bt709:out_range=tv,setsar=1,format=yuva420p,'
            # Opacity scales the alpha plane in place: an RGB colorchannelmixer round trip mixed BT.601/709 matrices.
            f'lut=a=val*{layer["opacity"]}[layer{i}]')
        # Use timestamps only to synchronize secondary input. Main frame index sets exact half-open visibility.
        filters.append(f'[{last}][layer{i}]overlay=x={x}:y={y}:eof_action=pass:repeatlast=0:shortest=0:'
            f'enable=\'gte(n,{a})*lt(n,{b})\':format=yuv420[out{i}]')
        last=f'out{i}'
    output=directory/'composited.mp4'
    tools.ff(args+['-filter_complex',';'.join(filters),'-map',f'[{last}]','-map','0:a?',
        '-c:v','libx264','-crf','18','-preset','medium','-r',str(fps),'-fps_mode','cfr',
        '-c:a','copy','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-color_range','tv',
        '-movflags','+faststart',str(output)])
    after=video_info({'path':str(output),'sha256':sha256(output)},tools)
    require(after['frames']==n and after['fps']==fps and
            all(abs(a-b)<.00001 for a,b in zip(base['clock'],after['clock'])),'OVERLAY_FRAME_CLOCK_CHANGED')
    require((after['video']['width'],after['video']['height'])==(v['width'],v['height']),'OVERLAY_BASE_GEOMETRY_CHANGED')
    before_audio=[s for s in base['media']['streams'] if s['codec_type']=='audio'];after_audio=[s for s in after['media']['streams'] if s['codec_type']=='audio']
    require(len(before_audio)==len(after_audio),'OVERLAY_AUDIO_COUNT_CHANGED');checks=[]
    for i,(a,b) in enumerate(zip(before_audio,after_audio)):
        require(all(a.get(k)==b.get(k) for k in ['codec_name','sample_rate','channels']),'OVERLAY_AUDIO_FORMAT_CHANGED')
        def coded(path):return exec_tool([tools.binary('ffmpeg'),'-v','error','-i',path,'-map',f'0:a:{i}','-c:a','copy','-f','hash','-hash','sha256','-']).stdout.strip()
        before=coded(base['asset']['path']);require(before==coded(str(output)),'OVERLAY_AUDIO_PAYLOAD_CHANGED');checks.append({'index':i,'coded_hash':before})
    source(q['source'])
    for layer in layers:source(layer['source'])
    result={'schema':'visual-layer-map/1','source':q['source'],'video':{'path':str(output),'sha256':sha256(output)},
        'frames':n,'fps':str(fps),'duration':float(Fraction(n,1)/fps),'canvas':[v['width'],v['height']],
        'layers':layers,'audio_checks':checks,'overlay_audio':'not mixed; base coded audio retained',
        'color_basis':'caller-declared BT709 SDR limited; unknown tags not independently measured',
        'visual_review':'NOT_RUN','limits':['Explicit static rectangles and constant opacity only; no tracking, asset choice or cut repair.',
            'Same rational FPS and zero-origin CFR required; no hidden looping, freeze, retiming or cropping.',
            'Layer source index=source_start_frame+(output_frame-start_frame), active in[start_frame,end_frame).',
            'H264 re-encode; outside-layer pixels are not promised bit-identical.','Does not certify meaning, visibility of protected subjects, readability or native-editor integration.']}
    write_json(directory/'overlay-map.json',result);return result
