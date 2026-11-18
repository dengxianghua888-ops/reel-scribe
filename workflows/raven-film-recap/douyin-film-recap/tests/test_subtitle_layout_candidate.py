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


def work_fixture():
    import hashlib
    from PIL import ImageFont
    doc = {'schema': 'work-document/1', 'plan': {'width': 360, 'height': 640, 'clips': [{'id': 'clip'}]},
           'captions': {'cue': {'clip_id': 'clip', 'start': 0, 'end': 2,
                               'text': '中文与 WiFi 网络连接成功，保留原文。',
                               'style_override': {'color_rgb': 'FFFFFF'}}},
           'caption_style': {'font': {'path': str(FONT), 'sha256': hashlib.sha256(FONT.read_bytes()).hexdigest()},
                             'font_family': ImageFont.truetype(str(FONT), 24).getname()[0],
                             'font_size': 24, 'margin_v': 60, 'color_rgb': 'FFFFFF'}}
    recipe = {'schema': 'style-recipe/1', 'id': 'linebreak', 'version': '1',
              'style': {'family': 'film', 'style_id': 'provided', 'version': '1', 'card': {'path': 'explicit-card', 'sha256': 'caller-provided'}},
              'parameters': {}, 'layout_constraints': {'schema': 'caption-layout/1'}}
    return doc, recipe


def work_digest(value):
    import json
    import hashlib
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def test_work_preview_adapter_preserves_text_time_and_existing_override():
    from douyin_film_recap.subtitle_layout import prepare_work_preview
    doc, recipe = work_fixture()
    before = deepcopy(doc); old_recipe = deepcopy(recipe)
    prepared = prepare_work_preview(doc, expected_document_sha256=work_digest(doc),
                                   store='explicit.sqlite', expected_version='version-1', recipe=recipe,
                                   caption_ids=['cue'], max_chars=12, max_lines=4)
    assert doc == before and recipe == old_recipe
    req = prepared['preview_request']
    assert req['operation'] == 'style-recipe-preview' and req['expected_version'] == 'version-1'
    assert req['expected_document_sha256'] == work_digest(doc)
    a, b = req['variants']
    assert a['recipe']['parameters']['caption_overrides']['cue']['line_breaks']['offsets'] == []
    assert b['recipe']['parameters']['caption_overrides']['cue']['line_breaks']['offsets']
    assert b['recipe']['parameters']['caption_overrides']['cue']['color_rgb'] == 'FFFFFF'
    assert b['scope']['caption_ids'] == ['cue'] and b['scope']['freeze_duration']
    assert b['scope']['freeze_positions'] == ['clip'] and not b['scope']['caption_style']
    assert b['expected_recipe_sha256'] == work_digest(b['recipe'])
    assert prepared['render_verification'] == 'NOT_PERFORMED' and not prepared['adopted']


@pytest.mark.parametrize('change,error', [('document', 'WORK_DOCUMENT_CHANGED'), ('font', 'WORK_FONT_CHANGED'),
    ('family', 'WORK_FONT_IDENTITY_MISMATCH'), ('constraints', 'WORK_LAYOUT_CONSTRAINTS_REQUIRED'),
    ('targets', 'WORK_CAPTION_TARGETS_INVALID')])
def test_work_preview_adapter_rejects_stale_or_unbound_inputs(change, error):
    from douyin_film_recap.subtitle_layout import prepare_work_preview
    doc, recipe = work_fixture(); digest = work_digest(doc); targets = ['cue']
    if change == 'document': doc['captions']['cue']['text'] += '新'
    if change == 'font': doc['caption_style']['font']['sha256'] = '0'*64
    if change == 'family': doc['caption_style']['font_family'] = 'NotTheFont'
    if change == 'constraints': recipe.pop('layout_constraints')
    if change == 'targets': targets = ['cue', 'cue']
    if change != 'document': digest = work_digest(doc)
    with pytest.raises(LayoutBlocked, match=error):
        prepare_work_preview(doc, expected_document_sha256=digest, store='explicit.sqlite',
                             expected_version='v1', recipe=recipe, caption_ids=targets, max_lines=4)


def test_work_preview_cli_prepares_only_and_never_overwrites(tmp_path):
    import json
    import subprocess
    import sys
    doc, recipe = work_fixture()
    request_path = tmp_path/'request.json'; output = tmp_path/'prepared.json'
    payload = {'document': doc, 'expected_document_sha256': work_digest(doc), 'store': str(tmp_path/'absent.sqlite'),
               'expected_version': 'v1', 'recipe': recipe, 'caption_ids': ['cue'], 'max_lines': 4}
    request_path.write_text(json.dumps(payload), encoding='utf-8')
    source_bytes = request_path.read_bytes()
    cmd = [sys.executable, '-m', 'douyin_film_recap.subtitle_layout', '--work-preview', str(request_path), str(output)]
    import os
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1]/'src')}
    subprocess.run(cmd, check=True, capture_output=True, env=env)
    assert json.loads(output.read_text())['status'] == 'PREPARED_NOT_EXECUTED'
    assert not (tmp_path/'absent.sqlite').exists()
    assert request_path.read_bytes() == source_bytes
    before = output.read_bytes()
    assert subprocess.run(cmd, capture_output=True, env=env).returncode != 0
    assert output.read_bytes() == before


def test_work_adapter_rejects_conflicting_recipe_without_dropping_styles():
    from douyin_film_recap.subtitle_layout import prepare_work_preview
    doc, recipe = work_fixture()
    recipe['parameters']['caption_overrides'] = {'cue': {'font_size': 48, 'color_rgb': 'FF0000'}}
    before = deepcopy(recipe)
    with pytest.raises(LayoutBlocked, match='WORK_RECIPE_TARGET_OVERRIDE_CONFLICT'):
        prepare_work_preview(doc, expected_document_sha256=work_digest(doc), store='explicit.sqlite',
                             expected_version='v1', recipe=recipe, caption_ids=['cue'])
    assert recipe == before
