"""color-grade-adjust: fixed bounded increments and their direction on probe colors.

Pure numerics; proves increments, caps and direction checks, not perceived taste.
"""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
np = pytest.importorskip('numpy')
import editing_runtime as rt  # noqa: E402

BASE = {'schema': 'color-grade/1', 'id': 'base', 'interpretation': 'bt709-sdr-display',
        'ops': [{'type': 'cdl', 'slope': [1.05, 1.0, 0.95], 'offset': [0, 0, 0], 'power': [1, 1, 1], 'saturation': 1.1}]}


def adjust(tmp_path, steps, name='adjust', grade=BASE, **extra):
    return rt.run({'operation': 'color-grade-adjust', 'grade': grade, 'steps': steps, 'adjusted_id': 'base-adjusted',
                   **extra}, tmp_path / name, rt.Tools())


@pytest.mark.parametrize('dimension,probe,key,sign', [
    ('warmth', 'mid-gray', 'delta_b', 1), ('tint', 'mid-gray', 'delta_a', -1), ('exposure', 'mid-gray', 'delta_L', 1),
    ('saturation', 'skin-like', 'delta_chroma', 1)])
@pytest.mark.parametrize('step', [1, -1])
def test_each_step_moves_its_probe_in_the_named_direction(tmp_path, dimension, probe, key, sign, step):
    receipt = adjust(tmp_path, {dimension: step})
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    result = receipt['result']
    assert result['direction_checks'] == {dimension: True}
    assert np.sign(result['probe_effect'][probe][key]) == sign * step
    assert result['grade']['ops'][:1] == BASE['ops'] and result['adopted'] is False


def test_contrast_spreads_or_flattens_the_gray_ramp(tmp_path):
    for step in (2, -2):
        effect = adjust(tmp_path, {'contrast': step}, f'contrast{step}')['result']['probe_effect']
        spread = effect['highlight-gray']['delta_L'] - effect['shadow-gray']['delta_L']
        assert np.sign(spread) == np.sign(step) and abs(effect['mid-gray']['delta_L']) < 0.3


def test_steps_are_cumulative_increments_in_a_fixed_order(tmp_path):
    result = adjust(tmp_path, {'saturation': -1, 'warmth': 2, 'contrast': 1, 'tint': -1, 'exposure': 3})['result']
    assert [op['type'] for op in result['appended_ops']] == ['white_balance', 'exposure', 'curves', 'cdl']
    wb, exposure, curves, cdl = result['appended_ops']
    assert wb['gains'] == [1.05, 0.98, 0.95] and wb['preserve_luminance'] is True
    assert exposure['stops'] == 0.5 and curves['master'][1] == [0.25, 0.23] and curves['master'][3] == [0.75, 0.77]
    assert cdl['saturation'] == 0.92 and result['grade']['ops'] == BASE['ops'] + result['appended_ops']
    compiled = rt.run({'operation': 'color-grade-compile', 'grade': result['grade'], 'lut_size': 17, 'exports': ['cube']},
                      tmp_path / 'compile', rt.Tools())
    assert compiled['status'] == 'SUCCEEDED', compiled.get('error')


def test_base_strength_also_scales_the_adjustment(tmp_path):
    full = adjust(tmp_path, {'warmth': 2}, 'full')['result']['probe_effect']['mid-gray']['delta_b']
    half = adjust(tmp_path, {'warmth': 2}, 'half', grade={**BASE, 'strength': 0.5})['result']['probe_effect']['mid-gray']['delta_b']
    assert half == pytest.approx(full / 2, rel=0.1)


def test_a_clipped_base_cannot_show_the_requested_direction(tmp_path):
    blown = {**BASE, 'ops': [{'type': 'exposure', 'stops': 4}]}
    receipt = adjust(tmp_path, {'warmth': 1}, 'blown', grade=blown)
    assert receipt['status'] == 'FAILED' and 'COLOR_ADJUST_DIRECTION_NOT_OBSERVED: warmth' in receipt['error']


@pytest.mark.parametrize('steps,extra,error', [
    ({'warmth': 4}, {}, 'COLOR_ADJUST_STEP_OVER_CAP: warmth 4 (cap 3)'),
    ({'warmth': 2}, {'caps': {'warmth': 1}}, 'COLOR_ADJUST_STEP_OVER_CAP: warmth 2 (cap 1)'),
    ({'warmth': 1}, {'caps': {'warmth': 5}}, 'COLOR_ADJUST_CAPS_INVALID'),
    ({'vibe': 1}, {}, 'COLOR_ADJUST_DIMENSION_UNSUPPORTED'),
    ({'warmth': True}, {}, 'COLOR_ADJUST_STEP_INTEGER_REQUIRED'),
    ({'warmth': 1.5}, {}, 'COLOR_ADJUST_STEP_INTEGER_REQUIRED'),
    ({'warmth': 0}, {}, 'COLOR_ADJUST_ALL_STEPS_ZERO'),
    ({}, {}, 'COLOR_ADJUST_STEPS_REQUIRED'),
])
def test_request_validation(tmp_path, steps, extra, error):
    receipt = adjust(tmp_path, steps, 'invalid', **extra)
    assert receipt['status'] == 'FAILED' and error in receipt['error'], receipt.get('error')


def test_too_many_ops_is_refused(tmp_path):
    long = {**BASE, 'ops': BASE['ops'] * 14}
    receipt = adjust(tmp_path, {'warmth': 1, 'exposure': 1, 'contrast': 1}, 'long', grade=long)
    assert receipt['status'] == 'FAILED' and 'COLOR_ADJUST_TOO_MANY_OPS' in receipt['error']
