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
