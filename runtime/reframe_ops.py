"""Explicit static crop, scale and canvas placement. No automatic subject selection."""
from fractions import Fraction
import json


def reframe(q,directory,tools):
    from editing_runtime import exact_keys,require,source,sha256,exec_tool,write_json,frame_rate
    from color_ops import frame_clock
    keys=['operation','source','crop','canvas','placement','background_rgb','allow_upscale','input_color']
    exact_keys(q,keys,keys);asset=source(q['source']);media=tools.probe(asset['path'])
    videos=[s for s in media['streams'] if s['codec_type']=='video'];require(len(videos)==1,'REFRAME_SINGLE_VIDEO_REQUIRED');video=videos[0]
    require(q['input_color']=='bt709-sdr-limited','REFRAME_COLOR_DECLARATION_REQUIRED')
    require(video.get('pix_fmt')=='yuv420p','REFRAME_PIXEL_FORMAT_UNSUPPORTED')
    for key,expected in {'color_space':'bt709','color_transfer':'bt709','color_primaries':'bt709','color_range':'tv'}.items():
        require(video.get(key) in [None,'unknown','unspecified',expected],'REFRAME_COLOR_CONFLICT: '+key)
    rotations=[video.get('tags',{}).get('rotate',0)]+[s.get('rotation',0) for s in video.get('side_data_list',[])]
    require(all(float(x)%360==0 for x in rotations),'REFRAME_ROTATION_UNSUPPORTED')
    require(video.get('sample_aspect_ratio') in [None,'1:1','0:1'],'REFRAME_SQUARE_PIXELS_REQUIRED')
    def rectangle(value,name):
        require(isinstance(value,list) and len(value)==4 and all(type(x) is int and x%2==0 for x in value),'REFRAME_EVEN_RECT_REQUIRED: '+name)
        x,y,w,h=value;require(x>=0 and y>=0 and w>=2 and h>=2,'REFRAME_RECT_INVALID: '+name);return x,y,w,h
    x,y,cw,ch=rectangle(q['crop'],'crop');px,py,pw,ph=rectangle(q['placement'],'placement')
    canvas=q['canvas'];require(isinstance(canvas,list) and len(canvas)==2 and all(type(x) is int and 2<=x<=8192 and x%2==0 for x in canvas),'REFRAME_CANVAS_INVALID');width,height=canvas
    require(x+cw<=video['width'] and y+ch<=video['height'],'REFRAME_CROP_OUTSIDE_SOURCE')
    require(px+pw<=width and py+ph<=height,'REFRAME_PLACEMENT_OUTSIDE_CANVAS')
    require(cw*ph==ch*pw,'REFRAME_ASPECT_DISTORTION')
    require(type(q['allow_upscale']) is bool,'REFRAME_UPSCALE_BOOLEAN_REQUIRED')
    require(q['allow_upscale'] or (pw<=cw and ph<=ch),'REFRAME_UPSCALE_NOT_ALLOWED')
    bg=q['background_rgb'];require(isinstance(bg,list) and len(bg)==3 and all(type(x) is int and 0<=x<=255 for x in bg),'REFRAME_BACKGROUND_REQUIRED')
    fps=frame_rate(video.get('avg_frame_rate'));require(0<fps<=120 and frame_rate(video.get('r_frame_rate'))==fps,'REFRAME_CFR_REQUIRED')
    times=frame_clock(asset['path'],tools);require(all(abs(t-float(Fraction(i,1)/fps))<.00001 for i,t in enumerate(times)),'REFRAME_ZERO_ORIGIN_REQUIRED')
    color='0x'+''.join(f'{c:02x}' for c in bg)
    filt=f'crop=w={cw}:h={ch}:x={x}:y={y}:exact=1,scale={pw}:{ph}:flags=lanczos,pad={width}:{height}:{px}:{py}:color={color},setsar=1'
    output=directory/'reframed.mp4'
    tools.ff(['-i',asset['path'],'-vf',filt,'-map','0:v:0','-map','0:a?','-r',str(fps),'-fps_mode','cfr','-c:v','libx264','-crf','18','-c:a','copy','-colorspace','bt709','-color_trc','bt709','-color_primaries','bt709','-color_range','tv','-movflags','+faststart',str(output)])
    after=tools.probe(output);v=next(s for s in after['streams'] if s['codec_type']=='video');clock=frame_clock(output,tools)
    require(v['width']==width and v['height']==height and frame_rate(v.get('avg_frame_rate'))==fps,'REFRAME_OUTPUT_GEOMETRY_CHANGED')
    require(len(clock)==len(times) and all(abs(a-b)<.00001 for a,b in zip(times,clock)),'REFRAME_FRAME_CLOCK_CHANGED')
    before_audio=[s for s in media['streams'] if s['codec_type']=='audio'];after_audio=[s for s in after['streams'] if s['codec_type']=='audio'];require(len(before_audio)==len(after_audio),'REFRAME_AUDIO_COUNT_CHANGED');checks=[]
    for i,(a,b) in enumerate(zip(before_audio,after_audio)):
        require(all(a.get(k)==b.get(k) for k in ['codec_name','sample_rate','channels']),'REFRAME_AUDIO_FORMAT_CHANGED')
        def coded(path):return exec_tool([tools.binary('ffmpeg'),'-v','error','-i',str(path),'-map',f'0:a:{i}','-c:a','copy','-f','hash','-hash','sha256','-']).stdout.strip()
        before=coded(asset['path']);require(before==coded(output),'REFRAME_AUDIO_PAYLOAD_CHANGED');checks.append({'index':i,'coded_hash':before})
    source(q['source'])
    result={'schema':'video-reframe/1','source':asset,'video':{'path':str(output),'sha256':sha256(output)},'crop':q['crop'],'canvas':canvas,'placement':q['placement'],'background_rgb':bg,'allow_upscale':q['allow_upscale'],'fps':str(fps),'frames':len(clock),'duration':float(Fraction(len(clock),1)/fps),'audio_checks':checks,'time_mapping':'source frame i to output frame i; no trimming or retiming','color_basis':'caller-declared BT709 SDR limited; unknown input tags not independently verified','subject_or_text_retention':'NOT_ASSESSED','limits':['static explicit rectangle only; no tracking, active-speaker or aesthetic choice','8bit square-pixel zero-origin CFR SDR only; normalize explicitly upstream if appropriate','cropped information lost, upscaling does not create detail','coded audio retained where mux supports it; listening unverified','H264 video re-encode, not lossless']}
    write_json(directory/'reframe-map.json',result);return result
