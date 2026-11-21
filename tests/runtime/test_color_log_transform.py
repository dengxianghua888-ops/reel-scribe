"""color-log-transform: synthetic camera Log clips encoded through OCIO, converted back explicitly.

The curve anchors check OCIO's colorspaces against the vendors' published 18% grey
code values. The clips prove the chain (code values, matrix, cube, encoding, tags)
against the exact processor and, for the un-tone-mapped view, against the BT.1886
formula. None of this says which view looks best.
"""
import hashlib
import math
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
np = pytest.importorskip('numpy')
ocio = pytest.importorskip('PyOpenColorIO')
import color_media as cm  # noqa: E402
import color_numerics as cn  # noqa: E402
import editing_runtime as rt  # noqa: E402
import log_ops  # noqa: E402

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')
CONFIG = 'ocio://studio-config-v5.0.0_aces-v2.1_ocio-v2.6'
REC709 = 'Rec.1886 Rec.709 - Display'
ACES_SDR = 'ACES 2.0 - SDR 100 nits (Rec.709)'
APPLE = {'colorspace': 'Apple Log', 'matrix': 'bt2020nc', 'code_values': 'full'}
# Scene-linear Rec.2020 patches: 18% grey, a warm colour, deep shadow, and a highlight 8x above diffuse white.
PATCHES = [(0.18, 0.18, 0.18), (0.5, 0.1, 0.05), (0.01, 0.01, 0.01), (8.0, 8.0, 8.0)]


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def config():
    return ocio.Config.CreateFromFile(CONFIG)


def encode_log(tmp_path, colorspace, name, code_values='full', matrix='bt2020', tags=True, pix_fmt='yuv444p10le', audio=False):
    """Four vertical patches, scene-linear Rec.2020 -> camera Log via OCIO, 10 frames of 10-bit video."""
    lin = np.zeros((64, 128, 3), np.float32)
    for i, value in enumerate(PATCHES):
        lin[:, i * 32:(i + 1) * 32] = value
    codes = lin.reshape(-1, 3).copy()
    config().getProcessor('Linear Rec.2020', colorspace).getOptimizedCPUProcessor(ocio.OPTIMIZATION_LOSSLESS).applyRGB(codes)
    raw = (np.clip(codes, 0, 1) * 65535 + 0.5).astype('<u2').tobytes() * 10
    out = tmp_path / f'{name}.mp4'
    rng = 'pc' if code_values == 'full' else 'tv'
    args = ['ffmpeg', '-v', 'error', '-y', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-s', '128x64', '-r', '25', '-i', '-']
    if audio:
        args += ['-f', 'lavfi', '-t', '0.4', '-i', 'sine=frequency=440:sample_rate=48000', '-c:a', 'aac']
    # zimg for the RGB -> Y'CbCr step: swscale's full-range float paths differ between FFmpeg releases.
    space = 'bt2020nc' if matrix == 'bt2020' else 'bt709'
    params = (f'colorspace={space}:color_primaries=bt2020:range={rng}' if tags else
              f'colorspace=unknown:color_primaries=unknown:color_trc=unknown:range={rng}')
    args += ['-vf', f"zscale=matrix={'2020_ncl' if matrix == 'bt2020' else '709'}:range={'full' if rng == 'pc' else 'limited'},"
                    f'format={pix_fmt},setparams={params}', '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast']
    if tags:
        args += ['-color_primaries', 'bt2020', '-colorspace', space, '-color_range', rng]
    subprocess.run(args + [str(out)], input=raw, check=True, timeout=120)
    return out, codes.reshape(64, 128, 3)


def request(video, view=ACES_SDR, display=REC709, declared=None, **extra):
    return {'operation': 'color-log-transform', 'source': ref(video), 'input': dict(declared or APPLE),
            'ocio': {'config': CONFIG, 'display': display, 'view': view}, 'lut_size': 65,
            'output_pix_fmt': 'yuv420p10le', 'sample_frames': [2, 7], **extra}


def patch_rgb(video, frame=3):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf',
                          f"select='eq(n,{frame})',zscale=matrixin=709:rangein=limited:range=full,format=rgb48le",
                          '-fps_mode', 'passthrough', '-frames:v', '1', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    rgb = np.frombuffer(raw, dtype='<u2').reshape(64, 128, 3) / 65535.0
    return np.array([rgb[8:56, i * 32 + 8:i * 32 + 24].reshape(-1, 3).mean(axis=0) for i in range(4)])


@pytest.mark.parametrize('colorspace,published', [
    # Apple Log white paper constants: gamma * log2(0.18 + beta) + delta (about 10-bit full-range CV 500).
    ('Apple Log', 0.08550479 * math.log2(0.18 + 0.00964052) + 0.69336945),
    ('S-Log3 S-Gamut3.Cine', 420 / 1023),  # Sony: 18% grey at 10-bit CV 420
    ('V-Log V-Gamut', 433 / 1023),  # Panasonic: 18% grey at 10-bit CV 433
])
def test_ocio_curves_match_the_published_grey_code_values(colorspace, published):
    codes = np.array([[0.18, 0.18, 0.18]], np.float32)
    config().getProcessor('ACES2065-1', colorspace).getOptimizedCPUProcessor(ocio.OPTIMIZATION_LOSSLESS).applyRGB(codes)
    assert codes[0] == pytest.approx([published] * 3, abs=5e-4)


def test_apple_log_round_trip_matches_the_exact_processor_with_bt709_tags(tmp_path):
    video, codes = encode_log(tmp_path, 'Apple Log', 'apple', audio=True)
    receipt = rt.run(request(video), tmp_path / 'aces', rt.Tools())
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    result = receipt['result']
    assert result['video']['tags'] == {'color_transfer': 'bt709', 'color_primaries': 'bt709', 'color_space': 'bt709',
                                       'color_range': 'tv'}
    assert result['output_interpretation'] == {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'}
    assert result['video']['frames'] == 10 and result['video']['pix_fmt'] == 'yuv420p10le'
    assert any(s.get('codec_type') == 'audio' for s in rt.Tools().probe(result['video']['path'])['streams'])
    assert result['cube']['bake_delta_e2000']['p95'] < 1.0 and result['readback']['delta_e2000_median'] < 1.0
    cpu = log_ops.processor({'config': CONFIG, 'display': REC709, 'view': ACES_SDR}, 'Apple Log')[0]
    expected = np.clip(log_ops.apply_exact(cpu, np.array([codes[0, i * 32] for i in range(4)])), 0, 1)
    delta = cn.ciede2000(cn.lab_from_rgb01(expected, 'bt1886')[0], cn.lab_from_rgb01(patch_rgb(result['video']['path']), 'bt1886')[0])
    assert delta.max() < 1.0, delta
    assert result['measured_source']['display_clipped_fraction'] == 0  # the ACES 2.0 view rolls the 8x highlight off
    assert result['warnings'] == []


def test_untone_mapped_view_follows_the_bt1886_formula_and_reports_clipping(tmp_path):
    video, _ = encode_log(tmp_path, 'Apple Log', 'apple')
    result = rt.run(request(video, view='Un-tone-mapped'), tmp_path / 'raw', rt.Tools())['result']
    grey, warm, shadow, highlight = patch_rgb(result['video']['path'])
    # Scene-linear Rec.2020 -> display-linear Rec.709 without tone mapping: grey stays 0.18, then BT.1886 inverse.
    assert grey == pytest.approx([0.18 ** (1 / 2.4)] * 3, abs=0.004)
    assert shadow == pytest.approx([0.01 ** (1 / 2.4)] * 3, abs=0.004)
    assert highlight == pytest.approx([1, 1, 1], abs=0.004)  # 8x white clips without a tone curve
    assert result['measured_source']['display_clipped_fraction'] == pytest.approx(0.25, abs=0.02)
    assert any('outside the display range' in w for w in result['warnings'])


def test_srgb_display_writes_srgb_tags(tmp_path):
    video, _ = encode_log(tmp_path, 'Apple Log', 'apple')
    result = rt.run(request(video, display='sRGB - Display'), tmp_path / 'srgb', rt.Tools())['result']
    assert result['video']['tags']['color_transfer'] == 'iec61966-2-1'
    assert result['output_interpretation']['space'] == 'srgb-sdr'


def test_slog3_video_range_with_bt709_matrix(tmp_path):
    declared = {'colorspace': 'S-Log3 S-Gamut3.Cine', 'matrix': 'bt709', 'code_values': 'video'}
    video, codes = encode_log(tmp_path, 'S-Log3 S-Gamut3.Cine', 'slog3', code_values='video', matrix='bt709')
    receipt = rt.run(request(video, view='Un-tone-mapped', declared=declared), tmp_path / 'slog3', rt.Tools())
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    assert patch_rgb(receipt['result']['video']['path'])[0] == pytest.approx([0.18 ** (1 / 2.4)] * 3, abs=0.004)


def test_wrong_code_values_are_reported_not_guessed(tmp_path):
    video, _ = encode_log(tmp_path, 'Apple Log', 'apple')  # full-range file
    receipt = rt.run(request(video, declared={**APPLE, 'code_values': 'video'}), tmp_path / 'wrong', rt.Tools())
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    result = receipt['result']
    # The 8x highlight sits at full-range code 0.95; read as video range it lands above 1.
    assert result['measured_source']['code_values_outside_0_1_fraction'] == pytest.approx(0.25, abs=0.02)
    assert any('check code_values' in w for w in result['warnings'])
    assert any('range tag is pc' in w for w in result['warnings'])


def test_untagged_source_is_accepted_and_its_tags_recorded(tmp_path):
    video, _ = encode_log(tmp_path, 'Apple Log', 'untagged', tags=False)
    result = rt.run(request(video), tmp_path / 'untagged-run', rt.Tools())['result']
    assert result['input_basis'] == 'caller-declared' and result['stream']['observed_tags']['color_space'] in (None, 'unknown')


@pytest.mark.parametrize('change,error', [
    (lambda r: r['input'].update(colorspace='Linear Rec.2020'), 'COLOR_LOG_COLORSPACE_UNSUPPORTED'),
    (lambda r: r['input'].update(colorspace='ACEScct'), 'COLOR_LOG_COLORSPACE_UNSUPPORTED'),  # log, but not a camera input
    (lambda r: r['input'].update(colorspace='Nikon N-Log'), 'COLOR_LOG_COLORSPACE_UNSUPPORTED'),
    (lambda r: r['input'].update(matrix='bt709'), 'COLOR_LOG_MATRIX_CONFLICT: color_space=bt2020nc'),
    (lambda r: r['input'].update(matrix='bt601'), 'COLOR_LOG_MATRIX_UNSUPPORTED'),
    (lambda r: r['input'].update(code_values='auto'), 'COLOR_LOG_CODE_VALUES_REQUIRED'),
    (lambda r: r['ocio'].update(config='ocio://studio-config-latest'), 'COLOR_LOG_CONFIG_UNSUPPORTED'),
    (lambda r: r['ocio'].update(config='/tmp/config.ocio'), 'COLOR_LOG_CONFIG_UNSUPPORTED'),
    (lambda r: r['ocio'].update(display='Display P3 - Display'), 'COLOR_LOG_DISPLAY_UNSUPPORTED'),
    (lambda r: r['ocio'].update(view='ACES 2.0 - HDR 1000 nits (P3 D65)'), 'COLOR_LOG_VIEW_UNSUPPORTED'),
    (lambda r: r.update(lut_size=17), 'COLOR_LOG_LUT_SIZE_UNSUPPORTED'),
    (lambda r: r.update(output_pix_fmt='yuv444p'), 'COLOR_LOG_OUTPUT_FORMAT_UNSUPPORTED'),
    (lambda r: r.update(sample_frames=[10]), 'COLOR_LOG_SAMPLE_FRAMES_INVALID'),
])
def test_request_validation(tmp_path, change, error):
    video, _ = encode_log(tmp_path, 'Apple Log', 'apple')
    req = request(video)
    change(req)
    receipt = rt.run(req, tmp_path / 'invalid', rt.Tools())
    assert receipt['status'] == 'FAILED' and error in receipt['error'], receipt.get('error')


def test_eight_bit_and_hdr_sources_are_refused(tmp_path):
    eight, _ = encode_log(tmp_path, 'Apple Log', 'eight', code_values='video', pix_fmt='yuv444p')
    receipt = rt.run(request(eight), tmp_path / 'eight-run', rt.Tools())
    assert receipt['status'] == 'FAILED' and 'COLOR_LOG_PIXEL_FORMAT_UNSUPPORTED: yuv444p' in receipt['error']
    video, _ = encode_log(tmp_path, 'Apple Log', 'hlg-tagged')
    hlg = tmp_path / 'hlg.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(video), '-c', 'copy', '-bsf:v',
                    'h264_metadata=transfer_characteristics=18', str(hlg)], check=True, timeout=60)  # 18 = HLG
    receipt = rt.run(request(hlg), tmp_path / 'hlg-run', rt.Tools())
    assert receipt['status'] == 'FAILED' and 'COLOR_LOG_HDR_TRANSFER_CONFLICT' in receipt['error'], receipt.get('error')


def test_output_feeds_color_profile_scan_as_verified_bt709(tmp_path):
    video, _ = encode_log(tmp_path, 'Apple Log', 'apple')
    result = rt.run(request(video), tmp_path / 'feed', rt.Tools())['result']
    scan = rt.run({'operation': 'color-profile-scan', 'source': ref(result['video']['path']), 'start': 0, 'end': 0.4,
                   'samples': {'mode': 'times', 'times': [0.1]}, 'max_samples': 1, 'analysis_size': [96, 48],
                   'input_color': result['output_interpretation'], 'palette_colors': 2}, tmp_path / 'scan', rt.Tools())
    assert scan['status'] == 'SUCCEEDED', scan.get('error')
