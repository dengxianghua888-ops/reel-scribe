"""Real synthetic-media comparisons, not real content/style acceptance."""
import copy
import json
from pathlib import Path
import re
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import editing_runtime as runtime
import style_preview_ops
import work_ops
from test_source_binding import tools, media, plan  # noqa: F401,E402


@pytest.fixture
def comparison(tmp_path, tools, media):
    voice = tmp_path / 'voice.wav'
    subprocess.run([tools.ffmpeg, '-nostdin', '-v', 'error', '-n', '-f', 'lavfi',
        '-i', 'sine=frequency=700:sample_rate=48000:duration=0.4', str(voice)], check=True)
    card = tmp_path / 'card.md'
    card.write_text('Synthetic comparison card; no real style validation')
    ref = style_preview_ops.reference
    document = {'schema': 'work-document/1', 'plan': plan(media['red'], mute=True),
        'captions': {}, 'caption_style': None, 'audio_tracks': {'voice': {
            'source': ref(voice), 'start': 0, 'end': 0.4, 'anchor_clip_id': 'one', 'offset': 0, 'gain_db': 0}},
        'style_bindings': {}, 'notes': {}}
    store = tmp_path / 'work.sqlite'
    output = tmp_path / 'init'
    output.mkdir()
    state = work_ops.work_version({'operation': 'work-version', 'action': 'init', 'store': str(store),
        'work_id': 'comparison', 'document': document, 'author': 'agent', 'message': 'synthetic'}, output, tools)
    scope = {'clip_ids': [], 'source_ids': [], 'caption_ids': [], 'audio_ids': ['voice'],
        'style_keys': ['*'], 'note_keys': [], 'output_fields': [], 'caption_style': False,
        'freeze_positions': ['one'], 'freeze_duration': True}
    variants = []
    for name, gain in [('quiet', -12), ('foreground', -3)]:
        recipe = {'schema': 'style-recipe/1', 'id': name, 'version': '1',
            'style': {'family': 'synthetic', 'style_id': 'test', 'version': '1', 'card': ref(card)},
            'parameters': {'audio_gain_db': {'voice': gain}}}
        variants.append({'id': name, 'recipe': recipe, 'expected_recipe_sha256': runtime.fingerprint(recipe),
            'capabilities': ['audio-track-gain'], 'scope': copy.deepcopy(scope)})
    request = {'operation': 'style-recipe-preview', 'store': str(store), 'expected_version': state['version'],
        'variants': variants, 'source_consumption': {'schema': 'source-consumption/1', 'mode': 'snapshot'}}
    folder = tmp_path / 'compare'
    folder.mkdir()
    return request, folder, tools, style_preview_ops.state(str(store))


def test_actual_two_variant_render_is_same_base_and_leaves_work_unchanged(comparison):
    request, folder, tools, state = comparison
    request['variants'][0]['id'] = 'batch-prepare'
    request['variants'][1]['id'] = 'recovery-batch'
    result = style_preview_ops.execute(request, folder, tools)
    assert result['status'] == 'PREVIEWS_RENDERED_NOT_COMMITTED'
    assert result['selected_variant'] is None and not result['applied_to_work']
    assert style_preview_ops.state(request['store']) == state
    recovery = json.loads((folder / 'batch-prepare-request.json').read_text())
    assert [job['preview_candidate'] for job in recovery['jobs']] == [v['candidate'] for v in result['variants']]
    variants = result['variants']
    assert len(variants) == 2 and variants[0]['video']['sha256'] != variants[1]['video']['sha256']
    for variant in variants:
        bundle = json.loads(Path(variant['candidate']['path']).read_text())
        assert bundle['base_version'] == state['version']
        assert bundle['base_document_sha256'] == state['document_sha256']
        assert bundle['document']['plan'] == state['document']['plan']
        assert bundle['document']['captions'] == state['document']['captions']
        rendered = json.loads((Path(variant['render_receipt']['path']).parent / 'rendered-document.json').read_text())
        assert runtime.fingerprint(rendered) == variant['document_sha256']
        assert tools.probe(variant['video']['path'])['duration'] > 0
        assert variant['source_consumption']['selection']['mode'] == 'snapshot'
    page = (folder / 'comparison.html').read_text()
    assert '<script' not in page and 'http://' not in page and 'https://' not in page
    paths = re.findall('src="([^"]+)"', page)
    assert len(paths) == 2
    for path in paths:
        assert not path.startswith('/') and '..' not in path.split('/')
        assert (folder / path).resolve().is_relative_to(folder.resolve())
        assert (folder / path).is_file()


@pytest.mark.parametrize('kind,error', [('stale', 'WORK_VERSION_CONFLICT'),
    ('duplicate', 'STYLE_PREVIEW_DUPLICATE_ID'), ('traversal', 'STYLE_PREVIEW_ID_INVALID'),
    ('capability', 'RECIPE_CAPABILITY_UNAVAILABLE'), ('one', 'STYLE_PREVIEW_REQUIRES_2_TO_4_VARIANTS')])
def test_invalid_comparison_never_renders_or_publishes(comparison, monkeypatch, kind, error):
    request, folder, tools, _ = comparison
    if kind == 'stale': request['expected_version'] = '0' * 64
    elif kind == 'duplicate': request['variants'][1]['id'] = request['variants'][0]['id']
    elif kind == 'traversal': request['variants'][1]['id'] = '../outside'
    elif kind == 'one': request['variants'] = request['variants'][:1]
    else: request['variants'][1]['capabilities'] = []
    monkeypatch.setattr(style_preview_ops, 'run', lambda *args: pytest.fail('must not render'))
    with pytest.raises(ValueError, match=error):
        style_preview_ops.execute(request, folder, tools)
    assert not (folder / 'style-preview.json').exists()
    assert not (folder / 'comparison.html').exists()


@pytest.mark.parametrize('kind', ['second-render-fails', 'stale-during-render'])
def test_partial_failure_or_changed_head_never_publishes_success(comparison, monkeypatch, kind):
    request, folder, tools, state = comparison
    original = work_ops.work_render
    calls = []
    def render(*args):
        calls.append(True)
        if len(calls) == 2:
            if kind == 'second-render-fails':
                raise runtime.ContractError('injected second render failure')
            # Mutate a real Work head after producing the second preview.
            result = original(*args)
            db = work_ops.connect(request['store'])
            try:
                current = work_ops.load(db)
                doc = copy.deepcopy(current['document'])
                doc['notes']['concurrent'] = 'explicit test concurrent edit'
                work_ops.append(db, current, doc, 'commit', 'test concurrent edit', 'human', {})
                db.commit()
            finally:
                db.close()
            return result
        return original(*args)
    monkeypatch.setattr(work_ops, 'work_render', render)
    with pytest.raises(ValueError, match='STYLE_PREVIEW_RENDER_FAILED|STYLE_PREVIEW_STALE_BASE'):
        style_preview_ops.execute(request, folder, tools)
    assert len(calls) == 2
    assert not (folder / 'style-preview.json').exists()
    assert not (folder / 'comparison.html').exists()
    assert (folder / 'batch-resume-request.json').is_file()
    if kind == 'second-render-fails':
        assert style_preview_ops.state(request['store']) == state
        # Explicit retry of failed jobs uses the existing batch ledger; the
        # verified first preview must not be rendered again.
        monkeypatch.setattr(work_ops, 'work_render', original)
        resume = json.loads((folder / 'batch-resume-request.json').read_text())
        resume['retry_failed'] = True
        retried = runtime.run(resume, folder / 'retry', tools)
        assert retried['status'] == 'SUCCEEDED', retried.get('error')
        assert retried['result']['status'] == 'RENDERED'
        assert any(e['job_id'] == 'quiet' and e['action'] == 'REUSED_VERIFIED' for e in retried['result']['events'])


def test_binding_replaced_after_batch_validation_cannot_be_reendorsed(comparison, monkeypatch):
    request, folder, tools, _ = comparison
    original = style_preview_ops.run
    def tamper(spec, directory, tools):
        receipt = original(spec, directory, tools)
        if spec.get('action') == 'run' and receipt['status'] == 'SUCCEEDED':
            job = receipt['result']['jobs'][0]
            (Path(job['receipt']).parent / 'render-binding.json').write_text('{}')
        return receipt
    monkeypatch.setattr(style_preview_ops, 'run', tamper)
    with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
        style_preview_ops.execute(request, folder, tools)
    assert not (folder / 'style-preview.json').exists()
    assert not (folder / 'comparison.html').exists()
