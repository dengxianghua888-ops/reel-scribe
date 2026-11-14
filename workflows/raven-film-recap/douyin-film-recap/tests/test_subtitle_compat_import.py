import hashlib
import pytest
from douyin_film_recap.asr import parse_srt_or_vtt, canonicalize_subtitle
from douyin_film_recap.qc import _parse_srt


def test_explicit_compat_extra_blanks_integer_seconds(tmp_path):
    source=tmp_path/'zh.srt'
    source.write_text('00:00:04,000 --> 00:00:06\n\n主引擎开始启动\n\n1\n\n00:00:43,000 --> 00:00:45,000\n\n中文轴不套英文\n')
    original=source.read_bytes()
    with pytest.raises(ValueError,match='SUBTITLE_UNATTACHED_TEXT_BLOCK'):parse_srt_or_vtt(source,'s')
    out=tmp_path/'canonical.srt';report=canonicalize_subtitle(source,out,identifier_policy="sequential-numeric")
    assert source.read_bytes()==original
    assert report['cue_count']==2 and report['strict_output_qc']=='PASS'
    assert report['source']['sha256']==hashlib.sha256(original).hexdigest()
    assert any(w['code']=='WHOLE_SECONDS_NORMALIZED' for w in report['warnings'])
    assert _parse_srt(out)==[(4.,6.,'主引擎开始启动'),(43.,45.,'中文轴不套英文')]
    assert parse_srt_or_vtt(out,'s')[1].start==43
    with pytest.raises(FileExistsError):canonicalize_subtitle(source,out,identifier_policy="sequential-numeric")


@pytest.mark.parametrize('text',[
 '1\n00:00:01,000 --> wrong\ntext',
 '1\n00:00:01,000 --> 00:00:02,000\n\ntext',
 '1\n00:00:02,000 --> 00:00:01,000\ntext',
 '1\n00:61:01,000 --> 00:61:02,000\ntext',
 '1\n00:00:01,000 --> 00:00:02,0000\ntext',
 '1\n00:00:02,000 --> 00:00:03,000\nfirst\n\n2\n00:00:01,000 --> 00:00:02,000\nsecond',
])
def test_timed_malformed_input_never_silently_drops(tmp_path,text):
    source=tmp_path/'bad.srt';source.write_text(text)
    with pytest.raises(ValueError,match='SUBTITLE_'):parse_srt_or_vtt(source,'s')


def test_vtt_header_notes_and_settings(tmp_path):
    source=tmp_path/'valid.vtt';source.write_text('WEBVTT\n\nNOTE ignored --> even arrows\ncomment\n\nidentifier\n00:01.000 --> 00:02.000 align:start position:20%\nHello\n\nNOTE end\n')
    rows=parse_srt_or_vtt(source,'s')
    assert len(rows)==1 and rows[0].text=='Hello' and rows[0].start==1
    assert all(w.timing_source=='estimated' for w in rows[0].words)


def test_compat_rejects_ambiguous_or_empty(tmp_path):
    source=tmp_path/'bad.srt'
    for text in ['1\n\n00:00:01 --> 00:00:02\n\ntext\n\n8\n\n00:00:03 --> 00:00:04\n\nsecond',
                 '00:00:01 --> 00:00:02\n\n00:00:03 --> 00:00:04\n\nsecond']:
        source.write_text(text)
        with pytest.raises(ValueError,match='SUBTITLE_'):canonicalize_subtitle(source,tmp_path/'out.srt')
    assert not (tmp_path/'out.srt').exists()


def test_compat_numeric_dialogue_not_silently_removed(tmp_path):
    source=tmp_path/'numeric.srt'
    source.write_text('00:00:01 --> 00:00:02\n\n比分\n\n1\n\n00:00:03 --> 00:00:04\n\n比分\n\n2\n\n00:00:05 --> 00:00:06\n\n结束')
    before=source.read_bytes()
    with pytest.raises(ValueError,match='SUBTITLE_COMPAT_IDENTIFIER_POLICY_REQUIRED'):
        canonicalize_subtitle(source,tmp_path/'out.srt')
    assert source.read_bytes()==before and not (tmp_path/'out.srt').exists()


def test_valid_multiline_numeric_dialogue_preserved(tmp_path):
    source=tmp_path/'numeric.srt'
    source.write_text('00:00:01,000 --> 00:00:02,000\n比分\n1\n\n00:00:03,000 --> 00:00:04,000\n比分\n2')
    out=tmp_path/'out.srt';canonicalize_subtitle(source,out)
    assert [x[2] for x in _parse_srt(out)]==['比分 1','比分 2']


def test_canonical_partial_staging_write_never_publishes_target(tmp_path,monkeypatch):
    import os
    source=tmp_path/'source.srt';source.write_text('1\n00:00:01,000 --> 00:00:02,000\n字幕\n')
    original=source.read_bytes();target=tmp_path/'canonical.srt'
    fdopen=os.fdopen
    class PartialWriter:
        def __init__(self, stream):self.stream=stream
        def __enter__(self):return self
        def __exit__(self,*args):self.stream.close()
        def write(self,data):
            self.stream.write(data[:8]);self.stream.flush()
            raise OSError('INJECTED_PARTIAL_WRITE')
    monkeypatch.setattr(os,'fdopen',lambda *a,**k:PartialWriter(fdopen(*a,**k)))
    with pytest.raises(OSError,match='INJECTED_PARTIAL_WRITE'):
        canonicalize_subtitle(source,target)
    assert not target.exists() and source.read_bytes()==original


def test_canonical_cleanup_failure_does_not_reverse_commit(tmp_path,monkeypatch):
    from pathlib import Path
    source=tmp_path/'source.srt';source.write_text('1\n00:00:01,000 --> 00:00:02,000\n字幕\n')
    def denied(*args,**kwargs):raise PermissionError('INJECTED_CLEANUP_FAILURE')
    monkeypatch.setattr(Path,'unlink',denied)
    target=tmp_path/'canonical.srt';report=canonicalize_subtitle(source,target)
    assert report['canonical']['sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
    assert _parse_srt(target)==[(1.,2.,'字幕')]
    assert list(tmp_path.glob('.subtitle-import-*.pending'))


def test_canonical_existing_source_and_target_never_overwritten(tmp_path):
    source=tmp_path/'source.srt';source.write_text('1\n00:00:01,000 --> 00:00:02,000\n字幕\n')
    target=tmp_path/'existing.srt';target.write_text('KEEP')
    before=source.read_bytes()
    for path in [source,target]:
        with pytest.raises(FileExistsError):canonicalize_subtitle(source,path)
    assert source.read_bytes()==before and target.read_text()=='KEEP'


def test_canonical_fsync_failure_never_publishes_target(tmp_path,monkeypatch):
    import os
    source=tmp_path/'source.srt';source.write_text('1\n00:00:01,000 --> 00:00:02,000\n字幕\n')
    def denied(*args):raise OSError('INJECTED_FSYNC_FAILURE')
    monkeypatch.setattr(os,'fsync',denied)
    target=tmp_path/'canonical.srt'
    with pytest.raises(OSError,match='INJECTED_FSYNC_FAILURE'):canonicalize_subtitle(source,target)
    assert not target.exists()


def test_detached_negation_rejected_default_retained_in_explicit_compat(tmp_path):
    source=tmp_path/'detached.srt'
    source.write_text('1\n00:00:01,000 --> 00:00:02,000\n第一行\n\n不能删除的否定补充\n\n2\n00:00:03,000 --> 00:00:04,000\n结束')
    original=source.read_bytes()
    with pytest.raises(ValueError,match='SUBTITLE_UNATTACHED_TEXT_BLOCK'):
        parse_srt_or_vtt(source,'s')
    target=tmp_path/'out.srt'
    report=canonicalize_subtitle(source,target,identifier_policy='sequential-numeric')
    assert _parse_srt(target)==[(1.,2.,'第一行 不能删除的否定补充'),(3.,4.,'结束')]
    assert any(w['code']=='EXPLICIT_COMPATIBILITY_REBLOCKING' for w in report['warnings'])
    assert source.read_bytes()==original


def test_source_identity_binds_exact_parsed_bytes_not_separate_read(tmp_path,monkeypatch):
    from pathlib import Path
    from douyin_film_recap.utils import SourceChangedDuringRead
    source=tmp_path/'source.srt'
    a=b'1\n00:00:01,000 --> 00:00:02,000\nA\n'
    b=b'1\n00:00:01,000 --> 00:00:02,000\nB\n'
    source.write_bytes(a)
    real_read=Path.read_bytes
    # Simulate a read seeing B while all later on-disk identity checks see A.
    monkeypatch.setattr(Path,'read_bytes',lambda p: b if p==source else real_read(p))
    target=tmp_path/'out.srt'
    with pytest.raises(SourceChangedDuringRead):canonicalize_subtitle(source,target)
    assert not target.exists()


def test_canonical_never_reopens_source_as_text(tmp_path,monkeypatch):
    from pathlib import Path
    source=tmp_path/'source.srt';source.write_bytes(b'1\n00:00:01,000 --> 00:00:02,000\nA\n')
    original=source.read_bytes();read_text=Path.read_text
    def guarded(path,*args,**kwargs):
        if path==source:raise AssertionError('source must parse same bytes used for digest')
        return read_text(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',guarded)
    target=tmp_path/'out.srt';report=canonicalize_subtitle(source,target)
    assert report['source']['sha256']==hashlib.sha256(original).hexdigest()
    assert _parse_srt(target)==[(1.,2.,'A')]
