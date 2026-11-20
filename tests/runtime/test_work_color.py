"""WorkDocument color section: validation, revision scope and real render placement.

Synthetic BT.709 media with known pixel values; proves arithmetic, scope and
ordering, not whether any grade looks good.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
np = pytest.importorskip('numpy')
pytest.importorskip('PIL')
import color_media as cm  # noqa: E402
import editing_runtime as rt  # noqa: E402
import work_ops  # noqa: E402

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')
BT709 = {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'}
UP = {'interpretation': 'bt709-sdr-display', 'ops': [{'type': 'exposure', 'stops': 1}], 'lut_size': 33}


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def scope(**changes):
    value = {'clip_ids': [], 'source_ids': [], 'caption_ids': [], 'audio_ids': [], 'style_keys': [], 'note_keys': [],
             'output_fields': [], 'caption_style': False, 'freeze_positions': [], 'freeze_duration': False}
    value.update(changes)
    return value


@pytest.fixture
def work(tmp_path):
    gray = cm.encode_sdr(cm.image(tmp_path / 'gray.png', [((100, 100, 100), 1)]), tmp_path / 'gray.mp4', seconds=1)
    green = cm.encode_sdr(cm.image(tmp_path / 'green.png', [((30, 180, 40), 1)]), tmp_path / 'green.mp4', seconds=1,
                          pix_fmt='yuv420p')  # visual layers require 8-bit 4:2:0 sources
    untagged = cm.encode_sdr(cm.image(tmp_path / 'u.png', [((100, 100, 100), 1)]), tmp_path / 'untagged.mp4',
                             seconds=1, tags=False)
    doc = {'schema': 'work-document/1',
           'plan': {'schema': 'execution-plan/1', 'fps': '25', 'width': 96, 'height': 64, 'fit': 'contain',
                    'sources': {'gray': ref(gray), 'untagged': ref(untagged)},
                    'clips': [{'id': 'a', 'source_id': 'gray', 'start': 0, 'end': 1, 'gain_db': 0},
                              {'id': 'b', 'source_id': 'gray', 'start': 0, 'end': 1, 'gain_db': 0}],
                    'allow_source_reuse': True},
           'captions': {}, 'caption_style': None, 'audio_tracks': {}, 'style_bindings': {}, 'notes': {}}
    return {'root': tmp_path, 'doc': doc, 'green': green, 'tools': rt.Tools()}


def with_color(doc, grades=None, inputs=None, order=None):
    doc = copy.deepcopy(doc)
    grades = copy.deepcopy(grades if grades is not None else {'up': {**UP, 'targets': ['b']}})
    doc['color'] = {'schema': 'work-color/1', 'inputs': copy.deepcopy(inputs if inputs is not None else {'gray': BT709}),
                    'grades': grades, 'order': order if order is not None else sorted(grades)}
    return doc


@pytest.mark.parametrize('change,error', [
    (lambda c: c['inputs'].update(missing=BT709), 'WORK_COLOR_INPUT_UNKNOWN_SOURCE'),
    (lambda c: c['grades']['up'].update(targets=['nope']), 'WORK_COLOR_TARGET_MISSING'),
    (lambda c: c['grades']['up'].update(targets=[]), 'WORK_COLOR_TARGETS_INVALID'),
    (lambda c: c['grades']['up'].update(interpretation='srgb-sdr-display'), 'WORK_COLOR_INTERPRETATION_MISMATCH'),
    (lambda c: c['inputs'].clear(), 'WORK_COLOR_INPUT_DECLARATION_REQUIRED'),
    (lambda c: c.update(order=[]), 'WORK_COLOR_ORDER_MUST_LIST_EVERY_GRADE_ONCE'),
    (lambda c: c['inputs'].update(untagged=BT709), 'WORK_COLOR_METADATA_REQUIRED: untagged'),
    (lambda c: c['inputs'].update(gray={**BT709, 'space': 'srgb-sdr', 'basis': 'caller-declared'}),
     'WORK_COLOR_METADATA_CONFLICT: gray.color_transfer'),
    (lambda c: c['grades']['up'].update(lut_size=20), 'COLOR_GRADE_LUT_SIZE_UNSUPPORTED'),
    (lambda c: c['grades']['up']['ops'].append({'type': 'exposure', 'stops': 9}), 'COLOR_GRADE_VALUE_OUT_OF_RANGE'),
    (lambda c: c.update(schema='work-color/2'), 'WORK_COLOR_SCHEMA_UNSUPPORTED'),
])
def test_color_section_validation(work, change, error):
    doc = with_color(work['doc'])
    change(doc['color'])
    with pytest.raises(rt.ContractError, match=error):
        work_ops.validate_document(doc, work['tools'])


def test_untagged_source_may_be_caller_declared(work):
    doc = with_color(work['doc'], inputs={'gray': BT709, 'untagged': {**BT709, 'basis': 'caller-declared'}})
    work_ops.validate_document(doc, work['tools'])


def diff(work, base, candidate, authorized):
    return work_ops.revision_diff(base, candidate, authorized, work['tools'])


def test_adding_color_requires_grade_and_input_scope(work):
    base, candidate = work['doc'], with_color(work['doc'])
    with pytest.raises(rt.ContractError, match='OUTSIDE_SCOPE: color.grades'):
        diff(work, base, candidate, scope())
    with pytest.raises(rt.ContractError, match='OUTSIDE_SCOPE: color.inputs'):
        diff(work, base, candidate, scope(grade_ids=['up']))
    result = diff(work, base, candidate, scope(grade_ids=['up'], color_inputs=True))
    assert result['color_grades'] == ['up'] and result['color_inputs_changed'] is True
    assert 'render' in result['invalidated'] and 'technical-qc' in result['invalidated']


def test_new_material_under_an_unchanged_grade_requires_its_review(work):
    base = with_color(work['doc'])
    moved = copy.deepcopy(base)
    moved['plan']['clips'][1].update(start=0.2, end=1)  # clip b now shows different source frames
    with pytest.raises(rt.ContractError, match='COLOR_REVIEW_SCOPE_REQUIRED'):
        diff(work, base, moved, scope(clip_ids=['b']))
    result = diff(work, base, moved, scope(clip_ids=['b'], grade_ids=['up']))
    assert result['color_revalidation_declared'] == ['up'] and result['color_grades'] == []
    everything = with_color(work['doc'], grades={'all': {**UP, 'targets': '*'}})
    extended = copy.deepcopy(everything)
    extended['plan']['clips'].append({'id': 'c', 'source_id': 'gray', 'start': 0, 'end': 0.4, 'gain_db': 0})
    with pytest.raises(rt.ContractError, match='COLOR_REVIEW_SCOPE_REQUIRED'):
        diff(work, everything, extended, scope(clip_ids=['c']))
    assert diff(work, everything, extended, scope(clip_ids=['c'], grade_ids=['all']))['color_revalidation_declared'] == ['all']
    shifted = copy.deepcopy(base)  # same material at a new position: the grade follows its clip, no review
    shifted['plan']['clips'][0].update(end=0.6)
    assert diff(work, base, shifted, scope(clip_ids=['a']))['color_revalidation_declared'] == []


def test_reordering_grades_is_a_scoped_change(work):
    grades = {'up': {**UP, 'targets': ['b']}, 'warm': {**UP, 'targets': ['a', 'b'],
              'ops': [{'type': 'white_balance', 'gains': [1.1, 1, 0.9], 'preserve_luminance': True}]}}
    base = with_color(work['doc'], grades=grades, order=['up', 'warm'])
    swapped = with_color(work['doc'], grades=grades, order=['warm', 'up'])
    with pytest.raises(rt.ContractError, match='OUTSIDE_SCOPE: color.order'):
        diff(work, base, swapped, scope())
    assert diff(work, base, swapped, scope(grade_ids=['up', 'warm']))['color_order_changed'] is True


def _frame_rgb(video, frame):
    import subprocess
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf',
                          f"select='eq(n,{frame})',scale=in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24",
                          '-fps_mode', 'passthrough', '-frames:v', '1', '-f', 'rawvideo', '-'],
                         check=True, capture_output=True).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(64, 96, 3).astype(float)


def test_render_grades_target_clips_only_and_before_visual_layers(work):
    doc = with_color(work['doc'])
    doc['visual_layers'] = {'inset': {'source': ref(work['green']), 'source_start_frame': 0, 'anchor_clip_id': 'b',
                                      'offset_frames': 0, 'duration_frames': 20, 'rect': [0, 0, 48, 32], 'opacity': 1,
                                      'z': 1, 'allow_upscale': False, 'input_color': 'bt709-sdr-limited'}}
    store = work['root'] / 'work.sqlite'
    init = work['root'] / 'init'
    init.mkdir()
    state = work_ops.work_version({'operation': 'work-version', 'action': 'init', 'store': str(store), 'work_id': 'color',
                                   'document': doc, 'author': 'agent', 'message': 'fixture'}, init, work['tools'])
    receipt = rt.run({'operation': 'work-render', 'store': str(store), 'expected_version': state['version']},
                     work['root'] / 'render', work['tools'])
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    rendered = json.loads((work['root'] / 'render' / 'render-binding.json').read_text())
    video = rendered['video']['path']
    children = [c['operation'] for c in json.loads((work['root'] / 'render' / 'receipt.json').read_text())
                ['result']['source_consumption']['child_receipts']]
    assert children.index('color-lut-apply') < children.index('visual-layer-render')
    up = float(np.clip((100 / 255) ** 2.4 * 2, 0, 1) ** (1 / 2.4) * 255)
    clip_a, clip_b = _frame_rgb(video, 12), _frame_rgb(video, 37)
    assert abs(clip_a[40:, 40:].mean() - 100) < 3  # ungraded clip
    assert abs(clip_b[40:, 40:].mean() - up) < 3  # graded clip, outside the inset
    inset = clip_b[4:28, 4:44].reshape(-1, 3).mean(axis=0)
    assert np.allclose(inset, [30, 180, 40], atol=6)  # overlay composited after grading stays ungraded
    # A preview candidate renders its own grade without touching the stored head.
    candidate = with_color(work['doc'], grades={'up': {**UP, 'targets': ['a']}})
    candidate['visual_layers'] = doc['visual_layers']
    bundle = work['root'] / 'candidate.json'
    bundle.write_text(json.dumps({'schema': 'work-candidate/1', 'base_version': state['version'],
                                  'base_document_sha256': state['document_sha256'], 'document': candidate,
                                  'scope': scope(grade_ids=['up'])}), encoding='utf-8')
    preview = rt.run({'operation': 'work-render', 'store': str(store), 'expected_version': state['version'],
                      'preview_candidate': ref(bundle)}, work['root'] / 'preview', work['tools'])
    assert preview['status'] == 'SUCCEEDED', preview.get('error')
    assert preview['result']['preview_status'] == 'CANDIDATE_PREVIEW_NOT_COMMITTED'
    swapped = preview['result']['video']['path']
    assert abs(_frame_rgb(swapped, 12)[40:, 40:].mean() - up) < 3 and abs(_frame_rgb(swapped, 37)[40:, 40:].mean() - 100) < 3
    with work_ops.connect(str(store)) as db:
        assert work_ops.load(db)['version'] == state['version']


@pytest.mark.parametrize('opacity', [1, 0.5])
def test_visual_layers_keep_bt709_colors(work, opacity):
    """Overlays stay in YUVA with explicit BT.709; opacity scales alpha only (no RGB matrix round trip)."""
    base = cm.encode_sdr(cm.image(work['root'] / 'base.png', [((100, 100, 100), 1)]), work['root'] / 'base.mp4',
                         seconds=1, pix_fmt='yuv420p')
    request = {'operation': 'visual-layer-render', 'source': ref(base), 'input_color': 'bt709-sdr-limited',
               'layers': [{'id': 'inset', 'source': ref(work['green']), 'source_start_frame': 0, 'start_frame': 0,
                           'duration_frames': 25, 'rect': [0, 0, 48, 32], 'opacity': opacity, 'z': 1,
                           'allow_upscale': False, 'input_color': 'bt709-sdr-limited'}]}
    receipt = rt.run(request, work['root'] / f'overlay-{opacity}', work['tools'])
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    rgb = _frame_rgb(receipt['result']['video']['path'], 12)
    expected = np.array([30, 180, 40]) * opacity + 100 * (1 - opacity)
    assert np.allclose(rgb[4:28, 4:44].reshape(-1, 3).mean(axis=0), expected, atol=6)
    assert abs(rgb[40:, 60:].mean() - 100) < 3


def test_srgb_tagged_timeline_keeps_its_transfer_through_the_color_step(work):
    srgb = cm.encode_sdr(cm.image(work['root'] / 's.png', [((100, 100, 100), 1)]), work['root'] / 'srgb.mp4',
                         seconds=1, transfer='iec61966-2-1')
    doc = copy.deepcopy(work['doc'])
    doc['plan']['sources'] = {'photo': ref(srgb)}
    for clip in doc['plan']['clips']:
        clip['source_id'] = 'photo'
    doc = with_color(doc, grades={'up': {**UP, 'interpretation': 'srgb-sdr-display', 'targets': ['b']}},
                     inputs={'photo': {**BT709, 'space': 'srgb-sdr'}})
    store, init = work['root'] / 'srgb.sqlite', work['root'] / 'srgb-init'
    init.mkdir()
    state = work_ops.work_version({'operation': 'work-version', 'action': 'init', 'store': str(store), 'work_id': 'srgb',
                                   'document': doc, 'author': 'agent', 'message': 'fixture'}, init, work['tools'])
    receipt = rt.run({'operation': 'work-render', 'store': str(store), 'expected_version': state['version']},
                     work['root'] / 'srgb-render', work['tools'])
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    color = json.loads((work['root'] / 'srgb-render' / 'color' / 'receipt.json').read_text())['result']
    assert color['input_color']['space'] == 'srgb-sdr' and color['output_color']['observed']['color_transfer'] == 'iec61966-2-1'
    video = json.loads((work['root'] / 'srgb-render' / 'render-binding.json').read_text())['video']['path']
    linear = ((100 / 255 + 0.055) / 1.055) ** 2.4 * 2  # sRGB EOTF, +1 stop, back through the sRGB OETF
    up = (1.055 * min(linear, 1) ** (1 / 2.4) - 0.055) * 255
    assert abs(_frame_rgb(video, 12).mean() - 100) < 3 and abs(_frame_rgb(video, 37).mean() - up) < 3
