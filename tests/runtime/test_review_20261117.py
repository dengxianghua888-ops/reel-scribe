"""Regressions from the 2026-11-17 repository review.

Fake tools supply ffprobe-shaped metadata only; no media is decoded and these
tests make no audiovisual or editorial quality claim.
"""
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import editing_runtime
from editing_runtime import ContractError, frame_rate, verified_json
import overlay_ops
import reframe_ops


def reference(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


class NoTools:
    def doctor(self):
        return {}


def test_unexpected_exception_still_writes_failed_receipt(tmp_path, monkeypatch):
    def defect(request, directory, tools):
        (directory / 'partial.txt').write_text('kept', encoding='utf-8')
        return Fraction('0/0')

    monkeypatch.setattr(editing_runtime, 'execute', defect)
    directory = tmp_path / 'run'
    receipt = editing_runtime.run({'operation': 'media-inspect'}, directory, NoTools())
    assert receipt['status'] == 'FAILED'
    assert receipt['error'].startswith('INTERNAL_ERROR: ZeroDivisionError')
    stored = json.loads((directory / 'receipt.json').read_text(encoding='utf-8'))
    assert stored['status'] == 'FAILED' and stored['internal_error'] is True
    names = {row['path'] for row in stored['artifacts']}
    assert {'request.json', 'partial.txt', 'internal-error-traceback.txt'} <= names


def test_non_json_request_is_rejected_before_creating_directory(tmp_path):
    directory = tmp_path / 'run'
    with pytest.raises(ContractError, match='REQUEST_JSON_INVALID'):
        editing_runtime.run({'operation': 'media-inspect', 'value': float('nan')}, directory, NoTools())
    assert not directory.exists()


@pytest.mark.parametrize('value,expected', [('0/0', 0), (None, 0), ('', 0), ('N/A', 0),
                                            ('30000/1001', Fraction(30000, 1001)), ('25/1', 25)])
def test_frame_rate_unknown_values_are_zero(value, expected):
    assert frame_rate(value) == expected


class UnknownRateTools:
    def probe(self, path):
        return {'duration': 1.0, 'format': {}, 'streams': [{
            'index': 0, 'codec_type': 'video', 'pix_fmt': 'yuv420p', 'width': 64, 'height': 64,
            'sample_aspect_ratio': '1:1', 'avg_frame_rate': '0/0', 'r_frame_rate': '0/0'}]}


def test_reframe_unknown_frame_rate_is_a_contract_error(tmp_path):
    media = tmp_path / 'source.mp4'
    media.write_bytes(b'not decoded by this test')
    request = {'operation': 'video-reframe', 'source': reference(media), 'crop': [0, 0, 64, 64],
               'canvas': [64, 64], 'placement': [0, 0, 64, 64], 'background_rgb': [0, 0, 0],
               'allow_upscale': False, 'input_color': 'bt709-sdr-limited'}
    with pytest.raises(ContractError, match='REFRAME_CFR_REQUIRED'):
        reframe_ops.reframe(request, tmp_path, UnknownRateTools())


def test_overlay_unknown_frame_rate_is_a_contract_error(tmp_path):
    media = tmp_path / 'base.mp4'
    media.write_bytes(b'not decoded by this test')
    with pytest.raises(ContractError, match='OVERLAY_CFR_REQUIRED'):
        overlay_ops.video_info(reference(media), UnknownRateTools())


def test_verified_json_parses_exactly_the_hashed_bytes(tmp_path, monkeypatch):
    path = tmp_path / 'markers.json'
    path.write_text(json.dumps({'schema': 'original'}), encoding='utf-8')
    ref = reference(path)
    artifact, data = verified_json(ref, 'MARKER')
    assert data == {'schema': 'original'} and artifact['sha256'] == ref['sha256']

    original_source = editing_runtime.source

    def replace_after_hash(value, *args, **kwargs):
        result = original_source(value, *args, **kwargs)
        path.write_text(json.dumps({'schema': 'substituted'}), encoding='utf-8')
        return result

    monkeypatch.setattr(editing_runtime, 'source', replace_after_hash)
    with pytest.raises(ContractError, match='SOURCE_HASH_MISMATCH'):
        verified_json(ref, 'MARKER')


def test_verified_json_reports_invalid_and_oversized_payloads(tmp_path):
    broken = tmp_path / 'broken.json'
    broken.write_bytes(b'{not json')
    with pytest.raises(ContractError, match='SYNC_EVIDENCE_JSON_INVALID'):
        verified_json(reference(broken), 'SYNC_EVIDENCE')
    large = tmp_path / 'large.json'
    large.write_bytes(b'[' + b'0,' * 10 + b'0]')
    with pytest.raises(ContractError, match='ASR_MODEL_LOCK_FILE_TOO_LARGE'):
        verified_json(reference(large), 'ASR_MODEL_LOCK', limit=8)


def test_still_image_decodes_the_hashed_buffer(tmp_path, monkeypatch):
    Image = pytest.importorskip('PIL.Image')
    import still_ops
    path = tmp_path / 'still.png'
    Image.new('RGB', (8, 8), (10, 20, 30)).save(path)
    ref = reference(path)
    substitute = tmp_path / 'other.png'
    Image.new('RGB', (8, 8), (200, 0, 0)).save(substitute)
    original_source = editing_runtime.source

    def replace_after_hash(value, *args, **kwargs):
        result = original_source(value, *args, **kwargs)
        if value == ref:
            path.write_bytes(substitute.read_bytes())
        return result

    monkeypatch.setattr(editing_runtime, 'source', replace_after_hash)
    request = {'operation': 'still-image-render', 'source': ref, 'frames': 2, 'fps': '24',
               'width': 8, 'height': 8, 'interpolation': 'linear', 'background_rgb': [0, 0, 0],
               'allow_upscale': False, 'input_color': 'srgb',
               'crop_keyframes': [{'frame': 0, 'rect': [0, 0, 8, 8]}, {'frame': 1, 'rect': [0, 0, 8, 8]}]}
    with pytest.raises(ContractError, match='SOURCE_HASH_MISMATCH'):
        still_ops.render_still(request, tmp_path, NoTools())


class CountingClockTools:
    """ffprobe-shaped metadata and decoded-clock observations; no media is read."""
    def __init__(self):
        self.clock_calls = []

    def doctor(self):
        return {}

    def probe(self, path):
        return {'duration': 10.0, 'format': {}, 'streams': [{'index': 0, 'codec_type': 'video'}]}

    def selected_video_clock(self, path, media, start, end):
        self.clock_calls.append((str(path), start, end))
        return {'clock_policy_version': 'selected-video-frames/1', 'stream_index': 0, 'stream_selector': 'v:0',
                'time_base': '1/25', 'observation_window': [str(start), str(end)],
                'observed_intervals': [['0', '10']], 'playback_intervals': [['0', '10']],
                'max_observed_frame_duration': '1/25'}


def _plan(media):
    return {'schema': 'execution-plan/1', 'fps': 25, 'width': 64, 'height': 64, 'fit': 'contain',
            'sources': {'a': reference(media)},
            'clips': [{'id': 'c1', 'source_id': 'a', 'start': 0, 'end': 2, 'gain_db': 0},
                      {'id': 'c2', 'source_id': 'a', 'start': 3, 'end': 5, 'gain_db': 0}]}


def test_timeline_patch_reuses_identical_clock_observations_within_one_run(tmp_path):
    media = tmp_path / 'source.mp4'
    media.write_bytes(b'metadata supplied by fake tools')
    plan = _plan(media)
    tools = CountingClockTools()
    request = {'operation': 'timeline-patch', 'plan': plan, 'expected_revision': editing_runtime.fingerprint(plan),
               'allowed_clip_ids': ['c1'], 'changes': [{'clip_id': 'c1', 'set': {'gain_db': -3}}]}
    receipt = editing_runtime.run(request, tmp_path / 'run', tools)
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    assert receipt['result']['changed_clip_ids'] == ['c1']
    # Base and patched plans share both source windows: observed once each, not twice.
    assert len(tools.clock_calls) == 2


def test_clock_observations_are_not_reused_outside_a_run_or_after_it(tmp_path):
    media = tmp_path / 'source.mp4'
    media.write_bytes(b'metadata supplied by fake tools')
    tools = CountingClockTools()
    first = editing_runtime.normalize_plan(_plan(media), tools)
    second = editing_runtime.normalize_plan(_plan(media), tools)
    assert len(tools.clock_calls) == 4
    assert first['clips'] == second['clips']
    assert editing_runtime.CLOCK_OBSERVATIONS.get() is None


def test_changed_source_bytes_are_rejected_before_cached_clock_reuse(tmp_path, monkeypatch):
    media = tmp_path / 'source.mp4'
    media.write_bytes(b'version one')
    plan = _plan(media)
    tools = CountingClockTools()
    original_normalize = editing_runtime.normalize_plan
    calls = []

    def normalize_then_mutate(value, bound_tools):
        result = original_normalize(value, bound_tools)
        calls.append(True)
        media.write_bytes(b'version two')  # The patched-plan normalization must not reuse.
        return result

    monkeypatch.setattr(editing_runtime, 'normalize_plan', normalize_then_mutate)
    request = {'operation': 'timeline-patch', 'plan': plan, 'expected_revision': editing_runtime.fingerprint(plan),
               'allowed_clip_ids': ['c1'], 'changes': [{'clip_id': 'c1', 'set': {'gain_db': -3}}]}
    receipt = editing_runtime.run(request, tmp_path / 'run', tools)
    assert receipt['status'] == 'FAILED' and 'SOURCE_HASH_MISMATCH' in receipt['error']
    assert len(calls) == 1


def test_tool_output_decoding_is_utf8_and_never_aborts_on_invalid_bytes():
    command = [sys.executable, '-c',
               "import sys; sys.stdout.buffer.write(b'tag:\\xe4\\xb8\\xad\\xff\\n'); sys.stderr.buffer.write(b'\\xfe')"]
    result = editing_runtime.owned_process(command, timeout=30)
    assert result.returncode == 0
    assert result.stdout == 'tag:中�\n' and result.stderr == '�'
