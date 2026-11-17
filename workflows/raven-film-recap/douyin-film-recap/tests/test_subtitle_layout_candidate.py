"""Measured candidate contract; actual pixels tested separately below."""
from copy import deepcopy
from pathlib import Path

import pytest

from douyin_film_recap.subtitle_layout import propose_layout, LayoutBlocked

FONT = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')


def request(text='中文与 WiFi 速度为 20Mbps。', **kw):
    return dict(cues=[dict(id='cue-1', start=1.25, end=4.5, text=text)],
                font_file=FONT, font_size=24, width=360, height=640,
                margin_x=30, margin_v=60, outline=2, max_chars=16, max_lines=4, **kw)


@pytest.mark.parametrize('text', ['中文不能改变正文。', '中文 WiFi 接入成功。', '速度为 20Mbps，不能关闭。',
                                 '（注意）不要删除，保留原文！', 'John Smith 不是张三。', '甲  乙\n保留原有换行。'])
@pytest.mark.parametrize('width,height', [(360,640), (640,360)])
@pytest.mark.parametrize('font', ['NotoSansCJK-Regular.ttc','NotoSerifCJK-Regular.ttc'])
def test_candidate_preserves_source_and_timing(text, width, height, font):
    r=request(text); r.update(width=width,height=height,font_file=FONT.with_name(font))
    assert Path(r['font_file']).is_file(), 'Font required for real width test; not silently skipped'
    original=deepcopy(r); out=propose_layout(**r)
    assert r==original
    cue=out['cues'][0]; proposed=cue['proposed_text']
    for offset in reversed(cue['inserted_newline_offsets']):
        text=text[:offset]+'\n'+text[offset:]
    assert proposed==text
    assert (cue['id'],cue['start'],cue['end'])==('cue-1',1.25,4.5)
    assert all(w<=r['width']-2*(r['margin_x']+r['outline']) for w in cue['line_widths_px'])
    assert out['adopted'] is False and out['render_verification']=='NOT_PERFORMED'


def test_font_and_canvas_identity_change():
    r=request(); a=propose_layout(**r)
    r['font_file']=FONT.with_name('NotoSansCJK-Bold.ttc'); b=propose_layout(**r)
    assert a['font_sha256']!=b['font_sha256']
    r['width']=540; c=propose_layout(**r)
    assert b['parameters']!=c['parameters']


@pytest.mark.parametrize('change,error', [({'width':40},'NO_AVAILABLE_REGION'),
    ({'font_file':'/does/not/exist'},None), ({'max_lines':1},'LINE_LIMIT'),
    ({'max_chars':True},'INVALID'), ({'height':False},'INVALID')])
def test_reject_instead_of_silent_fallback(change,error):
    r=request('这是一条非常长的测试字幕，用于验证超过行数时不能偷偷删字。'); r.update(change)
    with pytest.raises((LayoutBlocked,FileNotFoundError), match=error): propose_layout(**r)


def test_unbreakable_word_and_combining_text():
    with pytest.raises(LayoutBlocked,match='UNBREAKABLE_TOKEN'):
        propose_layout(**request('Supercalifragilisticexpialidocious'))
    with pytest.raises(LayoutBlocked,match='COMBINING'):
        propose_layout(**request('e\u0301'))


def test_duplicate_and_invalid_times():
    r=request();r['cues']*=2
    with pytest.raises(LayoutBlocked,match='CUE_ID'): propose_layout(**r)
    r=request(); r['cues'][0]['end']=0
    with pytest.raises(LayoutBlocked,match='CUE_TIME'): propose_layout(**r)


@pytest.mark.parametrize('width,height', [(360,640), (640,360)])
@pytest.mark.parametrize('font', ['NotoSansCJK-Regular.ttc','NotoSerifCJK-Regular.ttc'])
def test_real_libass_candidate_pixels(tmp_path, width, height, font):
    import shutil
    import subprocess
    from types import SimpleNamespace
    from PIL import Image
    from douyin_film_recap.config import RenderConfig
    from douyin_film_recap.render import _subtitle_style, _escape_subtitle_path
    from douyin_film_recap.subtitles import SubtitleCue, write_srt
    r=request('中文 WiFi 速度为 20Mbps，不要删除。')
    r.update(width=width,height=height,font_file=FONT.with_name(font))
    candidate=propose_layout(**r); row=candidate['cues'][0]
    srt=write_srt([SubtitleCue(0,1,row['proposed_text'])],tmp_path/'candidate.srt')
    cfg=SimpleNamespace(render=RenderConfig(width=width,height=height,subtitle_font_size=24,
        subtitle_margin_v=60,subtitle_outline=2,subtitle_font=candidate['font_family']))
    style=_subtitle_style(cfg)+',MarginL=30,MarginR=30,WrapStyle=2'
    ffmpeg=shutil.which('ffmpeg'); assert ffmpeg
    result=subprocess.run([ffmpeg,'-nostdin','-v','info','-f','lavfi','-i',
        f'color=c=black:s={width}x{height}:r=1:d=1','-vf',
        f"subtitles='{_escape_subtitle_path(srt)}':force_style='{style}'", '-frames:v','1',
        '-f','rawvideo','-pix_fmt','rgb24','-'],capture_output=True,check=True)
    assert b'failed to find' not in result.stderr.lower()
    image=Image.frombytes('RGB',(width,height),result.stdout)
    box=image.convert('L').point(lambda x:255 if x>180 else 0).getbbox()
    assert box is not None
    assert r['margin_x']<=box[0]<box[2]<=width-r['margin_x']
    assert 0<box[1]<box[3]<height-r['margin_v']+24
    image.save(tmp_path/'candidate.png')


@pytest.mark.parametrize('text', ['注\U000E0100记','❤️','👍🏽'])
def test_do_not_split_unsupported_graphemes(text):
    with pytest.raises(LayoutBlocked,match='COMBINING'):
        propose_layout(**request(text))


def test_missing_glyph_is_blocked():
    r=request(); r['font_file']='/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
    with pytest.raises(LayoutBlocked,match='MISSING_GLYPH'): propose_layout(**r)


def test_decimal_unit_is_not_split():
    r=request('12.345Mbps');r['max_chars']=4
    with pytest.raises(LayoutBlocked,match='UNBREAKABLE_TOKEN'): propose_layout(**r)


def test_cli_never_overwrites_source_or_existing_output(tmp_path, monkeypatch):
    import json
    import sys
    from douyin_film_recap.subtitle_layout import main
    source=tmp_path/'request.json'; output=tmp_path/'candidate.json'
    r=request();r['font_file']=str(r['font_file'])
    source.write_text(json.dumps(r),encoding='utf-8')
    before=source.read_bytes()
    monkeypatch.setattr(sys,'argv',['subtitle_layout',str(source),str(output)])
    main()
    assert source.read_bytes()==before
    old=output.read_bytes()
    with pytest.raises(FileExistsError): main()
    assert output.read_bytes()==old


def test_font_coverage_tool_missing_is_blocked(monkeypatch):
    from douyin_film_recap import subtitle_layout
    monkeypatch.setattr(subtitle_layout.shutil,'which',lambda name:None)
    with pytest.raises(LayoutBlocked,match='TOOL_UNAVAILABLE'): propose_layout(**request())
