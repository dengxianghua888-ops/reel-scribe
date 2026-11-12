"""Bound standalone PCM narration; fake probes are not actual-host acceptance."""
import copy
import json
import hashlib
import pytest
from test_blender_cut_import import fixture, seal, probe, rt, a as importer
from test_blender_cut_readback import a as reader


def setup(root):
    t=fixture(root)
    first=t['tracks']['children'][0]['children'][0]
    first['metadata']['recap']['segment_id']='original'
    second=copy.deepcopy(first);second['name']='vo-picture'
    second['source_range']['start_time']=rt(0)
    second['metadata']['recap'].update(segment_id='vo',source_start=0,target_start=2)
    t['tracks']['children'][0]['children'].append(second)
    data=b'fake PCM';(root/'media/vo.wav').write_bytes(data);sha=hashlib.sha256(data).hexdigest()
    resources=json.loads((root/'media-manifest.json').read_text())
    resources['resources']['narration:vo']={'kind':'narration','sha256':sha,'package_path':'media/vo.wav',
        'facts':{'sample_rate':48000,'channels':1,'audio_stream_index':0,'duration_samples':96000}}
    sound=copy.deepcopy(second);sound['name']='voice';sound['metadata']['recap'].update(resource_id='narration:vo')
    sound['media_reference']['metadata']['recap'].update(resource_id='narration:vo',sha256=sha)
    sound['media_reference']['target_url']='media/vo.wav'
    for key,value in [('start_time',0),('duration',96000)]:sound['source_range'][key]={'OTIO_SCHEMA':'RationalTime.1','value':value,'rate':48000}
    gap={'OTIO_SCHEMA':'Gap.1','name':'gap','metadata':{},'enabled':True,'effects':[],'markers':[],
         'source_range':{'OTIO_SCHEMA':'TimeRange.1','start_time':rt(0),'duration':rt(48)}}
    t['tracks']['children'].append({'OTIO_SCHEMA':'Track.1','kind':'Audio','enabled':True,
        'metadata':{'recap':{'role':'narration','track_id':'narration'}},'children':[gap,sound]})
    (root/'timeline.otio').write_text(json.dumps(t));(root/'media-manifest.json').write_text(json.dumps(resources));seal(root)
    return t,resources


def audio_probe(path):
    if str(path).endswith('.wav'):
        return [{'index':0,'codec_type':'audio','codec_name':'pcm_s16le','sample_rate':'48000','channels':1,'duration_ts':96000,'time_base':'1/48000'}]
    return probe(path)


def observe(root):
    plan=importer.validate(root,audio_probe)
    return {'package_sha256':plan['package_sha256'],'profile':{'fps':24,'width':160,'height':90},
            'frame_start':1,'frame_end':96,'clips':[dict(row,id=row['name']) for row in plan['clips']]}


def test_pcm_narration_and_gap_readback(tmp_path):
    setup(tmp_path);o=observe(tmp_path)
    t=reader.project(tmp_path,o,audio_probe)
    assert t['tracks']['children'][1]['children'][1]['source_range']['duration']['value']==96000
    # Actual source-only trim ripples unchanged narration and picture.
    o['clips'][0]['length']=36
    o['clips'][1]['target']=37;o['clips'][2]['target']=37;o['frame_end']=84
    t=reader.project(tmp_path,o,audio_probe)
    assert t['tracks']['children'][1]['children'][0]['source_range']['duration']['value']==36


@pytest.mark.parametrize('change',[
    {'codec_name':'aac'},{'codec_name':'pcm_f32le'},{'sample_rate':'44100'}, {'channels':2},
    {'start_time':'0.1'}, {'duration_ts':95999}, {'duration_ts':True}, {'time_base':'1/44100'}, {'index':1}])
def test_bad_probe_rejected(tmp_path,change):
    setup(tmp_path)
    def bad(path):
        rows=audio_probe(path)
        if str(path).endswith('.wav'):rows[0].update(change)
        return rows
    with pytest.raises(ValueError):importer.validate(tmp_path,bad)


@pytest.mark.parametrize('change',[
    {'sample_rate':True},{'channels':True},{'duration_samples':False},{'audio_stream_index':False},
    {'sample_rate':44100},{'duration_samples':95999}])
def test_bad_facts_rejected(tmp_path,change):
    _,r=setup(tmp_path);r['resources']['narration:vo']['facts'].update(change)
    (tmp_path/'media-manifest.json').write_text(json.dumps(r));seal(tmp_path)
    with pytest.raises(ValueError):importer.validate(tmp_path,audio_probe)


@pytest.mark.parametrize('change',[
    lambda o:o['clips'][2].update(length=47),lambda o:o['clips'][2].update(offset=1),
    lambda o:o['clips'][2].update(target=50),lambda o:o['clips'][1].update(offset=1),
    lambda o:o['clips'][1].update(length=47),lambda o:o['clips'][2].update(channel=1)])
def test_narration_changes_refused(tmp_path,change):
    setup(tmp_path);o=observe(tmp_path);change(o)
    with pytest.raises(ValueError):reader.project(tmp_path,o,audio_probe)


def test_wrong_role_tamper_and_hidden_video(tmp_path):
    t,_=setup(tmp_path);t['tracks']['children'][1]['metadata']['recap']['role']='original'
    (tmp_path/'timeline.otio').write_text(json.dumps(t));seal(tmp_path)
    with pytest.raises(ValueError,match='NARRATION_TRACK_ROLE'):importer.validate(tmp_path,audio_probe)
    t['tracks']['children'][1]['metadata']['recap']['role']='narration'
    (tmp_path/'timeline.otio').write_text(json.dumps(t));seal(tmp_path)
    def hidden(path):return audio_probe(path)+probe(path) if str(path).endswith('.wav') else probe(path)
    with pytest.raises(ValueError,match='NARRATION_STREAM_SELECTION'):importer.validate(tmp_path,hidden)
    (tmp_path/'media/vo.wav').write_bytes(b'changed')
    with pytest.raises(ValueError,match='MEMBER_CHANGED'):importer.validate(tmp_path,audio_probe)


def test_two_narrations_two_gaps_ripple(tmp_path):
    t,_=setup(tmp_path)
    video=t['tracks']['children'][0]['children']
    for i,c in enumerate(copy.deepcopy(video)):
        c['name']+='-second'
        c['metadata']['recap']['segment_id']+='-second'
        c['metadata']['recap']['target_start']+=4
        video.append(c)
    audio=t['tracks']['children'][1]['children']
    second=copy.deepcopy(audio)
    second[1]['name']+='-second'
    second[1]['metadata']['recap']['segment_id']+='-second'
    second[1]['metadata']['recap']['target_start']+=4
    audio.extend(second)
    (tmp_path/'timeline.otio').write_text(json.dumps(t));seal(tmp_path)
    o=observe(tmp_path);o['frame_end']=192
    reader.project(tmp_path,o,audio_probe)
    o['clips'][0]['length']=36
    for row in o['clips'][1:]:row['target']-=12
    o['frame_end']=180
    saved=reader.project(tmp_path,o,audio_probe)
    gaps=saved['tracks']['children'][1]['children']
    assert gaps[0]['source_range']['duration']['value']==36
    assert gaps[2]['source_range']['duration']['value']==48


def test_nonzero_narration_sample_window(tmp_path):
    t,r=setup(tmp_path)
    sound=t['tracks']['children'][1]['children'][1]
    sound['source_range']['start_time']['value']=48000
    sound['metadata']['recap']['source_start']=1
    r['resources']['narration:vo']['facts']['duration_samples']=144000
    (tmp_path/'timeline.otio').write_text(json.dumps(t))
    (tmp_path/'media-manifest.json').write_text(json.dumps(r));seal(tmp_path)
    def longer(path):
        rows=audio_probe(path)
        if str(path).endswith('.wav'):rows[0]['duration_ts']=144000
        return rows
    plan=importer.validate(tmp_path,longer)
    o={'package_sha256':plan['package_sha256'],'profile':{'fps':24,'width':160,'height':90},
       'frame_start':1,'frame_end':96,'clips':[dict(row,id=row['name']) for row in plan['clips']]}
    saved=reader.project(tmp_path,o,longer)
    assert saved['tracks']['children'][1]['children'][1]['source_range']['start_time']['value']==48000
