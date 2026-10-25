#!/usr/bin/env python3
"""Aggregate reviewed evaluation rows against a frozen roster, without judging content.

This tool never writes gold, invents scores, certifies evaluator independence, or
marks the library delivered. Missing runs/scores stay in frozen denominators.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

METRICS = ('scope_coverage', 'routing_mode', 'execution', 'production_usability')
THRESHOLDS = dict(zip(METRICS, (90, 90, 90, 85)))
# Version 1 is frozen: extending the live registry must not change old floors.
PACKAGES = {f'W{i:02d}' for i in range(1, 17)}
KNOWN_PACKAGES = PACKAGES | {'W17'}
STRATA = {'package', 'shared-atomic', 'cross-package', 'revision-recovery', 'failure-outside'}
FLAGS = ('in_declared_scope', 'full_production', 'critical')
CHECKS = ('scope_supported', 'routing_correct', 'execution_accepted', 'production_usable', 'critical_pass')


def require(ok, message):
    if not ok:
        raise ValueError(message)


def load(path):
    return json.loads(path.read_text(encoding='utf8'), parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON: ' + value)))


def binding(path):
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def indexed(rows, label):
    require(isinstance(rows, list), label + ' must be an array')
    result = {}
    for row in rows:
        require(isinstance(row, dict), label + ' row must be an object')
        key = row.get('case_id')
        require(isinstance(key, str) and bool(key.strip()) and key not in result, label + ': invalid/duplicate case_id')
        result[key] = row
    return result


def roster_scope(roster):
    """Choose the denominator universe from a frozen roster, never the registry."""
    if roster.get('schema') == 'evaluation-roster/1':
        return PACKAGES, 'legacy-full-library'
    require(roster.get('schema') == 'evaluation-roster/2', 'Unsupported roster schema')
    declared = roster.get('package_ids')
    require(isinstance(declared, list) and bool(declared)
            and all(isinstance(p, str) for p in declared)
            and len(declared) == len(set(declared)), 'Explicit unique package_ids required')
    packages = set(declared)
    require(packages <= KNOWN_PACKAGES, 'Unknown declared package')
    scope = roster.get('evaluation_scope')
    require(scope in ('declared-package-pilot', 'full-library'), 'Explicit evaluation_scope required')
    require(scope != 'full-library' or packages == KNOWN_PACKAGES,
            'Full-library roster requires every W01-W17 package')
    return packages, scope


def summarize(roster, runs_doc, scores_doc, roster_hash):
    packages, evaluation_scope = roster_scope(roster)
    evidence_class = roster.get('evidence_class')
    require(evidence_class in ('synthetic-harness-check', 'independent-holdout'), 'Explicit evidence_class required')
    require(isinstance(roster.get('revision'), str) and bool(roster['revision']), 'Frozen revision required')
    cases = indexed(roster.get('cases'), 'roster')
    require(bool(cases), 'Empty roster')
    for case in cases.values():
        require(isinstance(case.get('family_id'), str) and bool(case['family_id']), 'family_id required')
        require(case.get('stratum') in STRATA, 'Unknown stratum')
        require(case.get('work_package') in packages or case.get('work_package') is None, 'Unknown or undeclared package')
        require(case['stratum'] != 'package' or case.get('work_package') in packages, 'Package stratum requires a declared package')
        for field in FLAGS:
            require(type(case.get(field)) is bool, 'Boolean roster flag required: ' + field)
    for doc, schema in ((runs_doc, 'evaluation-runs/1'), (scores_doc, 'evaluation-scores/1')):
        require(doc.get('schema') == schema, 'Unsupported result schema')
        require(doc.get('roster_sha256') == roster_hash, 'Result bound to a different roster')
    runs = indexed(runs_doc.get('rows'), 'runs')
    scores = indexed(scores_doc.get('rows'), 'scores')
    require(set(runs) <= set(cases), 'Unknown run case')
    require(set(scores) <= set(cases), 'Unknown score case')
    for run in runs.values():
        require(run.get('status') in ('SUCCEEDED', 'FAILED', 'EXPECTED_REFUSAL', 'NOT_RUN', 'DEPENDENCY_MISSING'), 'Invalid run status')
        require(isinstance(run.get('run_id'), str) and bool(run['run_id']), 'run_id required')
        require(isinstance(run.get('environment'), dict) and bool(run['environment']), 'Recorded environment required')
    for key, score in scores.items():
        require(key in runs and score.get('run_id') == runs[key]['run_id'], 'Score bound to missing/different run')
        require(isinstance(score.get('reviewer'), str) and bool(score['reviewer'].strip()), 'Named reviewer required')
        require(isinstance(score.get('reason'), str) and bool(score['reason'].strip()), 'Review reason required')
        for field in CHECKS:
            require(score.get(field) is None or type(score.get(field)) is bool, 'Score must be true, false or null: ' + field)
        if runs[key]['status'] in ('NOT_RUN', 'DEPENDENCY_MISSING'):
            require(not any(score.get(field) is True for field in CHECKS), 'Unexecuted case cannot earn passes')
        if runs[key]['status'] == 'FAILED':
            require(score.get('execution_accepted') is not True and score.get('production_usable') is not True,
                    'Failed run cannot count as accepted execution/production')
        if runs[key]['status'] == 'EXPECTED_REFUSAL':
            require(score.get('production_usable') is not True, 'Refusal is not a usable production')
    eligibility = {
        'scope_coverage': lambda case: True,
        'routing_mode': lambda case: True,
        'execution': lambda case: case['in_declared_scope'],
        'production_usability': lambda case: case['full_production'],
    }
    score_fields = dict(zip(METRICS, CHECKS[:4]))

    def rate(keys, metric):
        eligible = [key for key in keys if eligibility[metric](cases[key])]
        passing = [key for key in eligible if scores.get(key, {}).get(score_fields[metric]) is True]
        den, num = len(eligible), len(passing)
        return {'numerator': num, 'denominator': den, 'percent': 100 * num / den if den else None,
                'target_percent': THRESHOLDS[metric], 'threshold_met': num * 100 >= den * THRESHOLDS[metric] if den else False,
                'missing_run_ids': [key for key in eligible if key not in runs],
                'unreviewed_ids': [key for key in eligible if scores.get(key, {}).get(score_fields[metric]) is None]}

    metrics = {metric: rate(cases, metric) for metric in METRICS}
    family_ids = sorted({case['family_id'] for case in cases.values()})
    family_metrics = {family: {metric: rate([key for key, c in cases.items() if c['family_id'] == family], metric)
                              for metric in METRICS} for family in family_ids}
    macro = {}
    for metric in METRICS:
        values = [row[metric]['percent'] for row in family_metrics.values() if row[metric]['denominator']]
        macro[metric] = {'family_count': len(values), 'mean_percent': sum(values) / len(values) if values else None,
                         'purpose': 'Descriptive family macro; does not replace the frozen case-denominator release threshold.'}
    critical = [key for key, c in cases.items() if c['critical']]
    critical_missing = [key for key in critical if scores.get(key, {}).get('critical_pass') is not True]
    allocation = {stratum: sum(c['stratum'] == stratum for c in cases.values()) for stratum in sorted(STRATA)}
    package_floor = {p: sum(c['stratum'] == 'package' and c['work_package'] == p for c in cases.values()) for p in sorted(packages)}
    minimum_cases = 8 * len(packages) + 52
    floor_met = (len(cases) >= minimum_cases and all(n >= 8 for n in package_floor.values()) and
                 allocation['shared-atomic'] >= 20 and allocation['cross-package'] >= 16 and
                 allocation['revision-recovery'] >= 8 and allocation['failure-outside'] >= 8)
    if evaluation_scope == 'declared-package-pilot':
        # The full-library allocation gate does not apply to a scoped pilot.
        # Null is deliberately not a passing floor or an acceptance conclusion.
        floor_met = None
    numeric_pass = all(m['threshold_met'] for m in metrics.values()) and bool(critical) and not critical_missing
    report = {'schema': 'evaluation-summary/1', 'status': 'AGGREGATED_NOT_ACCEPTANCE_CERTIFICATION',
            'evidence_class': evidence_class, 'roster_revision': roster['revision'], 'case_count': len(cases),
            'allocation': allocation, 'package_allocation': package_floor, 'initial_allocation_floor_met': floor_met,
            'metrics': metrics, 'family_metrics': family_metrics, 'family_macro': macro,
            'per_package': {p: {m: rate([key for key, c in cases.items() if c['work_package'] == p], m) for m in METRICS} for p in sorted(packages)},
            'critical': {'denominator': len(critical), 'numerator': len(critical) - len(critical_missing),
                         'all_passed': bool(critical) and not critical_missing, 'not_passed_ids': critical_missing},
            'numeric_thresholds_met': numeric_pass,
            'independent_acceptance': 'NOT_CERTIFIED_BY_THIS_TOOL',
            'release_accepted': False,
            'remaining_authority': ['Verify author/auditor/scorer roles and protected gold access',
                                   'Verify semantic-family contamination against development history',
                                   'Review actual source/work/output identity and score validity',
                                   'Review per-package category/material coverage beyond allocation counts',
                                   'Complete separate style, host, installation and publication gates']}
    if roster.get('schema') == 'evaluation-roster/2':
        report.update(schema='evaluation-summary/2', package_ids=sorted(packages),
                      evaluation_scope=evaluation_scope,
                      allocation_floor_applicable=evaluation_scope == 'full-library',
                      allocation_minimum_cases=minimum_cases if evaluation_scope == 'full-library' else None)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--roster', type=Path, required=True)
    parser.add_argument('--runs', type=Path, required=True)
    parser.add_argument('--scores', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'Output exists; preserve previous score snapshot')
    report = summarize(load(args.roster), load(args.runs), load(args.scores), binding(args.roster)['sha256'])
    report['inputs'] = {name: binding(getattr(args, name)) for name in ('roster', 'runs', 'scores')}
    report['script'] = binding(Path(__file__))
    with args.output.open('x', encoding='utf8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
    print(json.dumps({'status': report['status'], 'cases': report['case_count'], 'numeric_thresholds_met': report['numeric_thresholds_met'],
                      'independent_acceptance': report['independent_acceptance']}))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({'status': 'FAILED', 'error': str(exc)}), file=sys.stderr)
        sys.exit(1)
