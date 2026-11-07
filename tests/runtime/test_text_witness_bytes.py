"""Literal text reports bind the parsed buffer, not two pathname observations.

Temporary JSON and WAV inputs are real files. FakeAudioTools supplies metadata
only; these tests do not establish speech recognition or listening quality.
"""
import copy
import hashlib
import json
from pathlib import Path
import sys
import wave
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import editing_runtime
import text_compare_ops


def reference(path):
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def write(path, text):
    path.write_text(json.dumps({'text': text}, ensure_ascii=False), encoding='utf-8')
    return reference(path)


class FakeAudioTools:
    def probe(self, path):
        return {'duration': 1, 'streams': [{'index': 0, 'codec_type': 'audio'}]}


@pytest.fixture
def comparison(tmp_path):
    audio = tmp_path / 'source.wav'
    with wave.open(str(audio), 'wb') as stream:
        stream.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        stream.writeframes(b'\0\0' * 8000)
    witnesses = {}
    for side, text in [('reference', '保留否定：不可以'), ('observed', '保留否定：可以')]:
        witnesses[side] = {'role': 'user-script' if side == 'reference' else 'model-observation',
                           'artifact': write(tmp_path / (side + '.json'), text),
                           'pointers': ['/text'], 'joiner': ''}
    document = {'schema': 'text-comparison/1', 'source': reference(audio), 'audio_stream': 0,
                'window': [0, 1], 'language': 'zh', **witnesses}
    request = {'operation': 'transcript-reference-compare', 'document': document,
               'expected_revision': editing_runtime.fingerprint(document), 'normalization': 'exact'}
    output = tmp_path / 'result'
    output.mkdir()
    return request, output


@pytest.mark.parametrize('side', ['reference', 'observed'])
def test_hash_parse_hash_aba_cannot_hide_text_difference(comparison, side):
    request, output = comparison
    doc = request['document']
    artifact = doc[side]['artifact']
    path = Path(artifact['path'])
    original_bytes = path.read_bytes()
    other_side = 'observed' if side == 'reference' else 'reference'
    substitution = Path(doc[other_side]['artifact']['path']).read_bytes()
    original_source = text_compare_ops.source
    calls = []

    def replace_between_observations(ref, *args, **kwargs):
        if ref == artifact:
            if calls:
                path.write_bytes(original_bytes)
            result = original_source(ref, *args, **kwargs)
            if not calls:
                path.write_bytes(substitution)
            calls.append(True)
            return result
        return original_source(ref, *args, **kwargs)

    with patch.object(text_compare_ops, 'source', replace_between_observations):
        with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
            text_compare_ops.execute(request, output, FakeAudioTools())
    assert calls
    assert not (output / 'text-comparison.json').exists()


def test_persistent_change_during_selection_is_still_rejected(comparison):
    request, output = comparison
    path = Path(request['document']['reference']['artifact']['path'])
    original_pointer = text_compare_ops.pointer_value

    def change_after_selection(*args):
        result = original_pointer(*args)
        path.write_text('{}')
        return result

    with patch.object(text_compare_ops, 'pointer_value', change_after_selection):
        with pytest.raises(ValueError, match='SOURCE_HASH_MISMATCH'):
            text_compare_ops.execute(request, output, FakeAudioTools())
    assert not (output / 'text-comparison.json').exists()


@pytest.mark.parametrize('normalization', ['exact', 'whitespace-only'])
def test_valid_report_keeps_original_unicode_offsets_and_limits(comparison, normalization):
    request, output = comparison
    request['normalization'] = normalization
    before = {side: Path(request['document'][side]['artifact']['path']).read_bytes()
              for side in ('reference', 'observed')}
    result = text_compare_ops.execute(request, output, FakeAudioTools())
    report = json.loads((output / 'text-comparison.json').read_text())
    assert result['status'] == 'DIFFERENCES_FOUND'
    assert report['differences'][0]['reference_text'] == '不'
    assert report['differences'][0]['reference_range'] == [5, 6]
    assert report['audio_truth'] == 'NOT_VERIFIED'
    for side, payload in before.items():
        assert report[side]['artifact']['sha256'] == hashlib.sha256(payload).hexdigest()
        assert Path(report[side]['artifact']['path']).read_bytes() == payload


def test_bounded_reader_rejects_growth_before_json_decode(comparison):
    request, _ = comparison
    spec = request['document']['reference']
    original_source = text_compare_ops.source
    path = Path(spec['artifact']['path'])

    def enlarge_after_size_check(ref, *args, **kwargs):
        result = original_source(ref, *args, **kwargs)
        if ref == spec['artifact']:
            with path.open('wb') as stream:
                stream.truncate(32 * 1024 * 1024 + 1)
        return result

    with patch.object(text_compare_ops, 'source', enlarge_after_size_check), \
            patch.object(text_compare_ops.json, 'loads', side_effect=AssertionError('must not decode oversized input')):
        with pytest.raises(ValueError, match='WITNESS_FILE_TOO_LARGE'):
            text_compare_ops.witness(spec)


@pytest.mark.parametrize('value,error', [({'x': 1}, 'SELECTED_VALUE_NOT_TEXT'),
                                        ('x' * 20001, 'TEXT_TOO_LARGE_SPLIT_EXPLICITLY')])
def test_existing_text_validation_remains(comparison, value, error):
    request, _ = comparison
    spec = copy.deepcopy(request['document']['reference'])
    path = Path(spec['artifact']['path'])
    path.write_text(json.dumps({'text': value}))
    spec['artifact'] = reference(path)
    with pytest.raises(ValueError, match=error):
        text_compare_ops.witness(spec)
