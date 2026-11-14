import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('readability', ROOT/'tools/editor-adapters/plan_caption_readability.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class Font:
    def __init__(self, size=32):
        self.size = size
    def getlength(self, text):
        return len(text)*self.size
    def getbbox(self, text):
        return (0, 0, len(text)*self.size, self.size)
    def getmetrics(self):
        return (self.size, 8)


def row(text='字幕测试'):
    return {'id':'one','text':text,'start_frame':0,'end_frame':24,
            'declared_start_sec':0, 'declared_end_sec':1,
            'start_delta_sec':0, 'end_delta_sec':0}


def test_normalize_only_soft_whitespace():
    old='机器\n人。\nHello\nworld!'
    new=m.normalized(old)
    assert new=='机器人。 Hello world!'
    assert m.nonspace(new)==m.nonspace(old)


def test_words_not_split():
    assert m.wrap_two('Hello world',Font(1),6)==['Hello','world']
    with pytest.raises(ValueError,match='TWO_LINES_CANNOT_FIT'):
        m.wrap_two('unbreakable',Font(1),6)


def test_prefers_sentence_boundary():
    assert m.wrap_two('中文。文字文字',Font(1),5)==['中文。','文字文字']


def test_preserve_original_and_time(monkeypatch):
    monkeypatch.setattr(m.ImageFont,'truetype',lambda path,size:Font(size))
    data={'rows':[row('Hello\nworld')]};original=copy.deepcopy(data)
    result=m.plan(data,'unused',frame_end=24)
    assert data==original
    assert result['adopted'] is False
    assert result['font_size_px']>=32
    assert result['source_rows']==original['rows']
    for k,v in row().items():
        if k!='text':assert result['candidate_rows'][0][k]==v
    assert m.nonspace(result['candidate_rows'][0]['text'])==m.nonspace(data['rows'][0]['text'])
    assert result['measurements'][0]['reading_review_required']
    assert result['caption_box']['y']>=result['picture_box']['y']+result['picture_box']['height']


def test_cannot_fit_without_lowering_minimum(monkeypatch):
    monkeypatch.setattr(m.ImageFont,'truetype',lambda path,size:Font(size))
    with pytest.raises(ValueError,match='TWO_LINES_CANNOT_FIT_AT_MINIMUM_SIZE'):
        m.plan({'rows':[row('文'*100)]},'unused',frame_end=24)


@pytest.mark.parametrize('minimum,maximum',[(31,40),(40,32),(32,49),(True,40)])
def test_font_bounds(minimum,maximum):
    with pytest.raises(ValueError,match='FONT_SIZE_RANGE_UNSUPPORTED'):
        m.plan({'rows':[row()]},'unused',minimum=minimum,maximum=maximum)


def test_ack_required_before_access():
    with pytest.raises(ValueError,match='EXPLICIT_SOFT_WRAP_ACK_REQUIRED'):
        m.build(SimpleNamespace(acknowledge_reflow=False))


def test_stale_input_no_output(tmp_path):
    mp=tmp_path/'map.json';mp.write_text('{}');font=tmp_path/'font';font.write_bytes(b'font')
    args=SimpleNamespace(acknowledge_reflow=True,caption_map=mp,font=font,
                         map_sha256='0'*64,font_sha256=m.contract.digest(font),output=tmp_path/'out')
    with pytest.raises(ValueError,match='STALE_INPUT'):m.build(args)
    assert not args.output.exists()


def test_punctuation_and_quotes_remain(monkeypatch):
    monkeypatch.setattr(m.ImageFont,'truetype',lambda path,size:Font(10))
    text='"Fourty years\nlater" Whatever,\nThom. We\'re done.'
    result=m.plan({'rows':[row(text)]},'unused',frame_end=24)
    new=result['candidate_rows'][0]['text']
    assert m.nonspace(new)==m.nonspace(text)
    assert 'Fourty' in new  # no unsolicited spelling/semantic corrections
    assert result['measurements'][0]['english_words_per_minute']>240


@pytest.mark.parametrize('text', ['you’re', 'you‘re'])
def test_curly_apostrophe_does_not_split_word(text):
    with pytest.raises(ValueError, match='TWO_LINES_CANNOT_FIT'):
        m.wrap_two(text, Font(1), 4)
    assert m.wrap_two(text, Font(1), len(text)) == [text]


@pytest.mark.parametrize('text', ['Cafe\u0301', 'x\ufe0f', '字\U000e0100'])
def test_combining_marks_and_variation_selectors_rejected(text):
    with pytest.raises(ValueError, match='COMBINING_OR_VARIATION_SEQUENCE_UNSUPPORTED'):
        m.wrap_two(text, Font(1), 100)
    with pytest.raises(ValueError, match='COMBINING_OR_VARIATION_SEQUENCE_UNSUPPORTED'):
        m.normalized(text)


@pytest.mark.parametrize('fps', [0, -1, True, 24.0])
def test_invalid_fps(fps):
    with pytest.raises(ValueError, match='FPS_MUST_BE_POSITIVE_INTEGER'):
        m.plan({'rows': [row()]}, 'unused', fps=fps)


@pytest.mark.parametrize('frame_end', [0, -1, True, 24.0])
def test_invalid_frame_end(frame_end):
    with pytest.raises(ValueError, match='FRAME_END_MUST_BE_POSITIVE_INTEGER'):
        m.plan({'rows': [row()]}, 'unused', frame_end=frame_end)
