"""Apply a caller-selected SDR RGB cube LUT. No look selection or color matching."""
from fractions import Fraction
import json,math

# Source pixel format -> (bit depth, RGB working format for lut3d, output pixel format).
PIXEL_FORMATS={**{f:(8,'gbrp','yuv420p') for f in ['yuv420p','yuv422p','yuv444p','yuvj420p','yuvj422p','yuvj444p']},
               **{f:(10,'gbrp10le','yuv420p10le') for f in ['yuv420p10le','yuv422p10le','yuv444p10le']}}

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
    keys=['operation','source','lut','input_color','interpolation']
    exact_keys(request,keys+['strength'],keys);asset=source(request['source'])
    # Parse and apply the same verified bytes; strength derives a new cube on the same grid.
    lut,cube,lut_rows,lut_payload=verified_cube(request['lut'])
    strength=request.get('strength')
    if strength is not None:
        from editing_runtime import number
        strength=number(strength,'strength',0);require(0<strength<=1,'LUT_STRENGTH_OUT_OF_RANGE')
    color=request['input_color'];exact_keys(color,['space','range','basis'],['space','range','basis'])
    require(color['space']=='bt709-sdr','COLOR_SPACE_UNSUPPORTED')
    require(color['range'] in ['limited','full'],'COLOR_RANGE_REQUIRED')
    require(color['basis'] in ['verified-metadata','caller-declared'],'COLOR_BASIS_REQUIRED')
    interpolation=request['interpolation'];require(interpolation in ['trilinear','tetrahedral'],'LUT_INTERPOLATION_UNSUPPORTED')
    media=tools.probe(asset['path'])
    video=next((s for s in media['streams'] if s['codec_type']=='video'),None);require(video is not None,'VIDEO_STREAM_REQUIRED')
    require(video.get('pix_fmt') in PIXEL_FORMATS,'COLOR_PIXEL_FORMAT_UNSUPPORTED');bits,working,out_fmt=PIXEL_FORMATS[video['pix_fmt']]
    require(video['width']%2==0 and video['height']%2==0,'EVEN_DIMENSION_REQUIRED')
    rotations=[video.get('tags',{}).get('rotate',0)]+[s.get('rotation',0) for s in video.get('side_data_list',[])]
    require(all(float(x)%360==0 for x in rotations),'ROTATED_COLOR_SOURCE_UNSUPPORTED')
    expected={'color_space':'bt709','color_transfer':'bt709','color_primaries':'bt709','color_range':'tv' if color['range']=='limited' else 'pc'}
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
    # Local fixed name prevents LUT paths from being interpreted as filter code.
    if strength is None:
        (directory/'selected.cube').write_bytes(lut_payload)
    else:
        from color_numerics import cube_text, identity_table, table_from_rows
        identity=identity_table(cube['size']);table=table_from_rows(lut_rows,cube['size'])
        (directory/'selected.cube').write_text(cube_text(identity+strength*(table-identity),'derived strength %.6f'%strength),encoding='utf-8')
    rng='tv' if color['range']=='limited' else 'pc'
    filters=f'scale=in_color_matrix=bt709:in_range={rng}:out_range=pc,format={working},lut3d=file=selected.cube:interp={interpolation},scale=out_color_matrix=bt709:in_range=pc:out_range=tv,format={out_fmt}'
    output=directory/'graded.mp4'
    tools.ff(['-i',asset['path'],'-vf',filters,'-map','0:v:0','-map','0:a?','-r',str(fps),'-fps_mode','cfr',
              '-c:v','libx264','-crf','18','-preset','medium','-c:a','copy','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-color_range','tv','-movflags','+faststart','graded.mp4'],cwd=directory)
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
    result={'schema':'color-lut-apply/1','source':asset,'lut':lut,'cube':cube,'input_color':color,'interpolation':interpolation,
            'video':{'path':str(output),'sha256':sha256(output),'pix_fmt':out_fmt},
            'bit_depth':{'source':bits,'lut_working_format':working,'output':bits,'basis':'source pixel format; no 8-bit intermediate for 10-bit sources'},'frames':len(times),'fps':str(fps),'video_duration':float(Fraction(len(times),1)/fps),
            'time_mapping':'output frame i is source frame i; no trim, reordering or speed change','output_color':{'requested':requested_output,'observed':observed_output,'unobserved_fields':[k for k,v in observed_output.items() if v in unknown]},
            'audio':'all source audio streams copied when present; coded payload hash and format checked; listening not performed','audio_checks':audio_checks,
            'source_interpretation':'declared bt709 SDR YUV range to nonlinear RGB LUT to limited-range bt709; no HDR/log normalization',
            'effect_review':'NOT_RUN','limits':['LUT order and creative suitability are caller decisions','unknown source color metadata may be caller-declared but is not verified','no automatic matching, white balance, skin protection or clipping repair','lossy H264 re-encode, not pixel-lossless']}
    if strength is not None:
        result['strength']={'value':strength,'derivation':'identity + strength * (lut - identity) on the source cube grid, rounded to 6 decimals',
                            'applied_cube':{'path':str(directory/'selected.cube'),'sha256':sha256(directory/'selected.cube')}}
    write_json(directory/'color-lut-map.json',result);return result
