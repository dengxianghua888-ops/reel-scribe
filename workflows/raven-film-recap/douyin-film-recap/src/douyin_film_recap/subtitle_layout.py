"""Opt-in, non-adopting subtitle line-break proposals using an explicit font.

This is a planning artifact, never a PASSED render or a replacement Storyboard.
Pillow/RAQM measurements must still be checked with the final libass renderer.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import shutil
import subprocess
import tempfile
import unicodedata
from pathlib import Path

from PIL import ImageFont, features


class LayoutBlocked(ValueError):
    pass


def _number(value, name, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise LayoutBlocked(f"INVALID_{name}")
    return value


def _coverage(data: bytes, index: int) -> list[tuple[int, int]]:
    tool = shutil.which('fc-query')
    if not tool:
        raise LayoutBlocked('FONT_COVERAGE_TOOL_UNAVAILABLE')
    # Inspect the exact font bytes used for measurement, not a mutable path.
    with tempfile.TemporaryDirectory(prefix='subtitle-font-') as directory:
        font = Path(directory) / 'font.bin'
        font.write_bytes(data)
        result = subprocess.run([tool, f'--index={index}', '--format=%{charset}', str(font)],
                                capture_output=True, text=True, check=True, timeout=30)
    ranges = []
    for item in result.stdout.split():
        if not re.fullmatch(r'[0-9a-fA-F]+(?:-[0-9a-fA-F]+)?', item):
            raise LayoutBlocked('FONT_COVERAGE_INVALID')
        values = item.split('-')
        ranges.append((int(values[0], 16), int(values[-1], 16)))
    if not ranges:
        raise LayoutBlocked('FONT_COVERAGE_EMPTY')
    return ranges


def propose_layout(cues: list[dict], *, font_file: str | Path, font_size: int,
                   width: int, height: int, margin_x: int, margin_v: int,
                   outline: int = 3, max_chars: int = 16, max_lines: int = 2, font_index: int = 0) -> dict:
    """Return immutable-source proposals; only newline insertions are permitted.

    An explicit single face is required. No font lookup, fallback, download,
    time splitting, shortening, automatic adoption or mutation occurs here.
    Existing newlines are hard boundaries. Whitespace is preserved byte-for-byte.
    """
    for name, value in locals().copy().items():
        if name in {'font_size', 'width', 'height', 'margin_x', 'margin_v', 'outline', 'max_chars', 'max_lines', 'font_index'}:
            if type(value) is not int:
                raise LayoutBlocked(f"INVALID_{name}")
            _number(value, name, 1 if name in {'font_size', 'width', 'height', 'max_chars', 'max_lines'} else 0)
    if width > 8192 or height > 8192 or font_size > height or max_lines > 20:
        raise LayoutBlocked('LAYOUT_LIMIT_EXCEEDED')
    available = width - 2 * (margin_x + outline)
    if available <= 0 or margin_v + font_size > height:
        raise LayoutBlocked('NO_AVAILABLE_REGION')
    if not features.check('raqm'):
        raise LayoutBlocked('RAQM_UNAVAILABLE')
    path = Path(font_file)
    data = path.read_bytes()
    try:
        font = ImageFont.truetype(io.BytesIO(data), font_size, index=font_index, layout_engine=ImageFont.Layout.RAQM)
    except OSError as exc:
        raise LayoutBlocked('FONT_UNREADABLE') from exc
    coverage = _coverage(data, font_index)
    if not isinstance(cues, list) or len(cues) > 10000:
        raise LayoutBlocked('INVALID_CUES')
    source = json.dumps(cues, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    rows, ids = [], set()
    closing = '，。！？；：、,.!?;:）)]】》〉」』”’'
    opening = '（([【《〈「『“‘'
    for cue in cues:
        if not isinstance(cue, dict) or set(cue) != {'id', 'start', 'end', 'text'}:
            raise LayoutBlocked('INVALID_CUE_FIELDS')
        identity, text = cue['id'], cue['text']
        if not isinstance(identity, str) or not identity or identity in ids:
            raise LayoutBlocked('INVALID_CUE_ID')
        ids.add(identity)
        if not isinstance(text, str) or not text or len(text) > 4096 or any(
                unicodedata.category(c) in {'Cc', 'Cf', 'Cs'} and c != '\n' for c in text):
            raise LayoutBlocked('INVALID_CUE_TEXT')
        if _number(cue['end'], 'END') <= _number(cue['start'], 'START'):
            raise LayoutBlocked('INVALID_CUE_TIME')
        # Combining clusters and multilingual scripts require language-specific
        # segmentation; do not silently split a grapheme or pretend support.
        if any(unicodedata.category(c).startswith('M') or 0x1F3FB <= ord(c) <= 0x1F3FF for c in text):
            raise LayoutBlocked('COMBINING_TEXT_NOT_SUPPORTED')
        if any(c != '\n' and not any(lo <= ord(c) <= hi for lo, hi in coverage) for c in text):
            raise LayoutBlocked(f'MISSING_GLYPH:{identity}')
        positions, line_start = [], 0
        for chunk in text.split('\n'):
            start = 0
            while start < len(chunk):
                end = start
                while end < len(chunk) and end-start < max_chars and font.getlength(chunk[start:end+1]) <= available:
                    end += 1
                if end == start:
                    raise LayoutBlocked(f'GLYPH_TOO_WIDE:{identity}')
                if end < len(chunk):
                    tokens = list(re.finditer(r'[A-Za-z0-9]+(?:[.\-\'’][A-Za-z0-9]+)*', chunk))
                    candidates = [k for k in range(start+1, end+1)
                                  if chunk[k] not in closing and chunk[k-1] not in opening
                                  and not any(t.start() < k < t.end() for t in tokens)]
                    if not candidates:
                        raise LayoutBlocked(f'UNBREAKABLE_TOKEN:{identity}')
                    end = candidates[-1]
                    positions.append(line_start + end)
                start = end
            line_start += len(chunk) + 1
        proposed = text
        for position in reversed(positions):
            proposed = proposed[:position] + '\n' + proposed[position:]
        lines = proposed.split('\n')
        if len(lines) > max_lines:
            raise LayoutBlocked(f'LINE_LIMIT:{identity}')
        ascent, descent = font.getmetrics()
        if len(lines) * (ascent + descent) + 2 * outline + margin_v > height:
            raise LayoutBlocked(f'HEIGHT_LIMIT:{identity}')
        rows.append({**cue, 'proposed_text': proposed, 'inserted_newline_offsets': positions,
                     'line_widths_px': [font.getlength(line) for line in lines]})
    return {'schema': 'subtitle-layout-candidate/1', 'status': 'CANDIDATE_ONLY',
            'source_sha256': hashlib.sha256(source.encode()).hexdigest(),
            'font_index': font_index, 'font_sha256': hashlib.sha256(data).hexdigest(), 'font_family': font.getname()[0],
            'parameters': {'font_size': font_size, 'width': width, 'height': height,
                           'margin_x': margin_x, 'margin_v': margin_v, 'outline': outline,
                           'max_chars': max_chars, 'max_lines': max_lines},
            'cues': rows, 'render_verification': 'NOT_PERFORMED',
            'glyph_coverage': 'FONT_CMAP_CHECKED', 'human_readability': 'NOT_REVIEWED',
            'adopted': False}


def main():
    """Standalone candidate command: never writes a workspace or render artifact."""
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('request', type=Path, help='JSON containing cues and explicit layout parameters')
    parser.add_argument('output', type=Path, help='New candidate JSON; never overwrites')
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding='utf-8'))
    result = propose_layout(**request)
    # Exclusive creation, including rejection of symlink targets.
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')


if __name__ == '__main__':
    main()
