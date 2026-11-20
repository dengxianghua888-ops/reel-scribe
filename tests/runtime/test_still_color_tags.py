"""still-image-render writes the requested color tags with the installed FFmpeg.

Real encode, synthetic still. Proves stream tags only, not color correctness.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import editing_runtime as rt

pytestmark = pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')), reason='FFmpeg required')
Image = pytest.importorskip('PIL.Image')


@pytest.mark.parametrize('declared,transfer', [('srgb', 'iec61966-2-1'), ('bt709', 'bt709')])
def test_still_render_tags_reach_the_stream(tmp_path, declared, transfer):
    still = tmp_path / 'still.png'
    Image.new('RGB', (64, 48), (180, 120, 90)).save(still)
    request = {'operation': 'still-image-render',
               'source': {'path': str(still), 'sha256': hashlib.sha256(still.read_bytes()).hexdigest()},
               'frames': 3, 'fps': '24', 'width': 32, 'height': 24,
               'crop_keyframes': [{'frame': 0, 'rect': [0, 0, 64, 48]}, {'frame': 2, 'rect': [0, 0, 64, 48]}],
               'interpolation': 'linear', 'background_rgb': [0, 0, 0], 'allow_upscale': False, 'input_color': declared}
    receipt = rt.run(request, tmp_path / 'run', rt.Tools())
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    probe = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries',
                                       'stream=color_space,color_transfer,color_primaries,color_range', '-of', 'json',
                                       receipt['result']['video']['path']], check=True, capture_output=True).stdout)
    assert probe['streams'][0] == {'color_range': 'tv', 'color_space': 'bt709', 'color_transfer': transfer,
                                   'color_primaries': 'bt709'}
