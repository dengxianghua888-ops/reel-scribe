import copy,json
import pytest
from fractions import Fraction
from test_local_undo import case,audio_case,commit,state,request,run,scope
import editing_runtime as rt
import work_ops,shared_timeline
from audio_ops import validate_work_envelope
E=dict(sample_rate=48000,fade_in_samples=12000,fade_out_samples=12000,curve='tri')
@pytest.mark.parametrize('key', ['sample_rate','fade_in_samples','fade_out_samples'])
@pytest.mark.parametrize('bad',[None,False,True,1.0,'48000',-1])
def test_types(key,bad):
 with pytest.raises((ValueError,TypeError)):validate_work_envelope({**E,key:bad},1)
@pytest.mark.parametrize('bad',[None,False,{},'log','tri;volume=0'])
def test_curve(bad):
 with pytest.raises((ValueError,TypeError)):validate_work_envelope({**E,'curve':bad},1)
def test_max_and_overlap():
 assert validate_work_envelope({**E,'fade_in_samples':48000,'fade_out_samples':0},1)==48000
 with pytest.raises(ValueError):validate_work_envelope({**E,'fade_in_samples':48000,'fade_out_samples':1},1)
def doc(case):
 audio_case(case);return copy.deepcopy(state(case[0])['document'])
def test_scope_and_invalidation(case):
 old=doc(case);new=copy.deepcopy(old);new['audio_tracks']['music']['envelope']=E
 sc=scope();sc['audio_ids']=[]
 with pytest.raises(ValueError):work_ops.revision_diff(old,new,sc,case[2])
 diff=work_ops.revision_diff(old,new,scope(),case[2]);assert 'listening-review' in diff['invalidated'] and diff['audio_mapping_changed']
 assert shared_timeline.compatible(old,new)
 new['audio_tracks']['music']['offset']=.01
 assert not shared_timeline.compatible(old,new)
def test_source_hash(case):
 d=doc(case);d['audio_tracks']['music'].update(envelope=E)
 d['audio_tracks']['music']['source']['sha256']='0'*64
 with pytest.raises(ValueError,match='HASH'):work_ops.validate_document(d,case[2])
def test_binding(case):
 d=doc(case);d['audio_tracks']['music']['envelope']=E;d['style_bindings']['*']={}
 with pytest.raises(ValueError,match='STYLE_BINDING'):work_ops.validate_document(d,case[2])
def test_undo_conflict(case):
 doc(case);commit(case,lambda d:d['audio_tracks']['music'].update(envelope=E))
 commit(case,lambda d:d['audio_tracks']['music']['envelope'].update(fade_in_samples=100))
 q=request(case,3);q['fields']=[dict(kind='audio_track',id='music',field='envelope')];before=state(case[0])
 with pytest.raises(ValueError,match='CONFLICT'):run(case,q)
 assert state(case[0])==before
def test_undo_remove_then_restore(case):
 doc(case);commit(case,lambda d:d['audio_tracks']['music'].update(envelope=E))
 commit(case,lambda d:d['audio_tracks']['music'].pop('envelope'))
 commit(case,lambda d:d['audio_tracks']['music'].update(gain_db=-15))
 q=request(case,4);q['fields']=[dict(kind='audio_track',id='music',field='envelope')];before=state(case[0]);run(case,q)
 restored=json.loads((case[1]/'candidate.json').read_text())['document']['audio_tracks']['music']
 assert restored['envelope']==E and restored['gain_db']==-15 and state(case[0])==before
@pytest.mark.parametrize('a,b,ok',[(0,.5,False),(.25,.75,True),(.5,1,False),(.249,.75,False),(.25,.751,False)])
def test_protection(case,a,b,ok):
 d=doc(case);d['audio_tracks']['music']['envelope']=E;ref=d['audio_tracks']['music']['source']
 d['evidence_protection']={'schema':'work-evidence-protection/1','units':[dict(id='u',label='u',kind='claim',speaker='human',modality='audio',source=ref,start=a,end=b,evidence=ref,requires=[])],'required_units':['u'],'occurrences':[dict(id='o',unit_id='u',carriers=[dict(type='audio-track',id='music')],dependencies={})],'chapters':[dict(id='c',title='test',occurrence_ids=['o'])]}
 if ok:work_ops.validate_document(d,case[2])
 else:
  with pytest.raises(ValueError,match='ENVELOPE_OVERLAP'):work_ops.validate_document(d,case[2])

@pytest.fixture
def envelope_media(tmp_path):
 """Synthetic media verifies execution plumbing, not hearing or semantics."""
 tools=rt.Tools();base=tmp_path/'base.mp4';tone=tmp_path/'tone.wav'
 tools.ff(['-f','lavfi','-i','color=c=black:s=64x64:r=25:d=2','-an','-c:v','libx264',str(base)])
 tools.ff(['-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=1','-c:a','pcm_f32le',str(tone)])
 ref=lambda p:dict(path=str(p),sha256=rt.sha256(p))
 req=dict(operation='audio-mix',source=ref(base),base_gain_db=0,tracks=[dict(source=ref(tone),start=0,end=1,output_start=.5,gain_db=0,envelope=E)])
 out=tmp_path/'mix';out.mkdir()
 return req,out,tools

def test_decoded_incomplete_rejected(envelope_media):
 req,out,_=envelope_media
 class Short(rt.Tools):
  def ff(self,args):
   super().ff(args)
   if str(args[-1]).endswith('.f32'):
    from pathlib import Path
    p=Path(args[-1]);p.write_bytes(p.read_bytes()[:-8])
 with pytest.raises(ValueError,match='ENVELOPE_AUDIO_COVERAGE_INCOMPLETE'):
  rt.audio_mix(req,out,Short())
 assert not (out/'mixed.mp4').exists()

@pytest.mark.parametrize('curve',['tri','qsin'])
def test_explicit_decode_and_original_identity(envelope_media,curve):
 req,out,tools=envelope_media;req['tracks'][0]['envelope']={**E,'curve':curve}
 result=rt.audio_mix(req,out,tools);track=result['tracks'][0]
 assert all(track['source'][k]==v for k,v in req['tracks'][0]['source'].items())
 assert track['envelope_pcm']['samples']==48000 and track['envelope_pcm']['padding'] is False
 assert result['audio_review']=='NOT_RUN'
 assert (out/'mixed.mp4').is_file()

def test_real_five_frame_anchor_plus_decimal_offset(envelope_media):
 req,out,tools=envelope_media;source=req['source']
 doc={'schema':'work-document/1','plan':{'schema':'execution-plan/1','fps':'25','width':64,'height':64,'fit':'contain','sources':{'s':source},'clips':[{'id':'prefix','source_id':'s','start':0,'end':.2,'gain_db':0},{'id':'tail','source_id':'s','start':.2,'end':2,'gain_db':0}]},'captions':{},'caption_style':None,'audio_tracks':{'voice':{'source':req['tracks'][0]['source'],'start':0,'end':1,'anchor_clip_id':'tail','offset':.1,'gain_db':0,'envelope':E}},'style_bindings':{},'notes':{}}
 _,_,tracks=work_ops.validate_document(doc,tools)
 assert tracks[0]['output_start']==.3
 req['tracks']=tracks
 result=rt.audio_mix(req,out,tools)
 assert result['tracks'][0]['output_start_samples']==14400

def test_source_endpoint_float_cancellation(envelope_media):
 req,out,tools=envelope_media
 track=req['tracks'][0];track.update(start=9610/48000,end=24010/48000,envelope={**E,'fade_in_samples':2400,'fade_out_samples':2400})
 # Both endpoints encode exact integer samples; subtraction has float noise.
 result=rt.audio_mix(req,out,tools)
 assert result['tracks'][0]['envelope_pcm']['samples']==14400
