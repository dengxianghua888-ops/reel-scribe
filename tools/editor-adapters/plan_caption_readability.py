"""Pinned, candidate-only 720x1280 two-line soft-wrap plan; no timing edits."""
import argparse
import importlib.util
import json
import re
import unicodedata
from pathlib import Path
from PIL import ImageFont

SPEC = importlib.util.spec_from_file_location('caption_contract', Path(__file__).with_name('blender_caption_candidate.py'))
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)
require = contract.require
BOX = {'x': 48, 'y': 900, 'width': 624, 'height': 240}
PICTURE = {'x': 0, 'y': 160, 'width': 720, 'height': 600}


def validate_layout_text(text):
    contract.valid_text(text)
    require(all(not unicodedata.category(c).startswith('M') for c in text),
            'COMBINING_OR_VARIATION_SEQUENCE_UNSUPPORTED')


def normalized(text):
    validate_layout_text(text)
    # The caller declares these line breaks soft. No lexical/punctuation correction.
    text = re.sub(r'(?<=[\u3400-\u9fff])\n(?=[\u3400-\u9fff])', '', text)
    return ' '.join(text.replace('\n', ' ').split())


def nonspace(text):
    return ''.join(text.split())


def word_char(c):
    return ((c.isascii() and (c.isalnum() or c in "'-"))
            or '\u00c0' <= c <= '\u024f' or c in '\u2018\u2019')


def extent(font, text):
    bbox = font.getbbox(text)
    return max(font.getlength(text), bbox[2] - min(0, bbox[0]))


def wrap_two(text, font, width):
    validate_layout_text(text)
    if extent(font, text) <= width:
        return [text]
    choices = []
    for i in range(1, len(text)):
        if word_char(text[i-1]) and word_char(text[i]):
            continue
        a, b = text[:i].rstrip(), text[i:].lstrip()
        if not a or not b:
            continue
        widths = [extent(font, a), extent(font, b)]
        if max(widths) <= width:
            punctuation_penalty = 0 if a[-1] in '。！？；，.!?;,' else 1
            choices.append((punctuation_penalty, max(widths), abs(widths[0]-widths[1]), i, [a, b]))
    require(bool(choices), 'TWO_LINES_CANNOT_FIT')
    return min(choices)[-1]


def plan(data, font_path, *, fps=24, frame_end=984, minimum=32, maximum=40):
    require(type(minimum) is int and type(maximum) is int and 32 <= minimum <= maximum <= 48,
            'FONT_SIZE_RANGE_UNSUPPORTED')
    require(type(fps) is int and fps > 0, 'FPS_MUST_BE_POSITIVE_INTEGER')
    require(type(frame_end) is int and frame_end > 0, 'FRAME_END_MUST_BE_POSITIVE_INTEGER')
    rows = contract.validate_map(data, fps, frame_end)
    source = json.loads(json.dumps(rows))
    for size in range(maximum, minimum-1, -1):
        font = ImageFont.truetype(str(font_path), size)
        result = []
        try:
            for row in rows:
                flat = normalized(row['text'])
                lines = wrap_two(flat, font, BOX['width'])
                require(nonspace('\n'.join(lines)) == nonspace(row['text']), 'TEXT_CHANGED')
                ascent, descent = font.getmetrics()
                line_height = ascent + descent + 8
                require(line_height * len(lines) <= BOX['height'], 'TEXT_HEIGHT_EXCEEDS_BOX')
                duration = (row['end_frame']-row['start_frame'])/fps
                count = len(nonspace(flat))
                words = len(re.findall(r"[A-Za-z]+(?:['‘’-][A-Za-z]+)*", flat))
                wpm = words/duration*60
                edited = dict(row)
                edited['text'] = '\n'.join(lines)
                result.append({'row': edited, 'lines': lines,
                               'line_widths_px': [float(extent(font, x)) for x in lines],
                               'line_height_px': line_height,
                               'characters_per_host_second': count/duration,
                               'host_duration_sec': duration,
                               'english_words_per_minute': wpm,
                               'diagnostic_thresholds_not_acceptance': {'chars_per_sec':20, 'english_wpm':240, 'short_cue_sec':2},
                               'reading_review_required': duration < 2 or count/duration > 20 or wpm > 240})
        except ValueError as error:
            if str(error) not in {'TWO_LINES_CANNOT_FIT', 'TEXT_HEIGHT_EXCEEDS_BOX'}:
                raise
            continue
        return {'schema': 'caption-readability-plan/1', 'status': 'REVIEW_CANDIDATE_ONLY',
                'adopted': False, 'canvas': {'width':720, 'height':1280},
                'coordinate_system': 'top-left pixel rectangles', 'caption_box': BOX,
                'picture_box': PICTURE, 'picture_policy': 'fit entire picture, preserve aspect; black unused canvas; no crop',
                'font_size_px': size, 'minimum_font_size_px': minimum,
                'fps':fps, 'frame_end':frame_end, 'source_rows':source,
                'candidate_rows':[r['row'] for r in result], 'measurements':result,
                'limitations':['Pillow measurements are not Blender pixel verification',
                  'No cue splitting, time extension, word alignment or text correction',
                  'Reading-speed flags are diagnostics, not readability acceptance',
                  'Separate native rendering, safe-zone inspection and human reading review remain required']}
    raise ValueError('TWO_LINES_CANNOT_FIT_AT_MINIMUM_SIZE')


def build(args):
    require(args.acknowledge_reflow, 'EXPLICIT_SOFT_WRAP_ACK_REQUIRED')
    mp, fp = Path(args.caption_map).resolve(strict=True), Path(args.font).resolve(strict=True)
    require(mp.stat().st_size <= 10_000_000, 'MAP_SIZE_LIMIT')
    require(contract.digest(mp) == args.map_sha256 and contract.digest(fp) == args.font_sha256, 'STALE_INPUT')
    data = json.loads(mp.read_text(), object_pairs_hook=contract.unique)
    result = plan(data, fp, fps=args.fps, frame_end=args.frame_end,
                  minimum=args.minimum_size, maximum=args.maximum_size)
    require(contract.digest(mp) == args.map_sha256 and contract.digest(fp) == args.font_sha256, 'INPUT_CHANGED_DURING_READ')
    result['source_map_sha256'] = args.map_sha256
    result['font'] = {'path':str(fp), 'sha256':args.font_sha256, 'face_index':0}
    contract.write_candidate(args.output, result)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('caption-map','map-sha256','font','font-sha256','output'):
        p.add_argument('--'+name, required=True)
    p.add_argument('--acknowledge-reflow',action='store_true')
    p.add_argument('--fps',type=int,default=24)
    p.add_argument('--frame-end',type=int,required=True)
    p.add_argument('--minimum-size',type=int,default=32)
    p.add_argument('--maximum-size',type=int,default=40)
    build(p.parse_args())


if __name__ == '__main__':
    main()
