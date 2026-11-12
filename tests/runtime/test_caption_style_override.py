"""Cue-local presentation with shared ASS/mask semantics; no content edit authority."""
import copy,json,sys
from pathlib import Path
import pytest
sys.path[:0]=[str(Path(__file__).resolve().parents[2]/'runtime'),str(Path(__file__).resolve().parent)]
import editing_runtime as rt
import work_ops
import caption_style
import caption_layout
from test_result_preview import case as work_case
from test_caption_layout import layout_case
from test_source_binding import media,tools

@pytest.mark.parametrize('override',[{},None,{'font':'x'},{'text':'x'},{'font_size':True},{'font_size':12.5},{'font_size':7},{'font_size':65},{'margin_v':True},{'margin_v':64},{'margin_v':-1},{'color_rgb':'<red>'}])
def test_strict_override(override):
    with pytest.raises(rt.ContractError):caption_style.validate_override(override,64)

def test_effective_copy_and_font_frozen():
    base={'font':{'path':'font','sha256':'x'},'font_family':'Example','font_size':12,'margin_v':4,'color_rgb':'FFFFFF'}
    original=copy.deepcopy(base);value=caption_style.effective_style(base,{'font_size':16,'color_rgb':'ff00aa'},64)
    assert base==original and value['font']==base['font'] and value['font_size']==16
    value['font']['path']='other';assert base==original

def request():return {'font_family':'Example','font_size':12,'margin_v':4,'color_rgb':'FFFFFF','cues':[{'start':0,'end':.5,'text':'One'},{'start':.5,'end':1,'text':'Two'}]}

def test_legacy_ass_exact_bytes():
    expected='[Script Info]\nScriptType: v4.00+\nPlayResX: 64\nPlayResY: 64\nWrapStyle: 0\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,Example,12.0,&H00FFFFFF,&H00000000,1,1,0,2,20,20,4.0,1\n[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:00.00,0:00:00.50,Default,One\nDialogue: 0,0:00:00.50,0:00:01.00,Default,Two\n'
    assert rt.caption_ass(request(),64,64,1)==expected

def test_static_local_style_only_selected_cue():
    q=request();q['cues'][0]['style_override']={'font_size':16,'margin_v':8,'color_rgb':'FF0000'};before=copy.deepcopy(q)
    ass=rt.caption_ass(q,64,64,1)
    assert 'Style: Cue0000,Example,16.0,&H000000FF' in ass
    assert '0:00:00.50,Cue0000,One' in ass and '0:00:01.00,Default,Two' in ass
    assert '{' not in ass and q==before and ass==rt.caption_ass(q,64,64,1)

def test_work_preserves_override_digest_and_scope(work_case):
    _,_,t,doc=work_case;doc=copy.deepcopy(doc);doc['captions']={'c':{'clip_id':'full','start':0,'end':1,'text':'One'}}
    before=copy.deepcopy(doc);doc['captions']['c']['style_override']={'color_rgb':'AAFF00'}
    _,cues,_=work_ops.validate_document(doc,t)
    assert cues[0]['style_override']=={'color_rgb':'AAFF00'}
    assert cues[0]['effective_style_sha256']==rt.fingerprint({**doc['caption_style'],'color_rgb':'AAFF00'})
    scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],'style_keys':[],'note_keys':[],'output_fields':[],'caption_style':False,'freeze_positions':['full'],'freeze_duration':True}
    with pytest.raises(rt.ContractError):work_ops.revision_diff(before,doc,scope,t)
    scope['caption_ids']=['c'];diff=work_ops.revision_diff(before,doc,scope,t)
    assert diff['captions']==['c'] and not diff['caption_style_changed']
    assert doc['captions']['c']['text']==before['captions']['c']['text']

def test_no_override_work_cues_remain_unchanged_shape(work_case):
    _,_,t,doc=work_case;doc=copy.deepcopy(doc);doc['captions']={'c':{'clip_id':'full','start':0,'end':1,'text':'One'}}
    assert work_ops.validate_document(doc,t)[1]==[{'id':'c','start':0.0,'end':1.0,'text':'One'}]

def test_mask_and_burn_share_local_static_styles(layout_case):
    doc,constraints,folder,t=layout_case;doc['captions']['c']['text']='Hi';doc['captions']['c']['style_override']={'font_size':12,'color_rgb':'FFAA00','margin_v':5}
    r=caption_layout.check(doc,constraints,folder/'mask',t)
    assert r['observations'][0]['style_override']==doc['captions']['c']['style_override']
    normalized=work_ops.validate_document(doc,t)[1][0]
    assert r['observations'][0]['effective_style_sha256']==normalized['effective_style_sha256']
    ass=Path(r['observations'][0]['ass']['path']).read_text()
    direct=rt.caption_ass({**doc['caption_style'],'cues':[{'start':0,'end':1,'text':'Hi','style_override':doc['captions']['c']['style_override']}]},64,64,1)
    assert ass==direct

def test_override_cannot_hide_unsafe_layout(layout_case):
    doc,constraints,folder,t=layout_case;doc['captions']['c']['style_override']={'margin_v':35}
    with pytest.raises(rt.ContractError,match='LAYOUT_'):caption_layout.check(doc,constraints,folder/'unsafe',t)
    assert not (folder/'unsafe/layout-report.json').exists()

def test_actual_work_render_outputs_override_summary(layout_case):
    doc,_,folder,t=layout_case;doc['captions']['c']['text']='Hi';doc['captions']['c']['style_override']={'font_size':12}
    out=folder/'render';out.mkdir()
    result=work_ops.render_document(doc,out,t,work_version='isolated-test')
    report=json.loads((out/'output-captions.json').read_text())
    assert report['cues'][0]['style_override']=={'font_size':12}
    assert report['cues'][0]['effective_style_sha256']==rt.fingerprint({**doc['caption_style'],'font_size':12})
    assert Path(result['video']['path']).is_file()
    assert 'Cue0000' in (out/'captions/captions.ass').read_text()

def test_source_mapping_preserves_each_split_override(work_case):
    _,out,t,doc=work_case;plan=copy.deepcopy(doc['plan']);plan['clips'][0]['end']=.5
    plan['clips'].append({'id':'second','source_id':'s','start':.5,'end':1,'gain_db':0})
    q={'operation':'caption-map','plan':plan,'boundary_policy':'clip','cues':[{'id':'cue','source_id':'s','start':.2,'end':.8,'text':'Do not change','style_override':{'font_size':16}}]}
    r=rt.map_captions(q,out,t);mapped=json.loads((out/'captions.json').read_text())['cues']
    assert len(mapped)==2 and all(c['style_override']=={'font_size':16} for c in mapped)
    assert [(c['start'],c['end']) for c in mapped]==[(.2,.48),(.48,.78)]  # Existing25fps frame rounding, not a new style transform.
    assert all(c['partial'] and c['text']=='Do not change' for c in mapped)
    assert 'SRT cannot represent' in r['local_presentation']
    assert 'style_override' not in (out/'captions.srt').read_text()

def test_black_override_still_has_actual_alpha_glyphs(layout_case):
    doc,constraints,folder,t=layout_case;doc['captions']['c']['style_override']={'color_rgb':'000000'}
    r=caption_layout.check(doc,constraints,folder/'black',t)
    assert r['status']=='STATIC_GLYPH_COVERAGE_VERIFIED'
    assert r['style_resolver_sha256']==rt.sha256(Path(caption_style.__file__))
