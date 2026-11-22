"""Real-host cut readback with Color Balance; skipped unless a 4.3-series bpy module is importable.

Run with a Python that has bpy 4.3 (for example the bpy 4.3.0 wheel) and pytest:
    python -m pytest tests/editor_adapters/test_blender_cut_readback_host.py
The bridge pins Blender 4.3.2; the PyPI module is 4.3.0, so these tests lift the pin for the module
they load. They import a package with the cut importer, add Color Balance with the color bridge, and
read the saved project back in-process through the in-Blender entry (host_main) with the arguments
the launcher passes; the launcher's own subprocess is not run here.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

bpy = pytest.importorskip('bpy')
from test_blender_cut_import import fixture, seal  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('readback_host', ROOT / 'tools/editor-adapters/blender_cut_readback.py')
readback = importlib.util.module_from_spec(spec); spec.loader.exec_module(readback)
cb = readback.cb
pytestmark = [pytest.mark.skipif(tuple(bpy.app.version[:2]) != (4, 3), reason='the cut bridge supports the 4.3 series only'),
              pytest.mark.skipif(shutil.which('ffmpeg') is None, reason='ffmpeg required to make the test media')]
WARM = {'schema': 'color-grade/1', 'id': 'warm', 'interpretation': 'srgb-sdr-display',
        'ops': [{'type': 'cdl', 'slope': [1.1, 1.0, 0.9], 'offset': [0.02, 0.0, -0.03], 'power': [0.9, 1.0, 1.2],
                 'saturation': 1}]}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture
def cut(tmp_path, monkeypatch):
    monkeypatch.setattr(readback.imp, 'SUPPORTED_VERSION', tuple(bpy.app.version))
    root = tmp_path / 'package'; root.mkdir()
    timeline = fixture(root)
    media = root / 'media/clip.mov'
    subprocess.run(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc2=s=160x90:r=24:d=4',
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-f', 'mov', str(media)], check=True, timeout=60)
    sha = digest(media)
    timeline['tracks']['children'][0]['children'][0]['media_reference']['metadata']['recap']['sha256'] = sha
    manifest = json.loads((root / 'media-manifest.json').read_text())
    manifest['resources']['source']['sha256'] = sha
    (root / 'timeline.otio').write_text(json.dumps(timeline)); (root / 'media-manifest.json').write_text(json.dumps(manifest))
    seal(root)
    bpy.ops.wm.read_homefile(use_factory_startup=True)
    host = tmp_path / 'cut.blend'
    readback.imp.import_to_host(root, host, bpy)
    return tmp_path, root, host


def reopen(path):
    bpy.ops.wm.open_mainfile(filepath=str(path))
    return digest(path)


def save_variant(path, change):
    change(bpy.context.scene.sequence_editor.sequences_all['one'])
    bpy.ops.wm.save_as_mainfile(filepath=str(path), copy=True)
    return reopen(path)


def test_graded_cut_reads_back_with_its_grades(cut):
    tmp, root, host = cut
    base = readback.host_main(['blender', '--', str(root), str(tmp / 'base.otio'), reopen(host)], bpy)
    assert 'grades' not in base
    reopen(host)
    cb.apply_grades(bpy, {'one': WARM}, tmp / 'graded.blend')
    graded = reopen(tmp / 'graded.blend')
    with pytest.raises(ValueError, match=r'HOST_MODIFIER_UNSUPPORTED: one \(Color Balance needs a grades output\)'):
        readback.export_snapshot(root, tmp / 'plain.otio', bpy, graded)
    assert not (tmp / 'plain.otio').exists()
    # Through the in-Blender entry point, with the arguments the launcher passes.
    result = readback.host_main(['blender', '--', str(root), str(tmp / 'cut.otio'), graded,
                                 '--color', 'srgb-sdr-display', str(tmp / 'grades.json')], bpy)
    assert (tmp / 'cut.otio').read_bytes() == (tmp / 'base.otio').read_bytes()  # the cut is unchanged by the grade
    assert result['grades']['graded_strips'] == ['one'] and result['grades']['sha256'] == digest(tmp / 'grades.json')
    grades = json.loads((tmp / 'grades.json').read_text())
    assert grades['saved_host_sha256'] == graded and grades['package_sha256'] == digest(root / 'checksums.json')
    op = grades['grades']['one']['grade']['ops'][0]
    for key in ('slope', 'offset', 'power'):
        assert op[key] == pytest.approx(WARM['ops'][0][key], abs=5e-8)
    assert digest(tmp / 'graded.blend') == graded


@pytest.mark.parametrize('change,error', [
    (lambda strip: strip.modifiers.new('curves', 'CURVES'), 'HOST_MODIFIER_UNSUPPORTED: one CURVES'),
    (lambda strip: setattr(strip.modifiers.new('cb', 'COLOR_BALANCE'), 'mute', True), 'HOST_MODIFIER_DISABLED: one'),
    (lambda strip: [strip.modifiers.new(n, 'COLOR_BALANCE') for n in ('a', 'b')], 'HOST_MODIFIER_STACK_UNSUPPORTED: one'),
])
def test_other_modifiers_still_block_the_cut(cut, change, error):
    tmp, root, host = cut
    reopen(host)
    sha = save_variant(tmp / 'variant.blend', change)
    with pytest.raises(ValueError, match=error):
        readback.export_snapshot(root, tmp / 'cut.otio', bpy, sha, grades_output=tmp / 'grades.json', interpretation='srgb-sdr-display')
    assert not (tmp / 'cut.otio').exists() and not (tmp / 'grades.json').exists()

