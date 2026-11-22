"""Cut readback with an explicit Color Balance grades output: argument rules and launcher publication.

The launcher tests run a stand-in host executable that writes the staged files itself; they check the
parent-side identity checks and publication, not Blender. See test_blender_cut_readback_host.py for the host.
"""
import importlib.util
from pathlib import Path
import stat
import sys

import pytest
from test_blender_cut_import import fixture

spec = importlib.util.spec_from_file_location('readback_color', Path(__file__).resolve().parents[2] / 'tools/editor-adapters/blender_cut_readback.py')
a = importlib.util.module_from_spec(spec); spec.loader.exec_module(a)


def test_host_arguments():
    assert a.host_arguments(['pkg', 'new.otio', 'sha']) == (['pkg', 'new.otio', 'sha', None], {})
    args, options = a.host_arguments(['pkg', 'new.otio', 'sha', 'scope.json', 'ssha', '--color', 'srgb-sdr-display', 'g.json'])
    assert args == ['pkg', 'new.otio', 'sha', {'path': 'scope.json', 'sha256': 'ssha'}]
    assert options == {'interpretation': 'srgb-sdr-display', 'grades_output': 'g.json'}
    for bad in (['pkg', 'new.otio', 'sha', '--color', 'srgb-sdr-display'], ['pkg', 'new.otio', '--color', 'srgb-sdr-display', 'g.json'],
                ['pkg', 'new.otio', 'sha', '--color', 'srgb-sdr-display', 'g.json', 'extra']):
        with pytest.raises(ValueError):
            a.host_arguments(bad)


def test_host_main_passes_bpy_and_the_host_hash_in_place(monkeypatch):
    calls = []
    monkeypatch.setattr(a, 'export_snapshot', lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    bpy = object()
    a.host_main(['blender', '-b', 'edited.blend', '--python', 'x.py', '--', 'pkg', 'new.otio', 'sha'], bpy)
    a.host_main(['blender', '--', 'pkg', 'new.otio', 'sha', 'scope.json', 'ssha', '--color', 'srgb-sdr-display', 'g.json'], bpy)
    assert calls == [(('pkg', 'new.otio', bpy, 'sha', None), {}),
                     (('pkg', 'new.otio', bpy, 'sha', {'path': 'scope.json', 'sha256': 'ssha'}),
                      {'interpretation': 'srgb-sdr-display', 'grades_output': 'g.json'})]


def test_color_output_rules(tmp_path):
    root = tmp_path / 'package'; root.mkdir()
    out = tmp_path / 'cut.otio'
    assert a.color_output(root, out, None, None) is None
    assert a.color_output(root, out, tmp_path / 'grades.json', 'bt709-sdr-display') == tmp_path / 'grades.json'
    (tmp_path / 'old.json').write_text('{}')
    for grades, interpretation, error in [
            (tmp_path / 'grades.json', None, 'HOST_COLOR_OUTPUT_ARGUMENTS'), (None, 'srgb-sdr-display', 'HOST_COLOR_OUTPUT_ARGUMENTS'),
            (tmp_path / 'grades.json', 'rec2020', 'HOST_COLOR_INTERPRETATION_UNSUPPORTED'),
            (tmp_path / 'grades.txt', 'srgb-sdr-display', 'GRADES_OUTPUT_UNSAFE_OR_EXISTS'),
            (tmp_path / 'old.json', 'srgb-sdr-display', 'GRADES_OUTPUT_UNSAFE_OR_EXISTS'),
            (tmp_path / 'missing' / 'grades.json', 'srgb-sdr-display', 'GRADES_OUTPUT_UNSAFE_OR_EXISTS'),
            (root / 'grades.json', 'srgb-sdr-display', 'OUTPUT_CANNOT_MODIFY_PACKAGE')]:
        with pytest.raises(ValueError, match=error):
            a.color_output(root, out, grades, interpretation)


def fake_host(tmp_path, grades_sha=None):
    """A stand-in 'blender' that writes the staged OTIO and grades with the identities it was given."""
    script = tmp_path / 'fake-blender'
    script.write_text(f'''#!{sys.executable}
import json, sys
from pathlib import Path
args = sys.argv[sys.argv.index('--') + 1:]
root, otio, host_sha = args[:3]
Path(otio).write_text('{{}}')
if '--color' in args:
    at = args.index('--color')
    package = __import__('hashlib').sha256((Path(root) / 'checksums.json').read_bytes()).hexdigest()
    Path(args[at + 2]).write_text(json.dumps({{'grades': {{'one': {{}}}}, 'interpretation': args[at + 1],
                                              'saved_host_sha256': {grades_sha!r} or host_sha, 'package_sha256': package}}))
''')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


@pytest.fixture
def saved(tmp_path):
    root = tmp_path / 'package'; root.mkdir(); fixture(root)
    host = tmp_path / 'edited.blend'; host.write_bytes(b'saved host bytes')
    return root, host


def test_launcher_publishes_cut_and_grades_together(tmp_path, saved):
    root, host = saved
    result = a.launch(host, root, tmp_path / 'cut.otio', blender=fake_host(tmp_path),
                      grades_output=tmp_path / 'grades.json', interpretation='srgb-sdr-display')
    assert (tmp_path / 'cut.otio').is_file() and result['grades']['graded_strips'] == ['one']
    assert result['grades']['sha256'] == a.imp.digest(tmp_path / 'grades.json')
    plain = a.launch(host, root, tmp_path / 'plain.otio', blender=fake_host(tmp_path))
    assert plain['grades'] is None and not (tmp_path / 'grades.json.pending').exists()


def test_launcher_refuses_grades_from_another_host(tmp_path, saved):
    root, host = saved
    with pytest.raises(ValueError, match='HOST_GRADES_IDENTITY_MISMATCH'):
        a.launch(host, root, tmp_path / 'cut.otio', blender=fake_host(tmp_path, grades_sha='0' * 64),
                 grades_output=tmp_path / 'grades.json', interpretation='srgb-sdr-display')
    assert not (tmp_path / 'cut.otio').exists() and not (tmp_path / 'grades.json').exists()


def test_launcher_withdraws_the_cut_when_grades_cannot_be_published(tmp_path, saved, monkeypatch):
    root, host = saved
    publish = a.atomic_new
    def fail_on_grades(output, raw):
        if Path(output).suffix == '.json':
            raise FileExistsError(output)
        publish(output, raw)
    monkeypatch.setattr(a, 'atomic_new', fail_on_grades)
    with pytest.raises(FileExistsError):
        a.launch(host, root, tmp_path / 'cut.otio', blender=fake_host(tmp_path),
                 grades_output=tmp_path / 'grades.json', interpretation='srgb-sdr-display')
    assert not (tmp_path / 'cut.otio').exists()
