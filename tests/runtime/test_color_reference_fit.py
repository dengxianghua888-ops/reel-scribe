"""color-reference-fit on synthetic frames whose reference is a known transform of the target.

Proves the statistics, the fit and the reported distances; it does not show that
any fitted grade looks good or "like" a reference.
"""
import hashlib
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
np = pytest.importorskip('numpy')
pytest.importorskip('PIL')
import color_media as cm  # noqa: E402
import color_numerics as cn  # noqa: E402
import editing_runtime as rt  # noqa: E402

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')
BT709 = {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'}
SRGB = {'space': 'srgb-sdr', 'range': 'limited', 'basis': 'verified-metadata'}


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def mosaic(seed=7):
    """96x64 image of 8x8 blocks with random colors kept away from clipping."""
    rng = np.random.default_rng(seed)
    blocks = rng.uniform(0.12, 0.78, size=(8, 12, 3))
    return np.kron(blocks, np.ones((8, 8, 1)))


def video(tmp_path, name, rgb01, transfer='bt709'):
    from PIL import Image
    png = tmp_path / f'{name}.png'
    Image.fromarray(np.round(np.clip(rgb01, 0, 1) * 255).astype(np.uint8)).save(png)
    return cm.encode_sdr(png, tmp_path / f'{name}.mp4', seconds=0.4, transfer=transfer)  # 10 frames


def run_fit(tmp_path, reference, target, method, name, reference_color=BT709, **extra):
    request = {'operation': 'color-reference-fit', 'method': method, 'grade_id': 'match',
               'reference': {'source': ref(reference), 'input_color': reference_color, 'frames': [2, 7]},
               'target': {'source': ref(target), 'input_color': BT709, 'frames': [2, 7]}, **extra}
    return rt.run(request, tmp_path / f'fit-{name}', rt.Tools())


@pytest.fixture
def target(tmp_path):
    return mosaic(), video(tmp_path, 'target', mosaic())


def test_mvgd_recovers_a_per_channel_affine_transform_as_a_cdl(tmp_path, target):
    pixels, target_video = target
    slope, offset = np.array([1.12, 1.0, 0.88]), np.array([0.03, 0.0, -0.02])
    reference = video(tmp_path, 'affine', pixels * slope + offset)
    receipt = run_fit(tmp_path, reference, target_video, 'mvgd', 'mvgd')
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    result = receipt['result']
    op = result['grade']['ops'][0]
    assert op['type'] == 'cdl' and op['power'] == [1.0, 1.0, 1.0]
    assert np.allclose(op['slope'], slope, atol=0.03) and np.allclose(op['offset'], offset, atol=0.015)
    assert abs(op['saturation'] - 1) < 0.03
    before, after = result['distances_to_reference']['before'], result['distances_to_reference']['fitted_grade']
    assert before['mean_color_delta_e2000'] > 3 and after['mean_color_delta_e2000'] < 0.5
    assert after['sliced_wasserstein_lab'] < 0.2 * before['sliced_wasserstein_lab']
    assert result['fit_residual_delta_e2000']['median'] < 0.5
    assert result['adopted'] is False and result['strength'] == 'NOT_CHOSEN'


def test_reinhard_moves_mean_and_spread_toward_a_warmer_reference(tmp_path, target):
    pixels, target_video = target
    lab = cn.lab_from_rgb01(pixels.reshape(-1, 3), 'bt1886')[0]
    warm = lab * np.array([1.0, 0.8, 0.8]) + np.array([3.0, 6.0, 10.0])  # brighter, warmer, less spread in a*/b*
    reference = video(tmp_path, 'warm', cn.rgb01_from_lab(warm, 'bt1886').reshape(pixels.shape))
    result = run_fit(tmp_path, reference, target_video, 'reinhard-lab', 'reinhard')['result']
    details = result['method_details']
    assert np.allclose(details['lab_std_scale'], [1.0, 0.8, 0.8], atol=0.05)
    distances = result['distances_to_reference']
    assert distances['ideal_transfer']['mean_color_delta_e2000'] < 0.5
    assert distances['fitted_grade']['mean_color_delta_e2000'] < 0.3 * distances['before']['mean_color_delta_e2000']
    assert distances['fitted_grade']['js_divergence_lab'] < distances['before']['js_divergence_lab']


def test_histogram_matching_fits_monotone_channel_curves(tmp_path, target):
    pixels, target_video = target
    curved = np.stack([pixels[..., 0] ** 0.8, pixels[..., 1], pixels[..., 2] ** 1.25], axis=-1)
    reference = video(tmp_path, 'curved', curved)
    result = run_fit(tmp_path, reference, target_video, 'histogram', 'histogram')['result']
    op = result['grade']['ops'][0]
    assert op['type'] == 'curves' and set(op) == {'type', 'red', 'green', 'blue'}
    for name in ('red', 'green', 'blue'):
        ys = [y for _, y in op[name]]
        assert all(a <= b for a, b in zip(ys, ys[1:]))
    mid = dict((x, y) for x, y in op['red'])[0.5]
    assert abs(mid - 0.5 ** 0.8) < 0.04  # red lifted like the reference's x**0.8
    distances = result['distances_to_reference']
    assert distances['fitted_grade']['js_divergence_lab'] < 0.3 * distances['before']['js_divergence_lab']


def test_fitted_grade_compiles_and_an_srgb_reference_is_converted_first(tmp_path, target):
    pixels, target_video = target
    reference = video(tmp_path, 'srgb-ref', pixels * 0.9 + 0.05, transfer='iec61966-2-1')
    receipt = run_fit(tmp_path, reference, target_video, 'mvgd', 'cross', reference_color=SRGB)
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    result = receipt['result']
    assert result['domain'].startswith('reference converted') and result['grade']['interpretation'] == 'bt709-sdr-display'
    compiled = rt.run({'operation': 'color-grade-compile', 'grade': result['grade'], 'lut_size': 33, 'exports': ['cube']},
                      tmp_path / 'compile', rt.Tools())
    assert compiled['status'] == 'SUCCEEDED', compiled.get('error')
    repeat = run_fit(tmp_path, reference, target_video, 'mvgd', 'repeat', reference_color=SRGB)['result']
    assert repeat['grade'] == result['grade'] and repeat['distances_to_reference'] == result['distances_to_reference']


@pytest.mark.parametrize('change,error', [
    (lambda r: r.update(method='neural'), 'COLOR_FIT_METHOD_UNSUPPORTED'),
    (lambda r: r.update(grade_id='a#b'), 'COLOR_GRADE_ID_INVALID'),
    (lambda r: r['target'].update(frames=[2, 2]), 'COLOR_FIT_FRAMES_INVALID: target'),
    (lambda r: r['reference'].update(frames=[10]), 'COLOR_FIT_FRAMES_INVALID: reference'),
    (lambda r: r['reference'].update(frames=[]), 'COLOR_FIT_FRAMES_INVALID: reference'),
    (lambda r: r['target'].update(input_color=SRGB), 'METADATA'),
])
def test_request_validation(tmp_path, target, change, error):
    _, target_video = target
    request = {'operation': 'color-reference-fit', 'method': 'mvgd', 'grade_id': 'match',
               'reference': {'source': ref(target_video), 'input_color': BT709, 'frames': [1]},
               'target': {'source': ref(target_video), 'input_color': BT709, 'frames': [1]}}
    change(request)
    receipt = rt.run(request, tmp_path / 'invalid', rt.Tools())
    assert receipt['status'] == 'FAILED' and error in receipt['error'], receipt.get('error')


def test_mvgd_map_is_the_symmetric_monge_kantorovich_solution():
    import color_fit_ops
    rng = np.random.default_rng(3)
    mix = np.array([[0.20, 0.08, 0.02], [0.05, 0.15, 0.06], [0.01, 0.07, 0.18]])
    target = np.clip(0.45 + rng.normal(size=(4000, 3)) @ mix.T * 0.5, 0, 1)
    rotate = np.array([[0.9, 0.3, 0.0], [-0.2, 1.0, 0.2], [0.1, -0.1, 0.8]])
    reference = np.clip(0.5 + (target - 0.45) @ rotate.T, 0, 1)
    _, details = color_fit_ops._ideal('mvgd', target, reference, 'bt1886')
    transform = np.array(details['linear_map'])
    cov_t, cov_r = np.cov(target.T), np.cov(reference.T)
    assert np.allclose(transform, transform.T, atol=1e-5)  # MK map between Gaussians is symmetric positive definite
    assert np.all(np.linalg.eigvalsh(transform) > 0)
    assert np.allclose(transform @ cov_t @ transform, cov_r, atol=1e-4)


def test_cdl_fit_separates_saturation_from_slope():
    import color_fit_ops
    pixels = mosaic().reshape(-1, 3)
    luma = (pixels @ np.array(cn.LUMA_709))[:, None]
    op, _, _ = color_fit_ops._fit_cdl(pixels, np.clip(luma + 1.3 * (pixels - luma), 0, 1), 'bt1886')
    assert abs(op['saturation'] - 1.3) < 0.01 and np.allclose(op['slope'], 1, atol=0.01)


def test_more_saturated_reference_raises_fitted_saturation(tmp_path, target):
    pixels, target_video = target
    luma = (pixels @ np.array(cn.LUMA_709))[..., None]
    reference = video(tmp_path, 'vivid', luma + 1.3 * (pixels - luma))
    result = run_fit(tmp_path, reference, target_video, 'reinhard-lab', 'vivid')['result']
    # Code-value saturation is not a pure CIELAB chroma scale, so Reinhard's ideal mixes contrast and saturation.
    assert result['grade']['ops'][0]['saturation'] > 1.1
    distances = result['distances_to_reference']
    assert distances['fitted_grade']['sliced_wasserstein_lab'] < 0.5 * distances['before']['sliced_wasserstein_lab']


def test_bounds_keep_cdl_and_curves_inside_a_template(tmp_path, target):
    pixels, target_video = target
    reference = video(tmp_path, 'affine', pixels * np.array([1.12, 1.0, 0.88]) + np.array([0.03, 0.0, -0.02]))
    free = run_fit(tmp_path, reference, target_video, 'mvgd', 'free')['result']
    bounded = run_fit(tmp_path, reference, target_video, 'mvgd', 'bounded',
                      bounds={'slope': [0.95, 1.05], 'saturation': [0.9, 1.1], 'curve_max_shift': 0.02})['result']
    op = bounded['grade']['ops'][0]
    assert op['slope'][0] == 1.05 and op['slope'][2] == 0.95 and 0.9 <= op['saturation'] <= 1.1
    assert bounded['bounds']['hit']['slope'] == [True, False, True]
    assert bounded['bounds']['applied'] == {'slope': [0.95, 1.05], 'saturation': [0.9, 1.1]}
    assert bounded['bounds']['ignored'] == ['curve_max_shift']
    distance = lambda r, k: r['distances_to_reference'][k]['sliced_wasserstein_lab']  # noqa: E731
    assert distance(free, 'fitted_grade') < distance(bounded, 'fitted_grade') < distance(bounded, 'before')
    curved = video(tmp_path, 'curved', np.stack([pixels[..., 0] ** 0.8, pixels[..., 1], pixels[..., 2] ** 1.25], axis=-1))
    result = run_fit(tmp_path, curved, target_video, 'histogram', 'shift', bounds={'curve_max_shift': 0.02})['result']
    curves = result['grade']['ops'][0]
    assert all(abs(y - x) <= 0.02 + 1e-9 for name in ('red', 'green', 'blue') for x, y in curves[name])
    assert result['bounds']['hit']['points_clamped']['red'] > 0


@pytest.mark.parametrize('bounds', [{'slope': [1.2, 1.1]}, {'saturation': [0, 3]}, {'contrast': [0, 1]}, {},
                                    {'curve_max_shift': 0}])
def test_bounds_validation(tmp_path, target, bounds):
    _, target_video = target
    receipt = run_fit(tmp_path, target_video, target_video, 'mvgd', 'bad-bounds', bounds=bounds)
    assert receipt['status'] == 'FAILED' and 'COLOR_FIT_BOUNDS_INVALID' in receipt['error'], receipt.get('error')
