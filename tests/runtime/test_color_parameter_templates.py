"""Color style cards carry parameter templates that the color atomics accept as-is."""
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime'))
import color_adjust_ops  # noqa: E402
import color_fit_ops  # noqa: E402

CATALOG = json.loads((ROOT / 'styles/reference/catalog.json').read_text(encoding='utf-8'))
COLOR_STYLES = [s for s in CATALOG['styles'] if s['family'] == '色彩迁移']


def test_every_color_style_has_a_template():
    assert len(COLOR_STYLES) == 6
    assert all('color_parameters' in s for s in COLOR_STYLES)
    assert all('color_parameters' not in s for s in CATALOG['styles'] if s['family'] != '色彩迁移')


@pytest.mark.parametrize('style', COLOR_STYLES, ids=[s['id'] for s in COLOR_STYLES])
def test_template_is_accepted_by_the_atomics(style):
    template = style['color_parameters']
    assert set(template) <= {'schema', 'fit_methods', 'fit_bounds', 'strength_max', 'adjust_caps',
                             'suggested_protections', 'disable_when'}
    assert template['schema'] == 'color-parameter-template/1'
    assert set(template['fit_methods']) <= set(color_fit_ops.METHODS)
    if template['fit_methods']:
        color_fit_ops._bounds(template['fit_bounds'])  # raises on anything the fit would refuse
        models = {color_fit_ops.METHODS[m] for m in template['fit_methods']}
        keys = set(template['fit_bounds'])
        assert ('cdl' not in models or keys & set(color_fit_ops.CDL_BOUNDS)) and ('curves' not in models or 'curve_max_shift' in keys)
    else:
        assert 'fit_bounds' not in template
    assert 0 < template['strength_max'] <= 1
    assert color_adjust_ops._caps(template['adjust_caps']) == template['adjust_caps']
    assert set(template['adjust_caps']) == set(color_adjust_ops.DIMENSIONS)
    assert template['disable_when'] and all(isinstance(x, str) and x.strip() for x in template['disable_when'])
    assert isinstance(template['suggested_protections'], list)
    card = (ROOT / 'styles/reference' / f"{style['id']}.md").read_text(encoding='utf-8')
    assert '## 参数模板' in card and f"强度上限：{template['strength_max']}" in card
