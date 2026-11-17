"""Real Work validation with declared clock fixtures; not real-media acceptance."""
import copy
import hashlib
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_generation_intents as fixtures
import revision_impact
from editing_runtime import fingerprint


@pytest.fixture
def work():
    owner = fixtures.GenerationIntentContracts()
    owner.setUp()
    value = owner.work_fixture()
    value['root'] = owner.root
    yield value
    owner.doCleanups()


def scope(**kwargs):
    return fixtures.GenerationIntentContracts.scope(**kwargs)


def inspect(work, candidate, authorization=None, **kwargs):
    return revision_impact.analyze(work['document'], candidate, authorization or scope(), work['tools'],
        expected_base_sha256=kwargs.get('base_sha', fingerprint(work['document'])),
        expected_candidate_sha256=kwargs.get('candidate_sha', fingerprint(candidate)))


def captions(work):
    font = work['root'] / 'fixture-font'
    font.write_bytes(b'Not a real font: source binding only')
    work['document']['caption_style'] = {'font': {'path': str(font), 'sha256': fixtures.digest(font)},
        'font_family': 'Fixture', 'font_size': 20, 'margin_v': 4, 'color_rgb': 'FFFFFF'}
    work['document']['captions'] = {'cue': {'clip_id': 'clip', 'start': 0, 'end': 0.8, 'text': '不可以'}}


def test_no_change_does_not_grant_existing_qa(work):
    report = inspect(work, copy.deepcopy(work['document']))
    assert report['required_stages'] == []
    assert report['classification'] == []
    assert report['invalidated_reviews'] == []
    assert report['qa_status'] == 'NOT_RUN'
    assert report['prior_whole_document_qa'] == 'NOT_VERIFIED'
    assert report['cache_reuse'] == 'NOT_AUTHORIZED'


def test_deterministic_and_digest_bound_metadata_report(work):
    candidate = copy.deepcopy(work['document'])
    candidate['notes']['manual-note'] = 'new'
    authorization = scope(notes=['manual-note'])
    before = copy.deepcopy(candidate)
    report = inspect(work, candidate, authorization)
    assert report == inspect(work, candidate, authorization)
    assert candidate == before
    assert report['required_stages'] == []
    assert report['classification'] == ['notes-metadata']
    assert report['prior_whole_document_qa'] == 'STALE'
    assert report['base_document_sha256'] == fingerprint(work['document'])
    assert report['candidate_document_sha256'] == fingerprint(candidate)
    assert report['scope_sha256'] == fingerprint(authorization)
    body = {key: val for key, val in report.items() if key != 'impact_sha256'}
    assert report['impact_sha256'] == fingerprint(body)


@pytest.mark.parametrize('field,value', [('color_rgb', 'FF0000'), ('font_size', 30), ('margin_v', 8)])
def test_caption_presentation_does_not_request_asr_or_tts(work, field, value):
    captions(work)
    candidate = copy.deepcopy(work['document'])
    candidate['caption_style'][field] = value
    authorization = scope()
    authorization['caption_style'] = True
    report = inspect(work, candidate, authorization)
    assert report['classification'] == ['caption-presentation']
    assert report['required_stages'] == ['caption-layout', 'visual-composition', 'render']
    assert 'source-analysis' in report['unchanged_dependency_stages']
    assert 'audio-mix' in report['unchanged_dependency_stages']
    # Narrow execution dependencies must not silently relax the legacy QA gate.
    assert 'listening-review' in report['invalidated_reviews']
    assert 'content-review' in report['invalidated_reviews']


@pytest.mark.parametrize('field,value,category', [('text', '可以', 'caption-text'),
                                               ('end', 0.7, 'caption-placement')])
def test_caption_changes_are_distinguished(work, field, value, category):
    captions(work)
    candidate = copy.deepcopy(work['document'])
    candidate['captions']['cue'][field] = value
    authorization = scope()
    authorization['caption_ids'] = ['cue']
    report = inspect(work, candidate, authorization)
    assert report['classification'] == [category]
    assert 'source-analysis' not in report['required_stages']
    assert report['qa_status'] == 'NOT_RUN'


def test_clip_gain_conservatively_reconsiders_whole_work(work):
    candidate = copy.deepcopy(work['document'])
    candidate['plan']['clips'][0]['gain_db'] = -3
    report = inspect(work, candidate, scope(clips=['clip']))
    assert report['required_stages'] == list(revision_impact.STAGES[1:])
    assert report['changed_clip_ids'] == ['clip']
    assert report['affected_range_policy'].startswith('whole-work-conservative')


def test_new_source_identity_invalidates_analysis(work):
    candidate = copy.deepcopy(work['document'])
    replacement = work['root'] / 'replacement.bin'
    replacement.write_bytes(b'New declared media bytes')
    candidate['plan']['sources']['source'] = {'path': str(replacement), 'sha256': fixtures.digest(replacement)}
    report = inspect(work, candidate, scope(sources=['source'], clips=['clip']))
    assert report['required_stages'] == list(revision_impact.STAGES)
    assert 'source-identity' in report['classification']


def test_same_path_replaced_bytes_rejects_unavailable_base_not_reuses(work):
    candidate = copy.deepcopy(work['document'])
    source = candidate['plan']['sources']['source']
    Path(source['path']).write_bytes(b'replaced content')
    source['sha256'] = hashlib.sha256(b'replaced content').hexdigest()
    with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
        inspect(work, candidate, scope(sources=['source'], clips=['clip']))


@pytest.mark.parametrize('kwargs,error', [({'base_sha': 'a' * 64}, 'DOCUMENT_REVISION_CONFLICT'),
                                         ({'candidate_sha': 'b' * 64}, 'CANDIDATE_REVISION_CONFLICT')])
def test_stale_digests_rejected(work, kwargs, error):
    with pytest.raises(ValueError, match=error):
        inspect(work, work['document'], **kwargs)


def test_scope_violation_is_not_a_report(work):
    candidate = copy.deepcopy(work['document'])
    candidate['notes']['manual-note'] = 'unauthorized'
    with pytest.raises(ValueError, match='OUTSIDE_SCOPE'):
        inspect(work, candidate)


def test_unknown_document_fields_rejected(work):
    candidate = copy.deepcopy(work['document'])
    candidate['unknown_effect'] = {'enabled': True}
    with pytest.raises(ValueError):
        inspect(work, candidate)


def test_operation_writes_only_report_and_no_failed_artifact(work):
    output = work['root'] / 'impact'
    output.mkdir()
    request = {'operation': 'revision-impact-inspect', 'document': work['document'],
        'candidate': work['document'], 'scope': scope(),
        'expected_document_sha256': fingerprint(work['document']),
        'expected_candidate_sha256': fingerprint(work['document'])}
    report = revision_impact.execute(request, output, work['tools'])
    assert json.loads((output / 'revision-impact.json').read_text()) == report
    assert sorted(p.name for p in output.iterdir()) == ['revision-impact.json']
    failed = work['root'] / 'failed'
    failed.mkdir()
    request['expected_candidate_sha256'] = 'b' * 64
    with pytest.raises(ValueError):
        revision_impact.execute(request, failed, work['tools'])
    assert not list(failed.iterdir())


def test_style_binding_remains_metadata_not_an_effect(work):
    candidate = copy.deepcopy(work['document'])
    card = work['root'] / 'style.md'
    card.write_text('Authored style, not evidence of an effect')
    candidate['style_bindings']['*'] = {'family': 'talking-head', 'style_id': 'clear',
        'version': '1', 'card': {'path': str(card), 'sha256': fixtures.digest(card)}, 'parameters': {}}
    authorization = scope()
    authorization['style_keys'] = ['*']
    report = inspect(work, candidate, authorization)
    assert report['classification'] == ['style-metadata']
    assert report['required_stages'] == []
    assert report['invalidated_reviews'] == ['content-review', 'style-review']


def test_output_geometry_is_not_treated_as_local_caption_change(work):
    candidate = copy.deepcopy(work['document'])
    candidate['plan']['width'] = 128
    authorization = scope(clips=['clip'])
    authorization['output_fields'] = ['width']
    report = inspect(work, candidate, authorization)
    assert report['classification'] == ['output-specification']
    assert report['required_stages'] == list(revision_impact.STAGES[1:])


def test_shortening_requires_real_existing_work_scope(work):
    candidate = copy.deepcopy(work['document'])
    candidate['plan']['clips'][0]['end'] = 0.8
    authorization = scope(clips=['clip'])
    with pytest.raises(ValueError, match='FROZEN_POSITION_CHANGED'):
        inspect(work, candidate, authorization)
    authorization['freeze_positions'] = []
    authorization['freeze_duration'] = False
    report = inspect(work, candidate, authorization)
    assert report['shifted_clip_ids'] == ['clip']
    assert 'timeline' in report['required_stages']


def test_review_invalidation_is_exactly_existing_gate_not_new_authority(work):
    from work_ops import revision_diff
    captions(work)
    candidate = copy.deepcopy(work['document'])
    candidate['caption_style']['color_rgb'] = 'AA0000'
    authorization = scope()
    authorization['caption_style'] = True
    diff = revision_diff(work['document'], candidate, authorization, work['tools'])
    report = inspect(work, candidate, authorization)
    assert report['invalidated_reviews'] == sorted(set(diff['invalidated']))


@pytest.fixture
def generated_media_work(work):
    """Decoded one-second synthetic media, not creator footage/effect QA."""
    import shutil
    import subprocess
    from editing_runtime import Tools
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg and FFprobe required for synthetic media impact checks')
    video = work['root'] / 'synthetic.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=64x64:r=25:d=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-shortest', str(video)], check=True)
    work['tools'] = Tools()
    reference = {'path': str(video), 'sha256': fixtures.digest(video)}
    work['document']['plan']['sources']['source'] = reference
    work['document']['audio_tracks']['music'] = {'source': copy.deepcopy(reference), 'start': 0,
        'end': 0.8, 'anchor_clip_id': 'clip', 'offset': 0, 'gain_db': -6}
    work['document']['visual_layers']['inset'] = {'source': copy.deepcopy(reference),
        'source_start_frame': 0, 'anchor_clip_id': 'clip', 'offset_frames': 0, 'duration_frames': 20,
        'rect': [0, 0, 32, 32], 'opacity': 1, 'z': 1, 'allow_upscale': False,
        'input_color': 'bt709-sdr-limited'}
    return work


def test_audio_gain_requires_mix_not_source_analysis(generated_media_work):
    work = generated_media_work
    candidate = copy.deepcopy(work['document'])
    candidate['audio_tracks']['music']['gain_db'] = -12
    authorization = scope()
    authorization['audio_ids'] = ['music']
    report = inspect(work, candidate, authorization)
    assert report['required_stages'] == ['audio-mix', 'render']
    assert report['classification'] == ['audio-track-or-mapping']
    assert report['qa_status'] == 'NOT_RUN'


def test_visual_opacity_requires_composition_not_mix(generated_media_work):
    work = generated_media_work
    candidate = copy.deepcopy(work['document'])
    candidate['visual_layers']['inset']['opacity'] = 0.5
    authorization = scope()
    authorization['visual_ids'] = ['inset']
    report = inspect(work, candidate, authorization)
    assert report['required_stages'] == ['visual-composition', 'render']
    assert report['classification'] == ['visual-layer-or-mapping']


def test_shot_source_window_shift_revalidates_overlapping_audio_and_visual(generated_media_work):
    work = generated_media_work
    candidate = copy.deepcopy(work['document'])
    candidate['plan']['clips'][0].update(start=0.04, end=1)
    authorization = scope(clips=['clip'])
    authorization.update(freeze_positions=[], freeze_duration=False)
    with pytest.raises(ValueError, match='AUDIO_REVIEW_SCOPE_REQUIRED'):
        inspect(work, candidate, authorization)
    authorization['audio_ids'] = ['music']
    with pytest.raises(ValueError, match='VISUAL_REVIEW_SCOPE_REQUIRED'):
        inspect(work, candidate, authorization)
    authorization['visual_ids'] = ['inset']
    report = inspect(work, candidate, authorization)
    assert report['required_stages'] == list(revision_impact.STAGES[1:])
    assert report['changed_clip_ids'] == ['clip']


@pytest.mark.parametrize('field,key,scope_key,category', [
    ('audio_tracks', 'music', 'audio_ids', 'audio-source-identity'),
    ('visual_layers', 'inset', 'visual_ids', 'visual-source-identity'),
])
@pytest.mark.parametrize('change', ['add', 'remove', 'replace'])
def test_external_layer_source_identity_invalidates_analysis_and_content(
        generated_media_work, field, key, scope_key, category, change):
    work = generated_media_work
    original = copy.deepcopy(work['document'][field][key])
    if change == 'add':
        del work['document'][field][key]
    candidate = copy.deepcopy(work['document'])
    if change == 'add':
        candidate[field][key] = original
    elif change == 'remove':
        del candidate[field][key]
    else:
        # A changed reference must be considered even with equal copied bytes.
        replacement = work['root'] / ('replacement-' + field + '.mp4')
        replacement.write_bytes(Path(original['source']['path']).read_bytes())
        candidate[field][key]['source'] = {'path': str(replacement), 'sha256': fixtures.digest(replacement)}
    authorization = scope()
    authorization[scope_key] = [key]
    report = inspect(work, candidate, authorization)
    assert category in report['classification']
    assert report['required_stages'] == list(revision_impact.STAGES)
    assert report['unchanged_dependency_stages'] == []


@pytest.mark.parametrize('field,key,scope_key,patch,category', [
    ('audio_tracks', 'music', 'audio_ids', {'start': 0.04}, 'audio-source-window'),
    ('visual_layers', 'inset', 'visual_ids', {'source_start_frame': 1}, 'visual-source-window'),
])
def test_external_source_window_can_change_content(generated_media_work, field, key, scope_key, patch, category):
    work = generated_media_work
    candidate = copy.deepcopy(work['document'])
    candidate[field][key].update(patch)
    authorization = scope()
    authorization[scope_key] = [key]
    report = inspect(work, candidate, authorization)
    assert category in report['classification']
    assert report['required_stages'] == list(revision_impact.STAGES)
    assert report['unchanged_dependency_stages'] == []
