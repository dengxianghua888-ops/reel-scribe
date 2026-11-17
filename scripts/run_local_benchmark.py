#!/usr/bin/env python3
"""Opt-in new-batch cold/render reuse measurement. No runtime instrumentation."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def measure(prepare, output, run, clock=time.monotonic):
    if prepare.get('operation') != 'work-batch-render' or prepare.get('action') != 'prepare':
        raise ValueError('ONLY_BATCH_PREPARE')
    output = Path(output)
    output.mkdir(exist_ok=False, parents=True)
    request = dict(prepare, batch_dir=str(output / 'batch'))
    (output / 'prepare-request.json').write_text(json.dumps(request, indent=2))
    phases = []

    def call(name, req):
        start = clock(); r = run(req, output / name); end = clock()
        phases.append({'phase': name, 'elapsed_seconds': end - start, 'status': r.get('status'),
                       'receipt': {'path': str(output / name / 'receipt.json'),
                                   'sha256': digest(output / name / 'receipt.json')}})
        if r.get('status') != 'SUCCEEDED': raise ValueError('PHASE_FAILED:' + name)
        return r

    try:
        call('prepare', request)
        manifest = output / 'batch/manifest.json'
        run_request = {'operation': 'work-batch-render', 'action': 'run',
                       'batch_dir': str(output / 'batch'), 'manifest_sha256': digest(manifest), 'job_ids': [j['id'] for j in request.get('jobs', [])], 'retry_failed': False}
        cold = call('cold', run_request)
        warm = call('reuse', run_request)
        cold_events = cold['result']['events']; warm_events = warm['result']['events']
        if not cold_events or any(e['action'] != 'RENDER_ATTEMPT' or e.get('status') != 'SUCCEEDED' for e in cold_events):
            raise ValueError('NOT_COLD_SUCCESS')
        if len(warm_events) != len(cold_events) or any(e['action'] != 'REUSED_VERIFIED' for e in warm_events):
            raise ValueError('NOT_VERIFIED_REUSE')
        status = 'MEASURED_LOCAL_BATCH_ONLY'
    except Exception as e:
        status = 'FAILED:' + str(e)
    result = {'schema': 'local-batch-benchmark/1', 'status': status, 'phases': phases,
              'ffmpeg_invocations': 'NOT_RECORDED', 'model_calls': 0,
              'model_call_scope': 'Only this runner batch prepare/render/reuse path, no model operation; not a global audit.',
              'cost': 'NOT_RECORDED', 'human_time_saved': 'NOT_RECORDED',
              'prepare_request': {'path': str(output / 'prepare-request.json'), 'sha256': digest(output / 'prepare-request.json')},
              'manifest': ({'path': str(output / 'batch/manifest.json'), 'sha256': digest(output / 'batch/manifest.json')} if (output / 'batch/manifest.json').exists() else None),
              'scope': 'Monotonic wall seconds include validation, hashing and media work. Single cold/reuse observation, not a general speedup guarantee. Manifest binds sources/candidates/runtime/tools; receipts bind outputs.'}
    (output / 'benchmark.json').write_text(json.dumps(result, indent=2))
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--prepare-request', required=True)
    p.add_argument('--output', required=True); args = p.parse_args()
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
    import editing_runtime as rt
    result = measure(json.loads(Path(args.prepare_request).read_text()), Path(args.output).absolute(),
                     lambda request, directory: rt.run(request, directory, rt.Tools()))
    print(json.dumps(result, indent=2))
    if result['status'].startswith('FAILED:'): raise SystemExit(1)


if __name__ == '__main__': main()
