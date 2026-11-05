"""SQLite binding and synthetic-clock policy regressions, not media acceptance."""
import copy
import json
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_generation_intents as fixtures
import batch_ops


@pytest.fixture
def variant(tmp_path):
    contracts = fixtures.GenerationIntentContracts()
    contracts.setUp()
    try:
        work = contracts.work_fixture()
        work['tools'].doctor = lambda: {'fixture': 'synthetic clocks, no media decode'}
        doc = copy.deepcopy(work['document'])
        doc['notes']['manual-note'] = 'Reviewed A'
        candidate = contracts.work_candidate(work, doc, 'candidate', contracts.scope(notes=['manual-note']))
        output = tmp_path / 'output'
        output.mkdir()
        request = {'operation': 'work-variant-create', 'parent_store': str(work['store']),
                   'expected_parent_version': work['state']['version'],
                   'target_store': str(tmp_path / 'variant.sqlite'), 'variant_id': 'child',
                   'candidate': {'path': str(candidate), 'sha256': fixtures.digest(candidate)},
                   'message': 'Exact candidate', 'author': 'agent'}
        yield work, candidate, request, output
    finally:
        contracts.doCleanups()


def test_variant_rejects_replacement_after_initial_hash(variant):
    work, candidate, request, output = variant
    original = fixtures.editing_runtime.source
    before = batch_ops.work_state(work['store'])
    changed = json.loads(candidate.read_text())
    changed['document']['notes']['manual-note'] = 'Unreviewed B'

    def replace_after_hash(ref, *args, **kwargs):
        result = original(ref, *args, **kwargs)
        if ref == request['candidate']:
            candidate.write_text(json.dumps(changed))
        return result

    with patch.object(fixtures.editing_runtime, 'source', replace_after_hash):
        with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
            batch_ops.variant_create(request, output, work['tools'])
    assert not Path(request['target_store']).exists()
    assert batch_ops.work_state(work['store']) == before


def test_variant_rejects_replacement_during_scope_validation(variant):
    work, candidate, request, output = variant
    original = fixtures.work_ops.revision_diff

    def replace_after_validation(*args, **kwargs):
        result = original(*args, **kwargs)
        candidate.write_text('{}')
        return result

    with patch.object(fixtures.work_ops, 'revision_diff', replace_after_validation):
        with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
            batch_ops.variant_create(request, output, work['tools'])
    assert not Path(request['target_store']).exists()


def test_variant_keeps_verified_document_and_lineage_without_parent_mutation(variant):
    work, candidate, request, output = variant
    before = batch_ops.work_state(work['store'])
    result = batch_ops.variant_create(request, output, work['tools'])
    state = batch_ops.work_state(request['target_store'])
    assert state['document']['notes']['manual-note'] == 'Reviewed A'
    assert result['lineage']['candidate'] == request['candidate']
    assert state['document']['notes']['variant_lineage'] == result['lineage']
    assert batch_ops.work_state(work['store']) == before


@pytest.mark.parametrize('alias', ['same-path', 'symlink', 'copied-bytes'])
@pytest.mark.parametrize('allow,overlap', [(False, True), (True, True), (False, False)])
def test_alias_cannot_bypass_source_reuse_policy(tmp_path, alias, allow, overlap):
    source = tmp_path / 'source.bin'
    source.write_bytes(b'synthetic video')
    other = source
    if alias == 'symlink':
        other = tmp_path / 'alias.bin'
        other.symlink_to(source)
    elif alias == 'copied-bytes':
        other = tmp_path / 'copy.bin'
        other.write_bytes(source.read_bytes())
    plan = {'schema': 'execution-plan/1', 'fps': 25, 'width': 16, 'height': 16,
            'fit': 'contain', 'allow_source_reuse': allow,
            'sources': {'A': {'path': str(source), 'sha256': fixtures.digest(source)},
                        'B': {'path': str(other), 'sha256': fixtures.digest(other)}},
            'clips': [{'id': 'a', 'source_id': 'A', 'start': 0, 'end': .5, 'gain_db': 0},
                      {'id': 'b', 'source_id': 'B', 'start': .25 if overlap else .5,
                       'end': 1, 'gain_db': 0}]}
    if overlap and not allow:
        with pytest.raises(ValueError, match='SOURCE_REUSE_NOT_AUTHORIZED'):
            fixtures.editing_runtime.normalize_plan(plan, fixtures.SyntheticMediaTools())
    else:
        assert len(fixtures.editing_runtime.normalize_plan(plan, fixtures.SyntheticMediaTools())['clips']) == 2
