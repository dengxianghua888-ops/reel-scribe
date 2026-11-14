"""Explicit coordinate conversion, not automatic UI understanding."""
import copy
import hashlib
import json
import re
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'runtime'))
import editing_runtime as rt
import tutorial_ops as mod

class Tools:
    def __init__(self):self.calls=[];self.rotation=0;self.sar='1:1'
    def probe(self,path):
        w,h=(1920,1080) if Path(path).name!='focused.mp4' else map(int,re.search(r'scale=(\d+):(\d+)',self.calls[-1][self.calls[-1].index('-vf')+1]).groups())
        return {'duration':1,'streams':[{'codec_type':'video','width':w,'height':h,'tags':{'rotate':self.rotation},'sample_aspect_ratio':self.sar}]}
    def ff(self,args):self.calls.append(args);Path(args[-1]).write_bytes(b'fake media; contract test only')

@pytest.fixture
def case(tmp_path):
    p=tmp_path/'source';p.write_bytes(b'fixture')
    q={'operation':'screen-focus','source':{'path':str(p),'sha256':rt.sha256(p)},'crop':{'x':100,'y':100,'width':800,'height':400},'output':{'width':800,'height':400},
       'highlights':[{'start':0,'end':1,'box':{'x':110,'y':110,'width':200,'height':100},'thickness':2,'color_rgb':'FFAA00'}]}
    out=tmp_path/'out';out.mkdir();return q,out,Tools()

def display(q):
    q['coordinate_space']={'kind':'display','width':960,'height':540,'source_width':1920,'source_height':1080}
    return q

def test_legacy_source_coordinates_unchanged(case):
    q,out,t=case;before=copy.deepcopy(q);r=mod.screen_focus(q,out,t)
    assert q==before and r['crop']==q['crop'] and r['highlights']==q['highlights']
    assert 'coordinate_audit' not in r and Path(t.calls[0][-1]).name=='focused.mp4'

def test_display_mapping_is_exact_and_auditable(case):
    q,out,t=case;display(q);before=copy.deepcopy(q);r=mod.screen_focus(q,out,t)
    assert q==before and r['crop']=={'x':200,'y':200,'width':1600,'height':800}
    assert r['highlights'][0]['thickness']==4 and r['highlights'][0]['box']['x']==220
    assert r['coordinate_audit']['display_to_source_scale']=={'numerator':2,'denominator':1}
    assert r['coordinate_mapping']['offset_x']==200

@pytest.mark.parametrize('change,error',[
 (lambda q:q['coordinate_space'].update(source_width=960),'SOURCE_DIMENSION_MISMATCH'),
 (lambda q:q['coordinate_space'].update(width=961),'DISPLAY_ASPECT_MISMATCH'),
 (lambda q:q['coordinate_space'].update(width=True),'DIMENSIONS_INVALID'),
 (lambda q:q['coordinate_space'].update(height=0),'DIMENSIONS_INVALID'),
 (lambda q:q['coordinate_space'].update(kind='viewport'),'SPACE_UNSUPPORTED'),
 (lambda q:q['coordinate_space'].update(offset_x=10),'UNKNOWN_FIELDS'),
 (lambda q:q['crop'].update(x=900),'RECTANGLE_OUT_OF_FRAME'),
 (lambda q:q['highlights'][0]['box'].update(x=10),'HIGHLIGHT_OUTSIDE_CROP'),
 (lambda q:q['highlights'][0].update(thickness=True),'THICKNESS_INVALID'),
])
def test_rejects_invalid_declaration_before_render(case,change,error):
    q,out,t=case;display(q);change(q)
    with pytest.raises(rt.ContractError):mod.screen_focus(q,out,t)
    assert not t.calls and not (out/'focus-map.json').exists()

@pytest.mark.parametrize('field',['crop','thickness'])
def test_no_fractional_rounding(case,field):
    q,out,t=case;display(q);q['coordinate_space'].update(width=3840,height=2160)
    if field=='crop':q['crop']['x']=101
    else:q['highlights'][0]['thickness']=3
    with pytest.raises(rt.ContractError,match='NONINTEGER_SOURCE_COORDINATE'):mod.screen_focus(q,out,t)
    assert not t.calls

def test_integer_downscale_and_odd_crop_rule(case):
    q,out,t=case;display(q);q['coordinate_space'].update(width=3840,height=2160)
    q['crop']['x']=104
    r=mod.screen_focus(q,out,t);assert r['crop']['x']==52
    q['crop']['x']=102
    with pytest.raises(rt.ContractError,match='EVEN_CROP_REQUIRED'):mod.screen_focus(q,out,t)

@pytest.mark.parametrize('rotation,sar,error',[(90,'1:1','ROTATED'),(0,'2:1','NONSQUARE')])
def test_existing_geometry_refusals(case,rotation,sar,error):
    q,out,t=case;display(q);t.rotation=rotation;t.sar=sar
    with pytest.raises(rt.ContractError,match=error):mod.screen_focus(q,out,t)
    assert not t.calls

def test_changed_source_no_success_map(case):
    q,out,t=case;old=t.ff
    def mutate(args):old(args);Path(q['source']['path']).write_bytes(b'changed during render')
    t.ff=mutate
    with pytest.raises(rt.ContractError):mod.screen_focus(q,out,t)
    assert not (out/'focus-map.json').exists()

@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg required')
@pytest.mark.parametrize('display_dims,crop,box,thickness',[( (180,90),(10,10,120,60),(20,20,40,20),2),((540,270),(12,12,240,120),(24,24,60,30),3),((240,120),(16,16,200,100),(32,32,60,40),4)])
def test_real_display_and_source_requests_decode_equally(tmp_path,display_dims,crop,box,thickness):
    source=tmp_path/'source.mp4'
    subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=size=360x180:rate=10:duration=1','-f','lavfi','-i','sine=frequency=600:duration=1','-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac','-shortest',str(source)],check=True)
    q={'operation':'screen-focus','source':{'path':str(source),'sha256':rt.sha256(source)},'crop':dict(zip(['x','y','width','height'],crop)),'output':{'width':240,'height':120},'highlights':[{'start':0,'end':.8,'box':dict(zip(['x','y','width','height'],box)),'thickness':thickness,'color_rgb':'FFAA00'}],
       'coordinate_space':{'kind':'display','width':display_dims[0],'height':display_dims[1],'source_width':360,'source_height':180}}
    manual=copy.deepcopy(q);manual.pop('coordinate_space')
    from fractions import Fraction
    ratio=Fraction(360,display_dims[0])
    for key in manual['crop']:manual['crop'][key]=int(manual['crop'][key]*ratio)
    for key in manual['highlights'][0]['box']:manual['highlights'][0]['box'][key]=int(manual['highlights'][0]['box'][key]*ratio)
    manual['highlights'][0]['thickness']=int(manual['highlights'][0]['thickness']*ratio)
    hashes=[]
    for name,request in [('display',q),('source',manual)]:
        folder=tmp_path/name;folder.mkdir();mod.screen_focus(request,folder,rt.Tools());path=folder/'focused.mp4'
        rgb=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:v:0','-pix_fmt','rgb24','-f','rawvideo','-'])
        pcm=subprocess.check_output(['ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-f','s16le','-'])
        hashes.append((hashlib.sha256(rgb).hexdigest(),hashlib.sha256(pcm).hexdigest()))
    assert hashes[0]==hashes[1]

@pytest.mark.parametrize('fault,error', [('dimensions','DIMENSIONS_MISMATCH'),('sar','PIXEL_ASPECT_MISMATCH'),('audio','AUDIO_STREAM_METADATA_CHANGED')])
def test_failed_readback_has_no_success_map(case,fault,error):
    q,out,t=case;original=t.probe
    def wrong(path):
        data=original(path)
        if Path(path).name=='focused.mp4':
            if fault=='dimensions':data['streams'][0]['width']+=2
            elif fault=='sar':data['streams'][0]['sample_aspect_ratio']='2:1'
            else:data['streams'].append({'codec_type':'audio','codec_name':'aac','sample_rate':'48000','channels':2})
        return data
    t.probe=wrong
    with pytest.raises(rt.ContractError,match=error):mod.screen_focus(q,out,t)
    assert not (out/'focus-map.json').exists()

def test_mux_failure_no_success_map_or_retry(case):
    q,out,t=case
    def fail(args):t.calls.append(args);raise rt.ContractError('fixture mux failure')
    t.ff=fail
    with pytest.raises(rt.ContractError,match='mux failure'):mod.screen_focus(q,out,t)
    assert len(t.calls)==1 and not (out/'focus-map.json').exists()
