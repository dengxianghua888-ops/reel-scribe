import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('reading_time', ROOT/'tools/editor-adapters/analyze_caption_reading_time.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


def layout(windows=None):
    windows = windows or [('a', 'Hello world', 0, 24), ('b', '第二条', 60, 120)]
    rows, measurements = [], []
    for identity, text, start, end in windows:
        row = {'id':identity, 'text':text, 'start_frame':start, 'end_frame':end,
               'declared_start_sec':start/24, 'declared_end_sec':end/24,
               'start_delta_sec':0, 'end_delta_sec':0}
        rows.append(row)
        chars, words = m.counts(text)
        duration = (end-start)/24
        measurements.append({'row':copy.deepcopy(row), 'characters_per_host_second':chars/duration,
                             'english_words_per_minute':words/duration*60,
                             'host_duration_sec':duration,
                             'diagnostic_thresholds_not_acceptance':dict(m.THRESHOLDS),
                             'reading_review_required':duration<2 or chars/duration>20 or words/duration*60>240})
    return {'schema':'caption-readability-plan/1', 'status':'REVIEW_CANDIDATE_ONLY', 'adopted':False,
            'fps':24, 'frame_end':120, 'font_size_px':36, 'minimum_font_size_px':32,
            'font':{'path':'/fixed/font', 'sha256':'a'*64, 'face_index':0},
            'source_map_sha256':'b'*64, 'source_rows':copy.deepcopy(rows),
            'candidate_rows':rows, 'measurements':measurements}


def test_tail_option_only_and_input_unchanged():
    data=layout();before=copy.deepcopy(data)
    result=m.analyze(data)
    assert data==before
    assert result['adopted'] is False and result['sync_status']=='UNVERIFIED'
    assert 'candidate_rows' not in result
    option=result['review_options'][0]
    assert option['proposed_window']=={'start_frame':0,'end_frame':48}
    assert option['tail_lag_frames']==24
    assert option['available_tail_frames']==36
    assert result['within_diagnostic_limits_ids']==['b']


def test_collision_has_no_time_proposal():
    data=layout([('a','text',0,24),('b','第二条',29,120)])
    conflict=m.analyze(data)['conflicts'][0]
    assert conflict['proposed_window'] is None
    assert conflict['required_tail_extension_frames']==24
    assert conflict['available_tail_frames']==5
    assert conflict['shortfall_frames']==19


def test_scene_boundary_not_extended():
    data=layout([('a','text',96,120)])
    conflict=m.analyze(data)['conflicts'][0]
    assert conflict['boundary_kind']=='scene_end'
    assert conflict['shortfall_frames']==24
    assert conflict['proposed_window'] is None


def test_integer_ceil_not_float_round():
    assert m.ceil_ratio(13*60*24,240)==78
    assert m.ceil_ratio(37*24,20)==45
    assert m.ceil_ratio(20*24,20)==24


@pytest.mark.parametrize('change', ['font','fps','source_time','duplicate_id','nonspace','measurement','threshold','flag','missing','english_word_merge'])
def test_reject_stale_or_inconsistent_layout(change):
    data=layout()
    if change=='font':del data['font']
    elif change=='fps':data['fps']=False
    elif change=='source_time':data['source_rows'][0]['declared_end_sec']=2
    elif change=='duplicate_id':data['candidate_rows'][1]['id']='a'
    elif change=='nonspace':data['candidate_rows'][0]['text']='changed'
    elif change=='measurement':data['measurements'][0]['english_words_per_minute']=0
    elif change=='threshold':data['measurements'][0]['diagnostic_thresholds_not_acceptance']['short_cue_sec']=1
    elif change=='flag':data['measurements'][0]['reading_review_required']=False
    elif change=='missing':del data['candidate_rows'][0]['start_delta_sec']
    else:data['candidate_rows'][0]['text']='Helloworld'
    with pytest.raises((ValueError,KeyError,TypeError)):
        m.analyze(data)


def test_build_pinned_and_exclusive(tmp_path):
    source=tmp_path/'layout.json';source.write_text(json.dumps(layout()))
    output=tmp_path/'review.json'
    args=SimpleNamespace(layout=source,layout_sha256=m.contract.digest(source),output=output)
    m.build(args)
    assert json.loads(output.read_text())['layout_sha256']==args.layout_sha256
    with pytest.raises(FileExistsError):m.build(args)


def test_duplicate_json_and_stale_hash_no_output(tmp_path):
    source=tmp_path/'layout.json';source.write_text('{"fps":24,"fps":24}')
    output=tmp_path/'review.json'
    args=SimpleNamespace(layout=source,layout_sha256=m.contract.digest(source),output=output)
    with pytest.raises(ValueError,match='DUPLICATE_JSON_KEY'):m.build(args)
    assert not output.exists()
    args.layout_sha256='0'*64
    with pytest.raises(ValueError,match='STALE_LAYOUT'):m.build(args)
    assert not output.exists()
