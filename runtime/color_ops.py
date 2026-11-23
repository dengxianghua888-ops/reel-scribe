"""Apply a caller-selected SDR RGB cube LUT. No look selection or color matching."""
from fractions import Fraction
import json,math

# Source pixel format -> (bit depth, RGB working format for lut3d, output pixel format).
PIXEL_FORMATS={**{f:(8,'gbrp','yuv420p') for f in ['yuv420p','yuv422p','yuv444p','yuvj420p','yuvj422p','yuvj444p']},
               **{f:(10,'gbrp10le','yuv420p10le') for f in ['yuv420p10le','yuv422p10le','yuv444p10le']}}
# Declared SDR space -> transfer tag the source must carry and the output keeps; LUTs act on code values.
SPACE_TRANSFER={'bt709-sdr':'bt709','srgb-sdr':'iec61966-2-1'}
SPACE_EOTF={'bt709-sdr':'bt1886','srgb-sdr':'srgb'}
MAX_LAYERS=32
MAX_RANGES_PER_LAYER=512
MAX_READBACK_FRAMES=96
READBACK_WIDTH=256
READBACK_MAX_MEDIAN_DE2000=3.0
READBACK_PIXEL_BUDGET=1<<17  # predicted pixels per readback frame (tetrahedral numpy: about 0.2 s)
MIN_READBACK_BLOCK=8  # noise averages over at least 8x8 pixels whatever the resolution


def _layers(value,frames):
    """Validate ordered LUT layers; each applies to explicit [start, end) output frame ranges."""
    from editing_runtime import exact_keys,require,number
    require(isinstance(value,list) and 1<=len(value)<=MAX_LAYERS,'COLOR_LAYERS_INVALID')
    layers=[]
    for index,layer in enumerate(value):
        exact_keys(layer,['lut','ranges','strength'],['lut','ranges'])
        ranges=layer['ranges']
        require(isinstance(ranges,list) and 1<=len(ranges)<=MAX_RANGES_PER_LAYER,'COLOR_LAYER_RANGES_INVALID: %d'%index)
        previous=0
        for item in ranges:
            require(isinstance(item,list) and len(item)==2 and all(type(x) is int for x in item),'COLOR_LAYER_RANGE_INVALID: %d'%index)
            a,b=item
            require(previous<=a<b<=frames,'COLOR_LAYER_RANGE_OUTSIDE_OR_UNSORTED: %d'%index)
            previous=b
        strength=layer.get('strength')
        if strength is not None:
            strength=number(strength,'strength',0);require(0<strength<=1,'LUT_STRENGTH_OUT_OF_RANGE')
        lut,cube,rows,payload=verified_cube(layer['lut'])
        layers.append({'lut':lut,'cube':cube,'rows':rows,'payload':payload,'ranges':[list(r) for r in ranges],'strength':strength})
    return layers


def _rgb_frames(path,indices,width,height,rng,tools):
    """Decode exact frame numbers to full-range rgb24, point-sampled at a fixed analysis size.

    Point sampling (no averaging) keeps each analysis pixel a real source pixel, so a
    nonlinear LUT can be predicted per pixel; averaging first does not commute with it.
    """
    import subprocess
    from editing_runtime import require
    picks='+'.join('eq(n,%d)'%i for i in indices)  # single quotes protect the commas
    vf=(f"select='{picks}',scale={width}:{height}:flags=neighbor:in_color_matrix=bt709:in_range={rng}:out_range=pc,format=rgb24")
    raw=subprocess.run([tools.binary('ffmpeg'),'-v','error','-i',str(path),'-vf',vf,'-fps_mode','passthrough',
                        '-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True,timeout=600).stdout
    size=width*height*3
    require(len(raw)==size*len(indices),'COLOR_READBACK_DECODE_INCOMPLETE')
    return [raw[k*size:(k+1)*size] for k in range(len(indices))]


def _block_grid(width,height):
    """Blocks of b x b pixels (b = width / READBACK_WIDTH rounded up, at least 8) on an even sub-grid within the pixel budget."""
    block=max(1,min(max(MIN_READBACK_BLOCK,-(-width//READBACK_WIDTH)),width,height))
    across,down=width//block,height//block
    stride=max(1,math.ceil(math.sqrt(across*down*block*block/READBACK_PIXEL_BUDGET)))
    return block,stride,list(range(stride//2,down,stride)),list(range(stride//2,across,stride))


def _rgb_stream(path,indices,width,height,rng,tools,label):
    """Decode exact frame numbers to full-resolution, full-range rgb24 arrays (height, width, 3), one at a time."""
    from color_numerics import numpy
    from texture_ops import stream_raw_frames
    np=numpy()
    picks='+'.join('eq(n,%d)'%i for i in indices)  # single quotes protect the commas
    vf=f"select='{picks}',scale=in_color_matrix=bt709:in_range={rng}:out_range=pc,format=rgb24"
    command=[tools.binary('ffmpeg'),'-nostdin','-v','error','-i',str(path),'-map','0:v:0','-vf',vf,
             '-fps_mode','passthrough','-f','rawvideo','-pix_fmt','rgb24']
    raws=stream_raw_frames(command,len(indices),width*height*3,label,('COLOR_READBACK_DECODE_FAILED','COLOR_READBACK_DECODE_INCOMPLETE'))
    try:
        for raw in raws:
            yield np.frombuffer(raw,dtype=np.uint8).reshape(height,width,3)
    finally:
        raws.close()


def _readback(source_path,output_path,layers,frames,video,color,method,tools):
    """Compare decoded output frames with the numpy prediction of the active layers on the source frame."""
    from editing_runtime import require
    from color_numerics import numpy,interpolate,lab_from_rgb01,ciede2000
    np=numpy()
    picks=[(a+b-1)//2 for layer in layers for a,b in layer['ranges']]
    gap,cursor=None,0  # first frame outside every range, if any
    for a,b in sorted((a,b) for layer in layers for a,b in layer['ranges']):
        if a>cursor:
            gap=cursor;break
        cursor=max(cursor,b)
    if gap is None and cursor<frames:
        gap=cursor
    gaps=[gap] if gap is not None else []
    wanted=sorted(set(picks))
    if len(wanted)>MAX_READBACK_FRAMES-len(gaps):
        step=len(wanted)/(MAX_READBACK_FRAMES-len(gaps))
        wanted=sorted({wanted[int(k*step)] for k in range(MAX_READBACK_FRAMES-len(gaps))}|{wanted[0],wanted[-1]})
    indices=sorted(set(wanted)|set(gaps))
    width,height=int(video['width']),int(video['height'])
    block,stride,down,across=_block_grid(width,height)
    rng='tv' if color['range']=='limited' else 'pc'
    transfer=SPACE_EOTF[color['space']]

    def tiles(frame):  # (blocks, block*block pixels, 3) code values in [0,1]
        grid=frame[:(height//block)*block,:(width//block)*block].reshape(height//block,block,width//block,block,3)
        return grid[down][:,:,across].transpose(0,2,1,3,4).reshape(-1,block*block,3)/255.0

    # Each pixel is predicted (a nonlinear LUT does not commute with averaging); prediction and output are
    # then compared as block means, so sensor noise that the output encode smooths is not counted.
    sources=_rgb_stream(source_path,indices,width,height,rng,tools,'readback source decode')
    outputs=_rgb_stream(output_path,indices,width,height,'tv',tools,'readback output decode')
    rows=[]
    try:
        for f in indices:
            x,y=tiles(next(sources)),tiles(next(outputs)).mean(axis=1)
            predicted=x.reshape(-1,3)
            active=[li for li,layer in enumerate(layers) if any(a<=f<b for a,b in layer['ranges'])]
            for li in active:  # the stored table already includes the layer strength
                predicted=np.clip(interpolate(layers[li]['table'],predicted,method),0,1)
            predicted=predicted.reshape(x.shape).mean(axis=1)
            de=ciede2000(lab_from_rgb01(predicted,transfer)[0],lab_from_rgb01(y,transfer)[0])
            median=float(np.median(de))
            rows.append({'frame':f,'active_layers':active,'delta_e2000_median':round(median,3),
                         'delta_e2000_p95':round(float(np.percentile(de,95)),3)})
            require(median<=READBACK_MAX_MEDIAN_DE2000,'COLOR_LAYER_READBACK_MISMATCH: frame %d'%f)
        for stream in (sources,outputs):  # runs each decode's completion and exit-status checks
            require(next(stream,None) is None,'COLOR_READBACK_DECODE_INCOMPLETE: extra frames')
    finally:
        sources.close();outputs.close()
    return {'method':'numpy %s prediction of the active layers on every pixel of the sampled source blocks vs the decoded '
                     'output, compared as %dx%d block means'%(method,block,block),
            'block':block,'block_stride':stride,'blocks_per_frame':len(down)*len(across),
            'max_median_delta_e2000':READBACK_MAX_MEDIAN_DE2000,'frames':rows,
            'sampling':'full-resolution decode; every %d-th block in each direction, at most %d predicted pixels per frame'
                       %(stride,READBACK_PIXEL_BUDGET),
            'coverage':'middle frame of each range (capped at %d) plus one frame outside every range'%MAX_READBACK_FRAMES}

def validate_cube(path):
    from editing_runtime import require
    from color_numerics import parse_cube_text, MAX_CUBE_BYTES
    require(path.stat().st_size<=MAX_CUBE_BYTES,'LUT_TOO_LARGE')
    return parse_cube_text(path.read_text(encoding='utf-8-sig'))[0]


def verified_cube(ref):
    """Hash and parse one bounded buffer; return (artifact, info, rows, payload)."""
    import hashlib
    from editing_runtime import require, source
    from color_numerics import parse_cube_text, MAX_CUBE_BYTES
    artifact=source(ref)
    with open(artifact['path'],'rb') as stream:payload=stream.read(MAX_CUBE_BYTES+1)
    require(len(payload)<=MAX_CUBE_BYTES,'LUT_TOO_LARGE')
    require(hashlib.sha256(payload).hexdigest()==artifact['sha256'],'SOURCE_HASH_MISMATCH: '+artifact['path'])
    try:text=payload.decode('utf-8-sig')
    except UnicodeDecodeError as exc:raise ValueError('LUT_TEXT_INVALID') from exc
    info,rows=parse_cube_text(text)
    return artifact,info,rows,payload

def frame_clock(path,tools):
    from editing_runtime import exec_tool,require
    raw=exec_tool([tools.binary('ffprobe'),'-v','error','-select_streams','v:0','-show_frames',
                  '-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)])
    times=[float(f['best_effort_timestamp_time']) for f in json.loads(raw.stdout)['frames']]
    require(len(times)>=2 and all(math.isfinite(t) for t in times),'VIDEO_CLOCK_UNAVAILABLE')
    return times

def apply_lut(request,directory,tools):
    from editing_runtime import exact_keys,source,require,write_json,sha256,exec_tool,frame_rate
    keys=['operation','source','input_color','interpolation']
    exact_keys(request,keys+['lut','strength','layers'],keys);asset=source(request['source'])
    layered='layers' in request
    require(layered!=('lut' in request),'COLOR_LUT_OR_LAYERS_REQUIRED')
    require(not (layered and 'strength' in request),'COLOR_LAYER_STRENGTH_BELONGS_TO_LAYER')
    # Parse and apply the same verified bytes; strength derives a new cube on the same grid.
    if not layered:
        lut,cube,lut_rows,lut_payload=verified_cube(request['lut'])
    strength=request.get('strength')
    if strength is not None:
        from editing_runtime import number
        strength=number(strength,'strength',0);require(0<strength<=1,'LUT_STRENGTH_OUT_OF_RANGE')
    color=request['input_color'];exact_keys(color,['space','range','basis'],['space','range','basis'])
    require(color['space'] in SPACE_TRANSFER,'COLOR_SPACE_UNSUPPORTED');trc=SPACE_TRANSFER[color['space']]
    require(color['range'] in ['limited','full'],'COLOR_RANGE_REQUIRED')
    require(color['basis'] in ['verified-metadata','caller-declared'],'COLOR_BASIS_REQUIRED')
    interpolation=request['interpolation'];require(interpolation in ['trilinear','tetrahedral'],'LUT_INTERPOLATION_UNSUPPORTED')
    media=tools.probe(asset['path'])
    video=next((s for s in media['streams'] if s['codec_type']=='video'),None);require(video is not None,'VIDEO_STREAM_REQUIRED')
    require(video.get('pix_fmt') in PIXEL_FORMATS,'COLOR_PIXEL_FORMAT_UNSUPPORTED');bits,working,out_fmt=PIXEL_FORMATS[video['pix_fmt']]
    if layered:working='gbrpf32le'  # stacked layers stay in float between LUTs
    require(video['width']%2==0 and video['height']%2==0,'EVEN_DIMENSION_REQUIRED')
    rotations=[video.get('tags',{}).get('rotate',0)]+[s.get('rotation',0) for s in video.get('side_data_list',[])]
    require(all(float(x)%360==0 for x in rotations),'ROTATED_COLOR_SOURCE_UNSUPPORTED')
    expected={'color_space':'bt709','color_transfer':trc,'color_primaries':'bt709','color_range':'tv' if color['range']=='limited' else 'pc'}
    unknown={'unknown','unspecified',None}
    for key,value in expected.items():
        observed=video.get(key)
        require(observed in unknown or observed==value,'COLOR_METADATA_CONFLICT: '+key)
        if color['basis']=='verified-metadata':require(observed==value,'COLOR_METADATA_REQUIRED: '+key)
    if video['pix_fmt'].startswith('yuvj'):require(color['range']=='full','COLOR_METADATA_CONFLICT: full-range pixel format')
    fps=frame_rate(video.get('avg_frame_rate'));require(0<fps<=120,'COLOR_FRAME_RATE_UNSUPPORTED')
    require(frame_rate(video.get('r_frame_rate'))==fps,'COLOR_CFR_REQUIRED')
    times=frame_clock(asset['path'],tools)
    require(all(abs(t-float(Fraction(i,1)/fps))<=.00001 for i,t in enumerate(times)),'COLOR_ZERO_ORIGIN_CFR_REQUIRED')
    # Local fixed names prevent LUT paths from being interpreted as filter code.
    if layered:
        from color_numerics import cube_text, identity_table, table_from_rows
        layers=_layers(request['layers'],len(times));stages=[]
        for index,layer in enumerate(layers):
            name='layer-%02d.cube'%index
            table=table_from_rows(layer['rows'],layer['cube']['size'])
            if layer['strength'] is None:
                (directory/name).write_bytes(layer['payload'])
            else:
                identity=identity_table(layer['cube']['size'])
                table=identity+layer['strength']*(table-identity)
                (directory/name).write_text(cube_text(table,'derived strength %.6f'%layer['strength']),encoding='utf-8')
            layer['table']=table;layer['file']=name
            enable='+'.join('between(n,%d,%d)'%(a,b-1) for a,b in layer['ranges'])
            stages.append(f"lut3d=file={name}:interp={interpolation}:enable='{enable}'")
        lut_stage=','.join(stages)
    else:
        if strength is None:
            (directory/'selected.cube').write_bytes(lut_payload)
        else:
            from color_numerics import cube_text, identity_table, table_from_rows
            identity=identity_table(cube['size']);table=table_from_rows(lut_rows,cube['size'])
            (directory/'selected.cube').write_text(cube_text(identity+strength*(table-identity),'derived strength %.6f'%strength),encoding='utf-8')
        lut_stage=f'lut3d=file=selected.cube:interp={interpolation}'
    rng='tv' if color['range']=='limited' else 'pc'
    filters=f'scale=in_color_matrix=bt709:in_range={rng}:out_range=pc,format={working},{lut_stage},scale=out_color_matrix=bt709:in_range=pc:out_range=tv,format={out_fmt},setparams=colorspace=bt709:color_primaries=bt709:color_trc={trc}:range=tv'
    output=directory/'graded.mp4'
    tools.ff(['-i',asset['path'],'-vf',filters,'-map','0:v:0','-map','0:a?','-r',str(fps),'-fps_mode','cfr',
              '-c:v','libx264','-crf','18','-preset','medium','-c:a','copy','-colorspace','bt709','-color_trc',trc,'-color_primaries','bt709','-color_range','tv','-movflags','+faststart','graded.mp4'],cwd=directory)
    after=tools.probe(output);av=next(s for s in after['streams'] if s['codec_type']=='video');out_times=frame_clock(output,tools)
    require(len(out_times)==len(times) and all(abs(a-b)<=.00001 for a,b in zip(times,out_times)),'COLOR_FRAME_CLOCK_CHANGED')
    require(av['width']==video['width'] and av['height']==video['height'],'COLOR_GEOMETRY_CHANGED')
    require(av.get('pix_fmt')==out_fmt,'COLOR_OUTPUT_PIXEL_FORMAT_CHANGED')
    requested_output=expected|{'color_range':'tv'}
    observed_output={key:av.get(key) for key in requested_output}
    for key,value in requested_output.items():
        require(observed_output[key] in unknown or observed_output[key]==value,'COLOR_OUTPUT_METADATA_CONFLICT: '+key)
    audio_before=[s for s in media['streams'] if s['codec_type']=='audio']
    audio_after=[s for s in after['streams'] if s['codec_type']=='audio']
    require(len(audio_before)==len(audio_after),'COLOR_AUDIO_STREAM_COUNT_CHANGED')
    audio_checks=[]
    for i,(a,b) in enumerate(zip(audio_before,audio_after)):
        require(all(a.get(k)==b.get(k) for k in ['codec_name','sample_rate','channels']),'COLOR_AUDIO_FORMAT_CHANGED')
        def coded_hash(path):
            return exec_tool([tools.binary('ffmpeg'),'-v','error','-i',str(path),'-map',f'0:a:{i}',
                              '-c:a','copy','-f','hash','-hash','sha256','-']).stdout.strip()
        before_hash=coded_hash(asset['path']);after_hash=coded_hash(output)
        require(before_hash==after_hash,'COLOR_CODED_AUDIO_CHANGED')
        audio_checks.append({'index':i,'coded_sha256':before_hash,'format_preserved':True})
    # Requested output tags and actual ffprobe observations are different evidence.
    # Missing transfer/primaries fields stay unknown, even after explicitly setting tags.
    readback=_readback(asset['path'],output,layers,len(times),video,color,request['interpolation'],tools) if layered else None
    result={'schema':'color-lut-apply/1','source':asset,'input_color':color,'interpolation':interpolation,
            **({'lut':lut,'cube':cube} if not layered else {}),
            'video':{'path':str(output),'sha256':sha256(output),'pix_fmt':out_fmt},
            'bit_depth':{'source':bits,'lut_working_format':working,'output':bits,'basis':'source pixel format; no 8-bit intermediate for 10-bit sources'},'frames':len(times),'fps':str(fps),'video_duration':float(Fraction(len(times),1)/fps),
            'time_mapping':'output frame i is source frame i; no trim, reordering or speed change','output_color':{'requested':requested_output,'observed':observed_output,'unobserved_fields':[k for k,v in observed_output.items() if v in unknown]},
            'audio':'all source audio streams copied when present; coded payload hash and format checked; listening not performed','audio_checks':audio_checks,
            'source_interpretation':f'declared {color["space"]} YUV range to nonlinear RGB code values, LUT, limited-range BT.709-matrix YUV tagged {trc}; the LUT is applied to code values and must have been built for this transfer; no HDR/log normalization',
            'effect_review':'NOT_RUN','limits':['LUT order and creative suitability are caller decisions','unknown source color metadata may be caller-declared but is not verified','no automatic matching, white balance, skin protection or clipping repair','lossy H264 re-encode, not pixel-lossless']}
    if layered:
        result['bit_depth']['lut_working_format']=working
        result['bit_depth']['basis']='source pixel format; layers are applied in 32-bit float RGB'
        result['layers']=[{'index':i,'lut':l['lut'],'cube':l['cube'],'strength':l['strength'],'ranges':l['ranges'],
                           'frames':sum(b-a for a,b in l['ranges']),
                           'applied_cube':{'path':str(directory/l['file']),'sha256':sha256(directory/l['file'])}}
                          for i,l in enumerate(layers)]
        result['layer_order']='layers apply in listed order; frames outside every range keep source values (re-encoded)'
        result['readback']=readback
    if strength is not None:
        result['strength']={'value':strength,'derivation':'identity + strength * (lut - identity) on the source cube grid, rounded to 6 decimals',
                            'applied_cube':{'path':str(directory/'selected.cube'),'sha256':sha256(directory/'selected.cube')}}
    write_json(directory/'color-lut-map.json',result);return result
