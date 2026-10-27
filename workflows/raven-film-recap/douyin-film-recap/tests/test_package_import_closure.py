"""Relocated package imports must not fall back to this source checkout."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[4]
FILM_SRC = Path('workflows/raven-film-recap/douyin-film-recap/src')


class FilmImportClosureTests(unittest.TestCase):
    def test_both_relocated_packages_contain_the_existing_film_module_closure(self):
        probe = '''
import importlib, json, sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / sys.argv[2]))
for name in ['planning', 'retrieval', 'otio_readback', 'revision_preview', 'render_cache']:
    importlib.import_module('douyin_film_recap.' + name)
paths = {name: module.__file__ for name, module in sys.modules.items()
         if name.startswith('douyin_film_recap') and getattr(module, '__file__', None)}
assert paths
assert all(Path(path).resolve().is_relative_to(root) for path in paths.values()), paths
print(json.dumps(paths, sort_keys=True))
'''
        with tempfile.TemporaryDirectory(prefix='film-package-closure-') as temporary:
            directory = Path(temporary)
            for builder in ['build_portable_bundle.py', 'build_codex_plugin.py']:
                with self.subTest(builder=builder):
                    output = directory / builder.removesuffix('.py')
                    built = subprocess.run([
                        sys.executable, str(ROOT / 'scripts' / builder), '--out', str(output)],
                        cwd=directory, capture_output=True, text=True, timeout=60)
                    self.assertEqual(built.returncode, 0, built.stderr)
                    relocated = output.with_name(output.name + '-relocated')
                    output.rename(relocated)
                    result = subprocess.run([
                        sys.executable, '-I', '-c', probe, str(relocated), str(FILM_SRC)],
                        cwd=directory, capture_output=True, text=True, timeout=30)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    paths = json.loads(result.stdout)
                    for name in ['planning', 'retrieval', 'otio_readback',
                                 'revision_preview', 'render_cache']:
                        self.assertIn('douyin_film_recap.' + name, paths)


if __name__ == '__main__':
    unittest.main()
