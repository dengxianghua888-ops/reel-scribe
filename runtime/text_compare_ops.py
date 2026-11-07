"""Compare explicit, version-bound text witnesses without choosing a true reading."""
import difflib
import hashlib
import json
import re

from editing_runtime import exact_keys, require, source, fingerprint, span, write_json


def pointer_value(value, pointer):
    require(isinstance(pointer, str) and (pointer == '' or pointer.startswith('/')), 'JSON_POINTER_REQUIRED')
    if pointer == '':
        return value
    for part in pointer[1:].split('/'):
        require(not re.search(r'~(?![01])', part), 'JSON_POINTER_ESCAPE_INVALID')
        key = part.replace('~1', '/').replace('~0', '~')
        if isinstance(value, list):
            require(bool(re.fullmatch(r'0|[1-9][0-9]*', key)), 'JSON_POINTER_INDEX_INVALID')
            index = int(key)
            require(index < len(value), 'JSON_POINTER_NOT_FOUND')
            value = value[index]
        else:
            require(isinstance(value, dict) and key in value, 'JSON_POINTER_NOT_FOUND')
            value = value[key]
    return value


def witness(spec):
    exact_keys(spec, ['role', 'artifact', 'pointers', 'joiner'], ['role', 'artifact', 'pointers', 'joiner'])
    require(spec['role'] in ['corpus-reference', 'user-script', 'model-observation', 'human-transcript'], 'WITNESS_ROLE_REQUIRED')
    artifact = source(spec['artifact'])
    require(artifact['bytes'] <= 32 * 1024 * 1024, 'WITNESS_FILE_TOO_LARGE')
    # Hash and parse the same bounded buffer. Pathname checks alone cannot
    # detect a replacement that is restored before the final observation.
    with open(artifact['path'], 'rb') as stream:
        payload = stream.read(32 * 1024 * 1024 + 1)
    require(len(payload) <= 32 * 1024 * 1024, 'WITNESS_FILE_TOO_LARGE')
    require(hashlib.sha256(payload).hexdigest() == artifact['sha256'],
            'SOURCE_HASH_MISMATCH: ' + artifact['path'])
    artifact['bytes'] = len(payload)
    data = json.loads(payload.decode('utf-8'))
    pointers = spec['pointers']
    require(isinstance(pointers, list) and pointers and all(isinstance(p, str) for p in pointers), 'TEXT_POINTERS_REQUIRED')
    require(len(pointers) == len(set(pointers)), 'DUPLICATE_TEXT_POINTER')
    require(isinstance(spec['joiner'], str) and len(spec['joiner']) <= 4, 'JOINER_REQUIRED')
    chunks, selections, offset = [], [], 0
    for p in pointers:
        value = pointer_value(data, p)
        require(isinstance(value, str), 'SELECTED_VALUE_NOT_TEXT')
        if chunks:
            chunks.append(spec['joiner'])
            offset += len(spec['joiner'])
        start = offset
        chunks.append(value)
        offset += len(value)
        selections.append({'pointer': p, 'range': [start, offset]})
        require(offset <= 20000, 'TEXT_TOO_LARGE_SPLIT_EXPLICITLY')
    text = ''.join(chunks)
    # The byte identity is checked again after extracting the strings.
    source(spec['artifact'])
    return {'role': spec['role'], 'artifact': artifact, 'text': text, 'selections': selections,
            'joiner': spec['joiner'], 'authority': 'caller-declared role, not independently authenticated'}


def normalized(text, mode):
    pairs = [(i, ch) for i, ch in enumerate(text) if mode == 'exact' or not ch.isspace()]
    return ''.join(ch for _, ch in pairs), [i for i, _ in pairs]


def original_range(start, end, positions, raw_length):
    if start == end:
        point = positions[start] if start < len(positions) else raw_length
        return [point, point]
    return [positions[start], positions[end - 1] + 1]


def execute(request, directory, tools):
    exact_keys(request, ['operation', 'document', 'expected_revision', 'normalization'],
               ['operation', 'document', 'expected_revision', 'normalization'])
    doc = request['document']
    exact_keys(doc, ['schema', 'source', 'audio_stream', 'window', 'language', 'reference', 'observed'],
               ['schema', 'source', 'audio_stream', 'window', 'language', 'reference', 'observed'])
    require(doc['schema'] == 'text-comparison/1', 'TEXT_COMPARISON_SCHEMA_UNSUPPORTED')
    require(fingerprint(doc) == request['expected_revision'], 'TEXT_COMPARISON_REVISION_CONFLICT')
    mode = request['normalization']
    require(mode in ['exact', 'whitespace-only'], 'NORMALIZATION_UNSUPPORTED')
    require(isinstance(doc['language'], str) and doc['language'].strip(), 'LANGUAGE_REQUIRED')
    asset = source(doc['source'])
    media = tools.probe(asset['path'])
    require(type(doc['audio_stream']) is int and any(s.get('index') == doc['audio_stream'] and s['codec_type'] == 'audio'
                                                   for s in media['streams']), 'AUDIO_STREAM_REQUIRED')
    require(isinstance(doc['window'], list) and len(doc['window']) == 2, 'SOURCE_WINDOW_REQUIRED')
    start, end = span(*doc['window'], media['duration'])
    reference, observed = witness(doc['reference']), witness(doc['observed'])
    a, apos = normalized(reference['text'], mode)
    b, bpos = normalized(observed['text'], mode)
    require(a and b, 'NONEMPTY_COMPARISON_TEXT_REQUIRED')
    require(len(a) * len(b) <= 4000000, 'COMPARISON_TOO_LARGE_SPLIT_EXPLICITLY')
    differences = []
    for tag, a0, a1, b0, b1 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == 'equal':
            continue
        ar = original_range(a0, a1, apos, len(reference['text']))
        br = original_range(b0, b1, bpos, len(observed['text']))
        differences.append({'kind': tag, 'reference_range': ar, 'observed_range': br,
            'reference_text': reference['text'][ar[0]:ar[1]], 'observed_text': observed['text'][br[0]:br[1]],
            'comparison_reference': a[a0:a1], 'comparison_observed': b[b0:b1],
            'reference_fields': [s for s in reference['selections'] if ar[0] < ar[1] and s['range'][0] < ar[1] and s['range'][1] > ar[0]],
            'observed_fields': [s for s in observed['selections'] if br[0] < br[1] and s['range'][0] < br[1] and s['range'][1] > br[0]],
            'acoustic_boundary': None})
    source(doc['source'])
    source(doc['reference']['artifact'])
    source(doc['observed']['artifact'])
    report = {'schema': 'text-comparison-result/1', 'document_revision': fingerprint(doc),
        'status': 'DIFFERENCES_FOUND' if differences else 'TEXT_MATCH_UNDER_DECLARED_NORMALIZATION',
        'source': asset, 'audio_stream': doc['audio_stream'], 'source_window': [start, end], 'language': doc['language'],
        'reference': reference, 'observed': observed, 'normalization': mode, 'raw_equal': reference['text'] == observed['text'],
        'difference_count': len(differences), 'differences': differences,
        'algorithm': 'Python difflib.SequenceMatcher, autojunk=False; reference-to-observed codepoint opcodes, not minimum edit distance/CER',
        'source_association': 'caller-declared; file integrity checked, spoken content and pointer completeness not verified',
        'audio_truth': 'NOT_VERIFIED', 'semantic_review': 'NOT_RUN', 'acoustic_alignment': 'NOT_RUN',
        'corrections': [], 'cut_plan': None,
        'limits': ['Fields and order are explicit; no claim of whole-file or whole-source coverage.',
                   'No normalization of numerals, punctuation, case, width or simplified/traditional characters.',
                   'Empty-side ranges are text insertion points, never inferred missing-word times.',
                   'No ranking of witnesses, automatic text adoption, corrected transcript or media modification.']}
    write_json(directory / 'text-comparison.json', report)
    return {'status': report['status'], 'document_revision': report['document_revision'],
            'difference_count': len(differences), 'audio_truth': 'NOT_VERIFIED', 'corrections': [], 'cut_plan': None}
