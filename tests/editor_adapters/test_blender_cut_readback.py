"""Observation projection tests; fake media probing is not host/semantic acceptance."""
import copy
import importlib.util
from pathlib import Path
import pytest
from test_blender_cut_import import fixture,probe
spec=importlib.util.spec_from_file_location('readback',Path(__file__).resolve().parents[2]/'tools/editor-adapters/blender_cut_readback.py')
a=importlib.util.module_from_spec(spec);spec.loader.exec_module(a)

@pytest.fixture
def case(tmp_path):
 fixture(tmp_path); plan=a.imp.validate(tmp_path,probe)
 rows=[dict(r,id=r['name']) for r in plan['clips']]
 return tmp_path,{'package_sha256':plan['package_sha256'],'profile':{'fps':24,'width':160,'height':90},'frame_start':1,'frame_end':48,'clips':rows}

def test_unchanged_and_trim(case):
 p,o=case;before=copy.deepcopy(o);t=a.project(p,o,probe)
 assert t['tracks']['children'][0]['children'][0]['source_range']['duration']['value']==48
 assert o==before
 o['clips'][0]['length']=36;o['frame_end']=36
 t=a.project(p,o,probe)
 assert t['tracks']['children'][0]['children'][0]['metadata']['recap']['duration']=={'numerator':36,'denominator':24}

@pytest.mark.parametrize('change',[
 lambda o:o.update(package_sha256='0'*64),lambda o:o['profile'].update(fps=25),
 lambda o:o.update(frame_start=2),lambda o:o.update(frame_end=49),
 lambda o:o['clips'].clear(),lambda o:o['clips'].append(copy.deepcopy(o['clips'][0])),
 lambda o:o['clips'][0].update(id='other'),lambda o:o['clips'][0].update(name='other'),
 lambda o:o['clips'][0].update(path='/tmp/wrong'),lambda o:o['clips'][0].update(channel=3),
 lambda o:o['clips'][0].update(kind='Audio'),lambda o:o['clips'][0].update(offset=23),
 lambda o:o['clips'][0].update(length=49),lambda o:o['clips'][0].update(target=2),
 lambda o:o['clips'][0].update(offset=24.5),lambda o:o['clips'][0].update(length=True),
])
def test_unsupported_rejected(case,change):
 p,o=case;change(o)
 with pytest.raises(ValueError):a.project(p,o,probe)

@pytest.mark.parametrize('value',[True,1.5,float('nan'),float('inf'),'1'])
def test_integer_rejects(value):
 with pytest.raises((ValueError,OverflowError)):a.integer(value)

@pytest.mark.parametrize('sample_rate',[48000,44100])
def test_audio_retains_sample_clock_and_pairing(case,sample_rate):
 from test_blender_cut_import import seal
 import json
 p,o=case;t=json.loads((p/'timeline.otio').read_text())
 sound=copy.deepcopy(t['tracks']['children'][0]);sound['kind']='Audio';c=sound['children'][0]
 c['name']='original:one';c['metadata']['recap']['linked_video_instance']='one'
 for key in ('start_time','duration'):
  c['source_range'][key]['value']=int(c['source_range'][key]['value']*sample_rate/24);c['source_range'][key]['rate']=sample_rate
 t['tracks']['children'].append(sound);(p/'timeline.otio').write_text(json.dumps(t));seal(p)
 probe_audio=lambda path:probe(path)+[{'codec_type':'audio','start_time':'0'}]
 base=a.imp.validate(p,probe_audio);o['package_sha256']=base['package_sha256'];o['clips']=[dict(r,id=r['name']) for r in base['clips']]
 for r in o['clips']:r['length']=36
 o['frame_end']=36
 result=a.project(p,o,probe_audio)
 assert result['tracks']['children'][1]['children'][0]['source_range']['duration']=={'OTIO_SCHEMA':'RationalTime.1','value':sample_rate*3//2,'rate':float(sample_rate)}
 o['clips'][1]['length']=35
 with pytest.raises(ValueError,match='DESYNC'):a.project(p,o,probe_audio)

 if sample_rate==44100:
  o['clips'][0]['length']=35;o['frame_end']=35
  with pytest.raises(ValueError,match='SUBSAMPLE'):a.project(p,o,probe_audio)
