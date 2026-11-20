"""color-profile-scan against analytically known synthetic media.

Fixtures are exact 8-bit RGB stills encoded near-losslessly as BT.709 video
(see color_media). Tolerances cover one-code Y'CbCr round-trip error. These
tests prove arithmetic, interpretation and gating; not perception or taste.
"""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import color_media as cm
import editing_runtime as rt

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')
pytest.importorskip('numpy')
pytest.importorskip('PIL')

DECLARED = {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'}


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def lab(rgb):
    """Independent reference: BT.1886 gamma 2.4, BT.709 primaries, D65 CIELAB."""
    m = ((0.4123908, 0.3575843, 0.1804808), (0.2126390, 0.7151687, 0.0721923), (0.0193308, 0.1191948, 0.9505322))
    linear = [(c / 255) ** 2.4 for c in rgb]
    xyz = [sum(m[i][j] * linear[j] for j in range(3)) for i in range(3)]
    white = [sum(row) for row in m]
    def f(t):
        return t ** (1 / 3) if t > (6 / 29) ** 3 else t / (3 * (6 / 29) ** 2) + 4 / 29
    fx, fy, fz = (f(xyz[i] / white[i]) for i in range(3))
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e76(a, b):
    return math.dist(a, b)


def request(source, **changes):
    value = {'operation': 'color-profile-scan', 'source': ref(source), 'start': 0, 'end': 1,
             'samples': {'mode': 'times', 'times': [0.2, 0.6]}, 'analysis_size': [48, 32],
             'input_color': dict(DECLARED), 'palette_colors': 2, 'max_samples': 10}
    value.update(changes)
    return value


def run(tmp_path, req, name='run'):
    receipt = rt.run(req, tmp_path / name, rt.Tools())
    return receipt


@pytest.fixture
def media(tmp_path):
    def make(blocks, name, **encode):
        png = cm.image(tmp_path / (name + '.png'), blocks)
        return cm.encode_sdr(png, tmp_path / (name + '.mp4'), **encode)
    return make


def test_uniform_gray_matches_analytic_lab_and_luma(tmp_path, media):
    receipt = run(tmp_path, request(media([((128, 128, 128), 1)], 'gray')))
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    agg = receipt['result']['aggregate']
    expected = lab((128, 128, 128))
    assert delta_e76((agg['lab_mean']['L'], agg['lab_mean']['a'], agg['lab_mean']['b']), expected) < 0.6
    assert abs(agg['luma']['p50'] - 128 / 255) <= 1.5 / 255 and agg['chroma']['mean'] < 1.0
    assert agg['colorfulness_hasler_susstrunk'] < 1.0
    assert agg['clipping'] == {'highlight_channel_ratio': 0.0, 'shadow_crush_ratio': 0.0}
    assert agg['neutral_estimate']['pixel_share'] == 1.0 and abs(agg['neutral_estimate']['b_mean']) < 1.0
    stored = json.loads((tmp_path / 'run' / 'color-profile.json').read_text(encoding='utf-8'))
    assert stored['aesthetic_judgement'] == 'NOT_PROVIDED' and stored['skin_detection'] == 'NOT_PERFORMED'
    assert not (tmp_path / 'run' / 'samples').exists()
    assert all(len(s['rgb24_sha256']) == 64 for s in stored['samples'])


def test_black_white_split_reports_clipping_and_extreme_percentiles(tmp_path, media):
    receipt = run(tmp_path, request(media([((0, 0, 0), 0.5), ((255, 255, 255), 0.5)], 'split')))
    agg = receipt['result']['aggregate']
    assert agg['clipping']['highlight_channel_ratio'] == pytest.approx(0.5, abs=0.02)
    assert agg['clipping']['shadow_crush_ratio'] == pytest.approx(0.5, abs=0.02)
    assert agg['luma']['p01'] <= 1 / 255 and agg['luma']['p99'] >= 254 / 255


def test_saturated_patch_and_palette_centers_match_analytic_lab(tmp_path, media):
    red, blue = (200, 30, 30), (30, 40, 200)
    receipt = run(tmp_path, request(media([(red, 0.5), (blue, 0.5)], 'two')))
    result = receipt['result']
    colors = result['palette']['colors']
    assert result['palette']['found_colors'] == 2
    assert [round(c['share'], 1) for c in colors] == [0.5, 0.5]
    centers = sorted((c['lab']['L'], c['lab']['a'], c['lab']['b']) for c in colors)
    expected = sorted([lab(red), lab(blue)])
    assert all(delta_e76(a, b) < 2.0 for a, b in zip(centers, expected))
    shares = result['aggregate']['hue_histogram']['shares']
    assert result['aggregate']['hue_histogram']['chromatic_share'] == pytest.approx(1.0, abs=0.02)
    assert sum(shares) == pytest.approx(1.0, abs=1e-6) and sorted(shares)[-2:] == pytest.approx([0.5, 0.5], abs=0.03)


def test_declared_region_reports_vectorscope_angle_of_skin_like_patch(tmp_path, media):
    skin, gray = (224, 172, 140), (128, 128, 128)
    source = media([(skin, 0.5), (gray, 0.5)], 'skin')
    receipt = run(tmp_path, request(source, regions={'declared-face': [0.05, 0.1, 0.45, 0.9]}))
    region = receipt['result']['regions']['declared-face']
    v = [c / 255 for c in skin]
    y = 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2]
    angle = math.degrees(math.atan2((v[0] - y) / 1.5748, (v[2] - y) / 1.8556)) % 360
    assert region['vectorscope']['angle_degrees'] == pytest.approx(angle, abs=1.5)
    assert region['vectorscope']['skin_line_offset_degrees'] == pytest.approx(angle - 123.0, abs=1.5)
    assert region['declared_by'] == 'caller'
    assert delta_e76(tuple(region['lab_mean'][k] for k in 'Lab'), lab(skin)) < 1.5


def test_sample_drift_between_two_colors(tmp_path, media):
    gray = media([((128, 128, 128), 1)], 'g', seconds=1)
    red = media([((200, 30, 30), 1)], 'r', seconds=1)
    listing = tmp_path / 'list.txt'
    listing.write_text(f"file '{gray}'\nfile '{red}'\n", encoding='utf-8')
    joined = tmp_path / 'joined.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', listing, '-c', 'copy', joined], check=True)
    receipt = run(tmp_path, request(joined, end=2, samples={'mode': 'times', 'times': [0.5, 1.5]}))
    temporal = receipt['result']['temporal']
    assert temporal['max_consecutive_delta_e76'] == pytest.approx(delta_e76(lab((128, 128, 128)), lab((200, 30, 30))), abs=2.0)


@pytest.mark.parametrize('transfer', ['arib-std-b67', 'smpte2084'])
def test_real_hdr_encodings_are_refused_not_reinterpreted(tmp_path, media, transfer):
    hdr = cm.encode_hdr(media([((200, 30, 30), 1)], 'sdr'), tmp_path / f'{transfer}.mp4', transfer)
    for basis in ('verified-metadata', 'caller-declared'):
        receipt = run(tmp_path, request(hdr, input_color={**DECLARED, 'basis': basis}), basis)
        assert receipt['status'] == 'FAILED' and 'COLOR_PROFILE_HDR_TRANSFER_UNSUPPORTED' in receipt['error']


def test_conflicting_and_missing_tags(tmp_path, media):
    tagged = media([((128, 128, 128), 1)], 'tagged')
    conflict = cm.retag(tagged, tmp_path / 'bt601.mp4', colorspace='bt470bg', color_primaries='bt709',
                        color_trc='bt709', color_range='tv')
    receipt = run(tmp_path, request(conflict, input_color={**DECLARED, 'basis': 'caller-declared'}), 'conflict')
    assert receipt['status'] == 'FAILED' and 'COLOR_PROFILE_METADATA_CONFLICT: color_space' in receipt['error']
    untagged = media([((128, 128, 128), 1)], 'untagged', tags=False)
    receipt = run(tmp_path, request(untagged), 'strict')
    assert receipt['status'] == 'FAILED' and 'COLOR_PROFILE_METADATA_REQUIRED' in receipt['error']
    receipt = run(tmp_path, request(untagged, input_color={**DECLARED, 'basis': 'caller-declared'}), 'declared')
    assert receipt['status'] == 'SUCCEEDED'
    assert 'color_space' in receipt['result']['stream']['unobserved_tags']
    receipt = run(tmp_path, request(tagged, input_color={**DECLARED, 'range': 'full'}), 'range')
    assert receipt['status'] == 'FAILED' and 'COLOR_PROFILE_METADATA_CONFLICT: color_range' in receipt['error']


@pytest.mark.parametrize('changes,error', [
    ({'samples': {'mode': 'interval', 'interval_seconds': 0.05}, 'max_samples': 10}, 'COLOR_PROFILE_SAMPLE_LIMIT'),
    ({'samples': {'mode': 'times', 'times': [0.5, 0.2]}}, 'COLOR_PROFILE_TIMES_NOT_INCREASING'),
    ({'samples': {'mode': 'times', 'times': [1.0]}}, 'COLOR_PROFILE_TIME_OUTSIDE_RANGE'),
    ({'samples': {'mode': 'interval', 'interval_seconds': 0.5, 'times': [0.1]}}, 'COLOR_PROFILE_SAMPLE_FIELDS_INVALID'),
    ({'analysis_size': [4, 4]}, 'COLOR_PROFILE_ANALYSIS_SIZE_INVALID'),
    ({'palette_colors': 9}, 'COLOR_PROFILE_PALETTE_COLORS_INVALID'),
    ({'max_samples': 601}, 'COLOR_PROFILE_MAX_SAMPLES_INVALID'),
    ({'regions': {'bad': [0.5, 0.5, 0.4, 0.9]}}, 'COLOR_PROFILE_REGION_BOX_INVALID'),
    ({'input_color': {**DECLARED, 'space': 'rec2020'}}, 'COLOR_PROFILE_SPACE_UNSUPPORTED'),
])
def test_request_validation_fails_before_decoding(tmp_path, media, changes, error):
    receipt = run(tmp_path, request(media([((128, 128, 128), 1)], 'v'), **changes))
    assert receipt['status'] == 'FAILED' and error in receipt['error']
    assert not (tmp_path / 'run' / 'color-profile.json').exists()


def test_repeat_runs_are_deterministic(tmp_path, media):
    source = media([((200, 30, 30), 0.3), ((30, 40, 200), 0.3), ((224, 172, 140), 0.4)], 'det')
    a = run(tmp_path, request(source, palette_colors=3), 'a')['result']
    b = run(tmp_path, request(source, palette_colors=3), 'b')['result']
    assert a['aggregate'] == b['aggregate'] and a['palette'] == b['palette'] and a['samples'] == b['samples']


def test_doctor_inventories_color_filters_and_declares_scan_dependencies():
    import dependency_discovery
    root = Path(__file__).resolve().parents[2]
    report = dependency_discovery.inspect(root)
    filters = report['components']['ffmpeg-color-filters']
    assert filters['status'] == 'OBSERVED_NOT_EXECUTED' and filters['filters']['lut3d'] is True
    assert set(filters['routes']) == {'hdr_to_sdr_zscale_tonemap', 'hdr_to_sdr_libplacebo', 'cube_lut'}
    assert report['atomic']['color-profile-scan']['requirements'] == ['python', 'ffmpeg', 'ffprobe', 'numpy']
    missing = dependency_discovery.inspect(root, env={'PATH': ''})
    assert missing['components']['ffmpeg-color-filters']['status'] == 'NEEDS_FFMPEG'


def test_doctor_filter_parser_reports_missing_hdr_routes(monkeypatch):
    import dependency_discovery
    listing = (' ... lut3d             V->V       Adjust colors using a 3D LUT.\n'
               ' T.C eq                V->V       Adjust brightness, contrast, gamma, and saturation.\n'
               ' ... tonemap           V->V       Conversion to/from different dynamic ranges.\n')
    monkeypatch.setattr(dependency_discovery.subprocess, 'run',
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, listing, ''))
    probe = dependency_discovery._color_filters_probe(
        {'status': 'PRESENT_IDENTITY_OBSERVED', 'identity': {'resolved_binary': {'path': '/fixture/ffmpeg'}}})
    assert probe['filters']['lut3d'] and probe['filters']['eq'] and probe['filters']['tonemap']
    assert probe['routes'] == {'hdr_to_sdr_zscale_tonemap': False, 'hdr_to_sdr_libplacebo': False, 'cube_lut': True}


def _pooled_reference(rgb):
    """Independent reference: every statistic over all pixels held in memory at once."""
    import numpy as np
    from color_numerics import lab_from_rgb01
    lab, linear = lab_from_rgb01(rgb / 255.0)
    v = rgb.astype(float) / 255.0
    luma = v @ np.array([0.2126, 0.7152, 0.0722])
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    rg = v[:, 0] * 255 - v[:, 1] * 255
    yb = 0.5 * (v[:, 0] + v[:, 1]) * 255 - v[:, 2] * 255
    neutral = (chroma < 10) & (lab[:, 0] >= 20) & (lab[:, 0] <= 90)
    chromatic = chroma >= 8
    hue = np.degrees(np.arctan2(lab[chromatic, 2], lab[chromatic, 1])) % 360
    return {
        'luma': [luma.mean(), *np.percentile(luma, [1, 5, 50, 95, 99])],
        'chroma': [chroma.mean(), *np.percentile(chroma, [50, 95])],
        'lab_mean': lab.mean(axis=0), 'linear_mean': linear.mean(axis=0),
        'clipping': [(rgb >= 254).any(axis=1).mean(), (rgb <= 1).all(axis=1).mean()],
        'colorfulness': math.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * math.sqrt(rg.mean() ** 2 + yb.mean() ** 2),
        'neutral': [neutral.mean(), lab[neutral, 1].mean(), lab[neutral, 2].mean()],
        'hue': np.bincount((hue // 30).astype(int) % 12, minlength=12) / chromatic.sum(),
        'palette_points': lab if len(lab) <= 20000 else lab[np.linspace(0, len(lab) - 1, 20000).round().astype(int)],
    }


@pytest.mark.parametrize('chunks,pixels', [(3, 997), (37, 4096)])
def test_streamed_pooled_statistics_match_all_pixels_in_memory(chunks, pixels):
    import numpy as np
    import color_profile_ops as cp
    rng = np.random.default_rng(chunks)
    parts = [rng.integers(0, 256, size=(pixels, 3), dtype=np.uint8) for _ in range(chunks)]
    parts[0][:50] = 255
    parts[-1][:50] = 0
    parts[1][:200] = (128, 120, 118)  # near-neutral block
    pooled = cp.PooledStats(chunks * pixels)
    for part in parts:
        lab, linear = cp.lab_from_rgb8(part)
        pooled.add(part, lab, linear, np.hypot(lab[:, 1], lab[:, 2]))
    got = pooled.result()
    want = _pooled_reference(np.concatenate(parts))
    luma = got['luma']
    assert [luma[k] for k in ('mean', 'p01', 'p05', 'p50', 'p95', 'p99')] == pytest.approx(want['luma'], abs=2e-6)
    chroma = got['chroma']
    assert chroma['mean'] == pytest.approx(want['chroma'][0], abs=2e-6)
    assert [chroma['p50'], chroma['p95']] == pytest.approx(want['chroma'][1:], abs=cp.CHROMA_BIN)
    assert [got['lab_mean'][k] for k in 'Lab'] == pytest.approx(list(want['lab_mean']), abs=2e-6)
    assert got['gray_world_linear_ratio']['r_over_g'] == pytest.approx(want['linear_mean'][0] / want['linear_mean'][1], abs=2e-6)
    assert [got['clipping']['highlight_channel_ratio'], got['clipping']['shadow_crush_ratio']] == pytest.approx(want['clipping'], abs=2e-6)
    assert got['colorfulness_hasler_susstrunk'] == pytest.approx(want['colorfulness'], abs=2e-6)
    neutral = got['neutral_estimate']
    assert [neutral['pixel_share'], neutral['a_mean'], neutral['b_mean']] == pytest.approx(want['neutral'], abs=2e-6)
    assert got['hue_histogram']['shares'] == pytest.approx(list(want['hue']), abs=2e-6)
    points = pooled.palette_points()
    assert np.array_equal(points, want['palette_points'])
    assert len(points) == min(chunks * pixels, cp.PALETTE_POINTS)


def test_histogram_percentiles_reproduce_numpy_linear_interpolation():
    import numpy as np
    import color_profile_ops as cp
    values = np.random.default_rng(7).integers(0, 50, size=1001)
    counts = np.bincount(values, minlength=50)
    qs = (0, 1, 5, 33.3, 50, 95, 99, 100)
    assert cp.histogram_percentiles(counts, float, qs) == pytest.approx(list(np.percentile(values, qs)), abs=1e-12)
