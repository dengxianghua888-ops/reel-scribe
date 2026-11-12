"""Real synthetic FFmpeg plumbing; no content, listening or semantic acceptance."""
import copy
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from test_batch_preview import case as base_case, prepare, run
from test_source_binding import tools, media
import editing_runtime as rt
import work_ops
import shared_timeline


@pytest.fixture
def case(base_case):
    c=base_case;doc=copy.deepcopy(c['document'])
    doc['plan']['clips'][0]['mute']=False
    font=Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    if not font.is_file():pytest.skip('CJK fixture font unavailable')
    doc['captions']={'label':{'clip_id':'one','start':0,'end':.2,'text':'测试'}}
    doc['caption_style']={'font':{'path':str(font),'sha256':rt.sha256(font)},'font_family':'Noto Sans CJK SC','font_size':12,'margin_v':4,'color_rgb':'FFFFFF'}
    c['store']=c['root']/'caption.sqlite';folder=c['root']/'caption-init';folder.mkdir()
    c['state']=work_ops.work_version({'operation':'work-version','action':'init','store':str(c['store']),
        'work_id':'shared','document':doc,'author':'agent','message':'synthetic fixture'},folder,c['tools'])
    c['document']=doc;c['candidates']=[]
    scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],'style_keys':[],
           'note_keys':[],'output_fields':[],'caption_style':True,'freeze_positions':['one'],'freeze_duration':True}
    for i,size in enumerate([14,16]):
        d=copy.deepcopy(doc);d['caption_style']['font_size']=size
        bundle={'schema':'work-candidate/1','base_version':c['state']['version'],
            'base_document_sha256':c['state']['document_sha256'],'document':d,'scope':scope}
        p=c['root']/f'caption-candidate-{i}.json';rt.write_json(p,bundle)
        c['candidates'].append({'path':str(p),'sha256':rt.sha256(p)})
    return c


def receipt(c,i):
    return json.loads((c['root']/f'batch/jobs/{i}/attempt-0001/receipt.json').read_bytes())


def decoded(path,kind):
    args=['ffmpeg','-v','error','-i',str(path)]
    args+=['-map','0:v:0','-f','rawvideo','-pix_fmt','rgb24','-'] if kind=='video' else ['-map','0:a:0','-f','f32le','-']
    return subprocess.check_output(args)


def test_two_candidates_share_once_and_match_unshared_decoded_output(case):
    prepare(case,2);calls=[];original=rt.run
    def traced(q,*a,**k):calls.append(q['operation']);return original(q,*a,**k)
    with patch.object(rt,'run',traced):result=run(case,'first')
    assert result['status']=='RENDERED'
    assert calls.count('timeline-render')==1 and calls.count('caption-burn')==2 and calls.count('media-qc')==2
    first,second=receipt(case,0),receipt(case,1)
    assert 'timeline_reuse' not in first['result']
    assert second['result']['timeline_reuse']['execution']=='REUSED_VERIFIED_NOT_EXECUTED'
    baseline=rt.run({'operation':'work-render','store':str(case['store']),
        'expected_version':case['state']['version'],'preview_candidate':case['candidates'][1]},case['root']/'baseline',case['tools'])
    assert baseline['status']=='SUCCEEDED' and 'timeline_reuse' not in baseline['result']
    for kind in ['video','audio']:
        assert decoded(second['result']['video']['path'],kind)==decoded(baseline['result']['video']['path'],kind)
    repeated=run(case,'repeat')
    assert [x['action'] for x in repeated['events']]==['REUSED_VERIFIED','REUSED_VERIFIED']


def test_corrupt_donor_cannot_authorize_second_candidate(case):
    prepare(case,2);case['ids']=['0'];run(case,'first')
    (case['root']/'batch/jobs/0/attempt-0001/timeline/preview.mp4').write_bytes(b'corrupt')
    case['ids']=['1'];result=run(case,'second')
    assert result['status']!='RENDERED'
    assert receipt(case,1)['status']=='FAILED'


@pytest.mark.parametrize('field',['plan','captions','notes','audio_tracks','visual_layers'])
def test_different_dependencies_not_eligible(field):
    left={'captions':{'a':'one'},'plan':{'x':1},'notes':{},'audio_tracks':{},'visual_layers':{}}
    right=copy.deepcopy(left);right[field]={'different':1}
    assert not shared_timeline.compatible(left,right)


def test_source_changed_before_second_job_rejected(case):
    prepare(case,2);case['ids']=['0'];run(case,'first')
    Path(case['source']).write_bytes(b'changed source')
    case['ids']=['1'];result=run(case,'second')
    assert result['events'][0]['action']=='PREVIEW_VALIDATION_FAILED'


def test_copy_race_rejected(case,monkeypatch):
    prepare(case,2);case['ids']=['0'];run(case,'first')
    original=shared_timeline.copy_bound
    def corrupt_after_read(path,target,sha,size):
        original(path,target,sha,size)
        if str(path).endswith('timeline/preview.mp4'):
            Path(path).write_bytes(b'changed after checked read')
    monkeypatch.setattr(shared_timeline,'copy_bound',corrupt_after_read)
    case['ids']=['1'];result=run(case,'second')
    assert result['status']!='RENDERED'


@pytest.mark.parametrize('field',['tools','runtime_files'])
def test_changed_environment_never_reuses(case,monkeypatch,field):
    import batch_ops
    prepare(case,2)
    original=batch_ops.environment
    def changed(tools):
        env=copy.deepcopy(original(tools));env[field]['unexpected']='changed';return env
    monkeypatch.setattr(batch_ops,'environment',changed)
    with pytest.raises(rt.ContractError,match='BATCH_ENVIRONMENT_CHANGED'):
        run(case,'rejected')
    assert not (case['root']/'batch/jobs').exists()


def test_media_copy_does_not_read_entire_file(tmp_path,monkeypatch):
    source=tmp_path/'source.mp4';source.write_bytes(b'x'*(2*1024*1024+17))
    digest=rt.sha256(source);size=source.stat().st_size
    monkeypatch.setattr(Path,'read_bytes',lambda *_: (_ for _ in ()).throw(AssertionError('unbounded read')))
    shared_timeline.copy_bound(source,tmp_path/'copy.mp4',digest,size)
    assert rt.sha256(tmp_path/'copy.mp4')==digest


def test_donor_receipt_reparse_cannot_replace_verified_bytes(case,monkeypatch):
    import batch_ops
    prepare(case,2);case['ids']=['0'];run(case,'first')
    original=batch_ops.check_receipt
    def changed(path,*args,**kwargs):
        result=original(path,*args,**kwargs)
        if Path(path).parent.parent.name=='0':
            result=copy.deepcopy(result);result['unbound']='changed between receipt reads'
        return result
    monkeypatch.setattr(batch_ops,'check_receipt',changed)
    case['ids']=['1'];result=run(case,'second')
    assert result['status']!='RENDERED'
    assert receipt(case,1)['error']=='SHARED_TIMELINE_RECEIPT_CHANGED'
