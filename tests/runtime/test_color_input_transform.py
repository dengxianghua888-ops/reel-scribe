"""color-input-transform: real HLG/PQ encodes of a known SDR chart, converted back explicitly.

Round trips prove the chain and the tags; highlight cases prove the peak handling and
the measurements. None of this says which operator looks best.
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

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')
CLIP = {'operator': 'clip', 'desat': 0}


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def hdr(tmp_path, sdr, transfer, white_nits=100, pix_fmt='yuv420p10le'):
    """Real BT.2020 HLG/PQ encode where SDR white lands at white_nits (npl of the encoding zscale)."""
    out = tmp_path / f'{transfer}-{white_nits}-{pix_fmt}.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-i', str(sdr), '-vf',
                    f'zscale=t=linear,format=gbrpf32le,zscale=p=2020:t={transfer}:m=2020_ncl:r=tv:npl={white_nits},'
                    f'format={pix_fmt}', '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast', '-c:a', 'aac',
                    '-color_primaries', 'bt2020', '-color_trc', transfer, '-colorspace', 'bt2020nc', '-color_range', 'tv',
                    str(out)], check=True, timeout=120)
    return out


def convert(tmp_path, video, transfer, tonemap, name, **extra):
    request = {'operation': 'color-input-transform', 'source': ref(video),
               'input': {'transfer': transfer, 'range': 'limited', 'basis': 'verified-metadata'},
               'nominal_peak_nits': 100, 'tonemap': tonemap, 'output_pix_fmt': 'yuv420p', 'sample_frames': [3, 7], **extra}
    return rt.run(request, tmp_path / f'convert-{name}', rt.Tools())


def patch_rgb(video, frame=3, patch=16):
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-vf',
                          f"select='eq(n,{frame})',scale=in_color_matrix=bt709:in_range=tv:out_range=pc,format=rgb24",
                          '-fps_mode', 'passthrough', '-frames:v', '1', '-f', 'rawvideo', '-'], capture_output=True, check=True).stdout
    grid = np.frombuffer(raw, dtype=np.uint8).reshape(4 * patch, 6 * patch, 3) / 255.0
    # Patch interiors only: 4:2:0 chroma in the HDR encode blurs patch edges.
    return np.array([grid[r * patch + 4:r * patch + 12, c * patch + 4:c * patch + 12].reshape(-1, 3).mean(axis=0)
                     for r in range(4) for c in range(6)])[:len(cm.PATCHES)]


@pytest.fixture
def chart(tmp_path):
    png = cm.chart(tmp_path / 'chart.png')
    with_audio = tmp_path / 'sdr.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-loop', '1', '-framerate', '25', '-t', '0.4', '-i', str(png),
                    '-f', 'lavfi', '-t', '0.4', '-i', 'sine=frequency=440:sample_rate=48000', '-vf',
                    'scale=out_color_matrix=bt709:out_range=tv,format=yuv444p,' + cm.frame_tags(
                        colorspace='bt709', color_primaries='bt709', color_trc='bt709', color_range='tv'),
                    '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast', '-c:a', 'aac', '-shortest',
                    '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709', '-color_range', 'tv',
                    str(with_audio)], check=True, timeout=120)
    return with_audio


@pytest.mark.parametrize('transfer,tag', [('hlg', 'arib-std-b67'), ('pq', 'smpte2084')])
def test_clip_round_trip_recovers_the_sdr_chart_with_bt709_tags(tmp_path, chart, transfer, tag):
    # 4:4:4 keeps chroma from overshooting at patch edges, so white is the true peak.
    receipt = convert(tmp_path, hdr(tmp_path, chart, tag, pix_fmt='yuv444p10le'), transfer, CLIP, transfer)
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    result = receipt['result']
    assert result['video']['tags'] == {'color_transfer': 'bt709', 'color_primaries': 'bt709', 'color_space': 'bt709',
                                       'color_range': 'tv'}
    before, after = patch_rgb(chart), patch_rgb(result['video']['path'])
    delta = cn.ciede2000(cn.lab_from_rgb01(before, 'bt1886')[0], cn.lab_from_rgb01(after, 'bt1886')[0])
    assert delta.max() < 1.5, delta
    measured = result['measured_source']
    assert 99 < measured['peak_nits_max'] < 101 and measured['above_sdr_white_fraction'] == 0
    assert result['warnings'] == [] and result['output_interpretation']['space'] == 'bt709-sdr'
    streams = rt.Tools().probe(result['video']['path'])['streams']
    assert any(s.get('codec_type') == 'audio' for s in streams) and result['video']['frames'] == 10


def test_highlights_above_white_need_an_explicit_peak(tmp_path, chart):
    bright = hdr(tmp_path, chart, 'smpte2084', white_nits=1000)  # chart white now at 1000 nits
    clipped = convert(tmp_path, bright, 'pq', CLIP, 'clip')['result']
    assert 990 < clipped['measured_source']['peak_nits_p99'] < 1010
    assert clipped['measured_source']['above_sdr_white_fraction'] > 0.2
    assert clipped['warnings'][0].startswith('clip operator')
    mapped = convert(tmp_path, bright, 'pq', {'operator': 'hable', 'desat': 0, 'peak_nits': 1000}, 'hable')['result']
    assert mapped['warnings'] == [] and 'tonemap=hable:desat=0:peak=10,' in mapped['filter']
    gray = [name for name, _ in cm.PATCHES].index('gray-153')
    clip_gray, hable_gray = patch_rgb(clipped['video']['path'])[gray], patch_rgb(mapped['video']['path'])[gray]
    assert clip_gray.mean() > 0.95 > hable_gray.mean() > 0.6  # clip blows a ~300-nit gray to white; hable keeps it below
    too_high = convert(tmp_path, bright, 'pq', {'operator': 'hable', 'desat': 0, 'peak_nits': 4000}, 'high')['result']
    assert 'midtones will be darker' in too_high['warnings'][0]
    missing = convert(tmp_path, bright, 'pq', {'operator': 'mobius', 'desat': 0}, 'missing')
    assert missing['status'] == 'FAILED' and 'COLOR_INPUT_PEAK_REQUIRED: mobius' in missing['error']


def test_output_feeds_color_profile_scan_as_verified_bt709(tmp_path, chart):
    result = convert(tmp_path, hdr(tmp_path, chart, 'arib-std-b67'), 'hlg', CLIP, 'feed')['result']
    scan = rt.run({'operation': 'color-profile-scan', 'source': ref(result['video']['path']), 'start': 0, 'end': 0.4,
                   'samples': {'mode': 'times', 'times': [0.1]}, 'max_samples': 1, 'analysis_size': [96, 64],
                   'input_color': {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'},
                   'palette_colors': 2}, tmp_path / 'scan', rt.Tools())
    assert scan['status'] == 'SUCCEEDED', scan.get('error')


@pytest.mark.parametrize('change,error', [
    (lambda r: r['tonemap'].update(operator='aces'), 'COLOR_INPUT_OPERATOR_UNSUPPORTED'),
    (lambda r: r['tonemap'].update(peak_nits=1000), 'COLOR_INPUT_CLIP_TAKES_NO_PEAK_OR_PARAM'),
    (lambda r: r.update(tonemap={'operator': 'hable', 'desat': 0, 'peak_nits': 20}), 'COLOR_INPUT_PEAK_OUT_OF_RANGE'),
    (lambda r: r.update(tonemap={'operator': 'hable', 'desat': 0, 'peak_nits': 1000, 'param': 1}), 'COLOR_INPUT_PARAM_UNSUPPORTED'),
    (lambda r: r['input'].update(transfer='pq'), 'COLOR_INPUT_METADATA_CONFLICT: color_transfer=arib-std-b67'),
    (lambda r: r['input'].update(transfer='slog3'), 'COLOR_INPUT_TRANSFER_UNSUPPORTED'),
    (lambda r: r.update(sample_frames=[10]), 'COLOR_INPUT_SAMPLE_FRAMES_INVALID'),
    (lambda r: r.update(output_pix_fmt='yuv444p'), 'COLOR_INPUT_OUTPUT_FORMAT_UNSUPPORTED'),
    (lambda r: r.update(nominal_peak_nits=20), 'COLOR_INPUT_NOMINAL_PEAK_OUT_OF_RANGE'),
])
def test_request_validation(tmp_path, chart, change, error):
    video = hdr(tmp_path, chart, 'arib-std-b67')
    request = {'operation': 'color-input-transform', 'source': ref(video),
               'input': {'transfer': 'hlg', 'range': 'limited', 'basis': 'verified-metadata'}, 'nominal_peak_nits': 100,
               'tonemap': dict(CLIP), 'output_pix_fmt': 'yuv420p', 'sample_frames': [3]}
    change(request)
    receipt = rt.run(request, tmp_path / 'invalid', rt.Tools())
    assert receipt['status'] == 'FAILED' and error in receipt['error'], receipt.get('error')


def test_sdr_source_declared_as_hlg_is_refused(tmp_path, chart):
    receipt = convert(tmp_path, chart, 'hlg', CLIP, 'sdr')
    assert receipt['status'] == 'FAILED' and 'COLOR_INPUT_METADATA_CONFLICT: color_transfer=bt709' in receipt['error']
