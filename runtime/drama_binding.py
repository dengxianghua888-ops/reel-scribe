"""Hash-bound drama attachments for existing Work revisions; no second project store.

Checks consume the bytes whose digest was checked. A final boundary recheck is
not a filesystem/SQLite atomic transaction or protection against A-B-A writes.
"""
import errno
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import tempfile


class DramaBindingError(ValueError):
    pass


def require(value, message):
    if not value:
        raise DramaBindingError(message)


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def json_bytes(payload):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'DRAMA_DUPLICATE_JSON_KEY: ' + key)
            result[key] = value
        return result
    try:
        return json.loads(payload, object_pairs_hook=unique,
                          parse_constant=lambda value: require(False, 'DRAMA_NONFINITE_JSON'))
    except (UnicodeError, ValueError) as exc:
        raise DramaBindingError('DRAMA_JSON_INVALID: ' + str(exc)) from exc


def checked_bytes(path, identity):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'DRAMA_FILE_REQUIRED: ' + str(path))
    require(isinstance(identity, dict), 'DRAMA_IDENTITY_REQUIRED')
    require(isinstance(identity.get('sha256'), str) and
            re.fullmatch('[a-f0-9]{64}', identity['sha256']), 'DRAMA_SHA256_REQUIRED')
    require(type(identity.get('size_bytes')) is int and identity['size_bytes'] >= 0,
            'DRAMA_SIZE_REQUIRED')
    data = path.read_bytes()
    require(len(data) == identity['size_bytes'] and digest(data) == identity['sha256'],
            'DRAMA_IDENTITY_CHANGED: ' + str(path))
    return data


def member_path(root, name):
    require(isinstance(name, str) and bool(name) and '\\' not in name,
            'DRAMA_MEMBER_PATH_INVALID')
    relative = PurePosixPath(name)
    require(not relative.is_absolute() and '..' not in relative.parts and
            str(relative) == name, 'DRAMA_MEMBER_PATH_INVALID: ' + name)
    path = root.joinpath(*relative.parts)
    require(root.resolve() in path.resolve().parents, 'DRAMA_MEMBER_ESCAPES_PACKAGE')
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        require(not cursor.is_symlink(), 'DRAMA_SYMLINK_NOT_SUPPORTED')
    return path


def verify_package(manifest_path, identity=None):
    """Verify manifest, members, content rules and declared local media identities."""
    from drama_domain import validate_content
    path = Path(manifest_path).absolute()
    require(path.is_file() and not path.is_symlink(), 'DRAMA_MANIFEST_REQUIRED')
    raw = path.read_bytes() if identity is None else checked_bytes(path, identity)
    manifest = json_bytes(raw)
    require(isinstance(manifest, dict) and manifest.get('schema') == 'drama-package/0.1',
            'DRAMA_PACKAGE_SCHEMA_UNSUPPORTED')
    for key in ('package_id', 'package_revision', 'content_path'):
        require(isinstance(manifest.get(key), str) and manifest[key], 'DRAMA_PACKAGE_FIELD: ' + key)
    require(manifest.get('work_binding') == {'authority_kind': 'unbound_design',
            'work_id': None, 'revision_id': None, 'adoption_receipt': None},
            'DRAMA_PACKAGE_IS_NOT_ADOPTION_AUTHORITY')
    members = manifest.get('members')
    require(isinstance(members, list) and members, 'DRAMA_PACKAGE_MEMBERS_REQUIRED')
    records = [{'path': str(path), 'sha256': digest(raw), 'size_bytes': len(raw)}]
    payloads = {}
    for item in members:
        require(isinstance(item, dict), 'DRAMA_MEMBER_INVALID')
        name = item.get('path')
        target = member_path(path.parent, name)
        require(target != path and name not in payloads, 'DRAMA_DUPLICATE_OR_SELF_MEMBER')
        payloads[name] = checked_bytes(target, item)
        records.append({'path': str(target), 'sha256': item['sha256'], 'size_bytes': item['size_bytes']})
    require(manifest['content_path'] in payloads, 'DRAMA_CONTENT_NOT_IN_MANIFEST')
    content = json_bytes(payloads[manifest['content_path']])
    report = validate_content(content)
    require(report.get('status') == 'PASS', 'DRAMA_DOMAIN_NOT_PASS: ' + json.dumps(report, ensure_ascii=False))
    # The content file also cannot manufacture a host adoption receipt.
    require(content.get('work_binding') == manifest['work_binding'], 'DRAMA_CONTENT_BINDING_MISMATCH')
    content_root = member_path(path.parent, manifest['content_path']).parent
    documents = [('style_ref.path', content.get('style_ref', {}).get('path'))]
    documents += [('document_views.' + key, content.get('document_views', {}).get(key))
                  for key in ('screenplay', 'style_assets', 'shot_state')]
    for field, relative in documents:
        require(isinstance(relative, str) and relative, 'DRAMA_DOCUMENT_REFERENCE_REQUIRED: ' + field)
        target = member_path(content_root, relative)
        name = target.relative_to(path.parent).as_posix()
        require(name in payloads, 'DRAMA_DOCUMENT_NOT_IN_MANIFEST: ' + field)
    bindings = [(asset.get('asset_id', '?'), asset.get('actual_binding'))
                for asset in content.get('assets', [])]
    bindings += [(shot.get('shot_id', '?'), shot.get('actual_binding'))
                 for shot in content.get('shots', [])]
    for table in ('background', 'propositions', 'events'):
        for row in content.get(table, []):
            basis = row.get('basis') or {}
            bindings.append((table + '.basis', basis.get('actual_binding')))
    for snapshot in content.get('snapshots', []):
        for knowledge in snapshot.get('knowledge', []):
            bindings.append((snapshot['snapshot_id'] + '.observation_evidence',
                             knowledge.get('observation_evidence')))
    for owner, binding in bindings:
        if binding is None:
            continue
        require(isinstance(binding, dict) and isinstance(binding.get('path'), str),
                'DRAMA_LOCAL_MEDIA_BINDING_REQUIRED: ' + owner)
        media_path = Path(binding['path'])
        if not media_path.is_absolute():
            media_path = member_path(content_root, binding['path'])
            require(media_path.relative_to(path.parent).as_posix() in payloads, 'DRAMA_MEDIA_NOT_IN_MANIFEST')
        checked_bytes(media_path, binding)
        records.append({'path': str(media_path), 'sha256': binding['sha256'],
                        'size_bytes': binding['size_bytes']})
    return {'schema': 'drama-package-verification/0.1', 'status': 'PASS',
            'manifest': records[0], 'package_id': manifest['package_id'],
            'package_revision': manifest['package_revision'], 'content_schema': content['schema'],
            'domain_validation': report, 'checked_files': records,
            'media_review': 'NOT_RUN', 'semantic_review': 'NOT_RUN', 'host_adoption': 'NOT_RUN',
            'content': content, 'package': manifest}


def verify_reference(reference, *, expected_base=None, require_base=False):
    fields = {'schema', 'package_id', 'package_revision', 'manifest', 'content_schema', 'base_work_version'}
    require(isinstance(reference, dict) and set(reference) == fields, 'DRAMA_REF_FIELDS_INVALID')
    require(reference['schema'] == 'drama-domain-ref/0.1', 'DRAMA_REF_SCHEMA_UNSUPPORTED')
    require(isinstance(reference['base_work_version'], str) and reference['base_work_version'],
            'DRAMA_BASE_WORK_VERSION_REQUIRED')
    if require_base:
        require(reference['base_work_version'] == expected_base, 'DRAMA_BASE_WORK_VERSION_CONFLICT')
    identity = reference['manifest']
    require(isinstance(identity, dict) and isinstance(identity.get('path'), str) and
            Path(identity['path']).is_absolute(), 'DRAMA_ABSOLUTE_MANIFEST_REQUIRED')
    report = verify_package(identity['path'], identity)
    for key in ('package_id', 'package_revision', 'content_schema'):
        require(reference[key] == report[key], 'DRAMA_REF_IDENTITY_MISMATCH: ' + key)
    return report


def recheck(report):
    """Immediately before a Work append, recheck all bytes checked during validation."""
    for identity in report['checked_files']:
        checked_bytes(identity['path'], identity)


def public_report(report):
    return {key: value for key, value in report.items() if key not in ('content', 'package')}


def prepare_attachment(manifest_path, store, base_version):
    """Prepare only. The returned note must still use timeline-revise + Work CAS."""
    from work_ops import connect, load
    store = Path(store)
    require(store.is_absolute() and store.is_file(), 'DRAMA_EXISTING_WORK_STORE_REQUIRED')
    db = connect(store)
    try:
        state = load(db)
        require(state['version'] == base_version, 'DRAMA_BASE_WORK_VERSION_CONFLICT')
    finally:
        db.close()
    report = verify_package(manifest_path)
    root = store.parent / 'domain' / 'drama'
    root.mkdir(parents=True, exist_ok=True)
    target = root / report['manifest']['sha256']
    target_manifest = target / 'PACKAGE-MANIFEST.json'
    if not target.exists():
        with tempfile.TemporaryDirectory(prefix='.preparing-', dir=root) as temporary:
            temp = Path(temporary)
            source_root = Path(manifest_path).absolute().parent
            for item in report['package']['members']:
                data = checked_bytes(member_path(source_root, item['path']), item)
                out = member_path(temp, item['path'])
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_bytes(data)
            (temp / 'PACKAGE-MANIFEST.json').write_bytes(checked_bytes(manifest_path, report['manifest']))
            verify_package(temp / 'PACKAGE-MANIFEST.json', report['manifest'])
            try:
                temp.rename(target)
            except OSError as exc:
                if exc.errno not in (errno.EEXIST,errno.ENOTEMPTY):
                    raise
                # Another preparation may have won. Never trust the error alone;
                # verify its exact manifest and member bytes below.
    installed = verify_package(target_manifest, report['manifest'])
    reference = {'schema': 'drama-domain-ref/0.1',
                 'package_id': report['package_id'], 'package_revision': report['package_revision'],
                 'manifest': {**report['manifest'], 'path': str(target_manifest)},
                 'content_schema': report['content_schema'], 'base_work_version': base_version}
    # PREPARED is explicitly not an adopted scene, host change, or media proof.
    return {'status': 'PREPARED', 'work_id': state['work_id'], 'base_version': base_version,
            'note_key': 'drama_domain_ref', 'reference': reference,
            'validation': public_report(installed), 'host_adoption': 'NOT_RUN'}


def validate_work_attachment(document, *, previous=None, expected_base=None):
    reference = document.get('notes', {}).get('drama_domain_ref')
    if reference is None:
        # Absence remains backward compatible; explicit null is not a typed ref.
        require('drama_domain_ref' not in document.get('notes', {}), 'DRAMA_NULL_REF_INVALID')
        return None
    changed = previous is not None and previous.get('notes', {}).get('drama_domain_ref') != reference
    return verify_reference(reference, expected_base=expected_base, require_base=changed)
