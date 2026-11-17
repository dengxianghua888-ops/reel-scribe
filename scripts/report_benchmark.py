#!/usr/bin/env python3
"""Offline receipt observations, not authenticated performance or billing claims."""
import argparse
import hashlib
import json
from pathlib import Path

UNKNOWN = 'NOT_RECORDED'


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1048576), b''): h.update(chunk)
    return h.hexdigest()


def unique(pairs):
    d = {}
    for k, v in pairs:
        if k in d: raise ValueError('DUPLICATE_JSON_KEY')
        d[k] = v
    return d


def parse(data):
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE')))


def inside(root, path):
    p = Path(path)
    if not p.is_absolute(): p = root / p
    if p.is_symlink() or not p.resolve().is_relative_to(root): raise ValueError('OUTSIDE_EVIDENCE_ROOT')
    return p.resolve(strict=True)


def report(root, refs):
    root = Path(root).resolve(strict=True)
    evidence, seen, attempts, events, media = [], set(), {}, [], []

    def bound(path, expected):
        p = inside(root, path)
        if sha(p) != expected: raise ValueError('EVIDENCE_HASH_MISMATCH')
        return p

    def bound_json(path, expected):
        p = inside(root, path)
        data = p.read_bytes()
        if hashlib.sha256(data).hexdigest() != expected: raise ValueError("EVIDENCE_HASH_MISMATCH")
        return p, parse(data)

    def receipt(p, expected):
        p, d = bound_json(p, expected)
        if str(p) in seen: return
        seen.add(str(p))
        if d.get('schema') != 'operation-receipt/1': raise ValueError('RECEIPT_SCHEMA')
        evidence.append({'path': str(p), 'sha256': expected, 'operation': d.get('operation'), 'status': d.get('status')})
        artifacts = {}
        for a in d.get('artifacts', []):
            ap = inside(root, p.parent / a['path'])
            if ap in artifacts: raise ValueError('DUPLICATE_ARTIFACT')
            bound(ap, a['sha256'])
            if ap.stat().st_size != a['bytes']: raise ValueError('ARTIFACT_SIZE')
            artifacts[ap] = a
        r = d.get('result', {})
        if d.get('operation') == 'work-batch-render' and r.get('schema') == 'batch-state/1':
            batch = r['batch_id']; local = set()
            for a in r.get('attempts', []):
                attempt_path = inside(root, a['path'])
                key = (str(attempt_path), a['job_id'], a['number'])
                if key in local: raise ValueError('DUPLICATE_ATTEMPT')
                local.add(key)
                old = attempts.get(key)
                if old and old != a: raise ValueError('CONFLICTING_ATTEMPT_SNAPSHOTS')
                attempts[key] = a
            events.extend({'batch_id': batch, **e} for e in r.get('events', []))
            for j in r.get('jobs', []):
                if j.get('receipt') and j.get('receipt_sha256'): receipt(j['receipt'], j['receipt_sha256'])
        if d.get('operation') == 'timeline-render' and d.get('status') == 'SUCCEEDED':
            pp = inside(root, p.parent / r['normalized_plan'])
            if pp not in artifacts: raise ValueError('UNBOUND_PLAN')
            _, plan = bound_json(pp, artifacts[pp]['sha256'])
            media.append({'receipt_sha256': expected, 'source_windows': [
                {'source_id': c['source_id'], 'start': c['start'], 'end': c['end']}
                for c in plan['clips']], 'output_duration_seconds': r['media']['duration'],
                'source_identities': {k: {'sha256': v['sha256'], 'bytes': v['bytes']} for k, v in plan['sources'].items()}})
        for ap, a in artifacts.items():
            if ap.name == 'receipt.json': receipt(ap, a['sha256'])

    for ref in refs: receipt(ref['path'], ref['sha256'])
    return {'schema': 'receipt-benchmark/1', 'evidence': evidence, 'media': media,
            'attempts': list(attempts.values()), 'attempt_count': len(attempts),
            'failed_attempt_count': sum(a['status'] == 'FAILED' for a in attempts.values()),
            'events': events, 'reuse_verified_events': sum(e.get('action') == 'REUSED_VERIFIED' for e in events),
            'recovered_receipt_events': sum(e.get('action') == 'RECOVERED_RECEIPT' for e in events),
            'elapsed_seconds': UNKNOWN, 'ffmpeg_invocations': UNKNOWN, 'model_calls': UNKNOWN,
            'cost': UNKNOWN, 'human_time_saved': UNKNOWN,
            'scope': 'Historical bound receipt observations only; hashes detect changes, not forgery/authenticity. No current-head/cache approval. No timing inferred from mtime. Repeated receipt paths deduplicated; conflicting attempt snapshots rejected.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True)
    parser.add_argument('--receipt', action='append', required=True, help='SHA256=absolute-or-root-relative-path')
    args = parser.parse_args()
    refs = [dict(zip(('sha256', 'path'), r.split('=', 1))) for r in args.receipt]
    print(json.dumps(report(args.root, refs), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
