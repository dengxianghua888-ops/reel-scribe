"""The final source identity check follows checksumming the derived media."""
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import color_media as cm
import editing_runtime as rt

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')


def make_source(tmp_path, hdr):
    path = tmp_path / 'source.mp4'
    primaries, matrix, transfer = ('bt2020', 'bt2020nc', 'smpte2084') if hdr else ('bt709', 'bt709', 'bt709')
    if hdr:
        filters = subprocess.run(['ffmpeg', '-hide_banner', '-filters'], capture_output=True, text=True,
                                 check=True, timeout=30).stdout
        if not all(name in filters for name in (' zscale ', ' tonemap ')):
            pytest.skip('FFmpeg zscale and tonemap required')
    pixel_format = 'yuv420p10le' if hdr else 'yuv420p'
    tag_frames = f'setparams=color_primaries={primaries}:colorspace={matrix}:color_trc={transfer}:range=tv'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=gray:s=128x96:r=25:d=0.24',
                    '-vf', f'format={pixel_format},{tag_frames}', '-c:v', 'libx264', '-preset', 'ultrafast',
                    '-color_primaries', primaries, '-colorspace', matrix, '-color_trc', transfer, '-color_range', 'tv',
                    str(path)], check=True, timeout=120)
    return path


@pytest.mark.parametrize('hdr', [False, True], ids=['film-texture', 'hdr-to-sdr'])
@pytest.mark.parametrize('change', [False, True], ids=['unchanged', 'changed-while-hashing-derived'])
def test_published_derived_media_has_current_source_identity(tmp_path, monkeypatch, hdr, change):
    source = make_source(tmp_path, hdr)
    digest = rt.sha256(source)
    reference = {'path': str(source), 'sha256': digest}
    if hdr:
        request = {'operation': 'color-input-transform', 'source': reference,
                   'input': {'transfer': 'pq', 'range': 'limited', 'basis': 'verified-metadata'},
                   'nominal_peak_nits': 100, 'tonemap': {'operator': 'clip', 'desat': 0},
                   'output_pix_fmt': 'yuv420p', 'sample_frames': [0, 3]}
        media_name, result_name = 'sdr.mp4', 'color-input-transform.json'
    else:
        request = {'operation': 'film-texture-apply', 'source': reference,
                   'input_color': {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'},
                   'effects': {'vignette': {'strength': 0.25, 'start': 0.3}}, 'readback_frames': [0, 3]}
        media_name, result_name = 'textured.mp4', 'film-texture.json'

    request_path, out = tmp_path / 'request.json', tmp_path / 'out'
    request_path.write_text(json.dumps(request), encoding='utf-8')
    hasher = rt.sha256
    derived_seen = False

    def sha256(path):
        nonlocal derived_seen
        if Path(path) == out / media_name and not derived_seen:
            derived_seen = True
            if change:
                # Stand-in for a concurrent media edit while the derived file
                # is being checksummed. This MP4 padding leaves the frames intact.
                with source.open('ab') as stream:
                    stream.write(b'\x00\x00\x00\x0cfreesafe')
        return hasher(path)

    monkeypatch.setattr(rt, 'sha256', sha256)
    monkeypatch.setattr(sys, 'argv', ['editing_runtime.py', 'run', '--request', str(request_path),
                                      '--work-dir', str(out)])
    code = rt.main()
    receipt = json.loads((out / 'receipt.json').read_text(encoding='utf-8'))
    assert derived_seen and (out / media_name).is_file(), receipt
    if change:
        assert hasher(source) != digest
        assert code == 1 and receipt['status'] == 'FAILED', receipt
        assert receipt['error'].startswith('SOURCE_HASH_MISMATCH:')
        assert 'result' not in receipt and not (out / result_name).exists()
    else:
        assert code == 0 and receipt['status'] == 'SUCCEEDED', receipt
        assert hasher(source) == receipt['result']['source']['sha256'] == digest
        assert hasher(out / media_name) == receipt['result']['video']['sha256']
        assert (out / result_name).is_file()
