"""film-texture-apply on synthetic frames with known geometry and levels.

Proves the formulas, determinism and readback; says nothing about taste or film stocks.
"""
import hashlib
from pathlib import Path
import subprocess
import sys
import threading
import time

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


def still(tmp_path, name, rgb8, size=(128, 96), audio=False, transfer='bt709', seconds=0.4):
    from PIL import Image
    png = tmp_path / f'{name}.png'
    Image.fromarray(rgb8.astype(np.uint8) if hasattr(rgb8, 'shape') else
                    np.full((size[1], size[0], 3), rgb8, dtype=np.uint8)).save(png)
    out = tmp_path / f'{name}.mp4'
    tags = cm.frame_tags(colorspace='bt709', color_primaries='bt709', color_trc=transfer, color_range='tv')
    args = ['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-framerate', '25', '-t', str(seconds), '-i', str(png)]
    if audio:
        args += ['-f', 'lavfi', '-t', '0.4', '-i', 'sine=frequency=440:sample_rate=48000', '-c:a', 'aac', '-shortest']
    args += ['-vf', f'scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,{tags}', '-c:v', 'libx264', '-qp', '0',
             '-preset', 'ultrafast', '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', transfer,
             '-color_range', 'tv', str(out)]
    subprocess.run(args, check=True, timeout=120)
    return out


def derive(tmp_path, video, name, *args):
    """Re-encode or remux a test clip, keeping the color tags verified-metadata needs."""
    out = tmp_path / f'{name}.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *args[:-1], '-i', str(video), *args[-1], '-colorspace', 'bt709',
                    '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv', str(out)], check=True, timeout=120)
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


@pytest.mark.parametrize('setpts,error', [
    ("if(gte(N,5),(N+2)/25/TB,N/25/TB)", 'TEXTURE_CFR_REQUIRED'),  # a gap after frame 4
    ('PTS+0.2/TB', 'TEXTURE_ZERO_ORIGIN_CFR_REQUIRED'),  # constant rate, late start
])
def test_frames_must_keep_a_zero_origin_constant_clock(tmp_path, setpts, error):
    # Raw frames lose their timestamps and are restamped at one rate, which would retime these clips.
    video = derive(tmp_path, still(tmp_path, 'gray', (100, 100, 100)), 'retimed',
                   ['-vf', f"setpts='{setpts}'", '-fps_mode', 'passthrough', '-c:v', 'libx264', '-qp', '0',
                    '-preset', 'ultrafast'])
    receipt = run(tmp_path, video, {'grain': GRAIN}, 'clock')
    assert receipt['status'] == 'FAILED' and error in receipt['error'], receipt.get('error')


def test_rotated_sources_are_refused(tmp_path):
    # FFmpeg autorotates on decode; coded 128x96 frames would come out as 96x128 rows.
    video = derive(tmp_path, still(tmp_path, 'gray', (100, 100, 100)), 'rotated', '-display_rotation', '90',
                   ['-c', 'copy'])
    receipt = run(tmp_path, video, {'grain': GRAIN}, 'rotated')
    assert receipt['status'] == 'FAILED' and 'ROTATED_TEXTURE_SOURCE_UNSUPPORTED' in receipt['error'], receipt.get('error')


def test_readback_uses_the_first_video_stream_like_the_render(tmp_path):
    small = still(tmp_path, 'small', (90, 120, 150))
    large = still(tmp_path, 'large', (150, 120, 90), size=(256, 192))
    video = tmp_path / 'two-streams.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(small), '-i', str(large), '-map', '0:v', '-map', '1:v',
                    '-c', 'copy', str(video)], check=True, timeout=120)
    receipt = run(tmp_path, video, {'vignette': {'strength': 0.3, 'start': 0.4}}, 'streams')
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    assert abs(frame(receipt['result']['video']['path'], 3)[48, 64] - np.array([90, 120, 150]) / 255).max() < 0.01


class Cancel:
    """Set the run's cancellation event, then observe what the pipeline did."""

    def __init__(self, monkeypatch):
        self.event, self.calls, self.spawned = threading.Event(), [], []
        spawn, apply = texture_ops._spawn, texture_ops.apply
        monkeypatch.setattr(texture_ops, '_spawn', lambda command, log, **pipes: self.spawned.append(
            spawn(self.replace(command), log, **pipes)) or self.spawned[-1])
        monkeypatch.setattr(texture_ops, 'apply', lambda *a: self.calls.append(a[1]) or self.during(a[1]) or apply(*a))
        self.token = rt.RUN_CANCELLATION.set(self.event)

    def replace(self, command):
        return command

    def during(self, frame_index):
        pass

    def finish(self):
        rt.RUN_CANCELLATION.reset(self.token)
        assert self.spawned and all(p.poll() is not None for p in self.spawned)  # every child reaped


def test_cancellation_stops_the_frame_loop_and_reaps_both_processes(tmp_path, monkeypatch):
    video = still(tmp_path, 'gray', (100, 100, 100))
    cancel = Cancel(monkeypatch)
    cancel.during = lambda f: cancel.event.set() if f == 2 else None
    try:
        receipt = run(tmp_path, video, {'grain': GRAIN}, 'cancel')
    finally:
        cancel.finish()
    assert receipt['status'] == 'FAILED' and receipt.get('cancelled') is True, receipt
    assert receipt['error'].startswith('TEXTURE_CANCELLED: texture pipeline') and max(cancel.calls) <= 3, receipt['error']


def test_cancellation_interrupts_a_write_blocked_on_a_stuck_encoder(tmp_path, monkeypatch):
    video = still(tmp_path, 'gray', (100, 100, 100))
    cancel = Cancel(monkeypatch)
    # An "encoder" that never reads: the first 72 KiB frame fills the pipe and the write blocks.
    cancel.replace = lambda c: [sys.executable, '-c', 'import time; time.sleep(60)'] if '-tune' in c else c
    timer = threading.Timer(0.5, cancel.event.set)
    started = time.monotonic()
    timer.start()
    try:
        receipt = run(tmp_path, video, {'grain': GRAIN}, 'blocked')
    finally:
        timer.cancel()
        timer.join()
        cancel.finish()
    assert receipt.get('cancelled') is True and receipt['error'].startswith('TEXTURE_CANCELLED'), receipt
    assert time.monotonic() - started < 10 and cancel.calls == [0]


def test_a_stalled_pipeline_is_killed_after_the_stall_timeout(tmp_path, monkeypatch):
    video = still(tmp_path, 'gray', (100, 100, 100))
    monkeypatch.setattr(texture_ops, 'STALL_TIMEOUT_SEC', 0.5)
    cancel = Cancel(monkeypatch)
    cancel.during = lambda f: time.sleep(1.5) if f == 1 else None
    try:
        receipt = run(tmp_path, video, {'grain': GRAIN}, 'stall')
    finally:
        cancel.finish()
    assert receipt['status'] == 'FAILED' and receipt['error'].startswith('TEXTURE_STALLED: texture pipeline'), receipt
    assert cancel.calls == [0, 1]


def test_sample_aspect_ratio_survives_the_raw_frame_pipe(tmp_path):
    # 128x96 with 16:15 pixels; rawvideo has no SAR, so the encoder must be told.
    video = derive(tmp_path, still(tmp_path, 'gray', (100, 100, 100)), 'anamorphic',
                   ['-vf', 'setsar=16/15', '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast'])
    result = run(tmp_path, video, {'grain': GRAIN}, 'sar')['result']
    stream = next(s for s in rt.Tools().probe(result['video']['path'])['streams'] if s.get('codec_type') == 'video')
    assert stream['sample_aspect_ratio'] == result['video']['sample_aspect_ratio'] == '16:15'


def test_a_slow_but_working_readback_decode_is_not_a_stall(tmp_path, monkeypatch):
    # -re paces the readback decode at real time: 2.8 s between the two selected frames, no output in between.
    video = still(tmp_path, 'gray', (100, 100, 100), seconds=3)
    monkeypatch.setattr(texture_ops, 'STALL_TIMEOUT_SEC', 1.5)
    cancel = Cancel(monkeypatch)
    cancel.replace = lambda c: [c[0], '-re', *c[1:]] if any(a.startswith("select='") for a in c) else c
    try:
        receipt = run(tmp_path, video, {'grain': GRAIN}, 'slow', frames=(2, 72))
    finally:
        cancel.finish()
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    assert sum('-re' in p.args for p in cancel.spawned) == 2  # source and output readback
