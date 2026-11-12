"""Batch-local verified timeline reuse, never final-output or QA reuse."""
from contextvars import ContextVar
from contextlib import contextmanager
import copy
import hashlib
import json
from pathlib import Path

PROVIDER = ContextVar('batch_timeline_provider', default=None)


@contextmanager
def provider(callback):
    token = PROVIDER.set(callback)
    try:
        yield
    finally:
        PROVIDER.reset(token)


def compatible(left, right):
    """Only post-timeline presentation parameters may differ; never layer identity."""
    allowed = {'audio_tracks': {'gain_db'}, 'visual_layers': {'rect', 'opacity', 'z'}}
    def same_type(a, b):
        return type(a) is type(b) and (not isinstance(a, list) or
            len(a) == len(b) and all(same_type(x, y) for x, y in zip(a, b)))
    for field, mutable in allowed.items():
        before, after = left.get(field, {}), right.get(field, {})
        if not isinstance(before, dict) or not isinstance(after, dict) or before.keys() != after.keys():
            return False
        for key, value in before.items():
            other = after[key]
            if not isinstance(value, dict) or not isinstance(other, dict) or value.keys() != other.keys():
                return False
            if any(value[k] != other[k] for k in value if k not in mutable):
                return False
            if any(not same_type(value[k], other[k]) for k in mutable if k in value):
                return False
    excluded = {'caption_style', 'style_bindings', *allowed}
    def core(d):
        return {k: v for k, v in d.items() if k not in excluded}
    return core(left) == core(right)


def checked_bytes(path, sha, size=None):
    from editing_runtime import require
    p = Path(path)
    require(not p.is_symlink(), 'SHARED_TIMELINE_SYMLINK')
    require(p.stat().st_size <= 16*1024*1024, 'SHARED_TIMELINE_JSON_TOO_LARGE')
    with p.open('rb') as stream:raw = stream.read(16*1024*1024+1)
    require(hashlib.sha256(raw).hexdigest() == sha and
            (size is None or len(raw) == size), 'SHARED_TIMELINE_ARTIFACT_CHANGED')
    return raw



def checked_file(path, sha, size):
    from editing_runtime import require, sha256
    p = Path(path)
    require(not p.is_symlink() and p.is_file() and p.stat().st_size == size and
            sha256(p) == sha, 'SHARED_TIMELINE_ARTIFACT_CHANGED')


def copy_bound(source, target, sha, size):
    from editing_runtime import require
    checked_file(source, sha, size)
    digest = hashlib.sha256(); count = 0
    with Path(source).open('rb') as src, Path(target).open('xb') as dst:
        while chunk := src.read(1024*1024):
            count += len(chunk)
            require(count <= size, 'SHARED_TIMELINE_ARTIFACT_CHANGED')
            digest.update(chunk); dst.write(chunk)
    require(count == size and digest.hexdigest() == sha, 'SHARED_TIMELINE_ARTIFACT_CHANGED')
    checked_file(source, sha, size)
    checked_file(target, sha, size)


def inspect_lineage(folder, lineage):
    """Recheck donor and local copied bytes; hashes originate in donor receipt."""
    from editing_runtime import require
    donor = Path(lineage['donor_receipt']['path'])
    raw = checked_bytes(donor, lineage['donor_receipt']['sha256'])
    receipt = json.loads(raw)
    require(receipt['status'] == 'SUCCEEDED', 'SHARED_TIMELINE_DONOR_FAILED')
    require(not receipt['result'].get('timeline_reuse'), 'SHARED_TIMELINE_CHAIN_UNSUPPORTED')
    expected = [a for a in receipt['artifacts'] if a['path'].startswith('timeline/')]
    require(expected == lineage['artifacts'], 'SHARED_TIMELINE_ARTIFACT_SET_CHANGED')
    require(any(a['path'] == 'timeline/preview.mp4' for a in expected) and
            any(a['path'] == 'timeline/receipt.json' for a in expected), 'SHARED_TIMELINE_INCOMPLETE')
    for item in expected:
        relative = Path(item['path'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'SHARED_TIMELINE_PATH_INVALID')
        for root in (donor.parent, Path(folder)):
            p = root / relative
            require(p.resolve().is_relative_to(root.resolve()), 'SHARED_TIMELINE_PATH_ESCAPE')
            checked_file(p, item['sha256'], item['bytes'])
    return receipt


def obtain(document, request, directory, tools):
    from editing_runtime import require, write_json
    callback = PROVIDER.get()
    if callback is None:
        return None
    selected = callback(document, request)
    if selected is None:
        return None
    donor, receipt, recheck = selected
    expected = [a for a in receipt['artifacts'] if a['path'].startswith('timeline/')]
    lineage = {'schema': 'shared-timeline/1', 'donor_receipt': copy.deepcopy(donor),
               'artifacts': copy.deepcopy(expected), 'stage': 'timeline-render',
               'execution': 'REUSED_VERIFIED_NOT_EXECUTED', 'qa_inherited': False}
    require(not (directory/'timeline').exists(), 'SHARED_TIMELINE_TARGET_EXISTS')
    for item in expected:
        relative = Path(item['path'])
        require(not relative.is_absolute() and '..' not in relative.parts, 'SHARED_TIMELINE_PATH_INVALID')
        source = Path(donor['path']).parent / relative
        require(source.resolve().is_relative_to(Path(donor['path']).parent.resolve()), 'SHARED_TIMELINE_PATH_ESCAPE')
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        copy_bound(source, target, item['sha256'], item['bytes'])
    inspect_lineage(directory, lineage)
    recheck()
    write_json(directory/'timeline-reuse.json', lineage)
    return lineage, recheck
