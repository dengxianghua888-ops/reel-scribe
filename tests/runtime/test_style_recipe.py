"""Recipe contracts with real files/CAS and synthetic clock metadata, not style-effect QA."""
import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import editing_runtime
import style_recipe_ops
import test_generation_intents as fixtures


@pytest.fixture
def case(tmp_path):
    owner = fixtures.GenerationIntentContracts()
    owner.setUp()
    work = owner.work_fixture()
    font = tmp_path / 'font.bin'
    font.write_bytes(b'fixture font identity; no glyph render performed')
    card = tmp_path / 'style.md'
    card.write_text('Authored style card, not effect validated')
    ref = lambda p: {'path': str(p), 'sha256': fixtures.digest(p)}
    document = copy.deepcopy(work['document'])
    document['caption_style'] = {'font': ref(font), 'font_family': 'fixture',
                                'font_size': 20, 'margin_v': 2, 'color_rgb': 'FFFFFF'}
    document['captions'] = {'cue': {'clip_id': 'clip', 'start': 0, 'end': 1, 'text': '不可以'}}
    recipe = {'schema': 'style-recipe/1', 'id': 'clear', 'version': '1',
              'style': {'family': 'talking-head', 'style_id': 'clear', 'version': '1', 'card': ref(card)},
              'parameters': {'caption_style': {'color_rgb': 'FFFF00', 'font_size': 24}}}
    scope = owner.scope()
    scope.update(caption_style=True, style_keys=['*'])
    request = {'operation': 'style-recipe-compile', 'document': document,
               'base_version': work['state']['version'],
               'expected_document_sha256': editing_runtime.fingerprint(document),
               'recipe': recipe, 'expected_recipe_sha256': editing_runtime.fingerprint(recipe),
               'capabilities': ['caption-style'], 'scope': scope}
    output = tmp_path / 'output'
    output.mkdir()
    yield request, output, work, owner
    owner.doCleanups()


def compile_case(case):
    request, output, work, _ = case
    return style_recipe_ops.execute(request, output, work['tools'])


def test_compiles_only_presentation_and_does_not_mutate_work_or_inputs(case):
    request, output, work, _ = case
    before = copy.deepcopy(request)
    head = work['head']()
    result = compile_case(case)
    candidate = json.loads((output / 'candidate.json').read_text())['document']
    assert request == before and work['head']() == head
    for field in ['plan', 'captions', 'notes', 'audio_tracks', 'visual_layers']:
        assert candidate[field] == request['document'][field]
    assert candidate['caption_style']['font_size'] == 24
    assert candidate['caption_style']['font'] == request['document']['caption_style']['font']
    assert candidate['style_bindings']['*']['parameters']['recipe_sha256'] == request['expected_recipe_sha256']
    assert result['status'] == 'CANDIDATE_COMPILED'
    assert result['render'] == 'NOT_RUN' and result['style_effect'] == 'NOT_VERIFIED'
    assert result['applied_to_work'] is False
    assert 'render' in result['invalidated']


@pytest.mark.parametrize('change,error', [
    (lambda r: r.update(expected_recipe_sha256='0' * 64), 'RECIPE_REVISION_CONFLICT'),
    (lambda r: r.update(expected_document_sha256='0' * 64), 'DOCUMENT_REVISION_CONFLICT'),
    (lambda r: r.update(capabilities=[]), 'RECIPE_CAPABILITY_UNAVAILABLE'),
    (lambda r: r.update(capabilities=['caption-style', 'caption-style']), 'RECIPE_CAPABILITIES_INVALID'),
    (lambda r: r['scope'].update(caption_style=False), 'CAPTION_STYLE_FROZEN'),
    (lambda r: r['scope'].update(style_keys=[]), 'OUTSIDE_SCOPE'),
])
def test_stale_capability_and_scope_rejections_leave_no_candidate(case, change, error):
    change(case[0])
    with pytest.raises(ValueError, match=error):
        compile_case(case)
    assert list(case[1].iterdir()) == []


@pytest.mark.parametrize('parameters,error', [
    ({'caption_style': {'animation': 'bounce'}}, 'UNKNOWN_FIELDS'),
    ({'caption_style': {'font_size': True}}, 'FONT_SIZE_INVALID'),
    ({'caption_style': {'font_size': 500}}, 'FONT_SIZE_INVALID'),
    ({'caption_style': {'margin_v': 64}}, 'MARGIN_INVALID'),
    ({'caption_style': {'color_rgb': 'red'}}, 'COLOR_RGB_REQUIRED'),
    ({'caption_style': {}}, 'RECIPE_PARAMETERS_REQUIRED'),
    ({'audio_gain_db': {'missing': -8}}, 'AUDIO_TARGET_UNKNOWN'),
    ({'narrative': 'rewrite'}, 'UNKNOWN_FIELDS'),
    ({}, 'RECIPE_PARAMETERS_REQUIRED'),
])
def test_unsupported_or_malformed_recipes_fail_closed(case, parameters, error):
    request = case[0]
    request['recipe']['parameters'] = parameters
    request['expected_recipe_sha256'] = editing_runtime.fingerprint(request['recipe'])
    with pytest.raises(ValueError, match=error):
        compile_case(case)
    assert list(case[1].iterdir()) == []


def test_card_identity_changes_are_rejected(case):
    Path(case[0]['recipe']['style']['card']['path']).write_text('changed')
    with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
        compile_case(case)
    assert list(case[1].iterdir()) == []


def test_candidate_commits_through_existing_work_cas_and_stale_retry_fails(case):
    request, output, work, owner = case
    import work_ops
    store = output.parent / 'recipe-work.sqlite3'
    initial = output.parent / 'initial'
    initial.mkdir()
    state = work_ops.work_version({'operation': 'work-version', 'action': 'init',
        'store': str(store), 'work_id': 'recipe-test', 'document': request['document'],
        'author': 'agent', 'message': 'Initial document'}, initial, work['tools'])
    request['base_version'] = state['version']
    compile_case(case)
    commit_request = {'operation': 'work-version', 'action': 'commit', 'store': str(store),
        'expected_version': state['version'], 'candidate': {'path': str(output / 'candidate.json'),
        'sha256': fixtures.digest(output / 'candidate.json')}, 'author': 'agent', 'message': 'Apply presentation'}
    commit = output.parent / 'commit'
    commit.mkdir()
    result = work_ops.work_version(commit_request, commit, work['tools'])
    assert result['document']['caption_style']['color_rgb'] == 'FFFF00'
    assert result['document']['captions'] == request['document']['captions']
    retry = output.parent / 'retry'
    retry.mkdir()
    with pytest.raises(ValueError, match='WORK_VERSION_CONFLICT'):
        work_ops.work_version(commit_request, retry, work['tools'])


# The following test uses actual FFmpeg synthetic media, not a user content/style evaluation.
from test_source_binding import tools, media, plan  # noqa: F401,E402


def test_real_audio_recipe_preview_changes_gain_without_committing(tmp_path, tools, media):
    import math
    import struct
    import subprocess
    import work_ops
    voice = tmp_path / 'voice.wav'
    subprocess.run([tools.ffmpeg, '-nostdin', '-v', 'error', '-n', '-f', 'lavfi',
        '-i', 'sine=frequency=700:sample_rate=48000:duration=0.4', str(voice)], check=True)
    card = tmp_path / 'card.md'
    card.write_text('Synthetic technical gain recipe, not narrative/style-effect evidence')
    ref = lambda p: {'path': str(p), 'sha256': editing_runtime.sha256(p)}
    document = {'schema': 'work-document/1', 'plan': plan(media['red'], mute=True),
        'captions': {}, 'caption_style': None, 'audio_tracks': {'voice': {
        'source': ref(voice), 'start': 0, 'end': 0.4, 'anchor_clip_id': 'one', 'offset': 0, 'gain_db': 0}},
        'style_bindings': {}, 'notes': {}}
    store = tmp_path / 'audio-work.sqlite'
    initial = tmp_path / 'init'
    initial.mkdir()
    state = work_ops.work_version({'operation': 'work-version', 'action': 'init', 'store': str(store),
        'work_id': 'audio-recipe', 'document': document, 'author': 'agent', 'message': 'Synthetic media'}, initial, tools)
    baseline_dir = tmp_path / 'baseline'
    baseline_dir.mkdir()
    baseline = work_ops.work_render({'operation': 'work-render', 'store': str(store),
        'expected_version': state['version']}, baseline_dir, tools)
    recipe = {'schema': 'style-recipe/1', 'id': 'gain', 'version': '1',
        'style': {'family': 'test', 'style_id': 'gain', 'version': '1', 'card': ref(card)},
        'parameters': {'audio_gain_db': {'voice': -12}}}
    scope = fixtures.GenerationIntentContracts.scope()
    scope.update(audio_ids=['voice'], style_keys=['*'], freeze_positions=['one'])
    folder = tmp_path / 'compiled'
    folder.mkdir()
    request = {'operation': 'style-recipe-compile', 'document': document,
        'expected_document_sha256': editing_runtime.fingerprint(document), 'base_version': state['version'],
        'recipe': recipe, 'expected_recipe_sha256': editing_runtime.fingerprint(recipe),
        'capabilities': ['audio-track-gain'], 'scope': scope}
    for key, value, error in [('capabilities', [], 'RECIPE_CAPABILITY_UNAVAILABLE'),
                               ('scope', {**scope, 'audio_ids': []}, 'OUTSIDE_SCOPE')]:
        invalid = {**request, key: value}
        with pytest.raises(ValueError, match=error):
            style_recipe_ops.execute(invalid, folder, tools)
        assert list(folder.iterdir()) == []
    result = style_recipe_ops.execute(request, folder, tools)
    preview_dir = tmp_path / 'preview'
    preview_dir.mkdir()
    preview = work_ops.work_render({'operation': 'work-render', 'store': str(store),
        'expected_version': state['version'], 'preview_candidate': ref(folder / 'candidate.json')}, preview_dir, tools)
    assert preview['preview_status'] == 'CANDIDATE_PREVIEW_NOT_COMMITTED'
    rendered = json.loads((preview_dir / 'rendered-document.json').read_text())
    assert rendered['audio_tracks']['voice']['gain_db'] == -12
    assert rendered['plan'] == document['plan']
    assert result['document_sha256'] == preview['document_sha256']
    db = work_ops.connect(store)
    try:
        assert work_ops.load(db)['version'] == state['version']
    finally:
        db.close()

    def rms(video):
        raw = subprocess.run([tools.ffmpeg, '-v', 'error', '-i', video, '-vn', '-ac', '1',
            '-ar', '48000', '-f', 'f32le', '-'], check=True, stdout=subprocess.PIPE).stdout
        samples = struct.unpack('<' + 'f' * (len(raw) // 4), raw)
        return math.sqrt(sum(x*x for x in samples) / len(samples))
    ratio = rms(preview['video']['path']) / rms(baseline['video']['path'])
    assert 0.22 < ratio < 0.29  # -12 dB ~= 0.251 amplitude, with AAC encode tolerance.
    assert tools.probe(preview['video']['path'])['duration'] > 0


def test_identical_recipe_does_not_change_candidate_document_again(case):
    request, output, work, _ = case
    compile_case(case)
    candidate = json.loads((output / 'candidate.json').read_text())['document']
    request['document'] = candidate
    request['expected_document_sha256'] = editing_runtime.fingerprint(candidate)
    second = output.parent / 'second'
    second.mkdir()
    report = style_recipe_ops.execute(request, second, work['tools'])
    assert json.loads((second / 'candidate.json').read_text())['document'] == candidate
    assert report['invalidated'] == []
