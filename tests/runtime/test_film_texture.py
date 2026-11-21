"""film-texture-apply on synthetic frames with known geometry and levels.

Proves the formulas, determinism and readback; says nothing about taste or film stocks.
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
import color_numerics as cn  # noqa: E402
import editing_runtime as rt  # noqa: E402
import texture_ops  # noqa: E402

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')
BT709 = {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'}
GRAIN = {'amount': 0.03, 'size_px': 0, 'mode': 'luma', 'midtone_weighted': False, 'temporal': 'per-frame', 'seed': 11}


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def still(tmp_path, name, rgb8, size=(128, 96), audio=False, transfer='bt709'):
    from PIL import Image
    png = tmp_path / f'{name}.png'
    Image.fromarray(rgb8.astype(np.uint8) if hasattr(rgb8, 'shape') else
                    np.full((size[1], size[0], 3), rgb8, dtype=np.uint8)).save(png)
    out = tmp_path / f'{name}.mp4'
    tags = cm.frame_tags(colorspace='bt709', color_primaries='bt709', color_trc=transfer, color_range='tv')
    args = ['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-framerate', '25', '-t', '0.4', '-i', str(png)]
    if audio:
        args += ['-f', 'lavfi', '-t', '0.4', '-i', 'sine=frequency=440:sample_rate=48000', '-c:a', 'aac', '-shortest']
    args += ['-vf', f'scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,{tags}', '-c:v', 'libx264', '-qp', '0',
             '-preset', 'ultrafast', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', transfer,
             '-color_range', 'tv', str(out)]
    subprocess.run(args, check=True, timeout=120)
    return out


def run(tmp_path, video, effects, name, color=BT709, frames=(3,)):
    return rt.run({'operation': 'film-texture-apply', 'source': ref(video), 'input_color': color, 'effects': effects,
                   'readback_frames': list(frames)}, tmp_path / f'texture-{name}', rt.Tools())


def frame(video, n, width=128, height=96):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf',
                          f"select='eq(n,{n})',scale=in_color_matrix=bt709:in_range=tv:out_range=pc:"
                          "flags=accurate_rnd+full_chroma_int,format=rgb48le",
                          '-fps_mode', 'passthrough', '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-'],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype='<u2').reshape(height, width, 3) / 65535.0


def test_vignette_darkens_corners_by_the_declared_linear_factor(tmp_path):
    video = still(tmp_path, 'gray', (150, 150, 150))
    receipt = run(tmp_path, video, {'vignette': {'strength': 0.5, 'start': 0.3}}, 'vignette')
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    out = frame(receipt['result']['video']['path'], 3)
    gray = 150 / 255
    corner = cn.inverse_eotf(np.array([cn.eotf(np.array([gray]), 'bt1886')[0] * (1 - 0.5 * 0.97)]), 'bt1886')[0]
    assert abs(out[48, 64].mean() - gray) < 0.01  # center untouched
    assert abs(out[1, 1].mean() - corner) < 0.02  # corner pixel sits at r ~ 0.98 of the half diagonal
    ratio = receipt['result']['readback']['frames'][0]['corner_to_center_luma']
    assert abs(ratio['predicted'] - ratio['output']) < 0.01 and ratio['without_vignette'] == pytest.approx(1, abs=0.01)


def test_halation_adds_a_tinted_glow_around_highlights_only(tmp_path):
    canvas = np.zeros((96, 128, 3))
    canvas[40:56, 56:72] = 255
    video = still(tmp_path, 'spot', canvas)
    receipt = run(tmp_path, video, {'halation': {'threshold': 0.8, 'radius_px': 12, 'strength': 0.8,
                                                 'tint': [1.0, 0.35, 0.15]}}, 'halation')
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    out = frame(receipt['result']['video']['path'], 3)
    ring = out[36, 64]  # just above the white square
    assert ring[0] > ring[1] > ring[2] and ring[0] > 0.2
    assert out[2, 2].max() < 0.02  # far corner stays black
    added = receipt['result']['readback']['frames'][0]['halation_added_mean_rgb']
    assert np.allclose(added['predicted'], added['output'], atol=0.004) and added['output'][0] > added['output'][2] > 0


def test_grain_is_seeded_zero_mean_and_measured(tmp_path):
    video = still(tmp_path, 'mid', (128, 128, 128), audio=True)
    first = run(tmp_path, video, {'grain': GRAIN}, 'first')['result']
    again = run(tmp_path, video, {'grain': GRAIN}, 'again')['result']
    other = run(tmp_path, video, {'grain': {**GRAIN, 'seed': 12}}, 'other')['result']
    assert first['video']['sha256'] == again['video']['sha256'] != other['video']['sha256']
    grain = first['readback']['frames'][0]['grain_luma_std']
    assert grain['predicted'] == pytest.approx(0.03, rel=0.05) and grain['output'] == pytest.approx(grain['predicted'], rel=0.15)
    assert abs(grain['output_minus_prediction_mean']) < 0.002
    assert first['video']['frames'] == 10
    assert any(s.get('codec_type') == 'audio' for s in rt.Tools().probe(first['video']['path'])['streams'])


def test_static_grain_repeats_and_per_frame_grain_changes(tmp_path):
    video = still(tmp_path, 'mid', (128, 128, 128))
    per = run(tmp_path, video, {'grain': GRAIN}, 'per')['result']['video']['path']
    fixed = run(tmp_path, video, {'grain': {**GRAIN, 'temporal': 'static'}}, 'static')['result']['video']['path']
    change = lambda v: np.abs(frame(v, 4) - frame(v, 5)).mean()  # noqa: E731
    assert change(fixed) < 0.004 < change(per)


def test_midtone_weighting_spares_black_and_white():
    rgb = np.zeros((40, 40, 3))
    rgb[:, 20:] = 1.0
    out = texture_ops.apply(rgb, 0, {'grain': {**GRAIN, 'midtone_weighted': True}}, 'bt1886')
    assert np.abs(out - rgb).max() < 1e-12


def test_blur_keeps_the_mean_and_spreads_a_point():
    values = np.zeros((31, 31, 1))
    values[15, 15] = 1.0
    blurred = texture_ops.blur(values, 3)
    assert blurred.sum() == pytest.approx(1.0, abs=1e-9) and blurred[15, 15, 0] < 0.05 and blurred[15, 21, 0] > 0


def test_srgb_tags_are_kept(tmp_path):
    video = still(tmp_path, 'srgb', (120, 90, 60), transfer='iec61966-2-1')
    result = run(tmp_path, video, {'vignette': {'strength': 0.3, 'start': 0.5}}, 'srgb',
                 color={'space': 'srgb-sdr', 'range': 'limited', 'basis': 'verified-metadata'})['result']
    stream = next(s for s in rt.Tools().probe(result['video']['path'])['streams'] if s.get('codec_type') == 'video')
    assert stream.get('color_transfer') == 'iec61966-2-1'


@pytest.mark.parametrize('effects,error', [
    ({}, 'TEXTURE_EFFECTS_INVALID'),
    ({'bloom': {}}, 'TEXTURE_EFFECTS_INVALID'),
    ({'vignette': {'strength': 0.9, 'start': 0.3}}, 'TEXTURE_VIGNETTE_OUT_OF_RANGE'),
    ({'halation': {'threshold': 0.3, 'radius_px': 8, 'strength': 0.5, 'tint': [1, 0.3, 0.1]}}, 'TEXTURE_HALATION_OUT_OF_RANGE'),
    ({'halation': {'threshold': 0.8, 'radius_px': 8, 'strength': 0.5, 'tint': [0, 0, 0]}}, 'TEXTURE_HALATION_TINT_INVALID'),
    ({'grain': {**GRAIN, 'amount': 0.2}}, 'TEXTURE_GRAIN_OUT_OF_RANGE'),
    ({'grain': {**GRAIN, 'mode': 'chroma'}}, 'TEXTURE_GRAIN_MODE_INVALID'),
    ({'grain': {**GRAIN, 'seed': -1}}, 'TEXTURE_GRAIN_SEED_INVALID'),
    ({'grain': {k: v for k, v in GRAIN.items() if k != 'seed'}}, 'seed'),
])
def test_request_validation(tmp_path, effects, error):
    receipt = run(tmp_path, still(tmp_path, 'gray', (100, 100, 100)), effects, 'invalid')
    assert receipt['status'] == 'FAILED' and error in receipt['error'], receipt.get('error')


def test_readback_frames_must_exist(tmp_path):
    receipt = run(tmp_path, still(tmp_path, 'gray', (100, 100, 100)), {'grain': GRAIN}, 'frames', frames=(10,))
    assert receipt['status'] == 'FAILED' and 'TEXTURE_READBACK_FRAMES_INVALID' in receipt['error']
