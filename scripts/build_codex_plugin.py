#!/usr/bin/env python3
"""Build a small, runnable Codex plugin from the current library source.

The plugin contains current Skills, contracts, registry and runtime. Historical
evaluation assets are deliberately outside this executable package and retain
their original paths and evidence status in the main library.
"""
import argparse
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location('packaging_common', Path(__file__).with_name('packaging_common.py'))
_common = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_common)
_RESOURCE_SPEC = importlib.util.spec_from_file_location('resource_edges', Path(__file__).with_name('resource_edges.py'))
_resources = importlib.util.module_from_spec(_RESOURCE_SPEC)
_RESOURCE_SPEC.loader.exec_module(_resources)
digest = _common.digest


def inventory():
    files = _common.source_members(ROOT)
    _common.validate_package(ROOT, files)
    # This lightweight target has no implicit historical resource declaration.
    # If web assets are added, require a separately reviewed resource-capable target.
    _resources.closure(ROOT, files, None)
    return _common.inventory_rows(ROOT, files)


def build(destination):
    destination = destination.resolve()
    if destination.exists():
        raise FileExistsError('PLUGIN_OUTPUT_ALREADY_EXISTS')
    rows = inventory()
    destination.mkdir(parents=True, exist_ok=False)
    (destination / 'build-incomplete.json').write_text('{"status":"BUILD_INCOMPLETE"}\n', encoding='utf-8')
    _common.copy_members(ROOT, destination, rows)
    output_files = {destination / row['path'] for row in rows}
    edges = _common.validate_package(destination, output_files)
    _resources.closure(destination, output_files, None)
    structure = _common.validate_structure(destination, rows)
    manifest = {
        'schema': 'editing-codex-plugin-package/1',
        'status': 'BUILT_NOT_INSTALLED',
        'plugin_name': 'editing-skill-library',
        'files': rows,
        'source_candidate': _common.source_identity(ROOT, rows),
        'directory_navigation': [row for row in edges if row['kind'] == 'directory'],
        'references_verified_against_final_members': True,
        'structure': structure,
        'file_modes_verified': True,
        'file_mode_scope': 'POSIX rwx bits only; no setuid/setgid/sticky or ACL certification',
        'historical_evaluation_assets': 'EXCLUDED; see authoritative source library',
        'native_editor_host': 'NOT_REQUIRED_FOR_GENERIC_SKILLS',
        'media_generation_provider': 'AGENT_OWNED_NOT_REQUIRED_FOR_SKILL_LOAD',
    }
    _common.verify_rows(ROOT, rows)
    _common.verify_rows(destination, rows)
    with (destination / 'plugin-package-manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    (destination / 'build-incomplete.json').unlink()
    return {'status': manifest['status'], 'path': str(destination),
            'files': len(rows), 'manifest_sha256': digest(destination / 'plugin-package-manifest.json')}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True, help='New absolute output directory')
    args = parser.parse_args()
    if not args.out.is_absolute():
        raise ValueError('PLUGIN_OUTPUT_ABSOLUTE_PATH_REQUIRED')
    print(json.dumps(build(args.out), ensure_ascii=False))


if __name__ == '__main__':
    main()
