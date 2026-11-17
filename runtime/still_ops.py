"""Render an explicitly specified crop path over a still image; no shot design or generation."""
from fractions import Fraction
import hashlib,io,json,subprocess
import os
import signal
import threading
import time

ENCODER_TIMEOUT_SEC = 120
MAX_FRAMES = 36000
MAX_RENDER_PIXELS = 30_000_000_000
MAX_STILL_BYTES = 512 * 1024 * 1024

def render_still(request,directory,tools):
    from editing_runtime import exact_keys,source,require,number,sha256,write_json,ContractError,exec_tool,RUN_CANCELLATION,OperationCancelled,frame_rate
    try:
        from PIL import Image, __version__ as pillow_version
    except ImportError as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE: Pillow') from exc
    keys=['operation','source','frames','fps','width','height','crop_keyframes','interpolation','background_rgb','allow_upscale','input_color']
    exact_keys(request,keys,keys);asset=source(request['source'])
    require(request['input_color'] in ['srgb','bt709'],'STILL_COLOR_UNSUPPORTED')
    n=request['frames'];require(type(n) is int and 2<=n<=MAX_FRAMES,'STILL_FRAME_COUNT_INVALID')
    try:fps=Fraction(str(request['fps']))
    except (ValueError,ZeroDivisionError) as exc:raise ContractError('STILL_FPS_INVALID') from exc
    require(0<fps<=120,'STILL_FPS_INVALID')
    w=request['width'];h=request['height'];require(all(type(v) is int and 2<=v<=8192 and v%2==0 for v in [w,h]),'STILL_GEOMETRY_INVALID')
    require(n*w*h<=MAX_RENDER_PIXELS,'STILL_PIXEL_BUDGET_EXCEEDED')
    require(type(request['allow_upscale']) is bool,'STILL_UPSCALE_FLAG_REQUIRED')
    require(request['interpolation'] in ['linear','smoothstep'],'STILL_INTERPOLATION_UNSUPPORTED')
    bg=request['background_rgb'];require(isinstance(bg,list) and len(bg)==3 and all(type(v) is int and 0<=v<=255 for v in bg),'STILL_BACKGROUND_INVALID')
    # Decode the same bounded buffer that was hashed, not a second path read.
    with open(asset['path'],'rb') as stream:payload=stream.read(MAX_STILL_BYTES+1)
    require(len(payload)<=MAX_STILL_BYTES,'STILL_FILE_TOO_LARGE')
    require(hashlib.sha256(payload).hexdigest()==asset['sha256'],'SOURCE_HASH_MISMATCH: '+asset['path'])
    with Image.open(io.BytesIO(payload)) as opened:
        require(opened.format in ['PNG','JPEG','WEBP'],'STILL_FORMAT_UNSUPPORTED')
        require(getattr(opened,'n_frames',1)==1,'ANIMATED_IMAGE_UNSUPPORTED')
        require(opened.mode in ['RGB','RGBA','L','LA'],'STILL_PIXEL_MODE_UNSUPPORTED')
        require(opened.getexif().get(274,1)==1,'STILL_ORIENTATION_REQUIRES_NORMALIZATION')
        require(not opened.info.get('icc_profile'),'STILL_ICC_REQUIRES_NORMALIZATION')
        rgba=opened.convert('RGBA');base=Image.new('RGBA',rgba.size,tuple(bg)+ (255,));base.alpha_composite(rgba);im=base.convert('RGB')
    iw,ih=im.size;keyframes=request['crop_keyframes']
    require(isinstance(keyframes,list) and len(keyframes)>=2,'STILL_KEYFRAMES_REQUIRED');previous=-1
    for k in keyframes:
        exact_keys(k,['frame','rect'],['frame','rect']);f=k['frame'];require(type(f) is int and previous<f<n,'STILL_KEYFRAME_ORDER_INVALID');previous=f
        rect=k['rect'];require(isinstance(rect,list) and len(rect)==4,'STILL_RECT_REQUIRED')
        x,y,cw,ch=[number(v,'crop') for v in rect];require(x>=0 and y>=0 and cw>0 and ch>0 and x+cw<=iw and y+ch<=ih,'STILL_CROP_OUTSIDE_SOURCE')
        require(abs(cw/ch-w/h)<1e-7,'STILL_CROP_ASPECT_MISMATCH')
        require(request['allow_upscale'] or (cw>=w and ch>=h),'STILL_UPSCALE_NOT_ALLOWED')
    require(keyframes[0]['frame']==0 and keyframes[-1]['frame']==n-1,'STILL_ENDPOINTS_REQUIRED')
    output=directory/'still-motion.mp4';log=directory/'encode.log'
    command=[tools.binary('ffmpeg'),'-nostdin','-v','error','-f','rawvideo','-pixel_format','rgb24','-video_size',f'{w}x{h}',
        '-framerate',str(fps),'-i','pipe:0','-vf','scale=in_range=pc:out_range=tv:out_color_matrix=bt709,format=yuv420p',
        '-an','-frames:v',str(n),'-r',str(fps),'-fps_mode','cfr','-c:v','libx264','-crf','18','-preset','medium',
        '-color_range','tv','-colorspace','bt709','-color_primaries','bt709','-color_trc','iec61966-2-1' if request['input_color']=='srgb' else 'bt709','-movflags','+faststart',str(output)]
    paths=[];j=0
    with log.open('wb') as err:
        process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=err,
                                 start_new_session=True)
        expired = threading.Event()
        finished = threading.Event()
        cancellation = RUN_CANCELLATION.get()
        cancelled = threading.Event()
        def stop_encoder():
            deadline = time.monotonic() + ENCODER_TIMEOUT_SEC
            while not finished.wait(min(0.05, max(0, deadline - time.monotonic()))):
                if cancellation is not None and cancellation.is_set():
                    cancelled.set()
                    break
                if time.monotonic() >= deadline:
                    expired.set()
                    break
            if finished.is_set():
                return
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        # The watchdog covers blocked pipe writes, not just the final wait.
        watchdog = threading.Thread(target=stop_encoder, name="still-encoder-watchdog")
        watchdog.daemon = True
        watchdog.start()
        try:
            for f in range(n):
                if expired.is_set() or cancelled.is_set():
                    raise subprocess.TimeoutExpired(command, ENCODER_TIMEOUT_SEC)
                while j<len(keyframes)-2 and f>keyframes[j+1]['frame']:j+=1
                a,b=keyframes[j:j+2];t=(f-a['frame'])/(b['frame']-a['frame'])
                if request['interpolation']=='smoothstep':t=t*t*(3-2*t)
                x,y,cw,ch=[av+(bv-av)*t for av,bv in zip(a['rect'],b['rect'])]
                frame=im.resize((w,h),resample=Image.Resampling.LANCZOS,box=(x,y,x+cw,y+ch))
                process.stdin.write(frame.tobytes());paths.append({'frame':f,'rect':[x,y,cw,ch]})
            process.stdin.close();process.wait(timeout=ENCODER_TIMEOUT_SEC)
            if expired.is_set() or cancelled.is_set():
                raise subprocess.TimeoutExpired(command, ENCODER_TIMEOUT_SEC)
        except (BrokenPipeError,subprocess.TimeoutExpired) as exc:
            process.kill();process.wait()
            if cancelled.is_set():
                raise OperationCancelled('STILL_ENCODER_CANCELLED: partial outputs retained') from exc
            reason = 'STILL_ENCODER_TIMEOUT: ' if expired.is_set() else 'STILL_ENCODER_FAILED: '
            raise ContractError(reason+log.read_text(errors='replace')[-2000:]) from exc
        finally:
            finished.set()
            watchdog.join()
            if process.poll() is None:process.kill();process.wait()
            if not process.stdin.closed:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
        require(process.returncode==0,'STILL_ENCODER_FAILED: '+log.read_text(errors='replace')[-2000:])
    counted=json.loads(exec_tool([tools.binary('ffprobe'),'-v','error','-select_streams','v:0','-count_frames',
        '-show_entries','stream=nb_read_frames,avg_frame_rate,width,height','-of','json',str(output)]).stdout)['streams'][0]
    require(int(counted['nb_read_frames'])==n and frame_rate(counted.get('avg_frame_rate'))==fps,'STILL_OUTPUT_CLOCK_MISMATCH')
    require(counted['width']==w and counted['height']==h,'STILL_OUTPUT_GEOMETRY_MISMATCH')
    from color_ops import frame_clock
    times=frame_clock(output,tools);require(len(times)==n and all(abs(t-float(Fraction(i,1)/fps))<=.00001 for i,t in enumerate(times)),'STILL_OUTPUT_TIMESTAMP_MISMATCH')
    require(sha256(asset['path'])==asset['sha256'],'STILL_SOURCE_CHANGED_DURING_RENDER')
    write_json(directory/'crop-path.json',{'schema':'still-crop-path/1','source':asset,'frames':paths})
    result={'schema':'still-image-render/1','source':asset,'source_size':[iw,ih],'video':{'path':str(output),'sha256':sha256(output)},
        'frames':n,'fps':str(fps),'duration':float(Fraction(n,1)/fps),'geometry':[w,h],'interpolation':request['interpolation'],
        'crop_path':{'path':str(directory/'crop-path.json'),'sha256':sha256(directory/'crop-path.json')},'pillow_version':pillow_version,
        'audio':'none; caller explicitly places narration/music later','color':{'input_interpretation':request['input_color'],'basis':'caller-declared','output_transfer_requested':'iec61966-2-1' if request['input_color']=='srgb' else 'bt709','output_primaries_and_matrix_requested':'bt709','limit':'output tags requested, not independently measured color correctness; ICC and rotation rejected'},
        'generation_type':'deterministic still-image camera path, no synthesized subject motion or model generation',
        'effect_review':'NOT_RUN','limits':['crop and motion choices belong to caller','no perspective/parallax/3D/optical flow','H264 lossy encoding; not pixel-identical still preservation']}
    write_json(directory/'still-motion-map.json',result);return result
