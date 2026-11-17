from __future__ import annotations

from pathlib import Path

import pytest

from douyin_film_recap.media import find_sidecar_subtitle, merge_shots_to_units, build_scene_index
from douyin_film_recap.models import SourceInfo, SourceManifest, Storyboard, StoryboardSegment, TranscriptDocument, VisualReference
from douyin_film_recap.pipeline import FilmRecapPipeline
from douyin_film_recap.state import STAGES
from douyin_film_recap.tts import synthesize_storyboard
from douyin_film_recap.utils import content_fingerprint, write_json


def pipeline(tmp_path, config, monkeypatch):
    source = tmp_path / 'source.mp4'
    source.write_bytes(b'input fixture; provider and media are not called')
    monkeypatch.setattr('douyin_film_recap.pipeline.OpenAICompatibleClient', lambda _: object())
    return FilmRecapPipeline(input_path=source, work_dir=tmp_path / 'run', config=config)


def board(tmp_path, segments=None):
    source = SourceInfo(source_id='src', path=str(tmp_path/'source.mp4'), fingerprint='fixture', filename='source.mp4', duration=100, width=640, height=360, fps=25)
    return Storyboard(project_name='test', sources=[source], plan_fingerprint='p', target_duration_sec=4, segments=segments or [])


def voiceover(segment_id='vo', text='现在开始'):
    return StoryboardSegment(segment_id=segment_id, beat_id='b', mode='voiceover', title='test', text=text, visuals=[VisualReference(source_id='src', start=0, end=4)], audio_owner='narration', planned_duration_sec=4, notes='')


def test_sidecar_exact_then_language_never_numeric_prefix(tmp_path):
    video = tmp_path / '1.mp4'
    (tmp_path / '10.srt').write_text('wrong episode')
    assert find_sidecar_subtitle(video) is None
    language = tmp_path / '1.zh-CN.srt'
    language.write_text('correct episode')
    assert find_sidecar_subtitle(video) == language.resolve()
    exact = tmp_path / '1.SRT'
    exact.write_text('explicit choice')
    assert find_sidecar_subtitle(video) == exact.resolve()


@pytest.mark.parametrize('names', [('movie.zh.srt', 'movie.en.srt'), ('movie.zh.srt', 'movie.zh.ass')])
def test_ambiguous_subtitle_is_blocked(tmp_path, names):
    for name in names:
        (tmp_path / name).write_text('subtitle')
    with pytest.raises(ValueError, match='Ambiguous sidecar'):
        find_sidecar_subtitle(tmp_path / 'movie.mp4')


def test_sidecar_add_modify_delete_invalidates_input(tmp_path, app_config, monkeypatch):
    p = pipeline(tmp_path, app_config, monkeypatch)
    previous = p.state.input_fingerprint
    sidecar = tmp_path / 'source.srt'
    prior = p.work_dir / '01_transcript.json'
    prior.write_text('{}')
    for operation in ('add', 'modify', 'delete'):
        prior = p.work_dir / '01_transcript.json'
        prior.write_text('{}')
        p.store.pass_stage(p.state, 'transcript', artifact=str(prior))
        if operation == 'delete':
            sidecar.unlink()
        else:
            sidecar.write_text(operation)
        p = FilmRecapPipeline(input_path=tmp_path/'source.mp4', work_dir=tmp_path/'run', config=app_config)
        assert p.state.input_fingerprint != previous
        assert p.state.stages['transcript'].status == 'pending'
        previous = p.state.input_fingerprint


def test_nested_work_directory_rejected_before_provider(tmp_path, app_config, monkeypatch):
    (tmp_path/'source.mp4').write_bytes(b'fixture')
    monkeypatch.setattr('douyin_film_recap.pipeline.OpenAICompatibleClient', lambda _: pytest.fail('provider must not initialize'))
    with pytest.raises(ValueError, match='outside the input'):
        FilmRecapPipeline(input_path=tmp_path, work_dir=tmp_path/'work', config=app_config)


def test_source_cannot_overlap_generated_output(tmp_path, app_config, monkeypatch):
    source = tmp_path / 'output' / 'final.mp4'
    source.parent.mkdir()
    source.write_bytes(b'user source must survive')
    with pytest.raises(ValueError, match='protect source files'):
        FilmRecapPipeline(input_path=source, work_dir=tmp_path, config=app_config)
    assert source.read_bytes() == b'user source must survive'


def test_missing_final_invalidates_and_reruns_post_qc_and_delivery(tmp_path, app_config, monkeypatch):
    p = pipeline(tmp_path, app_config, monkeypatch)
    monkeypatch.setattr(p, '_stage_inputs', lambda stage: 'stable-input')
    for stage in STAGES:
        path = p.work_dir/f'{stage}.json'
        path.write_text(stage)
        p.store.pass_stage(p.state, stage, artifact=str(path), artifacts={str(path):content_fingerprint(path)}, input_fingerprint='stable-input')
    write_json(p.paths['storyboard'], board(tmp_path))
    Path(p.state.stages['render'].artifact).unlink()
    executed = []
    def run_stage(stage):
        executed.append(stage)
        p.state.stages[stage].status = 'passed'
    monkeypatch.setattr(p, '_run_stage', run_stage)
    p.run()
    assert executed == ['render', 'post_qc', 'delivery']


def test_missing_secondary_story_artifact_invalidates_cache(tmp_path, app_config, monkeypatch):
    p = pipeline(tmp_path, app_config, monkeypatch)
    monkeypatch.setattr(p, '_stage_inputs', lambda _: 'inputs')
    files = [p.paths[name] for name in ('story', 'characters', 'knowledge')]
    for file in files:
        file.write_text('{}')
    p.store.pass_stage(p.state, 'story', artifact=str(files[0]), artifacts={str(f):content_fingerprint(f) for f in files}, input_fingerprint='inputs')
    assert p._artifact_exists('story')
    files[1].unlink()
    assert not p._artifact_exists('story')


def test_shared_storyboard_runtime_fields_do_not_invalidate_qc(tmp_path, app_config, monkeypatch):
    p = pipeline(tmp_path, app_config, monkeypatch)
    sb = board(tmp_path, [voiceover()])
    write_json(p.paths['storyboard'], sb)
    for name in ('manifest','transcript','characters','story','knowledge','highlights','plan'):
        p.paths[name].write_text('{}')
    before = p._stage_inputs('pre_qc')
    sb.output = {'final_video':'new.mp4'}
    sb.segments[0].status = 'rendered'
    sb.segments[0].rendered_file = 'clip.mp4'
    sb.segments[0].rendered_duration_sec = 4
    write_json(p.paths['storyboard'], sb)
    assert p._stage_inputs('pre_qc') == before
    sb.segments[0].text = '人工修改文案'
    write_json(p.paths['storyboard'], sb)
    assert p._stage_inputs('pre_qc') != before


def test_explicit_downstream_resume_preserves_manual_plan(tmp_path, app_config, monkeypatch):
    p = pipeline(tmp_path, app_config, monkeypatch)
    path = p.paths['plan']; path.write_text('{"before":true}')
    monkeypatch.setattr(p, '_stage_inputs', lambda _: 'inputs')
    p.store.pass_stage(p.state, 'plan', artifact=str(path), artifacts={str(path):content_fingerprint(path)}, input_fingerprint='inputs')
    path.write_text('{"manual":"keep this"}')
    p._adopt_manual_artifacts('storyboard')
    assert p._artifact_exists('plan')
    assert path.read_text() == '{"manual":"keep this"}'


def test_long_shot_windows_cover_source_without_exceeding_limit():
    units = merge_shots_to_units([(0, 61)], min_unit=4, max_unit=16)
    assert units[0][0][0] == 0
    assert units[-1][-1][1] == 61
    assert all(group[-1][1] - group[0][0] <= 16 for group in units)
    assert all(left[-1][1] == right[0][0] for left, right in zip(units, units[1:]))
    assert sum(end-start for group in units for start,end in group) == 61


def test_split_windows_preserve_original_shot_identity(tmp_path, app_config, monkeypatch):
    from douyin_film_recap.models import SceneDetectionMetadata

    sb = board(tmp_path)
    sb.sources[0].duration = 40
    manifest = SourceManifest(sources=sb.sources, config_fingerprint='fixture')
    transcript = TranscriptDocument(provider='fixture', segments=[], source_fingerprints={'src':'fixture'})
    monkeypatch.setattr('douyin_film_recap.media.detect_shots_with_metadata', lambda *args: (
        [(0, 40)], SceneDetectionMetadata(detector_requested="scenedetect",
                                          detector_used="scenedetect",
                                          boundary_confidence="detector_estimated")))
    monkeypatch.setattr('douyin_film_recap.media.extract_frames_batch', lambda *args: None)
    monkeypatch.setattr('douyin_film_recap.media.make_contact_sheet', lambda *args: None)
    monkeypatch.setattr('douyin_film_recap.media.motion_score', lambda *args: 0)
    index = build_scene_index(manifest, transcript, app_config, tmp_path/'run')
    assert len(index.units) == 3
    assert all(unit.original_shot_spans == [(0, 40)] for unit in index.units)
    assert len({tuple(unit.continuity_shot_ids) for unit in index.units}) == 1
    assert all(unit.analysis_window_only for unit in index.units)


def test_tts_resume_reuses_completed_segment_and_retries_failure(tmp_path, app_config, monkeypatch):
    sb = board(tmp_path, [voiceover('first'), voiceover('second')])
    calls = []
    fail = {'enabled': True}
    def synth(*, text, output_path, config, intent_key=None):
        calls.append(str(output_path))
        if output_path.name.startswith('second') and fail['enabled']:
            raise RuntimeError('interrupted provider')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b'local audio fixture')
        return [{'text':text, 'start':0, 'duration':4}]
    monkeypatch.setattr('douyin_film_recap.tts.synthesize_edge_tts', synth)
    monkeypatch.setattr('douyin_film_recap.tts.media_duration', lambda _: 4)
    with pytest.raises(RuntimeError, match='interrupted provider'):
        synthesize_storyboard(sb.model_copy(deep=True), app_config, object(), tmp_path/'run')
    fail['enabled'] = False
    result = synthesize_storyboard(sb.model_copy(deep=True), app_config, object(), tmp_path/'run')
    assert sum(Path(path).name.startswith('first') for path in calls) == 1
    assert sum(Path(path).name.startswith('second') for path in calls) == 2
    assert all(segment.audio_duration_sec == 4 for segment in result.segments)
    calls.clear()
    result.segments[0].text = '新的文案'
    synthesize_storyboard(result, app_config, object(), tmp_path/'run')
    assert len(calls) == 1 and Path(calls[0]).name.startswith('first')


def test_receipts_survive_full_stage_cycle_and_revalidate_changed_video(tmp_path, app_config, monkeypatch):
    """Exercise real run/start/pass receipts; stub only expensive stage bodies."""
    p = pipeline(tmp_path, app_config, monkeypatch)
    executed = []
    sb = board(tmp_path)
    primary = {'ingest':'manifest','transcript':'transcript','scenes':'scene_index',
               'scene_analysis':'scene_analysis','story':'story','highlights':'highlights',
               'plan':'plan','storyboard':'storyboard','tts':'storyboard',
               'pre_qc':'pre_qc','post_qc':'post_qc','delivery':'delivery'}
    def handler(stage):
        def execute():
            executed.append(stage)
            if stage == 'ingest':
                write_json(p.paths['manifest'], SourceManifest(sources=sb.sources,config_fingerprint='f'))
            elif stage == 'transcript':
                write_json(p.paths['transcript'], TranscriptDocument(provider='fixture', segments=[], source_fingerprints={'src':'fixture'}))
            elif stage == 'scenes':
                write_json(p.paths['scene_index'], {'units':[], 'source_fingerprints':{}, 'detector':'fixture'})
            elif stage == 'story':
                for name in ('story','characters','knowledge'):
                    write_json(p.paths[name], {})
            elif stage in {'storyboard','tts'}:
                write_json(p.paths['storyboard'], sb)
                p.paths['script'].parent.mkdir(parents=True,exist_ok=True)
                p.paths['script'].write_text('script '+stage)
            elif stage == 'render':
                output = p.work_dir/'output'; output.mkdir(exist_ok=True)
                sb.output = {}
                for key, name in [('final_video','final.mp4'),('preview_video','preview.mp4'),('subtitle','master.srt'),('edl','edit_decision_list.json')]:
                    file=output/name; file.write_text('fixture '+stage+key)
                    sb.output[key]=str(file)
                write_json(p.paths['storyboard'],sb)
                return Path(sb.output['final_video'])
            elif stage == 'delivery':
                p.paths['delivery'].write_text('delivery')
            else:
                write_json(p.paths[primary[stage]], {})
            return p.paths[primary[stage]]
        return execute
    for stage in STAGES:
        monkeypatch.setattr(p, '_stage_'+stage, handler(stage))
    p.run()
    assert executed == STAGES
    executed.clear()
    p.run()
    assert executed == []
    Path(sb.output['final_video']).write_text('externally replaced')
    p.run()
    assert executed == ['render','post_qc','delivery']


def test_tts_uses_resolved_plan_rate_without_mutating_config(tmp_path, app_config, monkeypatch):
    from types import SimpleNamespace
    p = pipeline(tmp_path, app_config, monkeypatch)
    original = app_config.format.vo_chars_per_sec
    monkeypatch.setattr(p, '_plan', lambda: SimpleNamespace(
        duration_mode='short', resolved_constraints={'vo_chars_per_sec': [3.0, 4.0]},
        rhythm=SimpleNamespace(vo_chars_per_sec=(4.2, 5.2)),
    ))
    effective = p._effective_tts_config()
    assert effective.format.vo_chars_per_sec == (3.0, 4.0)
    assert app_config.format.vo_chars_per_sec == original


def test_original_cues_verified_only_against_matching_transcript_source(tmp_path, app_config, monkeypatch):
    p = pipeline(tmp_path, app_config, monkeypatch)
    seg = voiceover(); seg.mode='original'; seg.audio_owner='action_sound'
    sb = board(tmp_path,[seg])
    manifest = SourceManifest(sources=sb.sources,config_fingerprint='fixture')
    transcript = TranscriptDocument(provider='fixture',segments=[],source_fingerprints={})
    monkeypatch.setattr(p, '_manifest', lambda: manifest)
    monkeypatch.setattr(p, '_transcript', lambda: transcript)
    p._attach_original_cues(sb)
    assert not seg.original_cues_verified
    transcript.source_fingerprints={'src':'wrong-source-version'}
    p._attach_original_cues(sb)
    assert not seg.original_cues_verified
    transcript.source_fingerprints={'src':'fixture'}
    p._attach_original_cues(sb)
    assert seg.original_cues_verified and seg.original_cues == []


def test_exact_sidecar_preserves_documented_format_priority(tmp_path):
    for extension in ('.ssa', '.vtt', '.ass', '.srt'):
        (tmp_path/('movie'+extension)).write_text(extension)
    assert find_sidecar_subtitle(tmp_path/'movie.mp4') == (tmp_path/'movie.srt').resolve()
    (tmp_path/'movie.srt').unlink()
    assert find_sidecar_subtitle(tmp_path/'movie.mp4') == (tmp_path/'movie.ass').resolve()
