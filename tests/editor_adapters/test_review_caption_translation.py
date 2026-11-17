import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('translation_review', ROOT/'tools/editor-adapters/review_caption_translation.py')
m = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m)


class Font:
    def __init__(self, size):self.size=size
    def getlength(self, text):return len(text)*self.size
    def getbbox(self, text):return (0,0,len(text)*self.size,self.size)
    def getmetrics(self):return self.size,8


def source():
    return {'rows':[{'id':'one','text':'A source sentence.', 'start_frame':0,'end_frame':24,
                     'declared_start_sec':0,'declared_end_sec':1,'start_delta_sec':0,'end_delta_sec':0},
                    {'id':'two','text':'Next.', 'start_frame':24,'end_frame':72,
                     'declared_start_sec':1,'declared_end_sec':3,'start_delta_sec':0,'end_delta_sec':0}]}


def draft():
    return {'schema':'caption-translation-draft/1','entries':[
        {'id':'one','source_text':'A source sentence.','target_text':'示例译文。','target_language':'zh-CN',
         'context_ids':['two'],'fidelity_notes':['Only a draft.'],'omitted_information':[]}]}


@pytest.fixture(autouse=True)
def font(monkeypatch):
    monkeypatch.setattr(m.ImageFont,'truetype',lambda path,size:Font(size))


def test_comparison_not_adoption_and_short_window_retained():
    s,d=source(),draft();before=copy.deepcopy((s,d))
    result=m.review(s,d,'unused',fps=24,frame_end=72)
    assert (s,d)==before
    assert result['adopted'] is False and 'candidate_rows' not in result
    r=result['reports'][0]
    assert r['source_context']==[s['rows'][1]]
    assert r['source_window']['end_frame']==24
    assert r['target_characters_per_host_second']<r['source_characters_per_host_second']
    assert 'SHORT_DURATION_REVIEW_PROMPT_NOT_FAILURE' in r['warnings']
    assert r['human_readability']==r['semantic_fidelity']==r['audio_alignment']=='UNVERIFIED'
    assert r['spatial_measurement']['font_size_px']>=32


def test_long_target_reports_conflict_not_truncation():
    d=draft();d['entries'][0]['target_text']='长'*100
    r=m.review(source(),d,'unused',fps=24,frame_end=72)['reports'][0]
    assert r['target_text']=='长'*100
    assert r['spatial_measurement']['status']=='GEOMETRY_CONFLICT_AT_MINIMUM_SIZE'
    assert r['spatial_measurement']['lines'] is None
    assert r['semantic_fidelity']=='UNVERIFIED'


@pytest.mark.parametrize('change',['unknown','duplicate','wrong_source','newline','empty','language',
                                    'unknown_context','duplicate_context','approved','root_approved',
                                    'missing','notes_type','omission_type','combining'])
def test_reject_bad_draft(change):
    d=draft();e=d['entries'][0]
    if change=='unknown':e['id']='missing'
    elif change=='duplicate':d['entries'].append(copy.deepcopy(e))
    elif change=='wrong_source':e['source_text']='not exact'
    elif change=='newline':e['target_text']='两\n行'
    elif change=='empty':e['target_text']=' '
    elif change=='language':e['target_language']='en'
    elif change=='unknown_context':e['context_ids']=['missing']
    elif change=='duplicate_context':e['context_ids']=['two','two']
    elif change=='approved':e['approved']=True
    elif change=='root_approved':d['approved']=True
    elif change=='missing':del e['omitted_information']
    elif change=='notes_type':e['fidelity_notes']='not a list'
    elif change=='omission_type':e['omitted_information']=[True]
    else:e['target_text']='Cafe\u0301'
    with pytest.raises(ValueError):m.review(source(),d,'unused',fps=24,frame_end=72)


def test_declared_omission_always_unverified():
    d=draft();d['entries'][0]['omitted_information']=['A qualification may be missing.']
    r=m.review(source(),d,'unused',fps=24,frame_end=72)['reports'][0]
    assert 'DRAFT_DECLARES_OMISSIONS_REQUIRING_SEMANTIC_REVIEW' in r['warnings']
    assert r['semantic_fidelity']=='UNVERIFIED'


@pytest.mark.parametrize('fps,end,minimum',[(0,72,32),(True,72,32),(24,0,32),(24,True,32),(24,72,31)])
def test_invalid_bounds(fps,end,minimum):
    with pytest.raises(ValueError):m.review(source(),draft(),'unused',fps=fps,frame_end=end,minimum=minimum)


def args(tmp_path):
    s=tmp_path/'source.json';d=tmp_path/'draft.json';f=tmp_path/'font'
    s.write_text(json.dumps(source()));d.write_text(json.dumps(draft()));f.write_bytes(b'fake font')
    return SimpleNamespace(source_map=s,draft=d,font=f,source_sha256=m.contract.digest(s),
                           draft_sha256=m.contract.digest(d),font_sha256=m.contract.digest(f),
                           fps=24,frame_end=72,minimum_size=32,maximum_size=40,output=tmp_path/'review.json')


def test_build_exclusive_pinned(tmp_path):
    a=args(tmp_path);m.build(a)
    result=json.loads(a.output.read_text());assert result['draft_sha256']==a.draft_sha256
    assert result['font']['sha256']==a.font_sha256
    with pytest.raises(FileExistsError):m.build(a)


@pytest.mark.parametrize('field',['source_sha256','draft_sha256','font_sha256'])
def test_stale_input_rejected(tmp_path,field):
    a=args(tmp_path);setattr(a,field,'0'*64)
    with pytest.raises(ValueError,match='STALE_INPUT'):m.build(a)
    assert not a.output.exists()


def test_duplicate_json_keys_rejected(tmp_path):
    a=args(tmp_path);a.draft.write_text('{"schema":1,"schema":2}')
    a.draft_sha256=m.contract.digest(a.draft)
    with pytest.raises(ValueError,match='DUPLICATE_JSON_KEY'):m.build(a)
    assert not a.output.exists()


@pytest.mark.parametrize('separator', ['\u2028', '\u2029'])
def test_unicode_line_and_paragraph_separator_rejected(separator):
    d=draft();d['entries'][0]['target_text']='前'+separator+'后'
    with pytest.raises(ValueError,match='TARGET_MUST_BE_SINGLE_PARAGRAPH'):
        m.review(source(),d,'unused',fps=24,frame_end=72)


@pytest.mark.parametrize('target', ['source_map', 'draft'])
def test_report_never_attributes_reopened_json_to_pinned_bytes(tmp_path, monkeypatch, target):
    a = args(tmp_path)
    path = getattr(a, target)
    frozen = path.read_bytes()
    changed = json.loads(frozen)
    if target == 'source_map':
        changed['rows'][1]['text'] = 'Unpinned context replacement.'
    else:
        changed['entries'][0]['target_text'] = 'Unpinned translation replacement.'
    real_read_text = Path.read_text

    def replacing_read(self, *pos, **kw):
        if self == path:
            self.write_text(json.dumps(changed))
            try:
                return real_read_text(self, *pos, **kw)
            finally:
                self.write_bytes(frozen)
        return real_read_text(self, *pos, **kw)

    monkeypatch.setattr(Path, 'read_text', replacing_read)
    m.build(a)
    result = json.loads(real_read_text(a.output))
    assert path.read_bytes() == frozen
    assert result['draft_sha256'] == a.draft_sha256
    assert result['source_map_sha256'] == a.source_sha256
    row = result['reports'][0]
    assert row['target_text'] == draft()['entries'][0]['target_text']
    assert row['source_context'][0]['text'] == source()['rows'][1]['text']


@pytest.mark.parametrize('target', ['source_map', 'draft'])
def test_persistent_json_change_during_analysis_rejected(tmp_path, monkeypatch, target):
    a = args(tmp_path)
    original_review = m.review

    def changing_review(*pos, **kw):
        result = original_review(*pos, **kw)
        getattr(a, target).write_text('{}')
        return result

    monkeypatch.setattr(m, 'review', changing_review)
    with pytest.raises(ValueError, match='INPUT_CHANGED_DURING_READ'):
        m.build(a)
    assert not a.output.exists()


@pytest.mark.parametrize('target', ['source_map', 'draft'])
def test_json_size_limit_checked_on_consumed_bytes(tmp_path, monkeypatch, target):
    a = args(tmp_path)
    path = getattr(a, target)
    path.write_bytes(b' ' * 10_000_001)
    setattr(a, 'source_sha256' if target == 'source_map' else 'draft_sha256', m.contract.digest(path))
    with pytest.raises(ValueError, match='JSON_SIZE_LIMIT'):
        m.build(a)
    assert not a.output.exists()
