"""Pinned translation-draft comparison report, never automatic translation/adoption."""
import argparse
import importlib.util
import json
from pathlib import Path
from PIL import ImageFont

SPEC = importlib.util.spec_from_file_location('readability_plan', Path(__file__).with_name('plan_caption_readability.py'))
layout = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(layout)
contract = layout.contract
require = contract.require
ENTRY_FIELDS = {'id', 'source_text', 'target_text', 'target_language', 'context_ids',
                'fidelity_notes', 'omitted_information'}


def strings(value, code):
    require(isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value), code)
    for x in value:
        contract.valid_text(x)


def validate_draft(draft, source):
    require(isinstance(draft, dict) and set(draft) == {'schema', 'entries'}
            and draft['schema'] == 'caption-translation-draft/1', 'DRAFT_FIELDS_OR_SCHEMA_INVALID')
    entries = draft['entries']
    require(isinstance(entries, list) and 0 < len(entries) <= len(source), 'DRAFT_ENTRIES_REQUIRED')
    known = {r['id']: r for r in source}
    seen = set()
    for entry in entries:
        require(isinstance(entry, dict) and set(entry) == ENTRY_FIELDS, 'DRAFT_ENTRY_FIELDS_INVALID')
        identity = entry['id']
        require(isinstance(identity, str) and identity in known and identity not in seen,
                'DRAFT_ID_UNKNOWN_OR_DUPLICATE')
        seen.add(identity)
        require(entry['source_text'] == known[identity]['text'], 'SOURCE_TEXT_MISMATCH')
        target = entry['target_text']
        layout.validate_layout_text(target)
        require(not any(c in target for c in ('\n', '\r', '\u2028', '\u2029')),
                'TARGET_MUST_BE_SINGLE_PARAGRAPH')
        require(entry['target_language'] == 'zh-CN', 'TARGET_LANGUAGE_UNSUPPORTED')
        context = entry['context_ids']
        require(isinstance(context, list) and all(isinstance(x, str) and x in known for x in context)
                and len(set(context)) == len(context), 'CONTEXT_IDS_INVALID')
        strings(entry['fidelity_notes'], 'FIDELITY_NOTES_INVALID')
        strings(entry['omitted_information'], 'OMITTED_INFORMATION_INVALID')
    return known, entries


def fit(text, font_path, minimum, maximum):
    for size in range(maximum, minimum - 1, -1):
        font = ImageFont.truetype(str(font_path), size)
        try:
            lines = layout.wrap_two(text, font, layout.BOX['width'])
        except ValueError as error:
            if str(error) != 'TWO_LINES_CANNOT_FIT':
                raise
            continue
        line_height = sum(font.getmetrics()) + 8
        if line_height * len(lines) > layout.BOX['height']:
            continue
        require(layout.nonspace('\n'.join(lines)) == layout.nonspace(text), 'TARGET_TEXT_CHANGED')
        return {'status': 'MEASURED_FIT_NOT_RENDER_VERIFIED', 'font_size_px': size,
                'lines': lines, 'line_widths_px': [float(layout.extent(font, x)) for x in lines],
                'line_height_px': line_height, 'box': dict(layout.BOX)}
    return {'status': 'GEOMETRY_CONFLICT_AT_MINIMUM_SIZE', 'font_size_px': None,
            'lines': None, 'minimum_font_size_px': minimum, 'box': dict(layout.BOX)}


def review(source_map, draft, font_path, *, fps, frame_end, minimum=32, maximum=40):
    require(type(fps) is int and fps > 0 and type(frame_end) is int and frame_end > 0, 'INVALID_TIMEBASE')
    require(type(minimum) is int and type(maximum) is int and 32 <= minimum <= maximum <= 48,
            'FONT_SIZE_RANGE_UNSUPPORTED')
    source = contract.validate_map(source_map, fps, frame_end)
    known, entries = validate_draft(draft, source)
    reports = []
    for entry in entries:
        row = known[entry['id']]
        frames = row['end_frame'] - row['start_frame']
        duration = frames / fps
        source_chars, target_chars = len(layout.nonspace(row['text'])), len(layout.nonspace(entry['target_text']))
        warnings = []
        if frames < 2 * fps:
            warnings.append('SHORT_DURATION_REVIEW_PROMPT_NOT_FAILURE')
        if target_chars * fps > 20 * frames:
            warnings.append('TARGET_CHARACTER_RATE_REVIEW_PROMPT_NOT_FAILURE')
        if entry['omitted_information']:
            warnings.append('DRAFT_DECLARES_OMISSIONS_REQUIRING_SEMANTIC_REVIEW')
        reports.append({'id': entry['id'], 'source_text': row['text'],
                        'source_window': {k: v for k, v in row.items() if k not in {'text', 'id'}},
                        'source_context': [dict(known[x]) for x in entry['context_ids']],
                        'target_text': entry['target_text'], 'target_language': entry['target_language'],
                        'draft_fidelity_notes_not_verified': list(entry['fidelity_notes']),
                        'draft_omitted_information_not_verified': list(entry['omitted_information']),
                        'host_duration_sec': duration,
                        'source_nonspace_characters': source_chars, 'target_nonspace_characters': target_chars,
                        'source_characters_per_host_second': source_chars / duration,
                        'target_characters_per_host_second': target_chars / duration,
                        'character_rate_change_per_host_second': (target_chars - source_chars) / duration,
                        'spatial_measurement': fit(entry['target_text'], font_path, minimum, maximum),
                        'warnings': warnings, 'semantic_fidelity': 'UNVERIFIED',
                        'audio_alignment': 'UNVERIFIED', 'human_readability': 'UNVERIFIED', 'adopted': False})
    return {'schema': 'caption-translation-review/1', 'status': 'REVIEW_ONLY', 'adopted': False,
            'fps': fps, 'frame_end': frame_end, 'reports': reports,
            'diagnostic_prompts_not_acceptance': {'short_window_sec': 2, 'target_chars_per_sec': 20},
            'limitations': ['No automatic translation, source/project change, timing change or adoptable cue map',
                           'Draft fidelity and omission statements are not verified assertions',
                           'Pinned Pillow font measurement is not actual Blender raster verification',
                           'A short window or lower character rate is neither automatic failure nor human readability acceptance',
                           'Language label does not verify language, accuracy, meaning, or speech alignment']}


def build(args):
    paths = [Path(args.source_map).resolve(strict=True), Path(args.draft).resolve(strict=True),
             Path(args.font).resolve(strict=True)]
    expected = [args.source_sha256, args.draft_sha256, args.font_sha256]
    require(all(p.stat().st_size <= 10_000_000 for p in paths[:2]), 'JSON_SIZE_LIMIT')
    require(all(contract.digest(p) == h for p, h in zip(paths, expected)), 'STALE_INPUT')
    source, draft = [json.loads(p.read_text(), object_pairs_hook=contract.unique) for p in paths[:2]]
    result = review(source, draft, paths[2], fps=args.fps, frame_end=args.frame_end,
                    minimum=args.minimum_size, maximum=args.maximum_size)
    require(all(contract.digest(p) == h for p, h in zip(paths, expected)), 'INPUT_CHANGED_DURING_READ')
    result['source_map_sha256'], result['draft_sha256'] = expected[:2]
    result['font'] = {'path': str(paths[2]), 'sha256': expected[2], 'face_index': 0}
    contract.write_candidate(args.output, result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-map', 'source-sha256', 'draft', 'draft-sha256', 'font', 'font-sha256', 'output'):
        parser.add_argument('--' + name, required=True)
    parser.add_argument('--fps', type=int, required=True)
    parser.add_argument('--frame-end', type=int, required=True)
    parser.add_argument('--minimum-size', type=int, default=32)
    parser.add_argument('--maximum-size', type=int, default=40)
    build(parser.parse_args())


if __name__ == '__main__':
    main()
