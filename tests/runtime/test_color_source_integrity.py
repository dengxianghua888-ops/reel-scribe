"""Benign synthetic source replacement around real FFmpeg; not snapshot/ABA coverage."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import editing_runtime as rt
import color_numerics as cn
import color_media as cm

pytestmark = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')


@pytest.mark.parametrize(('when', 'layered'), [
    ('unchanged', False), ('after_probe', False), ('at_encode', False), ('after_encode', False),
    ('unchanged', True), ('after_probe', True), ('at_encode', True), ('after_encode', True),
    ('after_encode_same_frames', True),
])
def test_source_identity_checked_before_success(tmp_path, when, layered):
    red = cm.image(tmp_path / 'red.png', [((220, 20, 20), 1.0)])
    blue = cm.image(tmp_path / 'blue.png', [((20, 20, 220), 1.0)])
    source = cm.encode_sdr(red, tmp_path / 'source.mp4', seconds=0.24)
    replacement = cm.encode_sdr(blue, tmp_path / 'replacement.mp4', seconds=0.24)
    digest = rt.sha256(source)
    cube = tmp_path / 'identity.cube'
    cube.write_text(cn.cube_text(cn.identity_table(2), 'identity'), encoding='utf-8')
    encoded = []

    class ReplacementTools(rt.Tools):
        def probe(self, path):
            result = super().probe(path)
            if when == 'after_probe' and Path(path) == source:
                shutil.copyfile(replacement, source)
            return result

        def ff(self, args, **kwargs):
            if 'graded.mp4' in args:
                encoded.append(True)
                if when == 'at_encode':
                    shutil.copyfile(replacement, source)
                result = super().ff(args, **kwargs)
                if when == 'after_encode':
                    shutil.copyfile(replacement, source)
                elif when == 'after_encode_same_frames':
                    # A valid MP4 free-space box changes file identity without
                    # changing coded frames or clocks; visual readback still passes.
                    with source.open('ab') as video:
                        video.write(b'\x00\x00\x00\x0cfreedemo')
                return result
            return super().ff(args, **kwargs)

    request = {'operation': 'color-lut-apply',
               'source': {'path': str(source), 'sha256': digest},
               'lut': {'path': str(cube), 'sha256': hashlib.sha256(cube.read_bytes()).hexdigest()},
               'input_color': {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'},
               'interpolation': 'tetrahedral'}
    if layered:
        lut = request.pop('lut')
        request['layers'] = [{'lut': lut, 'ranges': [[0, 2]]},
                             {'lut': lut, 'ranges': [[1, 4]]}]
    out = tmp_path / 'operation'
    receipt = rt.run(request, out, ReplacementTools())
    stored = json.loads((out / 'receipt.json').read_text())
    if when == 'unchanged':
        assert receipt['status'] == stored['status'] == 'SUCCEEDED'
        assert receipt['result']['source']['sha256'] == rt.sha256(source) == digest
        assert (out / 'color-lut-map.json').is_file()
    else:
        assert receipt['status'] == stored['status'] == 'FAILED'
        expected = ('COLOR_SOURCE_CHANGED_', 'COLOR_LAYER_READBACK_MISMATCH') if layered and when == 'after_encode' else ('COLOR_SOURCE_CHANGED_',)
        assert any(code in receipt['error'] for code in expected)
        if when == 'after_encode_same_frames':
            assert receipt['error'] == 'COLOR_SOURCE_CHANGED_DURING_RENDER'
        assert 'result' not in stored
        assert not (out / 'color-lut-map.json').exists()
        assert rt.sha256(source) != digest
        assert bool(encoded) == (when != 'after_probe')
