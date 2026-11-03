import pytest
from douyin_film_recap.asr import parse_srt_or_vtt, parse_ass
from douyin_film_recap.models import StoryboardSegment
from douyin_film_recap.subtitles import _cues_from_boundaries


def segment(boundaries):
    return StoryboardSegment(segment_id='s', beat_id='b', mode='voiceover', title='t',
        text='你好，世界！', planned_duration_sec=2, audio_duration_sec=2,
        audio_owner='narration', visuals=[], notes='x', tts_word_boundaries=boundaries)


def boundary(text, start):
    return {'text': text, 'start': start, 'duration': .3}


@pytest.mark.parametrize('parts', [
    [boundary('你好', 0)],
    [boundary('你好', 0), boundary('你好', .5), boundary('世界', 1)],
    [boundary('世界', 0), boundary('你好', .5)],
    [boundary('你好', 1), boundary('世界', .5)],
])
def test_bad_boundaries_cannot_silently_omit_or_reorder(parts):
    with pytest.raises(ValueError, match='TTS_BOUNDARY_'):
        _cues_from_boundaries(segment(parts), 0, 20)


def test_complete_boundaries_accept_punctuation_difference():
    cues = _cues_from_boundaries(segment([boundary('你好', 0), boundary('世界', .5)]), 0, 20)
    assert ''.join(c.text for c in cues) == '你好世界'


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig'])
def test_valid_subtitle_utf8(tmp_path, encoding):
    p = tmp_path / 'sample.srt'
    p.write_bytes('1\n00:00:00,000 --> 00:00:01,000\n你好世界\n'.encode(encoding))
    assert parse_srt_or_vtt(p, 's')[0].text == '你好世界'


@pytest.mark.parametrize('encoding', ['utf-16-le', 'utf-16-be', 'gbk'])
def test_unsupported_encoding_is_explicit(tmp_path, encoding):
    p = tmp_path / 'sample.srt'
    p.write_bytes('1\n00:00:00,000 --> 00:00:01,000\n你好世界\n'.encode(encoding))
    with pytest.raises(ValueError, match='SUBTITLE_ENCODING_'):
        parse_srt_or_vtt(p, 's')


def test_ass_encoding_rejected(tmp_path):
    p = tmp_path / 'sample.ass'
    p.write_bytes('[Events]\nDialogue: 你好'.encode('gbk'))
    with pytest.raises(ValueError, match='SUBTITLE_ENCODING_'):
        parse_ass(p, 's')


def test_out_of_range_boundary_cannot_drop_cue():
    with pytest.raises(ValueError, match='TTS_BOUNDARY_CUE_INCOMPLETE'):
        _cues_from_boundaries(segment([boundary('你好', 0), boundary('世界', 3)]), 0, 1)
