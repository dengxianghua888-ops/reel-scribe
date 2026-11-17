"""The packaged entry points reach the implementation, not an unknown operation."""
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import editing_runtime
import dependency_discovery


def test_recipe_and_impact_dispatch(tmp_path):
    for operation, module in [('style-recipe-compile', 'style_recipe_ops'),
                              ('revision-impact-inspect', 'revision_impact'),
                              ('style-recipe-preview', 'style_preview_ops'),
                              ('result-preview-compile', 'result_preview_ops')]:
        request = {'operation': operation}
        with patch(module + '.execute', return_value={'sentinel': operation}) as target:
            assert editing_runtime.execute(request, tmp_path, None) == {'sentinel': operation}
            target.assert_called_once_with(request, tmp_path, None)
        assert dependency_discovery.ATOMIC_REQUIREMENTS[operation] == (
            ('sqlite', 'ffmpeg', 'ffprobe') if operation == 'style-recipe-preview' else
            ('sqlite', 'ffprobe') if operation == 'result-preview-compile' else ('ffprobe',))
