"""Explicit scope projection contracts, not editorial or real-host approval."""
import copy,json
import pytest
from test_blender_cut_readback import a,case
from test_blender_cut_import import probe,seal

@pytest.fixture
def paired(case):
 p,o=case;t=json.loads((p/'timeline.otio').read_text());sound=copy.deepcopy(t['tracks']['children'][0]);sound['kind']='Audio'
 c=sound['children'][0];c['name']='original:one';c['metadata']['recap']['linked_video_instance']='one'
 for key in ['start_time','duration']:
  c['source_range'][key]['value']*=2000;c['source_range'][key]['rate']=48000
 t['tracks']['children'].append(sound);(p/'timeline.otio').write_text(json.dumps(t));seal(p)
 def media(_):return [{**probe(None)[0],'duration_ts':96,'time_base':'1/24'},
                        {'codec_type':'audio','start_time':'0','duration_ts':192000,'time_base':'1/48000'}]
 base=a.imp.validate(p,media);o['package_sha256']=base['package_sha256'];o['clips']=[dict(r,id=r['name']) for r in base['clips']]
 h=json.loads((p/'media-manifest.json').read_text())['resources']['source']['sha256']
 scope={'schema':'blender-bound-extension/1','package_sha256':base['package_sha256'],'host_sha256':'a'*64,
    'instances':{r['id']:{'source_sha256':h,'before_start_frame':24,'before_end_frame':72,'start_frame':24,'end_frame':84,'target_start_frame':0} for r in o['clips']}}
 for r in o['clips']:r['length']=60
 o['frame_end']=60
 return p,o,media,scope


def test_explicit_pair_extended(paired):
 p,o,media,s=paired
 with pytest.raises(ValueError,match='EXTENSION_UNSUPPORTED'):a.project(p,o,media)
 t=a.project(p,o,media,extension_scope=s)
 assert t['tracks']['children'][0]['children'][0]['source_range']['duration']['value']==60
 assert t['tracks']['children'][1]['children'][0]['source_range']['duration']['value']==120000


@pytest.mark.parametrize('mutation',[
 lambda s:s.update(package_sha256='0'*64),lambda s:s.update(host_sha256=None),
 lambda s:s['instances'].pop('original:one'),lambda s:s['instances']['one'].update(source_sha256='0'*64),
 lambda s:s['instances']['one'].update(start_frame=True),lambda s:s['instances']['one'].update(end_frame=85),
 lambda s:s['instances']['one'].update(before_end_frame=73),lambda s:s['instances']['one'].update(target_start_frame=1),
 lambda s:s['instances'].update(unknown=copy.deepcopy(s['instances']['one'])),
])
def test_scope_rejections(paired,mutation):
 p,o,media,s=paired;mutation(s)
 with pytest.raises(ValueError):a.project(p,o,media,extension_scope=s)


def test_source_overrun(paired):
 p,o,media,s=paired
 for r in o['clips']:r['length']=84
 for r in s['instances'].values():r['end_frame']=108
 o['frame_end']=84
 with pytest.raises(ValueError,match='SOURCE_OVERRUN'):a.project(p,o,media,extension_scope=s)


def test_live_audio_duration_short(paired):
 p,o,media,s=paired
 def shorter(path):
  rows=media(path);rows[1]['duration_ts']=150000;return rows
 with pytest.raises(ValueError,match='SOURCE_OVERRUN'):a.project(p,o,shorter,extension_scope=s)


def test_one_track_unchanged_rejects(paired):
 p,o,media,s=paired;o['clips'][1]['length']=48;s['instances'].pop('original:one')
 with pytest.raises(ValueError,match='DESYNC'):a.project(p,o,media,extension_scope=s)


def test_scope_byte_binding(tmp_path):
 p=tmp_path/'scope.json';p.write_text('{}');ref={'path':str(p),'sha256':a.imp.digest(p)}
 assert a.read_extension(ref)=={}
 p.write_text('{"changed":true}')
 with pytest.raises(ValueError,match='IDENTITY_CHANGED'):a.read_extension(ref)
