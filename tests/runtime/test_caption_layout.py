"""Static libass glyph coverage, never automatic scene/UI understanding."""
import copy
from pathlib import Path
import shutil
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import caption_layout
import editing_runtime as runtime
import style_recipe_ops
from test_style_recipe import case  # noqa: F401,E402
from test_source_binding import tools, media, plan  # noqa: F401,E402


@pytest.fixture
def layout_case(tmp_path, tools, media):
    font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if not font.is_file():
        candidates = list(Path('/usr/share/fonts').rglob('DejaVuSans.ttf'))
        assert candidates, 'Install the project font dependency; cannot skip mask validation'
        font = candidates[0]
    document = {'schema': 'work-document/1', 'plan': plan(media['red']),
        'captions': {'c': {'clip_id': 'one', 'start': 0, 'end': .4, 'text': 'SAFE'}},
        'caption_style': {'font': {'path': str(font), 'sha256': runtime.sha256(font)},
            'font_family': 'DejaVu Sans', 'font_size': 8, 'margin_v': 4, 'color_rgb': 'FFFFFF'},
        'audio_tracks': {}, 'style_bindings': {}, 'notes': {}}
    constraints = {'schema': 'caption-layout/1', 'canvas': {'width': 64, 'height': 64},
        'subtitle_band': {'x': 0, 'y': 35, 'width': 64, 'height': 29},
        'protected_regions': [{'id': 'explicit-ui', 'rect': {'x': 0, 'y': 0, 'width': 64, 'height': 30}}]}
    return document, constraints, tmp_path, tools


def test_actual_alpha_mask_respects_band_and_does_not_have_opaque_background(layout_case):
    document, constraints, folder, tools = layout_case
    result = caption_layout.check(document, constraints, folder/'layout', tools)
    assert result['status'] == 'STATIC_GLYPH_COVERAGE_VERIFIED'
    assert result['aesthetic_readability'] == 'NOT_VERIFIED'
    bounds = result['observations'][0]['bbox']
    assert bounds[0] > 0 and bounds[2] < 64 and bounds[1] > 35 and bounds[3] < 64
    assert document['captions']['c']['text'] == 'SAFE'


def test_declared_band_cannot_fake_renderer_placement(layout_case):
    document, constraints, folder, tools = layout_case
    constraints['subtitle_band'] = {'x': 0, 'y': 0, 'width': 64, 'height': 25}
    constraints['protected_regions'][0]['rect'] = {'x': 0, 'y': 35, 'width': 64, 'height': 29}
    with pytest.raises(ValueError, match='LAYOUT_GLYPHS_OUTSIDE_DECLARED_BAND'):
        caption_layout.check(document, constraints, folder/'layout', tools)
    assert not (folder/'layout/layout-report.json').exists()


def test_clipped_glyphs_are_detected_on_padded_canvas(layout_case):
    document, constraints, folder, tools = layout_case
    document['caption_style']['font_size'] = 28
    document['caption_style']['margin_v'] = 55
    with pytest.raises(ValueError, match='LAYOUT_GLYPHS_CLIPPED|LAYOUT_PADDING_EQUIVALENCE_UNVERIFIED'):
        caption_layout.check(document, constraints, folder/'layout', tools)


@pytest.mark.parametrize('kind,error', [('overlap','LAYOUT_DECLARED_BAND_OVERLAP'),
    ('canvas','LAYOUT_CANVAS_MISMATCH'), ('outside','LAYOUT_RECT_OUTSIDE_CANVAS'),
    ('duplicate','LAYOUT_REGION_ID_DUPLICATE_OR_EMPTY')])
def test_bad_constraints_fail_closed(layout_case,kind,error):
    document, constraints, folder, tools = layout_case
    if kind == 'overlap': constraints['protected_regions'][0]['rect']['height'] = 50
    elif kind == 'canvas': constraints['canvas']['width'] = 128
    elif kind == 'outside': constraints['subtitle_band']['width'] = 65
    else: constraints['protected_regions'] *= 2
    with pytest.raises(ValueError, match=error):
        caption_layout.check(document, constraints, folder/'layout', tools)


def test_unconstrained_existing_recipe_has_unknown_layout(case):
    request, output, work, _ = case
    result = style_recipe_ops.execute(request, output, work['tools'])
    assert result['caption_layout']['status'] == 'UNKNOWN'
    assert not (output/'layout').exists()


@pytest.mark.parametrize('text,size', [('SAFE', 8), ('21 > 20', 10), ('WiFi', 12)])
def test_three_masks_agree_with_real_caption_burn_layout(layout_case, text, size):
    import subprocess
    from PIL import Image
    document, constraints, folder, tools = layout_case
    document['captions']['c']['text'] = text
    document['caption_style']['font_size'] = size
    # A larger declared subtitle band still excludes explicitly protected top UI.
    constraints['subtitle_band']['y'] = 20
    constraints['subtitle_band']['height'] = 44
    constraints['protected_regions'][0]['rect']['height'] = 15
    result = caption_layout.check(document, constraints, folder/'layout', tools)
    render = folder/'render'; render.mkdir()
    source_ref = document['plan']['sources']['main']
    runtime.caption_burn({'operation': 'caption-burn', 'source': source_ref,
        **document['caption_style'], 'cues': [{'start': 0, 'end': .4, 'text': text}]}, render, tools)
    actual_ass = (render/'captions.ass').read_text()
    mask_ass = (folder/'layout/ cue-0000/original.ass'.replace(' ', '')).read_text()
    assert actual_ass.replace('0:00:00.40', '0:00:01.00') == mask_ass
    raw = subprocess.run([tools.ffmpeg, '-v', 'error', '-i', str(render/'captioned.mp4'),
        '-frames:v','1','-f','rawvideo','-pix_fmt','rgb24','-'], check=True, stdout=subprocess.PIPE).stdout
    image = Image.frombytes('RGB',(64,64),raw)
    # White glyph cores on a real encoded red background remain within the
    # actual alpha footprint (allowing 2px encoding halo in reported bound).
    pixels = list(image.getdata())
    points = [(i%64,i//64) for i,(r,g,b) in enumerate(pixels) if min(r,g,b)>190]
    assert points
    left,top,right,bottom = result['observations'][0]['padded_bbox']
    assert all(left<=x<right and top<=y<bottom for x,y in points)


def test_layout_constraints_bind_candidate_and_scope(layout_case):
    document, constraints, folder, tools = layout_case
    card=folder/'card.md';card.write_text('test authored unvalidated style')
    recipe={'schema':'style-recipe/1','id':'safe','version':'1','style':{'family':'test',
        'style_id':'test','version':'1','card':{'path':str(card),'sha256':runtime.sha256(card)}},
        'parameters':{'caption_style':{'font_size':8}},'layout_constraints':constraints}
    scope={'clip_ids':[],'source_ids':[],'caption_ids':[],'audio_ids':[],'style_keys':['*'],
        'note_keys':[],'output_fields':[],'caption_style':True,'freeze_positions':['one'],'freeze_duration':True}
    request={'operation':'style-recipe-compile','document':document,'expected_document_sha256':runtime.fingerprint(document),
        'base_version':'0'*64,'recipe':recipe,'expected_recipe_sha256':runtime.fingerprint(recipe),
        'scope':scope,'capabilities':['caption-style']}
    output=folder/'compile';output.mkdir()
    result=style_recipe_ops.execute(request,output,tools)
    import json
    candidate=json.loads((output/'candidate.json').read_text())['document']
    assert candidate['style_bindings']['*']['parameters']['layout_constraints']==constraints
    assert result['caption_layout']['document_sha256']==runtime.fingerprint(candidate)
    assert candidate['plan']==document['plan'] and candidate['captions']==document['captions']


def test_pixel_budget_rejects_large_project_before_mask_render(layout_case, monkeypatch):
    document, constraints, folder, tools = layout_case
    document['plan'].update(width=1920,height=1920)
    document['captions']={f'c{i}':{'clip_id':'one','start':i*.001,'end':(i+1)*.001,'text':'x'} for i in range(100)}
    constraints['canvas']={'width':1920,'height':1920}
    monkeypatch.setattr(tools,'ff',lambda *a,**k:pytest.fail('must reject before mask render'))
    with pytest.raises(ValueError,match='LAYOUT_PIXEL_BUDGET_EXCEEDED'):
        caption_layout.check(document,constraints,folder/'layout',tools)


def test_dynamic_ass_overrides_cannot_enter_mask(layout_case):
    document,constraints,folder,tools=layout_case
    document['captions']['c']['text']=r'{\move(0,0,100,100)}test'
    with pytest.raises(ValueError,match='ASS_CONTROL_CHARACTERS_UNSUPPORTED'):
        caption_layout.check(document,constraints,folder/'layout',tools)
    assert not (folder/'layout/layout-report.json').exists()


def test_masks_preserve_lossless_evidence_without_raw_files_or_repeated_font_copies(layout_case):
    document,constraints,folder,tools=layout_case
    caption_layout.check(document,constraints,folder/'layout',tools)
    assert len(list((folder/'layout').rglob('*.png')))==2
    assert not list((folder/'layout').rglob('*.rgba'))
    assert len(list((folder/'layout').rglob('*.ttf')))==1


def test_distant_lines_cannot_escape_finite_padding_observation(layout_case):
    document,constraints,folder,tools=layout_case
    document['captions']['c']['text']='CLIPPED'+ '\n'*100 + 'SAFE'
    with pytest.raises(ValueError,match='LAYOUT_EXPLICIT_SPACING_UNSUPPORTED'):
        caption_layout.check(document,constraints,folder/'layout',tools)
