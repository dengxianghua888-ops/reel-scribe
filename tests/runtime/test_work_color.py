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


def test_reordering_differently_trimmed_covered_clips_needs_no_color_review(work):
    base = with_color(work['doc'], grades={'all': {**UP, 'targets': '*'}})
    base['plan']['clips'][1].update(start=0.2, end=1)  # a and b now cover different source frames
    swapped = copy.deepcopy(base)
    swapped['plan']['clips'].reverse()
    result = diff(work, base, swapped, scope(clip_ids=['a', 'b']))
    assert result['color_revalidation_declared'] == [] and result['color_grades'] == []


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


# --- C2b: local undo, recipe color_grade group, revision impact, A/B preview -------------

def init_store(work, doc, name):
    folder = work['root'] / f'{name}-init'
    folder.mkdir()
    store = work['root'] / f'{name}.sqlite'
    state = work_ops.work_version({'operation': 'work-version', 'action': 'init', 'store': str(store), 'work_id': name,
                                   'document': doc, 'author': 'agent', 'message': 'fixture'}, folder, work['tools'])
    return store, state


def head(store):
    with work_ops.connect(str(store)) as db:
        return work_ops.load(db)


def commit_candidate(work, store, candidate_path, label):
    folder = work['root'] / f'commit-{label}'
    folder.mkdir()
    return work_ops.work_version({'operation': 'work-version', 'action': 'commit', 'store': str(store),
                                  'expected_version': head(store)['version'], 'candidate': ref(candidate_path),
                                  'message': label, 'author': 'human'}, folder, work['tools'])


def commit(work, store, change, authorized, label):
    current = head(store)
    candidate = copy.deepcopy(current['document'])
    change(candidate)
    folder = work['root'] / f'revise-{label}'
    folder.mkdir()
    work_ops.timeline_revise({'operation': 'timeline-revise', 'base_version': current['version'],
                              'document': current['document'], 'expected_document_sha256': current['document_sha256'],
                              'candidate': candidate, 'scope': authorized}, folder, work['tools'])
    return commit_candidate(work, store, folder / 'candidate.json', label)


def prepare_undo(work, store, sequence, fields, authorized, label, **extra):
    folder = work['root'] / f'undo-{label}'
    folder.mkdir()
    request = {'operation': 'work-version', 'action': 'prepare-local-undo', 'store': str(store),
               'expected_version': head(store)['version'], 'undo_sequence': sequence, 'fields': fields,
               'scope': authorized, **extra}
    return work_ops.work_version(request, folder, work['tools']), folder


def test_local_undo_restores_one_grade_field_and_keeps_later_edits(work):
    store, _ = init_store(work, with_color(work['doc']), 'undo')
    grade_scope = scope(grade_ids=['up'])
    commit(work, store, lambda d: d['color']['grades']['up']['ops'][0].update(stops=0.5), grade_scope, 'soften')  # seq 2
    commit(work, store, lambda d: d['color']['grades']['up'].update(targets=['a', 'b']), grade_scope, 'widen')  # seq 3
    report, folder = prepare_undo(work, store, 2, [{'kind': 'color_grade', 'id': 'up', 'field': 'ops'}], grade_scope, 'ops')
    assert report['status'] == 'CANDIDATE_PREPARED' and report['fields'][0]['status'] == 'RESTORE_BEFORE'
    restored = json.loads((folder / 'candidate.json').read_text())['document']['color']['grades']['up']
    assert restored['ops'] == [{'type': 'exposure', 'stops': 1}] and restored['targets'] == ['a', 'b']
    with pytest.raises(rt.ContractError, match='OUTSIDE_SCOPE: color.grades'):
        prepare_undo(work, store, 2, [{'kind': 'color_grade', 'id': 'up', 'field': 'ops'}], scope(), 'unscoped')
    commit(work, store, lambda d: d['color']['grades']['up']['ops'][0].update(stops=-1), grade_scope, 'darken')  # seq 4
    with pytest.raises(rt.ContractError, match='UNDO_FIELD_CONFLICT'):
        prepare_undo(work, store, 2, [{'kind': 'color_grade', 'id': 'up', 'field': 'ops'}], grade_scope, 'conflict')
    commit(work, store, lambda d: d['color']['grades']['up'].update(strength=0.5), grade_scope, 'blend')  # seq 5
    report, folder = prepare_undo(work, store, 5, [{'kind': 'color_grade', 'id': 'up', 'field': 'strength'}],
                                  grade_scope, 'strength')
    assert report['fields'][0]['presence'] == {'before': False, 'after': True, 'current': True}
    assert 'strength' not in json.loads((folder / 'candidate.json').read_text())['document']['color']['grades']['up']
    with pytest.raises(rt.ContractError, match='UNDO_FIELD_UNSUPPORTED'):
        prepare_undo(work, store, 5, [{'kind': 'color_grade', 'id': 'up', 'field': 'schema'}], grade_scope, 'bad')


def test_local_undo_of_targets_is_still_validated_against_the_current_clips(work):
    store, _ = init_store(work, with_color(work['doc'], grades={'up': {**UP, 'targets': ['a']}}), 'targets')
    commit(work, store, lambda d: d['color']['grades']['up'].update(targets=['b']), scope(grade_ids=['up']), 'retarget')  # seq 2
    commit(work, store, lambda d: d['plan'].update(clips=d['plan']['clips'][1:]), scope(clip_ids=['a']), 'drop-a')  # seq 3
    with pytest.raises(rt.ContractError, match='WORK_COLOR_TARGET_MISSING'):
        prepare_undo(work, store, 2, [{'kind': 'color_grade', 'id': 'up', 'field': 'targets'}], scope(grade_ids=['up']), 'stale')


def recipe(work, stops, version):
    card = work['root'] / 'look-card.md'
    if not card.exists():
        card.write_text('fixture style card: explicit exposure only', encoding='utf-8')
    return {'schema': 'style-recipe/1', 'id': 'look', 'version': version,
            'style': {'family': 'fixture', 'style_id': 'look', 'version': '1', 'card': ref(card)},
            'parameters': {'color_grade': {'look': {'targets': '*', 'interpretation': 'bt709-sdr-display',
                                                    'ops': [{'type': 'exposure', 'stops': stops}], 'lut_size': 33}}}}


def compile_recipe(work, store, value, capabilities, label):
    import style_recipe_ops
    current = head(store)
    folder = work['root'] / f'recipe-{label}'
    folder.mkdir()
    result = style_recipe_ops.execute({'operation': 'style-recipe-compile', 'base_version': current['version'],
        'document': current['document'], 'expected_document_sha256': current['document_sha256'], 'recipe': value,
        'expected_recipe_sha256': rt.fingerprint(value), 'capabilities': capabilities,
        'scope': scope(grade_ids=['look'], style_keys=['*'])}, folder, work['tools'])
    return result, folder


def inputs_only(work):
    doc = with_color(work['doc'], grades={}, order=[])
    assert doc['color']['grades'] == {} and doc['color']['order'] == []
    return doc


def test_recipe_color_group_binding_undo_and_revision_impact(work):
    import revision_impact
    import style_recipe_ops
    store, _ = init_store(work, inputs_only(work), 'recipe')
    with pytest.raises(rt.ContractError, match='RECIPE_CAPABILITY_UNAVAILABLE'):
        compile_recipe(work, store, recipe(work, 1, 'v1'), [], 'no-capability')
    no_color = work['doc']
    with pytest.raises(rt.ContractError, match='EXISTING_COLOR_INPUTS_REQUIRED'):
        style_recipe_ops.execute({'operation': 'style-recipe-compile', 'base_version': '0' * 64, 'document': no_color,
            'expected_document_sha256': rt.fingerprint(no_color), 'recipe': recipe(work, 1, 'v1'),
            'expected_recipe_sha256': rt.fingerprint(recipe(work, 1, 'v1')), 'capabilities': ['color-grade'],
            'scope': scope(grade_ids=['look'], style_keys=['*'])}, work['root'], work['tools'])
    v1, v2 = recipe(work, 1, 'v1'), recipe(work, -1, 'v2')
    result, folder = compile_recipe(work, store, v1, ['color-grade'], 'v1')
    assert result['required_capabilities'] == ['color-grade']
    commit_candidate(work, store, folder / 'candidate.json', 'apply-v1')  # seq 2
    before = head(store)['document']
    _, folder = compile_recipe(work, store, v2, ['color-grade'], 'v2')
    after = json.loads((folder / 'candidate.json').read_text())['document']
    report = revision_impact.analyze(before, after, scope(grade_ids=['look'], style_keys=['*']), work['tools'],
                                     expected_base_sha256=rt.fingerprint(before),
                                     expected_candidate_sha256=rt.fingerprint(after))
    assert report['required_stages'] == ['color-grade', 'render']
    assert report['classification'] == ['color-grade-or-order', 'style-metadata']
    commit_candidate(work, store, folder / 'candidate.json', 'apply-v2')  # seq 3
    fields = [{'kind': 'color_grade', 'id': 'look', 'field': 'ops'}]
    undo_scope = scope(grade_ids=['look'], style_keys=['*'])
    with pytest.raises(rt.ContractError, match='UNDO_STYLE_BINDING_REQUIRES_EXPLICIT_RESOLUTION'):
        prepare_undo(work, store, 3, fields, undo_scope, 'unresolved')
    resolution = {'recipe': v2, 'expected_recipe_sha256': rt.fingerprint(v2), 'derived_recipe_id': 'look',
                  'derived_recipe_version': 'v2-undo-ops'}
    report, folder = prepare_undo(work, store, 3, fields, undo_scope, 'resolved', binding_resolution=resolution)
    document = json.loads((folder / 'candidate.json').read_text())['document']
    assert document['color']['grades']['look']['ops'] == [{'type': 'exposure', 'stops': 1}]
    presentation = document['style_bindings']['*']['parameters']
    assert presentation['recipe_version'] == 'v2-undo-ops'
    assert presentation['presentation']['color_grade']['look']['ops'] == [{'type': 'exposure', 'stops': 1}]
    assert report['binding_resolution']['policy'] == 'EXPLICIT_DERIVED_RECIPE'


def test_ab_preview_renders_color_variants_without_committing(work):
    import style_preview_ops
    store, state = init_store(work, inputs_only(work), 'preview')
    variants = []
    for name, stops in (('brighter', 1), ('darker', -1)):
        value = recipe(work, stops, name)
        variants.append({'id': name, 'recipe': value, 'expected_recipe_sha256': rt.fingerprint(value),
                         'capabilities': ['color-grade'], 'scope': scope(grade_ids=['look'], style_keys=['*'])})
    folder = work['root'] / 'ab'
    folder.mkdir()
    result = style_preview_ops.execute({'operation': 'style-recipe-preview', 'store': str(store),
                                        'expected_version': state['version'], 'variants': variants}, folder, work['tools'])
    videos = {row['id']: row['video']['path'] for row in result['variants']}
    gray = 100 / 255
    expected = {'brighter': min(gray ** 2.4 * 2, 1) ** (1 / 2.4) * 255, 'darker': (gray ** 2.4 / 2) ** (1 / 2.4) * 255}
    for name, value in expected.items():
        assert abs(_frame_rgb(videos[name], 37).mean() - value) < 3, name
    assert head(store)['version'] == state['version']


def captioned(work, doc):
    font = work['root'] / 'font.bin'
    font.write_bytes(b'fixture font identity; no glyph render performed')
    doc = copy.deepcopy(doc)
    doc['caption_style'] = {'font': ref(font), 'font_family': 'fixture', 'font_size': 20, 'margin_v': 2, 'color_rgb': 'FFFFFF'}
    doc['captions'] = {'cue': {'clip_id': 'a', 'start': 0, 'end': 0.5, 'text': 'cue'}}
    return doc


def cue_compile(work, doc, parameters, capabilities, authorized, label):
    import style_recipe_ops
    value = recipe(work, 1, label)
    value['parameters'] = parameters
    folder = work['root'] / f'cue-{label}'
    folder.mkdir()
    result = style_recipe_ops.execute({'operation': 'style-recipe-compile', 'base_version': '0' * 64, 'document': doc,
        'expected_document_sha256': rt.fingerprint(doc), 'recipe': value, 'expected_recipe_sha256': rt.fingerprint(value),
        'capabilities': capabilities, 'scope': authorized}, folder, work['tools'])
    return result, json.loads((folder / 'candidate.json').read_text())['document']


def test_cue_recipe_carries_grades_unchanged_and_color_recipe_carries_cues(work):
    look = {'targets': '*', **UP}
    doc = captioned(work, with_color(work['doc'], grades={'look': look}))
    cue_scope = scope(caption_ids=['cue'], grade_ids=['look'], style_keys=['*'])
    changed = {**look, 'ops': [{'type': 'exposure', 'stops': -1}]}
    # A cue-only edit must not change a grade, even with grade scope and no color capability.
    with pytest.raises(rt.ContractError, match='CUE_RECIPE_GLOBAL_CHANGE_FORBIDDEN'):
        cue_compile(work, doc, {'caption_overrides': {'cue': {'font_size': 28}}, 'color_grade': {'look': changed}},
                    ['caption-cue-style'], cue_scope, 'cue-changes-grade')
    result, candidate = cue_compile(work, doc, {'caption_overrides': {'cue': {'font_size': 28}}, 'color_grade': {'look': look}},
                                    ['caption-cue-style'], scope(caption_ids=['cue'], style_keys=['*']), 'cue-carries-grade')
    assert result['required_capabilities'] == ['caption-cue-style']
    assert candidate['color'] == doc['color'] and candidate['captions']['cue']['style_override'] == {'font_size': 28}
    # A later color recipe may carry the bound cue mapping unchanged, without caption scope.
    _, candidate = cue_compile(work, candidate, {'caption_overrides': {'cue': {'font_size': 28}}, 'color_grade': {'look': changed}},
                               ['color-grade'], scope(grade_ids=['look'], style_keys=['*']), 'grade-carries-cue')
    assert candidate['color']['grades']['look'] == changed and candidate['captions']['cue']['style_override'] == {'font_size': 28}
    with pytest.raises(rt.ContractError, match='CUE_RECIPE_UNSELECTED_OVERRIDE_CHANGED'):
        cue_compile(work, candidate, {'caption_overrides': {'cue': {'font_size': 30}}, 'color_grade': {'look': look}},
                    ['color-grade'], scope(grade_ids=['look'], style_keys=['*']), 'grade-changes-cue')


def test_color_recipe_carrying_cues_must_keep_the_whole_bound_cue_mapping(work):
    look = {'targets': '*', **UP}
    doc = captioned(work, with_color(work['doc'], grades={'look': look}))
    doc['captions']['other'] = {'clip_id': 'b', 'start': 0, 'end': 0.5, 'text': 'other'}
    overrides = {'cue': {'font_size': 28}, 'other': {'color_rgb': 'FF0000'}}
    for cid, value in overrides.items():
        doc['captions'][cid]['style_override'] = dict(value)
    prior = recipe(work, 1, 'prior')
    doc['style_bindings'] = {'*': {**copy.deepcopy(prior['style']), 'parameters': {
        'recipe_id': 'look', 'recipe_version': 'prior', 'recipe_sha256': 'a' * 64,
        'presentation': {'caption_overrides': copy.deepcopy(overrides), 'color_grade': {'look': look}},
        'layout_constraints': {'fixture': 'declared'}}}}
    changed = {**look, 'ops': [{'type': 'exposure', 'stops': -1}]}
    grade_scope = scope(grade_ids=['look'], style_keys=['*'])
    with pytest.raises(rt.ContractError, match='CUE_RECIPE_BINDING_PARAMETERS_DROPPED'):
        cue_compile(work, doc, {'caption_overrides': {'cue': {'font_size': 28}}, 'color_grade': {'look': changed}},
                    ['color-grade'], grade_scope, 'drops-a-cue')
    with pytest.raises(rt.ContractError, match='CUE_RECIPE_CONSTRAINTS_MUST_PERSIST'):
        cue_compile(work, doc, {'caption_overrides': copy.deepcopy(overrides), 'color_grade': {'look': changed}},
                    ['color-grade'], grade_scope, 'drops-constraints')


def test_new_recipe_grades_get_a_deterministic_order(work):
    import style_recipe_ops
    doc = inputs_only(work)
    orders = []
    for names in (['z-dark', 'a-bright'], ['a-bright', 'z-dark']):
        value = recipe(work, 1, 'two')
        value['parameters']['color_grade'] = {name: {'targets': '*', 'interpretation': 'bt709-sdr-display', 'lut_size': 33,
                                                     'ops': [{'type': 'exposure', 'stops': 4 if name == 'a-bright' else -4}]}
                                              for name in names}
        folder = work['root'] / f'order-{names[0]}'
        folder.mkdir()
        style_recipe_ops.execute({'operation': 'style-recipe-compile', 'base_version': '0' * 64, 'document': doc,
            'expected_document_sha256': rt.fingerprint(doc), 'recipe': value, 'expected_recipe_sha256': rt.fingerprint(value),
            'capabilities': ['color-grade'], 'scope': scope(grade_ids=names, style_keys=['*'])}, folder, work['tools'])
        orders.append(json.loads((folder / 'candidate.json').read_text())['document']['color']['order'])
    assert orders == [['a-bright', 'z-dark'], ['a-bright', 'z-dark']]


# C2c: protections and limits gate the render after the color step.
BOX_B = {'kind': 'region', 'targets': ['b'], 'box': [0.1, 0.1, 0.9, 0.9], 'max_median_delta_e2000': 2.0, 'action': 'fail'}


def render_store(work, doc, name):
    store, state = init_store(work, doc, name)
    receipt = rt.run({'operation': 'work-render', 'store': str(store), 'expected_version': state['version']},
                     work['root'] / f'render-{name}', work['tools'])
    return receipt


def test_render_gate_keeps_unchanged_protections_and_blocks_violated_ones(work):
    kept = with_color(work['doc'])
    kept['color']['protections'] = {'a-box': {**BOX_B, 'targets': ['a']}}  # clip a is not graded
    receipt = render_store(work, kept, 'kept')
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    check = receipt['result']['color_check']
    assert check['gate'] == 'PASSED' and check['failures'] == []
    children = [c['operation'] for c in receipt['result']['source_consumption']['child_receipts']]
    assert children.index('color-lut-apply') < children.index('color-consistency-check') < children.index('media-qc')
    report = json.loads(Path(check['report']['path']).read_text())
    assert [s['id'] for s in report['segments']] == ['a', 'b'] and report['protections']['a-box']['status'] == 'KEPT'
    violated = with_color(work['doc'])
    violated['color']['protections'] = {'b-box': BOX_B}  # clip b gets +1 stop
    receipt = render_store(work, violated, 'violated')
    assert receipt['status'] == 'FAILED' and 'WORK_COLOR_CHECK_FAILED: protection b-box violated' in receipt['error']
    flagged = copy.deepcopy(violated)
    flagged['color']['protections']['b-box']['action'] = 'flag'
    flagged['color']['limits'] = {'max_clip_increase': 0.5}
    receipt = render_store(work, flagged, 'flagged')
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    assert receipt['result']['color_check']['gate'] == 'FLAGGED'
    assert receipt['result']['color_check']['flags'] == ['protection b-box violated']


@pytest.mark.parametrize('change,error', [
    (lambda c: c.update(protections={'p': {**BOX_B, 'targets': ['missing']}}), 'WORK_COLOR_TARGET_MISSING'),
    (lambda c: c.update(protections={'p': {**BOX_B, 'targets': '*'}}, inputs={}, grades={}, order=[]),
     'WORK_COLOR_INPUT_DECLARATION_REQUIRED'),
    (lambda c: c.update(protections={'p': {k: v for k, v in BOX_B.items() if k != 'targets'}}),
     'WORK_COLOR_PROTECTION_TARGETS_REQUIRED'),
    (lambda c: c.update(protections={'p': {**BOX_B, 'kind': 'skin'}}), 'COLOR_CHECK_PROTECTION_KIND_UNSUPPORTED'),
    (lambda c: c.update(protections={'p': {**BOX_B, 'box': [0.5, 0, 0.4, 1]}}), 'COLOR_CHECK_REGION_BOX_INVALID'),
    (lambda c: c.update(limits={'max_banding': 1}), 'max_banding'),
])
def test_protection_and_limit_validation(work, change, error):
    doc = with_color(work['doc'])
    change(doc['color'])
    with pytest.raises(rt.ContractError, match=error):
        work_ops.validate_document(doc, work['tools'])


def test_changing_checks_needs_its_own_scope_and_only_reruns_color_and_render(work):
    import revision_impact
    base = with_color(work['doc'])
    assert diff(work, work['doc'], base, scope(grade_ids=['up'], color_inputs=True))['color_checks_changed'] is False
    protected = copy.deepcopy(base)
    protected['color']['protections'] = {'b-box': BOX_B}
    with pytest.raises(rt.ContractError, match='OUTSIDE_SCOPE: color.protections or color.limits'):
        diff(work, base, protected, scope(grade_ids=['up']))
    authorized = scope(color_checks=True)
    assert diff(work, base, protected, authorized)['color_checks_changed'] is True
    report = revision_impact.analyze(base, protected, authorized, work['tools'], expected_base_sha256=rt.fingerprint(base),
                                     expected_candidate_sha256=rt.fingerprint(protected))
    assert report['classification'] == ['color-checks'] and report['required_stages'] == ['color-grade', 'render']
