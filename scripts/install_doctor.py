#!/usr/bin/env python3
"""Read-only dependency diagnosis for an installed or candidate library root."""
import argparse
import json
from pathlib import Path
import sys
import importlib.util
import hashlib


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--ffmpeg', help='Absolute FFmpeg path; overrides EDITING_FFMPEG and PATH')
    parser.add_argument('--ffprobe', help='Absolute ffprobe path; overrides EDITING_FFPROBE and PATH')
    parser.add_argument('--bindings', type=Path, help='JSON with font/asr lock path+sha256 references')
    parser.add_argument('--request', type=Path, help='Exact local runtime request JSON for branch-specific dependency diagnosis')
    parser.add_argument('--out', type=Path, help='New exclusive JSON result path; refuses overwrite')
    args = parser.parse_args(argv)
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    try:
        source = root / 'runtime/dependency_discovery.py'
        if not source.is_file() or source.is_symlink():
            raise ValueError('TARGET_DIAGNOSTIC_MODULE_MISSING_OR_SYMLINK')
        raw = source.read_bytes()
        expected = hashlib.sha256(raw).hexdigest()
        spec = importlib.util.spec_from_file_location('_target_dependency_discovery', source)
        module = importlib.util.module_from_spec(spec)
        exec(compile(raw, str(source), 'exec'), module.__dict__)
        inspect = module.inspect
        bindings = json.loads(args.bindings.read_text(encoding='utf-8')) if args.bindings else None
        request = json.loads(args.request.read_text(encoding='utf-8')) if args.request else None
        result = inspect(root, ffmpeg=args.ffmpeg, ffprobe=args.ffprobe, bindings=bindings, request=request)
        if hashlib.sha256(source.read_bytes()).hexdigest() != expected:
            raise ValueError('TARGET_DIAGNOSTIC_MODULE_DRIFT')
        result['diagnostic_source'] = {'path': str(source), 'sha256': expected}
        payload = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
        if args.out:
            if not args.out.is_absolute():
                raise ValueError('ABSOLUTE_OUTPUT_PATH_REQUIRED')
            with args.out.open('x', encoding='utf-8') as stream:
                stream.write(payload)
        else:
            print(payload, end='')
        return 2 if result['status'] == 'BUNDLE_DIAGNOSTIC_IDENTITY_FAILED' else 0
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(json.dumps({'status': 'FAILED', 'error': str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
