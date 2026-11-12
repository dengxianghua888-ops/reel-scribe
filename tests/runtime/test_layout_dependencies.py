import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
from dependency_discovery import _selected_requirements


def test_compile_layout_requirements_are_conditional():
    normal, unknown, branch = _selected_requirements('style-recipe-compile', {'recipe': {}})
    assert 'ffmpeg' not in normal and 'Pillow' not in normal
    assert not unknown
    layout, unknown, branch = _selected_requirements('style-recipe-compile', {'recipe': {'layout_constraints': {}}})
    assert {'ffmpeg', 'ffprobe', 'Pillow'} <= set(layout)
    assert branch == 'actual-static-caption-layout'
    assert _selected_requirements('style-recipe-compile', None)[1]


def test_preview_variant_layout_selects_pillow_only_when_requested():
    no_layout = {'variants': [{'recipe': {}}]}
    assert 'Pillow' not in _selected_requirements('style-recipe-preview', no_layout)[0]
    request = {'variants': [{'recipe': {}}, {'recipe': {'layout_constraints': {}}}]}
    assert 'Pillow' in _selected_requirements('style-recipe-preview', request)[0]
