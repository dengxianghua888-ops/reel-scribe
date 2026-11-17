"""Actual static libass alpha coverage against explicitly declared output regions.

No scene/UI recognition. Shares the pure ASS generator with caption_burn;
actual libass renders lossless alpha masks, with no lossy video encode.
"""
import copy
from pathlib import Path
import shutil
import re

from PIL import Image

from editing_runtime import caption_ass, exact_keys, fingerprint, require, sha256, source, write_json
from work_ops import validate_document


def rect(value, width, height):
    fields = ['x', 'y', 'width', 'height']
    exact_keys(value, fields, fields)
    require(all(type(value[k]) is int for k in fields), 'LAYOUT_INTEGER_PIXELS_REQUIRED')
    x, y, w, h = (value[k] for k in fields)
    require(x >= 0 and y >= 0 and w > 0 and h > 0 and x+w <= width and y+h <= height,
            'LAYOUT_RECT_OUTSIDE_CANVAS')
    return [x, y, x+w, y+h]


def intersects(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def check(document, constraints, directory, tools):
    fields = ['schema', 'canvas', 'subtitle_band', 'protected_regions']
    exact_keys(constraints, fields, fields)
    require(constraints['schema'] == 'caption-layout/1', 'LAYOUT_SCHEMA_UNSUPPORTED')
    exact_keys(constraints['canvas'], ['width', 'height'], ['width', 'height'])
    require(all(type(constraints['canvas'][k]) is int for k in ['width','height']), 'LAYOUT_INTEGER_PIXELS_REQUIRED')
    width, height = document['plan']['width'], document['plan']['height']
    require(constraints['canvas'] == {'width': width, 'height': height}, 'LAYOUT_CANVAS_MISMATCH')
    require(type(width) is int and type(height) is int and 0 < width <= 1920 and 0 < height <= 1920,
            'LAYOUT_CANVAS_LIMIT')
    band = rect(constraints['subtitle_band'], width, height)
    protected = constraints['protected_regions']
    require(isinstance(protected, list) and 0 < len(protected) <= 64, 'LAYOUT_REGIONS_REQUIRED')
    boxes = {}; ids = set()
    for item in protected:
        exact_keys(item, ['id', 'rect'], ['id', 'rect'])
        require(isinstance(item['id'], str) and item['id'].strip() and item['id'] not in ids,
                'LAYOUT_REGION_ID_DUPLICATE_OR_EMPTY')
        ids.add(item['id']); boxes[item['id']] = rect(item['rect'], width, height)
    require(not any(intersects(band, box) for box in boxes.values()), 'LAYOUT_DECLARED_BAND_OVERLAP')
    _, cues, _ = validate_document(document, tools)
    require(0 < len(cues) <= 256, 'LAYOUT_CUE_LIMIT')
    padding = max(width, height)
    require(len(cues)*(width+2*padding)*(height+2*padding) <= 200_000_000, 'LAYOUT_PIXEL_BUDGET_EXCEEDED')
    require(document['caption_style'] is not None, 'LAYOUT_CAPTION_STYLE_REQUIRED')
    directory.mkdir(exist_ok=False)
    font = source(document['caption_style']['font'])
    suffix = Path(font['path']).suffix.lower()
    require(suffix in ['.ttf', '.otf', '.ttc'], 'FONT_FORMAT_UNSUPPORTED')
    (directory/'fonts').mkdir()
    shutil.copyfile(font['path'], directory/'fonts'/('specified'+suffix))
    require(sha256(directory/'fonts'/('specified'+suffix)) == font['sha256'], 'LAYOUT_FONT_CHANGED')
    observations = []
    for index, cue in enumerate(cues):
        folder = directory / f'cue-{index:04d}'
        folder.mkdir()
        # Canonical ASS is shared with the real caption renderer. Added margins
        # preserve the usable wrapping width and shift origin by padding only.
        style = copy.deepcopy(document['caption_style'])
        style['cues'] = [{'start': 0, 'end': 1, 'text': cue['text']}]
        if 'style_override' in cue:style['cues'][0]['style_override']=copy.deepcopy(cue['style_override'])
        require(len(cue['text']) <= 256, 'LAYOUT_TEXT_LIMIT')
        require(not any(ch in cue['text'] for ch in ['\n','\t'])
                and re.search(r'\s{2,}', cue['text']) is None, 'LAYOUT_EXPLICIT_SPACING_UNSUPPORTED')
        padding = max(width, height)
        masks = []
        for label, pad in [('original', 0), ('padded', padding)]:
            ass = caption_ass(style, width, height, 1, layout_padding=pad)
            (folder/(label+'.ass')).write_text(ass, encoding='utf-8')
            w, h = width+2*pad, height+2*pad
            tools.ff(['-f', 'lavfi', '-i', f'color=c=black@0:s={w}x{h}:r=1:d=1,format=rgba',
                '-vf', f'ass={label}.ass:fontsdir=../fonts:alpha=1,format=rgba',
                '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgba', label+'.rgba'], cwd=folder)
            raw_path = folder/(label+'.rgba')
            payload = raw_path.read_bytes()
            require(len(payload) == w*h*4, 'LAYOUT_MASK_SIZE_INVALID')
            mask = Image.frombytes('RGBA', (w,h), payload).getchannel('A')
            del payload
            mask.save(folder/(label+'.png'))
            raw_path.unlink()  # Own temporary raw bytes; lossless alpha PNG retained.
            masks.append(mask)
        original, padded_mask = masks
        require(original.tobytes() == padded_mask.crop((padding,padding,padding+width,padding+height)).tobytes(),
                'LAYOUT_PADDING_EQUIVALENCE_UNVERIFIED')
        padded_bounds = padded_mask.getbbox()
        require(padded_bounds is not None, 'LAYOUT_NO_VISIBLE_GLYPHS')
        # Text visible beyond the original canvas is clipped in a normal burn.
        require(padded_bounds[0] >= padding and padded_bounds[1] >= padding
                and padded_bounds[2] <= padding+width and padded_bounds[3] <= padding+height,
                'LAYOUT_GLYPHS_CLIPPED')
        min_x, min_y, right, bottom = (padded_bounds[0]-padding, padded_bounds[1]-padding,
                                      padded_bounds[2]-padding, padded_bounds[3]-padding)
        max_x, max_y = right-1, bottom-1
        require(max_x >= 0, 'LAYOUT_NO_VISIBLE_GLYPHS')
        bounds = [min_x, min_y, max_x+1, max_y+1]
        padded = [min_x-2, min_y-2, max_x+3, max_y+3]
        require(padded[0] >= 0 and padded[1] >= 0 and padded[2] <= width and padded[3] <= height,
                'LAYOUT_CANVAS_EDGE_UNSAFE')
        require(band[0] <= padded[0] and band[1] <= padded[1]
                and padded[2] <= band[2] and padded[3] <= band[3], 'LAYOUT_GLYPHS_OUTSIDE_DECLARED_BAND')
        require(not any(intersects(padded, box) for box in boxes.values()), 'LAYOUT_ACTUAL_PIXELS_OVERLAP')
        observations.append({'cue_id': cue['id'], 'output_window': [cue['start'], cue['end']],
            'text_sha256': fingerprint(cue['text']), 'bbox': bounds, 'padded_bbox': padded,
            'mask': {'path': str(folder/'original.png'), 'sha256': sha256(folder/'original.png')},
            'ass': {'path': str(folder/'original.ass'), 'sha256': sha256(folder/'original.ass')},
            'padded_mask_sha256': sha256(folder/'padded.png'), 'padding_pixels': padding})
        if 'style_override' in cue:
            observations[-1].update(style_override=copy.deepcopy(cue['style_override']),effective_style_sha256=cue['effective_style_sha256'])
    source(document['caption_style']['font'])
    report = {'schema': 'caption-layout-result/1', 'status': 'STATIC_GLYPH_COVERAGE_VERIFIED',
        'document_sha256': fingerprint(document), 'constraints': copy.deepcopy(constraints),
        'constraints_sha256': fingerprint(constraints), 'font': source(document['caption_style']['font']),
        'rendered_cue_timing': 'Static shape normalized to [0,1]; original cue windows retained; no timing acceptance',
        'renderer_sha256': sha256(Path(__file__).with_name('editing_runtime.py')),
        'tools': tools.doctor(), 'observations': observations, 'safety_padding_pixels': 2,
        'resource_limits': {'maximum_total_padded_pixels': 200_000_000, 'maximum_canvas_side': 1920,
                            'temporary_raw_masks_removed': True, 'font_copies': 1},
        'sampling': 'Each nonoverlapping static cue, constant glyph layout; animation/control syntax rejected by caption_burn',
        'scope': 'Pre-encode subtitle glyph/outline alpha coverage only; declared UI regions, no UI recognition',
        'font_fallback_verified': False, 'text_accuracy': 'NOT_VERIFIED',
        'aesthetic_readability': 'NOT_VERIFIED', 'post_codec_pixels': 'NOT_VERIFIED'}
    if any('style_override' in cue for cue in cues):
        report['style_resolver_sha256']=sha256(Path(__file__).with_name('caption_style.py'))
    write_json(directory/'layout-report.json', report)
    return report
