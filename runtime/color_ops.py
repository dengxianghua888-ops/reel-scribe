"""Apply a caller-selected SDR RGB cube LUT. No look selection or color matching."""
from fractions import Fraction
import json,math,shutil

def validate_cube(path):
    from editing_runtime import require
    require(path.stat().st_size<=16*1024*1024,'LUT_TOO_LARGE')
    size=None;rows=[];seen=set();data_started=False
    for raw in path.read_text(encoding='utf-8-sig').splitlines():
        line=raw.split('#',1)[0].strip()
        if not line:continue
        parts=line.split();key=parts[0]
        if key in ['TITLE','LUT_3D_SIZE','DOMAIN_MIN','DOMAIN_MAX']:
            require(not data_started and key not in seen,'LUT_DUPLICATE_OR_LATE_HEADER');seen.add(key)
            if key=='TITLE':
                require(line.startswith('TITLE "') and line.endswith('"'),'LUT_TITLE_INVALID')
            elif key=='LUT_3D_SIZE':
                require(len(parts)==2,'LUT_SIZE_INVALID')
                size=int(parts[1]);require(2<=size<=65,'LUT_SIZE_UNSUPPORTED')
            else:
                require(len(parts)==4,'LUT_DOMAIN_INVALID');values=[float(x) for x in parts[1:]]
                require(values==([0.,0.,0.] if key=='DOMAIN_MIN' else [1.,1.,1.]),'LUT_DOMAIN_UNSUPPORTED')
        else:
            require(size is not None,'LUT_SIZE_REQUIRED_BEFORE_DATA');data_started=True
            require(len(parts)==3,'LUT_ROW_INVALID')
            values=[float(x) for x in parts]
            require(all(math.isfinite(x) and 0<=x<=1 for x in values),'LUT_VALUE_OUT_OF_RANGE')
            rows.append(values);require(len(rows)<=size**3,'LUT_TOO_MANY_ROWS')
    require(size is not None and len(rows)==size**3,'LUT_INCOMPLETE')
    return {'size':size,'rows':len(rows),'domain':[0,1],'ordering':'red fastest, then green, then blue; caller supplies intended mapping'}

def frame_clock(path,tools):
    from editing_runtime import exec_tool,require
    raw=exec_tool([tools.binary('ffprobe'),'-v','error','-select_streams','v:0','-show_frames',
                  '-show_entries','frame=best_effort_timestamp_time','-of','json',str(path)])
    times=[float(f['best_effort_timestamp_time']) for f in json.loads(raw.stdout)['frames']]
    require(len(times)>=2 and all(math.isfinite(t) for t in times),'VIDEO_CLOCK_UNAVAILABLE')
    return times

def apply_lut(request,directory,tools):
    from pathlib import Path
    from editing_runtime import exact_keys,source,require,write_json,sha256,exec_tool,frame_rate
    keys=['operation','source','lut','input_color','interpolation']
    exact_keys(request,keys,keys);asset=source(request['source']);lut=source(request['lut'])
    color=request['input_color'];exact_keys(color,['space','range','basis'],['space','range','basis'])
    require(color['space']=='bt709-sdr','COLOR_SPACE_UNSUPPORTED')
    require(color['range'] in ['limited','full'],'COLOR_RANGE_REQUIRED')
    require(color['basis'] in ['verified-metadata','caller-declared'],'COLOR_BASIS_REQUIRED')
    interpolation=request['interpolation'];require(interpolation in ['trilinear','tetrahedral'],'LUT_INTERPOLATION_UNSUPPORTED')
    cube=validate_cube(Path(lut['path']));media=tools.probe(asset['path'])
    video=next((s for s in media['streams'] if s['codec_type']=='video'),None);require(video is not None,'VIDEO_STREAM_REQUIRED')
    require(video.get('pix_fmt') in ['yuv420p','yuv422p','yuv444p','yuvj420p','yuvj422p','yuvj444p'],'COLOR_PIXEL_FORMAT_UNSUPPORTED')
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
    shutil.copyfile(lut['path'],directory/'selected.cube')
    rng='tv' if color['range']=='limited' else 'pc'
    filters=f'scale=in_color_matrix=bt709:in_range={rng}:out_range=pc,format=gbrp,lut3d=file=selected.cube:interp={interpolation},scale=out_color_matrix=bt709:in_range=pc:out_range=tv,format=yuv420p'
    output=directory/'graded.mp4'
    tools.ff(['-i',asset['path'],'-vf',filters,'-map','0:v:0','-map','0:a?','-r',str(fps),'-fps_mode','cfr',
              '-c:v','libx264','-crf','18','-preset','medium','-c:a','copy','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-color_range','tv','-movflags','+faststart','graded.mp4'],cwd=directory)
    after=tools.probe(output);av=next(s for s in after['streams'] if s['codec_type']=='video');out_times=frame_clock(output,tools)
    require(len(out_times)==len(times) and all(abs(a-b)<=.00001 for a,b in zip(times,out_times)),'COLOR_FRAME_CLOCK_CHANGED')
    require(av['width']==video['width'] and av['height']==video['height'],'COLOR_GEOMETRY_CHANGED')
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
            'video':{'path':str(output),'sha256':sha256(output)},'frames':len(times),'fps':str(fps),'video_duration':float(Fraction(len(times),1)/fps),
            'time_mapping':'output frame i is source frame i; no trim, reordering or speed change','output_color':{'requested':requested_output,'observed':observed_output,'unobserved_fields':[k for k,v in observed_output.items() if v in unknown]},
            'audio':'all source audio streams copied when present; coded payload hash and format checked; listening not performed','audio_checks':audio_checks,
            'source_interpretation':'declared bt709 SDR YUV range to nonlinear RGB LUT to limited-range bt709; no HDR/log normalization',
            'effect_review':'NOT_RUN','limits':['LUT order and creative suitability are caller decisions','unknown source color metadata may be caller-declared but is not verified','no automatic matching, white balance, skin protection or clipping repair','lossy H264 re-encode, not pixel-lossless']}
    write_json(directory/'color-lut-map.json',result);return result
