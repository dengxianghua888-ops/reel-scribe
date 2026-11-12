"""Deterministic declared TTS boundaries, not real alignment or readability QA."""
import pytest

from douyin_film_recap.models import StoryboardSegment
from douyin_film_recap.subtitles import _cues_from_boundaries


def grouped(items, *, max_chars=28, audio_duration=None):
    text = ''.join(item[0] for item in items)
    duration = audio_duration or max(start + length for _, start, length in items)
    segment = StoryboardSegment(segment_id='s', beat_id='b', mode='voiceover',
        title='test', text=text, planned_duration_sec=duration, audio_duration_sec=duration,
        audio_owner='narration', visuals=[], notes='Declared timings; not acoustic truth',
        tts_word_boundaries=[{'text': value, 'start': start, 'duration': length}
                             for value, start, length in items])
    cues = _cues_from_boundaries(segment, 2, max_chars)
    assert ''.join(c.text for c in cues) == text
    assert all(c.start >= 2 and c.end > c.start and c.end <= 2 + duration for c in cues)
    assert all(a.end <= b.start for a, b in zip(cues, cues[1:]))
    return cues


@pytest.mark.parametrize('ending', ['。', '！', '？', '!', '?', '；', ';'])
def test_sentence_final_word_stays_with_negation_and_not_next_sentence(ending):
    cues = grouped([('不要', 0, .4), ('停' + ending, .4, .6), ('继续', 1, .5)])
    assert [c.text for c in cues] == ['不要停' + ending, '继续']
    assert [(c.start, c.end) for c in cues] == [(2, 3), (3, 3.5)]


def test_separate_punctuation_closes_current_sentence():
    cues = grouped([('不要', 0, .4), ('停', .4, .5), ('。', .9, .1), ('继续', 1, .5)])
    assert [c.text for c in cues] == ['不要停。', '继续']


def test_short_sentence_keeps_existing_minimum_group_duration_policy():
    cues = grouped([('好！', 0, .2), ('继续', .2, .3)])
    assert [c.text for c in cues] == ['好！继续']


def test_length_limit_still_splits_before_token_then_recomputes_duration():
    cues = grouped([('前段', 0, 1), ('不要', 1, .3), ('停。', 1.3, .3), ('继续', 1.6, .4)], max_chars=4)
    assert [c.text for c in cues] == ['前段不要', '停。继续']
    assert all(len(c.text) <= 4 for c in cues)


def test_time_limit_still_splits_before_token_then_recomputes_duration():
    cues = grouped([('前段', 0, 3), ('不要停。', 3, .3), ('继续', 3.3, .4)])
    assert [c.text for c in cues] == ['前段', '不要停。继续']
    assert all(c.end - c.start <= 3.2 for c in cues)


def test_final_cue_remains_clamped_to_audio_duration():
    cues = grouped([('不要', 0, .4), ('停。', .4, .6), ('继续', 1, .3)], audio_duration=1.3)
    assert [c.text for c in cues] == ['不要停。', '继续']
    assert cues[-1].end == 3.3
