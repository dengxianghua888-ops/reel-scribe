"""Presentation-only breaks; real libass masks, not human readability acceptance."""
import copy
import hashlib
import json
import pytest
from test_style_recipe import case  # noqa: F401
from test_cue_style_recipe import local, sync
from test_caption_layout import layout_case, tools, media  # noqa: F401
import caption_style
import caption_layout
import editing_runtime as rt
import style_recipe_ops


def breaks(text, offsets):
    return {'text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest(),'offsets':offsets}


def test_materializes_only_presentation():
    text='这是 OpenAI 3.14kg 原文'
    value={'line_breaks':breaks(text,[3,10])}
    assert caption_style.presentation_text(text,value)=='这是 \nOpenAI \n3.14kg 原文'
    assert caption_style.presentation_text(text,{'line_breaks':breaks(text,[])})==text


@pytest.mark.parametrize('text,offsets,error',[
    ('OpenAI',[3],'TOKEN_SPLIT'),('3.14kg',[2],'TOKEN_SPLIT'),
    ('你好。',[2],'PUNCTUATION'),('（你好',[1],'PUNCTUATION'),
    ('a\u0301b',[1],'UNSAFE'),('👩\u200d💻',[1],'UNSAFE'),
    ('👍🏽好',[1],'UNSAFE'),('你好',[0],'OFFSETS'),
    ('你好',[True],'OFFSETS'),('你好',[2],'OFFSETS'),
    ('你好世界',[2,1],'OFFSETS'),('你好世界',[1,1],'OFFSETS'),
])
def test_unsafe_breaks_rejected(text,offsets,error):
    with pytest.raises(ValueError,match=error):caption_style.validate_override({'line_breaks':breaks(text,offsets)},100,text)


def test_stale_text_refused():
    with pytest.raises(ValueError,match='TEXT_CHANGED'):
        caption_style.presentation_text('新原文',{'line_breaks':breaks('旧原文',[1])})


def test_recipe_preserves_text_time_and_scope(case):
    q,out,tools=local(case);before=copy.deepcopy(q['document'])
    q['recipe']['parameters']['caption_overrides']['cue']={'line_breaks':breaks(before['captions']['cue']['text'],[1])};sync(q)
    style_recipe_ops.execute(q,out,tools)
    candidate=json.loads((out/'candidate.json').read_text())['document']
    assert {k:v for k,v in candidate['captions']['cue'].items() if k!='style_override'}==before['captions']['cue']
    assert candidate['captions']['untargeted']==before['captions']['untargeted']
    assert candidate['plan']==before['plan']


def test_recipe_rejects_stale_breaks(case):
    q,out,tools=local(case)
    q['recipe']['parameters']['caption_overrides']['cue']={'line_breaks':breaks('旧文本',[1])};sync(q)
    with pytest.raises(ValueError,match='TEXT_CHANGED'):style_recipe_ops.execute(q,out,tools)
    assert not (out/'candidate.json').exists()


def test_global_style_does_not_gain_break_authority(case):
    q,out,work,_=case
    q['recipe']['parameters']={'caption_style':{'line_breaks':breaks('你好',[1])}};sync(q)
    with pytest.raises(ValueError,match='UNKNOWN_FIELDS'):style_recipe_ops.execute(q,out,work['tools'])


def test_actual_libass_layout_uses_breaks_without_changing_text(layout_case):
    doc,constraints,folder,tools=layout_case
    text='A B';doc['captions']['c']['text']=text
    doc['captions']['c']['style_override']={'line_breaks':breaks(text,[2])}
    result=caption_layout.check(doc,constraints,folder/'breaks',tools)
    ass=(folder/'breaks/ cue-0000/original.ass'.replace(' ','')).read_text()
    assert r'A \NB' in ass
    assert result['status']=='STATIC_GLYPH_COVERAGE_VERIFIED'
    assert doc['captions']['c']['text']==text


def test_measured_adapter_real_preview_explicit_commit_and_undo(layout_case):
    import sys
    from pathlib import Path
    import style_preview_ops
    import work_ops
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'workflows/raven-film-recap/douyin-film-recap/src'))
    from douyin_film_recap.subtitle_layout import prepare_work_preview
    doc,constraints,folder,tools=layout_case
    doc['captions']['c']['text']='A B C'
    doc['plan']['clips'][0]['mute']=True
    card=folder/'card.md';card.write_text('Synthetic linebreak comparison, no human acceptance')
    recipe={'schema':'style-recipe/1','id':'breaks','version':'1','style':{'family':'synthetic','style_id':'breaks','version':'1','card':{'path':str(card),'sha256':rt.sha256(card)}},
            'parameters':{},'layout_constraints':constraints}
    store=str(folder/'work.sqlite');init=folder/'init';init.mkdir()
    state=work_ops.work_version({'operation':'work-version','action':'init','store':store,'work_id':'breaks','document':doc,'author':'agent','message':'fixture'},init,tools)
    prep=prepare_work_preview(doc,expected_document_sha256=rt.fingerprint(doc),store=store,expected_version=state['version'],recipe=recipe,caption_ids=['c'],max_chars=3)
    request=prep['preview_request'];request['source_consumption']={'schema':'source-consumption/1','mode':'snapshot'}
    preview=folder/'preview';preview.mkdir();result=style_preview_ops.execute(request,preview,tools)
    assert style_preview_ops.state(store)['version']==state['version']
    assert result['status']=='PREVIEWS_RENDERED_NOT_COMMITTED'
    assert result['variants'][0]['video']['sha256']!=result['variants'][1]['video']['sha256']
    selected=next(v for v in result['variants'] if v['id']=='measured')
    commit=folder/'commit';commit.mkdir()
    adopted=work_ops.work_version({'operation':'work-version','action':'commit','store':store,'expected_version':state['version'],'candidate':selected['candidate'],'author':'human','message':'explicit synthetic test selection'},commit,tools)
    assert adopted['document']['captions']['c']['text']=='A B C'
    assert adopted['document']['captions']['c']['style_override']['line_breaks']['offsets']
    assert adopted['document']['plan']==doc['plan']
    with pytest.raises(ValueError,match='WORK_VERSION_CONFLICT'):
        style_preview_ops.execute(request,folder/'stale',tools)
    variant=request['variants'][1];undo=folder/'undo';undo.mkdir()
    # Keep the empty-break presentation explicit in a derived recipe when undoing.
    report=work_ops.work_version({'operation':'work-version','action':'prepare-local-undo','store':store,
        'expected_version':adopted['version'],'undo_sequence':2,'fields':[{'kind':'caption_override','id':'c','field':'line_breaks'}],
        'scope':variant['scope'],'binding_resolution':{'recipe':variant['recipe'],'expected_recipe_sha256':variant['expected_recipe_sha256'],
        'derived_recipe_id':'breaks-undo','derived_recipe_version':'1','detach_empty_binding':True}},undo,tools)
    assert report['status']=='CANDIDATE_PREPARED'
    undone=json.loads((undo/'candidate.json').read_text())['document']
    assert undone['captions']==doc['captions']
    assert undone['style_bindings']=={}
    assert report['binding_resolution']['policy']=='EXPLICIT_EMPTY_BINDING_DETACHED'
    assert style_preview_ops.state(store)['version']==adopted['version']
    undo_commit=folder/'undo-commit';undo_commit.mkdir()
    restored=work_ops.work_version({'operation':'work-version','action':'commit','store':store,'expected_version':adopted['version'],
        'candidate':{'path':str(undo/'candidate.json'),'sha256':rt.sha256(undo/'candidate.json')},'author':'human','message':'explicit synthetic undo'},undo_commit,tools)
    assert restored['document']['captions']==doc['captions'] and restored['document']['style_bindings']=={}
    assert restored['document']['plan']==doc['plan']


@pytest.mark.parametrize('log,error',[
    ('Using font provider fontconfig\n','SELECTION_UNVERIFIED'),
    ('fontselect: (Test, 400, 0) -> Test, 0, Test\n','PROVIDER_UNVERIFIED'),
    ('Using font provider fontconfig\nfontselect: (Test, 400, 0) -> Other, 0, Other\n','FALLBACK_REFUSED'),
    ('Using font provider fontconfig\nfontselect: (Test, 400, 0) -> Test, 1, Test\n','FALLBACK_REFUSED'),
    ('Using font provider fontconfig\nfontselect: (Test, 400, 0) -> Test, 0, Test\nGlyph 0x123 not found, selecting one more font\n','FALLBACK_REFUSED'),
])
def test_font_selection_fail_closed(tmp_path,log,error):
    import caption_font_binding
    font=tmp_path/'font.ttf';font.write_bytes(b'parser fixture, not a font')
    binding={'font_path':str(font),'font_sha256':rt.sha256(font),'names':{'Test'},'directory':tmp_path}
    with pytest.raises(ValueError,match=error):caption_font_binding.verify(log,binding,'rejected')
    assert (tmp_path/'rejected.log').read_text()==log


def test_curly_apostrophe_token_not_split():
    with pytest.raises(ValueError,match='TOKEN_SPLIT'):
        caption_style.validate_override({'line_breaks':breaks('can’t',[4])},100,'can’t')
