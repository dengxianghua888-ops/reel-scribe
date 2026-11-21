"""color-consistency-check on synthetic media with known colors.

Proves what the gate measures and when it fails; it does not show that any
grade looks good or that a hue range corresponds to skin.
"""
import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
np = pytest.importorskip('numpy')
pytest.importorskip('PIL')
import color_media as cm  # noqa: E402
import color_grade_ops as cg  # noqa: E402
import color_numerics as cn  # noqa: E402
import editing_runtime as rt  # noqa: E402

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')
BT709 = {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'}
ORANGE, BLUE = (200, 140, 110), (40, 80, 170)
SKIN = {'kind': 'hue-range', 'segments': ['all'], 'hue_degrees': [20, 80], 'min_chroma': 10,
        'max_median_delta_e2000': 2.0, 'action': 'fail'}


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def cube(tmp_path, name, ops, size=33):
    spec = cg.normalize({'schema': 'color-grade/1', 'id': name, 'interpretation': 'bt709-sdr-display', 'ops': ops})
    grid = cn.identity_table(size)
    table = cg.evaluate(*spec, grid.reshape(-1, 3)).reshape(grid.shape)
    path = tmp_path / f'{name}.cube'
    path.write_text(cn.cube_text(table, name), encoding='utf-8')
    return path


def apply(tmp_path, video, name, layers):
    receipt = rt.run({'operation': 'color-lut-apply', 'source': ref(video), 'input_color': BT709,
                      'interpolation': 'tetrahedral', 'layers': layers}, tmp_path / f'apply-{name}', rt.Tools())
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    return Path(receipt['result']['video']['path'])


def run_check(tmp_path, reference, candidate, name, segments=None, **extra):
    request = {'operation': 'color-consistency-check', 'reference': ref(reference), 'candidate': ref(candidate),
               'input_color': BT709, 'segments': segments or [{'id': 'all', 'start_frame': 0, 'end_frame': 25}],
               'samples_per_segment': 3, **extra}
    return rt.run(request, tmp_path / f'check-{name}', rt.Tools())


@pytest.fixture
def media(tmp_path):
    png = cm.image(tmp_path / 'two.png', [(ORANGE, 0.5), (BLUE, 0.5)], size=(96, 64))
    video = cm.encode_sdr(png, tmp_path / 'two.mp4', seconds=1)  # 25 frames: orange left, blue right
    blue_only = cube(tmp_path, 'blue-only', [{'type': 'hsl', 'bands': {'blue': {'hue': 30, 'saturation': 0.3, 'lightness': 15}}}])
    swap = cube(tmp_path, 'swap', [{'type': 'cdl', 'slope': [1, 1, 1], 'offset': [0, 0, 0], 'power': [1, 1, 1],
                                     'saturation': 0.0}])
    return {'video': video, 'blue_only': apply(tmp_path, video, 'blue', [{'lut': ref(blue_only), 'ranges': [[0, 25]]}]),
            'gray': apply(tmp_path, video, 'gray', [{'lut': ref(swap), 'ranges': [[0, 25]]}])}


def test_protections_keep_untouched_colors_and_catch_changed_ones(tmp_path, media):
    protections = {'skin-like': SKIN,
                   'orange-box': {'kind': 'region', 'segments': ['all'], 'box': [0.05, 0.1, 0.45, 0.9],
                                  'max_median_delta_e2000': 2.0, 'action': 'fail'},
                   'blue-box': {'kind': 'region', 'segments': ['all'], 'box': [0.55, 0.1, 0.95, 0.9],
                                'max_median_delta_e2000': 2.0, 'action': 'flag'}}
    receipt = run_check(tmp_path, media['video'], media['blue_only'], 'blue', protections=protections)
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    result = receipt['result']
    rows = result['protections']
    assert rows['skin-like']['status'] == 'KEPT' and rows['skin-like']['median_delta_e2000'] < 1.0
    assert rows['orange-box']['status'] == 'KEPT'
    assert rows['blue-box']['status'] == 'VIOLATED' and rows['blue-box']['median_delta_e2000'] > 5
    assert result['gate'] == 'FLAGGED' and result['failures'] == [] and result['flags'] == ['protection blue-box violated']
    # Desaturating everything breaks the orange protection; with action fail the gate fails.
    result = run_check(tmp_path, media['video'], media['gray'], 'gray', protections={'skin-like': SKIN})['result']
    assert result['protections']['skin-like']['status'] == 'VIOLATED' and result['gate'] == 'FAILED'


def test_unmeasurable_protection_is_not_a_pass(tmp_path, media):
    green = {**SKIN, 'hue_degrees': [120, 170]}
    result = run_check(tmp_path, media['video'], media['blue_only'], 'green-fail', protections={'green': green})['result']
    assert result['protections']['green']['status'] == 'UNMEASURED' and result['gate'] == 'FAILED'
    result = run_check(tmp_path, media['video'], media['blue_only'], 'green-flag',
                       protections={'green': {**green, 'action': 'flag'}})['result']
    assert result['gate'] == 'FLAGGED'


def test_without_declared_thresholds_numbers_are_reported_and_the_gate_passes(tmp_path, media):
    result = run_check(tmp_path, media['video'], media['gray'], 'report')['result']
    assert result['gate'] == 'PASSED' and result['protections'] == {} and result['limits'] == {}
    segment = result['segments'][0]
    assert segment['sampled_frames'] == [4, 12, 20]
    assert segment['reference']['flicker_max_delta_l'] < 0.5 and segment['candidate']['out_of_range_fraction'] == 0


def test_declared_limits_catch_flicker_clipping_drift_and_illegal_luma(tmp_path, media):
    video = media['video']
    bright = cube(tmp_path, 'bright', [{'type': 'exposure', 'stops': 3}])
    # Frames 5, 13 and 21 follow the sampled frames 4, 12 and 20: a grade on them alone is flicker.
    flicker = apply(tmp_path, video, 'flicker', [{'lut': ref(bright), 'ranges': [[5, 6], [13, 14], [21, 22]]}])
    result = run_check(tmp_path, video, flicker, 'flicker', limits={'max_flicker_increase': 2.0})['result']
    assert result['gate'] == 'FAILED' and result['failures'] == ['flicker increase in segment all']
    clipped = apply(tmp_path, video, 'clipped', [{'lut': ref(bright), 'ranges': [[0, 25]]}])
    result = run_check(tmp_path, video, clipped, 'clip', limits={'max_clip_increase': 0.05})['result']
    assert result['segments'][0]['clip_increase']['highlight_clipped'] > 0.4 and result['gate'] == 'FAILED'
    halves = [{'id': 'first', 'start_frame': 0, 'end_frame': 12}, {'id': 'second', 'start_frame': 12, 'end_frame': 25}]
    drifted = apply(tmp_path, video, 'drift', [{'lut': ref(bright), 'ranges': [[12, 25]]}])
    result = run_check(tmp_path, video, drifted, 'drift', segments=halves, limits={'max_drift_increase': 5})['result']
    assert result['drift'][0]['reference_delta_e2000'] < 1 and result['drift'][0]['increase'] > 5
    assert result['failures'] == ['drift increase between first and second']
    superwhite = tmp_path / 'superwhite.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-vf', 'lutyuv=y=250,' + cm.frame_tags(
        colorspace='bt709', color_primaries='bt709', color_trc='bt709', color_range='tv'), '-c:v', 'libx264', '-qp', '0',
        '-preset', 'ultrafast', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709',
        '-color_range', 'tv', str(superwhite)], check=True, timeout=120)
    result = run_check(tmp_path, video, superwhite, 'legal', limits={'max_out_of_range_fraction': 0.01})['result']
    assert result['segments'][0]['candidate']['out_of_range_fraction'] == 1 and result['gate'] == 'FAILED'


@pytest.mark.parametrize('change,error', [
    (lambda r: r.update(segments=[{'id': 'a', 'start_frame': 0, 'end_frame': 12}, {'id': 'b', 'start_frame': 10, 'end_frame': 25}]),
     'COLOR_CHECK_SEGMENT_OUTSIDE_OR_UNSORTED'),
    (lambda r: r.update(segments=[{'id': 'a', 'start_frame': 0, 'end_frame': 26}]), 'COLOR_CHECK_SEGMENT_OUTSIDE_OR_UNSORTED'),
    (lambda r: r.update(protections={'p': {**SKIN, 'segments': ['missing']}}), 'COLOR_CHECK_PROTECTION_SEGMENTS_INVALID'),
    (lambda r: r.update(protections={'p': {**SKIN, 'hue_degrees': [20, 400]}}), 'COLOR_CHECK_HUE_RANGE_INVALID'),
    (lambda r: r.update(protections={'p': {**SKIN, 'kind': 'skin'}}), 'COLOR_CHECK_PROTECTION_KIND_UNSUPPORTED'),
    (lambda r: r.update(protections={'p': {**SKIN, 'action': 'warn'}}), 'COLOR_CHECK_ACTION_INVALID'),
    (lambda r: r.update(protections={'p': {**SKIN, 'max_median_delta_e2000': 0}}), 'COLOR_CHECK_THRESHOLD_INVALID'),
    (lambda r: r.update(limits={'max_banding': 1}), 'UNKNOWN_FIELD|max_banding'),
    (lambda r: r.update(samples_per_segment=9), 'COLOR_CHECK_SAMPLES_INVALID'),
])
def test_request_validation(tmp_path, media, change, error):
    request = {'operation': 'color-consistency-check', 'reference': ref(media['video']), 'candidate': ref(media['gray']),
               'input_color': BT709, 'segments': [{'id': 'all', 'start_frame': 0, 'end_frame': 25}], 'samples_per_segment': 3}
    change(request)
    receipt = rt.run(request, tmp_path / 'invalid', rt.Tools())
    assert receipt['status'] == 'FAILED'
    assert any(part in receipt['error'] for part in error.split('|')), receipt['error']


def test_videos_must_be_frame_aligned(tmp_path, media):
    longer = cm.encode_sdr(cm.image(tmp_path / 'o.png', [(ORANGE, 1)]), tmp_path / 'longer.mp4', seconds=2)
    receipt = run_check(tmp_path, media['video'], longer, 'misaligned')
    assert receipt['status'] == 'FAILED' and 'COLOR_CHECK_VIDEOS_NOT_ALIGNED' in receipt['error']


def test_hue_mask_needs_chroma_and_wraps_through_zero():
    import color_check_ops
    def lab(hue, chroma):
        return [50, chroma * np.cos(np.radians(hue)), chroma * np.sin(np.radians(hue))]
    points = np.array([lab(45, 0.7), lab(45, 30), lab(350, 30), lab(10, 30), lab(180, 30)])
    assert color_check_ops._hue_mask(points, 20, 80, 10).tolist() == [False, True, False, False, False]
    assert color_check_ops._hue_mask(points, 20, 80, 0).tolist() == [True, True, False, False, False]
    assert color_check_ops._hue_mask(points, 340, 20, 10).tolist() == [False, False, True, True, False]


def test_hue_range_box_limits_the_selection_to_the_declared_area(tmp_path, media):
    # Orange on the left, blue on the right; desaturation changes both.
    left = {**SKIN, 'box': [0.0, 0.0, 0.5, 1.0]}
    right = {**SKIN, 'box': [0.5, 0.0, 1.0, 1.0], 'action': 'flag'}
    result = run_check(tmp_path, media['video'], media['gray'], 'box', protections={'left': left, 'right': right})['result']
    rows = result['protections']
    assert rows['left']['status'] == 'VIOLATED' and rows['left']['box'] == [0.0, 0.0, 0.5, 1.0]
    whole = run_check(tmp_path, media['video'], media['gray'], 'whole', protections={'all': SKIN})['result']['protections']['all']
    assert rows['left']['protected_pixels'] == whole['protected_pixels']  # the orange half holds every orange pixel
    assert rows['right']['status'] == 'UNMEASURED' and rows['right']['protected_pixels'] == 0


def test_flicker_is_compared_pair_by_pair(tmp_path, media):
    video = media['video']
    step = cube(tmp_path, 'step', [{'type': 'exposure', 'stops': 2}])
    small = cube(tmp_path, 'small', [{'type': 'exposure', 'stops': 0.5}])
    # The reference already has a big natural change between frames 4 and 5.
    reference = apply(tmp_path, video, 'stepped', [{'lut': ref(step), 'ranges': [[5, 25]]}])
    # The grade adds a smaller flash on frame 13 only, right after the sampled frame 12.
    flashed = apply(tmp_path, reference, 'flash', [{'lut': ref(small), 'ranges': [[13, 14]]}])
    segment = run_check(tmp_path, reference, flashed, 'pairs', limits={'max_flicker_increase': 2.0})['result']
    row = segment['segments'][0]
    assert row['reference']['flicker_max_delta_l'] > row['flicker_increase'] > 2.0
    assert segment['failures'] == ['flicker increase in segment all']
