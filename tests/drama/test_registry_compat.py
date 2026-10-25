"""Frozen-roster and registry compatibility; synthetic data is not creative QC."""
import hashlib
import importlib.util
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('drama_evaluation', ROOT / 'scripts/summarize_evaluation.py')
evaluation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(evaluation)


def fixture():
    cases = []
    for package in sorted(evaluation.PACKAGES):
        for index in range(8):
            cases.append({'case_id': package + '-' + str(index), 'family_id': package + '-family',
                          'stratum': 'package', 'work_package': package, 'in_declared_scope': True,
                          'full_production': True, 'critical': index == 0})
    for stratum, count in [('shared-atomic', 20), ('cross-package', 16),
                           ('revision-recovery', 8), ('failure-outside', 8)]:
        for index in range(count):
            inside = stratum != 'failure-outside'
            cases.append({'case_id': stratum + '-' + str(index), 'family_id': stratum,
                          'stratum': stratum, 'work_package': None, 'in_declared_scope': inside,
                          'full_production': inside, 'critical': index == 0})
    roster = {'schema': 'evaluation-roster/1', 'evidence_class': 'synthetic-harness-check',
              'revision': 'compat-synthetic-1', 'cases': cases}
    runs = {'schema': 'evaluation-runs/1', 'roster_sha256': 'frozen-fixture', 'rows': []}
    scores = {'schema': 'evaluation-scores/1', 'roster_sha256': 'frozen-fixture', 'rows': []}
    for case in cases:
        key = case['case_id']
        runs['rows'].append({'case_id': key, 'status': 'SUCCEEDED' if case['in_declared_scope'] else 'EXPECTED_REFUSAL',
                             'run_id': key + '-run', 'environment': {'kind': 'synthetic-fixture'}})
        scores['rows'].append({'case_id': key, 'run_id': key + '-run', 'reviewer': 'synthetic-harness',
                               'reason': 'Synthetic compatibility input; not media or independent acceptance.',
                               'scope_supported': True, 'routing_correct': True,
                               'execution_accepted': case['in_declared_scope'],
                               'production_usable': True if case['full_production'] else None,
                               'critical_pass': True})
    return roster, runs, scores


def summary_digest(report):
    return hashlib.sha256(json.dumps(report, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


class LegacyCompatibility(unittest.TestCase):
    # Captured by running the upstream aggregator at
    # 0288db1a7c9ec3cbeb77673d5cf18279385c2340 on the fixture above.
    COMPLETE_DIGEST = '07f8fd4ec3b655a673866d1ff6459fcca76793a1ba16a0f77b6ac06c2a5f004d'
    MISSING_DIGEST = 'd3c935cce658a9fd59b410de63367ae66c22c987984a269e03e8151718eb5173'

    def test_complete_v1_report_byte_semantics_unchanged(self):
        report = evaluation.summarize(*fixture(), 'frozen-fixture')
        self.assertEqual(summary_digest(report), self.COMPLETE_DIGEST)
        self.assertEqual(report['case_count'], 180)
        self.assertTrue(report['initial_allocation_floor_met'])
        self.assertEqual(len(report['package_allocation']), 16)

    def test_missing_runs_and_scores_still_in_frozen_denominators(self):
        roster, runs, scores = fixture()
        runs['rows'] = runs['rows'][1:]
        scores['rows'] = scores['rows'][2:]
        report = evaluation.summarize(roster, runs, scores, 'frozen-fixture')
        self.assertEqual(summary_digest(report), self.MISSING_DIGEST)
        self.assertEqual(report['metrics']['scope_coverage']['denominator'], 180)
        self.assertEqual(report['metrics']['scope_coverage']['numerator'], 178)

    def test_v1_cannot_silently_add_w17(self):
        roster, runs, scores = fixture()
        roster['cases'][0]['work_package'] = 'W17'
        with self.assertRaisesRegex(ValueError, 'package'):
            evaluation.summarize(roster, runs, scores, 'frozen-fixture')


class ExplicitV2Scope(unittest.TestCase):
    def pilot(self):
        roster, runs, scores = fixture()
        roster.update(schema='evaluation-roster/2', package_ids=['W17'],
                      evaluation_scope='declared-package-pilot')
        roster['cases'] = [roster['cases'][0]]
        roster['cases'][0]['work_package'] = 'W17'
        runs['rows'] = [runs['rows'][0]]
        scores['rows'] = [scores['rows'][0]]
        return roster, runs, scores

    def test_pilot_is_scoped_and_not_library_acceptance(self):
        report = evaluation.summarize(*self.pilot(), 'frozen-fixture')
        self.assertEqual(report['schema'], 'evaluation-summary/2')
        self.assertEqual(report['package_allocation'], {'W17': 1})
        self.assertFalse(report['allocation_floor_applicable'])
        self.assertIsNone(report['initial_allocation_floor_met'])
        self.assertFalse(report['release_accepted'])

    def test_explicit_package_list_and_scope_required(self):
        for missing in ['package_ids', 'evaluation_scope']:
            roster, runs, scores = self.pilot()
            del roster[missing]
            with self.assertRaises(ValueError):
                evaluation.summarize(roster, runs, scores, 'frozen-fixture')

    def test_duplicates_unknown_and_undeclared_packages_rejected(self):
        for declared in [['W17', 'W17'], ['W18'], ['W16'], [], None]:
            roster, runs, scores = self.pilot()
            roster['package_ids'] = declared
            with self.assertRaises(ValueError):
                evaluation.summarize(roster, runs, scores, 'frozen-fixture')

    def test_pilot_cannot_claim_full_library(self):
        roster, runs, scores = self.pilot()
        roster['evaluation_scope'] = 'full-library'
        with self.assertRaisesRegex(ValueError, 'every W01-W17'):
            evaluation.summarize(roster, runs, scores, 'frozen-fixture')

    def test_full_library_requires_new_package_in_floor(self):
        roster, runs, scores = fixture()
        roster.update(schema='evaluation-roster/2', package_ids=sorted(evaluation.KNOWN_PACKAGES),
                      evaluation_scope='full-library')
        report = evaluation.summarize(roster, runs, scores, 'frozen-fixture')
        self.assertEqual(report['allocation_minimum_cases'], 188)
        self.assertEqual(report['package_allocation']['W17'], 0)
        self.assertFalse(report['initial_allocation_floor_met'])

    def test_full_library_floor_accepts_all_188_declared_cases(self):
        roster, runs, scores = fixture()
        roster.update(schema='evaluation-roster/2', package_ids=sorted(evaluation.KNOWN_PACKAGES),
                      evaluation_scope='full-library')
        for index in range(8):
            key = 'W17-' + str(index)
            roster['cases'].append({**roster['cases'][index], 'case_id': key,
                                    'family_id': 'W17-family', 'work_package': 'W17'})
            runs['rows'].append({**runs['rows'][index], 'case_id': key, 'run_id': key + '-run'})
            scores['rows'].append({**scores['rows'][index], 'case_id': key, 'run_id': key + '-run'})
        report = evaluation.summarize(roster, runs, scores, 'frozen-fixture')
        self.assertEqual(report['case_count'], 188)
        self.assertTrue(report['initial_allocation_floor_met'])
        self.assertFalse(report['release_accepted'])

    def test_unexecuted_pilot_cannot_earn_pass(self):
        roster, runs, scores = self.pilot()
        runs['rows'][0]['status'] = 'NOT_RUN'
        with self.assertRaisesRegex(ValueError, 'Unexecuted'):
            evaluation.summarize(roster, runs, scores, 'frozen-fixture')


class RegistryIntegration(unittest.TestCase):
    def test_new_workflow_preserves_old_ids_and_dependency_kind(self):
        registry = json.loads((ROOT / 'registry/skills.json').read_text())
        entries = registry['entries']
        self.assertEqual(len(entries), 52)
        self.assertEqual(len({e['id'] for e in entries}), 52)
        self.assertEqual(sum(e['layer'] == 'complex' for e in entries), 17)
        self.assertEqual(sum(e['layer'] == 'atomic' for e in entries), 34)
        self.assertEqual(sum(e['layer'] == 'agent-adapter' for e in entries), 1)
        legacy_entries = [e for e in entries if e['id'] != 'raven-drama-production']
        self.assertEqual(summary_digest(legacy_entries),
                         '704388ebeb4d11bcd9cda4f977141f2bba5f24e88356a329586212466e70957d')
        drama = next(e for e in entries if e['id'] == 'raven-drama-production')
        self.assertEqual(drama['work_package'], 'W17')
        self.assertNotIn('runtime_operations', drama)
        kinds = {e['id']: e['layer'] for e in entries}
        self.assertTrue(all(kinds[dep] == 'atomic' for dep in drama['atomic_dependencies']))

    def test_route_examples_cover_six_explicit_boundaries(self):
        entry = ROOT / 'workflows/raven-drama-production'
        text = (entry / 'references/route-and-reuse.md').read_text()
        for fragment in ['原创一个两分钟', '已授权小说', '现有剧情素材', '解说这部电影',
                         '只缺一个雨夜', '只帮我写或修改剧本']:
            self.assertIn(fragment, text)
        # This checks fixture coverage, not model routing success.
        self.assertIn('raven-film-recap', text)
        self.assertIn('raven-script-generation', text)


if __name__ == '__main__':
    unittest.main()
