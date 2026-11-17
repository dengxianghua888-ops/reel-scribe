"""Real FFmpeg synthetic fixtures, not human speech/creative acceptance."""
import array
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

SCRIPT=Path(__file__).resolve().parents[2]/'scripts/normalize_media.py'
spec=importlib.util.spec_from_file_location('normalize_media',SCRIPT)
n=importlib.util.module_from_spec(spec);spec.loader.exec_module(n)


def ff(*args):
    subprocess.run(['ffmpeg','-nostdin','-v','error','-n',*map(str,args)],check=True,capture_output=True)


@pytest.fixture
def source(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):pytest.skip('FFmpeg required')
    p=tmp_path/'source.mov'
    ff('-f','lavfi','-i','color=black:s=160x96:r=30:d=4',
       '-f','lavfi','-i','sine=frequency=1000:sample_rate=48000:duration=4',
       '-c:v','libx264','-pix_fmt','yuv420p','-c:a','pcm_s16le',p)
    return p


def run(source,output,**kw):
    return n.normalize(source,n.rt.sha256(source),output,start=.5,end=3.5,accept_lossy=True,**kw)


def test_success_and_immutable(source,tmp_path):
    digest=n.rt.sha256(source);r=run(source,tmp_path/'out')
    assert r['status']=='SUCCEEDED_TECHNICAL_NEEDS_REVIEW'
    assert r['source_unchanged'] and n.rt.sha256(source)==digest
    assert r['policy']['lossy'] and r['exact_changed_frame_and_sample_counts']=='UNKNOWN'
    assert '-copyts' in r['argv'] and 'STARTPTS' not in ''.join(r['argv'])
    assert Path(r['derived']['path']).exists()
    assert json.loads((tmp_path/'out/receipt.json').read_text())['full_decode']=='PASS'
    with pytest.raises(ValueError,match='OUTPUT_MUST_BE_NEW_DIRECTORY'):run(source,tmp_path/'out')


@pytest.mark.parametrize('offset',[-.12,.12])
def test_positive_negative_av_event_offset(tmp_path,offset):
    p=tmp_path/'offset.mov'
    ff('-f','lavfi','-i',"color=black:s=160x96:r=30:d=4,drawbox=color=white:t=fill:enable='gte(t,2)'",
       '-itsoffset',offset,'-f','lavfi','-i',"aevalsrc=if(gte(t\\,2)\\,0.5*sin(2*PI*1000*t)\\,0):s=48000:d=4",
       '-copyts','-c:v','libx264','-pix_fmt','yuv420p','-c:a','pcm_s16le',p)
    r=run(p,tmp_path/'normalized');derived=r['derived']['path']
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',derived,'-map','0:a:0','-f','s16le','-'])
    samples=array.array('h');samples.frombytes(raw)
    onset=next(i for i,x in enumerate(samples) if abs(x)>1000)/48000
    # shared origin yields white video event at 1.5; preserve signed audio offset
    assert abs(onset-(1.5+offset))<.003
    for time,bright in [(1.43,False),(1.6,True)]:
        pixel=subprocess.check_output(['ffmpeg','-v','error','-ss',str(time),'-i',derived,
            '-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','-'])
        assert (pixel[0]>200)==bright


def test_input_rejections(source,tmp_path):
    kwargs=dict(start=0,end=1,accept_lossy=True)
    for bad in ['https://example.org/a.webm','pipe:0']:
        with pytest.raises(ValueError,match='LOCAL_FILE_REQUIRED'):
            n.normalize(bad,'0'*64,tmp_path/'bad',**kwargs)
    with pytest.raises(ValueError,match='SOURCE_HASH_MISMATCH'):
        n.normalize(source,'0'*64,tmp_path/'bad',**kwargs)
    with pytest.raises(ValueError,match='EXPLICIT_LOSSY_ACCEPTANCE_REQUIRED'):
        n.normalize(source,n.rt.sha256(source),tmp_path/'bad',start=0,end=1)
    link=tmp_path/'alias.mov';link.symlink_to(source)
    with pytest.raises(ValueError,match='SYMLINK_FORBIDDEN'):run(link,tmp_path/'bad')
    with pytest.raises(ValueError,match='FINITE_NUMBER_REQUIRED'):
        n.normalize(source,n.rt.sha256(source),tmp_path/'bad',start=float('nan'),end=1,accept_lossy=True)
    assert not (tmp_path/'bad').exists()


def test_large_real_gap_rejected(tmp_path):
    p=tmp_path/'gap.mov'
    ff('-f','lavfi','-i','color=black:s=160x96:r=30:d=4',
       '-itsoffset','1','-f','lavfi','-i','sine=frequency=1000:sample_rate=48000:duration=3',
       '-copyts','-c:v','libx264','-c:a','pcm_s16le',p)
    with pytest.raises(ValueError,match='AUDIO_GAP_EXCEEDS_EXPLICIT_LIMIT'):
        n.normalize(p,n.rt.sha256(p),tmp_path/'bad',start=0,end=3,accept_lossy=True)
    assert not (tmp_path/'bad').exists()


def test_encoder_failure_has_no_success_artifact(source,tmp_path,monkeypatch):
    original=n.rt.exec_tool
    def fail(args,**kw):
        if '-filter_complex' in args:raise RuntimeError('TEST_ENCODER_FAILURE')
        return original(args,**kw)
    monkeypatch.setattr(n.rt,'exec_tool',fail)
    with pytest.raises(RuntimeError,match='TEST_ENCODER_FAILURE'):run(source,tmp_path/'failed')
    receipt=json.loads((tmp_path/'failed/receipt.json').read_text())
    assert receipt['status']=='FAILED' and 'derived' not in receipt
    assert not (tmp_path/'failed/normalized.mov').exists()


def test_source_changed_during_encode_rejected(source,tmp_path,monkeypatch):
    original=n.rt.exec_tool
    def change(args,**kw):
        result=original(args,**kw)
        if '-filter_complex' in args:
            with source.open('ab') as f:f.write(b'changed-fixture')
        return result
    monkeypatch.setattr(n.rt,'exec_tool',change)
    with pytest.raises(ValueError,match='SOURCE_CHANGED_DURING_IMPORT'):run(source,tmp_path/'changed')
    assert json.loads((tmp_path/'changed/receipt.json').read_text())['status']=='FAILED'
    assert not (tmp_path/'changed/normalized.mov').exists()


def test_playlist_and_missing_audio_rejected(tmp_path):
    playlist=tmp_path/'input.mov';playlist.write_text('#EXTM3U\nhttps://example.org/private\n')
    with pytest.raises(ValueError,match='ONLY_SELF_CONTAINED_WEBM_OR_ISOBMFF_INPUT'):
        n.normalize(playlist,n.rt.sha256(playlist),tmp_path/'bad',start=0,end=1,accept_lossy=True)
    video=tmp_path/'video.mov'
    ff('-f','lavfi','-i','color=black:s=160x96:r=30:d=1','-c:v','libx264',video)
    with pytest.raises(ValueError,match='EXACTLY_ONE_VIDEO_AND_AUDIO_REQUIRED'):
        n.normalize(video,n.rt.sha256(video),tmp_path/'bad',start=0,end=1,accept_lossy=True)


def test_leading_audio_offset_keeps_silence(tmp_path):
    p=tmp_path/'leading.mov'
    ff('-f','lavfi','-i','color=black:s=160x96:r=30:d=2',
       '-itsoffset','0.12','-f','lavfi','-i','sine=frequency=1000:sample_rate=48000:duration=2',
       '-copyts','-c:v','libx264','-c:a','pcm_s16le',p)
    r=n.normalize(p,n.rt.sha256(p),tmp_path/'out',start=0,end=1,accept_lossy=True,max_audio_gap=.15)
    raw=subprocess.check_output(['ffmpeg','-v','error','-i',r['derived']['path'],'-f','s16le','-'])
    samples=array.array('h');samples.frombytes(raw)
    onset=next(i for i,x in enumerate(samples) if abs(x)>1000)/48000
    assert abs(onset-.12)<.003
    assert max(map(abs,samples[:5000]))==0


def test_external_dref_refused_before_probe(tmp_path,monkeypatch):
    def box(name,data):return (len(data)+8).to_bytes(4,'big')+name+data
    payload=box(b'url ',b'\0\0\0\0https://example.org/media\0')
    dref=box(b'dref',b'\0'*4+(1).to_bytes(4,'big')+payload)
    p=tmp_path/'reference.mp4';p.write_bytes(box(b'ftyp',b'isom\0\0\0\0')+
        box(b'moov',box(b'trak',box(b'mdia',box(b'minf',box(b'dinf',dref))))))
    monkeypatch.setattr(n.rt.Tools,'probe',lambda *_:pytest.fail('probe must not execute'))
    with pytest.raises(ValueError,match='EXTERNAL_MEDIA_REFERENCE_FORBIDDEN'):
        n.normalize(p,n.rt.sha256(p),tmp_path/'bad',start=0,end=1,accept_lossy=True)


def test_unlink_failure_cannot_break_committed_import(source,tmp_path,monkeypatch):
    def denied(*args,**kwargs):raise PermissionError('TEST_UNLINK_DENIED')
    monkeypatch.setattr(Path,'unlink',denied)
    r=run(source,tmp_path/'out')
    assert n.completed_import(tmp_path/'out')==r
    assert (tmp_path/'out/pending.mov').exists()  # no cleanup in commit path


def test_receipt_write_failure_rolls_back_same_inode(source,tmp_path,monkeypatch):
    original=Path.open
    def denied(self,*args,**kwargs):
        if self.name=='.success-receipt.pending.json':raise PermissionError('TEST_RECEIPT_WRITE_DENIED')
        return original(self,*args,**kwargs)
    monkeypatch.setattr(Path,'open',denied)
    with pytest.raises(PermissionError,match='TEST_RECEIPT_WRITE_DENIED'):run(source,tmp_path/'out')
    assert not (tmp_path/'out/normalized.mov').exists()
    receipt=json.loads((tmp_path/'out/receipt.json').read_text())
    assert receipt['status']=='FAILED' and receipt['rollback']=='REMOVED_SAME_INODE_MEDIA_LINK'
    with pytest.raises(ValueError,match='IMPORT_NOT_COMMITTED'):n.completed_import(tmp_path/'out')


def test_receipt_failure_with_unlink_denied_leaves_uncommitted_only(source,tmp_path,monkeypatch):
    original=Path.open
    def denied_write(self,*args,**kwargs):
        if self.name=='.success-receipt.pending.json':raise PermissionError('TEST_RECEIPT_WRITE_DENIED')
        return original(self,*args,**kwargs)
    def denied_unlink(*args,**kwargs):raise PermissionError('TEST_UNLINK_DENIED')
    monkeypatch.setattr(Path,'open',denied_write);monkeypatch.setattr(Path,'unlink',denied_unlink)
    with pytest.raises(PermissionError):run(source,tmp_path/'out')
    assert (tmp_path/'out/normalized.mov').exists()
    receipt=json.loads((tmp_path/'out/receipt.json').read_text())
    assert receipt['status']=='FAILED' and 'UNCOMMITTED_MEDIA_MAY_REMAIN' in receipt['rollback']
    with pytest.raises(ValueError,match='IMPORT_NOT_COMMITTED'):n.completed_import(tmp_path/'out')


def test_receipt_link_failure_cannot_overwrite_competitor(source,tmp_path,monkeypatch):
    original=n.os.link
    def race(src,dst,*args,**kwargs):
        if Path(src).name=='.success-receipt.pending.json':
            Path(dst).write_text('{"status":"another writer"}')
        return original(src,dst,*args,**kwargs)
    monkeypatch.setattr(n.os,'link',race)
    with pytest.raises(RuntimeError,match='IMPORT_UNCOMMITTED'):run(source,tmp_path/'out')
    assert json.loads((tmp_path/'out/receipt.json').read_text())=={'status':'another writer'}
    with pytest.raises(ValueError,match='IMPORT_NOT_COMMITTED'):n.completed_import(tmp_path/'out')
    assert not (tmp_path/'out/normalized.mov').exists()
