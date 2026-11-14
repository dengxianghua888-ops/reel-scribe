"""Review-only reading-time conflicts; no changed cue map or sync acceptance."""
import argparse
import importlib.util
import json
import math
import re
from pathlib import Path

SPEC = importlib.util.spec_from_file_location('caption_contract', Path(__file__).with_name('blender_caption_candidate.py'))
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)
require = contract.require
THRESHOLDS = {'chars_per_sec': 20, 'english_wpm': 240, 'short_cue_sec': 2}


def nonspace(text):
    return ''.join(text.split())


def counts(text):
    # Match the pinned readability planner's ASCII-English diagnostic token rule.
    flat = ' '.join(text.replace('\n', ' ').split())
    return len(nonspace(flat)), len(re.findall(r"[A-Za-z]+(?:['‘’-][A-Za-z]+)*", flat))


def ceil_ratio(numerator, denominator):
    return (numerator + denominator - 1) // denominator


def finite_matches(value, expected):
    return (type(value) in (int, float) and math.isfinite(value)
            and math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-12))


def validate(data):
    require(isinstance(data, dict) and data.get('schema') == 'caption-readability-plan/1'
            and data.get('status') == 'REVIEW_CANDIDATE_ONLY' and data.get('adopted') is False,
            'READABILITY_CANDIDATE_REQUIRED')
    fps, end = data['fps'], data['frame_end']
    require(type(fps) is int and fps > 0 and type(end) is int and end > 0, 'INVALID_TIMEBASE')
    require(re.fullmatch('[0-9a-f]{64}', data['source_map_sha256']) is not None,
            'SOURCE_MAP_DIGEST_REQUIRED')
    font = data['font']
    require(isinstance(font, dict) and isinstance(font['path'], str) and bool(font['path'])
            and re.fullmatch('[0-9a-f]{64}', font['sha256']) is not None
            and type(font['face_index']) is int and font['face_index'] == 0, 'FONT_BINDING_REQUIRED')
    require(type(data['font_size_px']) is int and type(data['minimum_font_size_px']) is int
            and 32 <= data['minimum_font_size_px'] <= data['font_size_px'] <= 48,
            'FONT_SIZE_REQUIRED')
    source = contract.validate_map({'rows': data['source_rows']}, fps, end)
    rows = contract.validate_map({'rows': data['candidate_rows']}, fps, end)
    measurements = data['measurements']
    require(isinstance(measurements, list) and len(source) == len(rows) == len(measurements),
            'ROW_SET_MISMATCH')
    for a, b, measure in zip(source, rows, measurements):
        require({k: v for k, v in a.items() if k != 'text'} == {k: v for k, v in b.items() if k != 'text'}
                and nonspace(a['text']) == nonspace(b['text'])
                and counts(a['text']) == counts(b['text']), 'SOURCE_CANDIDATE_CHANGED')
        require(measure['row'] == b and measure['diagnostic_thresholds_not_acceptance'] == THRESHOLDS,
                'MEASUREMENT_BINDING_MISMATCH')
        chars, words = counts(b['text'])
        frames = b['end_frame'] - b['start_frame']
        cps, wpm, duration = chars * fps / frames, words * 60 * fps / frames, frames / fps
        require(finite_matches(measure['characters_per_host_second'], cps)
                and finite_matches(measure['english_words_per_minute'], wpm)
                and finite_matches(measure['host_duration_sec'], duration), 'STALE_MEASUREMENTS')
        flagged = frames < 2 * fps or chars * fps > 20 * frames or words * 60 * fps > 240 * frames
        require(measure['reading_review_required'] is flagged, 'STALE_REVIEW_FLAG')
    return rows, fps, end


def analyze(data):
    rows, fps, frame_end = validate(data)
    options, conflicts, within = [], [], []
    for i, row in enumerate(rows):
        chars, words = counts(row['text'])
        duration = row['end_frame'] - row['start_frame']
        target = max(2 * fps, ceil_ratio(chars * fps, 20), ceil_ratio(words * 60 * fps, 240))
        extra = max(0, target - duration)
        if extra == 0:
            within.append(row['id'])
            continue
        limit = rows[i + 1]['start_frame'] if i + 1 < len(rows) else frame_end
        available = limit - row['end_frame']
        item = {'id': row['id'], 'text_unchanged': row['text'],
                'original_window': {'start_frame': row['start_frame'], 'end_frame': row['end_frame']},
                'minimum_diagnostic_duration_frames': target,
                'required_tail_extension_frames': extra, 'available_tail_frames': available,
                'boundary_kind': 'next_caption_start' if i + 1 < len(rows) else 'scene_end',
                'boundary_frame': limit, 'sync_status': 'UNVERIFIED', 'adopted': False}
        if extra <= available:
            item.update(proposed_window={'start_frame': row['start_frame'], 'end_frame': row['end_frame'] + extra},
                        tail_lag_frames=extra,
                        status='TAIL_EXTENSION_REVIEW_OPTION_NOT_APPLIED')
            options.append(item)
        else:
            item.update(proposed_window=None, shortfall_frames=extra - available,
                        status='INSUFFICIENT_TAIL_SPACE_NO_TIME_PROPOSAL')
            conflicts.append(item)
    return {'schema': 'caption-reading-time-review/1', 'status': 'REVIEW_ONLY',
            'adopted': False, 'sync_status': 'UNVERIFIED', 'fps': fps, 'frame_end': frame_end,
            'diagnostic_thresholds_not_acceptance': THRESHOLDS,
            'source_map_sha256': data['source_map_sha256'], 'font_reference_only': data['font'],
            'review_options': options, 'conflicts': conflicts, 'within_diagnostic_limits_ids': within,
            'limitations': ['No changed cue map, no automatic adoption, no word alignment',
                           'An empty subtitle interval does not establish silence or semantic room',
                           'Meeting numeric diagnostics does not establish speech synchronization or human readability',
                           'No borrowing before cue start, merging, deletion, rewriting, or extension beyond the next cue/scene']}


def build(args):
    path = Path(args.layout).resolve(strict=True)
    require(path.stat().st_size <= 10_000_000, 'LAYOUT_SIZE_LIMIT')
    require(contract.digest(path) == args.layout_sha256, 'STALE_LAYOUT')
    data = json.loads(path.read_text(), object_pairs_hook=contract.unique)
    result = analyze(data)
    require(contract.digest(path) == args.layout_sha256, 'LAYOUT_CHANGED_DURING_READ')
    result['layout_sha256'] = args.layout_sha256
    contract.write_candidate(args.output, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('layout', 'layout-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    build(parser.parse_args())


if __name__ == '__main__':
    main()
