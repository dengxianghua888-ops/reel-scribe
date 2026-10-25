#!/usr/bin/env python3
"""Provider-free drama checks. Preparation never commits a Work revision."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))


def read(path):
    from drama_binding import json_bytes
    return json_bytes(Path(path).read_bytes())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'context', 'variant', 'impact', 'verify-package', 'prepare-attachment'):
        sub = commands.add_parser(command)
        if command in ('verify-package', 'prepare-attachment'):
            sub.add_argument('manifest')
        elif command == 'impact':
            sub.add_argument('before'); sub.add_argument('after')
        else:
            sub.add_argument('content')
        if command == 'context':
            sub.add_argument('--scene', required=True)
            sub.add_argument('--budget-chars', type=int, required=True)
        if command == 'variant':
            sub.add_argument('variant')
        if command == 'prepare-attachment':
            sub.add_argument('--store', required=True)
            sub.add_argument('--base-version', required=True)
        sub.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    from drama_domain import validate_content, assemble_context, validate_variant
    from drama_impact import analyze_impact
    from drama_binding import verify_package, public_report, prepare_attachment
    try:
        if args.command == 'validate':
            result = validate_content(read(args.content))
        elif args.command == 'context':
            payload = Path(args.content).read_bytes()
            from drama_binding import json_bytes
            content = json_bytes(payload)
            resources = {}
            style_path = content.get('style_ref', {}).get('path')
            if isinstance(style_path, str):
                # A package's relative reference cannot silently read outside its root.
                from drama_binding import member_path
                target = member_path(Path(args.content).absolute().parent, style_path)
                if target.is_file():
                    resources[style_path] = target.read_bytes().decode('utf-8')
            result = assemble_context(content, args.scene, args.budget_chars,
                                      source_sha256=hashlib.sha256(payload).hexdigest(), resources=resources)
        elif args.command == 'variant':
            result = validate_variant(read(args.content), read(args.variant))
        elif args.command == 'impact':
            result = analyze_impact(read(args.before), read(args.after))
        elif args.command == 'verify-package':
            result = public_report(verify_package(args.manifest))
        else:
            result = prepare_attachment(args.manifest, args.store, args.base_version)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        result = {'status': 'FAIL', 'error': str(exc), 'host_adoption': 'NOT_RUN', 'media_review': 'NOT_RUN'}
    payload = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if args.output:
        # Exclusive create prevents silently replacing a previous evidence receipt.
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(payload)
    else:
        print(payload, end='')
    return 1 if result.get('status') == 'FAIL' else 2 if result.get('status') == 'UNCERTAIN' else 0


if __name__ == '__main__':
    raise SystemExit(main())
