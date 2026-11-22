"""Real-host Blender Color Balance checks; skipped unless the bpy module is importable.

Run with a Python that has bpy (for example the bpy 4.3.0 or 5.3.0 wheels), Pillow and pytest:
    python -m pytest tests/editor_adapters/test_blender_color_balance_host.py
Each test builds a scene shaped like blender_cut_import's (movie strip, sRGB sequencer, Standard
view), renders a frame without and with the modifier, and compares Blender's pixels with the
CDL applied to the unmodified render. This checks the Color Balance mapping in the host; decode
differences between Blender and FFmpeg are kept out by using Blender's own unmodified render.
"""
import hashlib
import importlib.util
from pathlib import Path
import shutil
import subprocess

import pytest

bpy = pytest.importorskip('bpy')
np = pytest.importorskip('numpy')
Image = pytest.importorskip('PIL.Image')

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('color_balance_host', ROOT / 'tools/editor-adapters/blender_color_balance.py')
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)
pytestmark = pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg required to make the test movie')
WARM = {'schema': 'color-grade/1', 'id': 'warm', 'interpretation': 'srgb-sdr-display',
        'ops': [{'type': 'cdl', 'slope': [1.1, 1.0, 0.9], 'offset': [0.02, 0.0, -0.03], 'power': [0.9, 1.0, 1.2],
                 'saturation': 1}]}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def project(tmp_path):
    """A saved project shaped like blender_cut_import's, with one movie strip of eight colour patches."""
    clip = tmp_path / 'clip.mp4'
    boxes = ','.join(f'drawbox=x={(i % 4) * 16}:y={(i // 4) * 24}:w=16:h=24:color={c}:t=fill' for i, c in enumerate(
        ['#101010', '#404040', '#808080', '#c0c0c0', '#f0f0f0', '#c04020', '#20a050', '#3050d0']))
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=black:s=64x48:r=24:d=0.5', '-vf',
                    boxes + ',format=yuv444p', '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast', str(clip)],
                   check=True, timeout=60)
    bpy.ops.wm.read_homefile(use_factory_startup=True, use_empty=True)
    scene = bpy.context.scene
    scene.render.fps, scene.render.fps_base = 24, 1
    scene.render.resolution_x, scene.render.resolution_y, scene.render.resolution_percentage = 64, 48, 100
    scene.view_settings.view_transform = 'Standard'
    scene.sequencer_colorspace_settings.name = 'sRGB'
    seq = scene.sequence_editor_create()
    strips = seq.strips if hasattr(seq, 'strips') else seq.sequences
    strip = strips.new_movie('one', str(clip), 1, 1)
    strip['reel_instance_id'] = 'one'
    scene['reel_adapter'] = 'experimental-blender-cut/1'
    scene.frame_start, scene.frame_end = 1, 12
    settings = scene.render.image_settings
    settings.file_format, settings.color_mode, settings.color_depth = 'PNG', 'RGB', '8'
    base = tmp_path / 'base.blend'
    bpy.ops.wm.save_as_mainfile(filepath=str(base))
    return tmp_path, base


def render(path):
    scene = bpy.context.scene
    scene.frame_current = 3
    scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)
    return np.asarray(Image.open(path).convert('RGB')).astype(float)


def cdl(rgb, op):
    out = np.clip(rgb / 255 * np.array(op['slope']) + np.array(op['offset']), 0, 1) ** np.array(op['power'])
    return np.clip(out, 0, 1) * 255


def test_applied_grade_renders_as_the_cdl_and_reads_back(project):
    root, base = project
    before = render(root / 'before.png')
    result = cb.apply_grades(bpy, {'one': WARM}, root / 'graded.blend')
    assert result['host_version'][:2] in ([4, 3], [5, 3])
    graded = render(root / 'graded.png')
    assert np.abs(graded - before).max() > 20  # the grade did change the picture
    assert np.abs(graded - cdl(before, WARM['ops'][0])).max() <= 1.0  # 8-bit rounding of Blender's 1024-entry table
    bpy.ops.wm.open_mainfile(filepath=str(root / 'graded.blend'))
    read = cb.read_grades(bpy, 'srgb-sdr-display')['grades']['one']['grade']['ops'][0]
    for key in ('slope', 'offset', 'power'):  # offsets come back as Blender applies them (float32 offset + 1)
        assert read[key] == pytest.approx(WARM['ops'][0][key], abs=5e-8)
    reopened = render(root / 'reopened.png')
    assert np.array_equal(reopened, graded)  # the saved copy carries the modifier
    bpy.ops.wm.open_mainfile(filepath=str(base))
    assert not list(cb.scene_strips(bpy)[1]['one'].modifiers)  # the opened project was saved as a copy, not over


@pytest.mark.parametrize('inverts', [(False, False, False), (True, True, True)])
def test_lift_gamma_gain_edit_reads_back_as_the_rendered_cdl(project, inverts):
    root, base = project
    before = render(root / 'before.png')
    strip = cb.scene_strips(bpy)[1]['one']
    modifier = strip.modifiers.new(name='user edit', type='COLOR_BALANCE')
    data = modifier.color_balance
    data.correction_method = 'LIFT_GAMMA_GAIN'
    data.lift, data.gamma, data.gain = (0.95, 1.0, 1.08), (1.2, 1.0, 0.85), (1.1, 0.95, 1.0)
    data.invert_lift, data.invert_gamma, data.invert_gain = inverts
    edited = render(root / 'edited.png')
    read = cb.read_grades(bpy, 'srgb-sdr-display')
    assert read['grades']['one']['mode'] == 'LIFT_GAMMA_GAIN'
    op = read['grades']['one']['grade']['ops'][0]
    assert np.abs(edited - cdl(before, op)).max() <= 1.0


def test_unrepresentable_host_state_is_refused(project):
    root, _ = project
    strip = cb.scene_strips(bpy)[1]['one']
    strip.modifiers.new(name='curves', type='CURVES')
    with pytest.raises(ValueError, match='HOST_MODIFIER_UNSUPPORTED: one CURVES'):
        cb.read_grades(bpy, 'srgb-sdr-display')
    strip.modifiers.remove(strip.modifiers[0])
    modifier = strip.modifiers.new(name='mult', type='COLOR_BALANCE')
    modifier.color_multiply = 1.5
    with pytest.raises(ValueError, match='color_multiply'):
        cb.read_grades(bpy, 'srgb-sdr-display')
    strip.modifiers.remove(modifier)
    with pytest.raises(ValueError, match='BLENDER_GRADE_NOT_REPRESENTABLE'):
        cb.apply_grades(bpy, {'one': {**WARM, 'ops': [{**WARM['ops'][0], 'saturation': 0.8}]}}, root / 'no.blend')
    assert not list(strip.modifiers) and not (root / 'no.blend').exists()
