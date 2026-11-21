"""Compare a graded video with its pre-grade reference over declared segments.

Measures what grading changed: caller-declared protections (CIELAB hue ranges
or regions) as CIEDE2000 between the same reference and candidate pixels,
per-segment flicker and clipping, limited-range legality, and drift between
adjacent segments. Gates apply only where the caller declared a threshold or a
protection. Nothing here judges looks, detects skin or faces, or normalizes
any colour toward a target.
"""
import math

from color_numerics import lab_from_rgb01, ciede2000, numpy as _numpy

SCHEMA = 'color-consistency/1'
MAX_SEGMENTS = 256
MAX_PROTECTIONS = 16
MAX_SAMPLES_PER_SEGMENT = 8
MAX_FRAMES = 512
ANALYSIS_WIDTH = 256
MIN_PROTECTED_PIXELS = 64
HIGHLIGHT_CODE = 254
SHADOW_CODE = 1
LEGAL_Y = (16, 235)
LIMIT_KEYS = ('max_flicker_increase', 'max_clip_increase', 'max_drift_increase', 'max_out_of_range_fraction')
TRANSFERS = {'bt709-sdr': 'bt1886', 'srgb-sdr': 'srgb'}


def _r(value, digits=4):
    return None if value is None else round(float(value), digits)


def _segments(value, frames):
    from editing_runtime import exact_keys, require
    require(isinstance(value, list) and 1 <= len(value) <= MAX_SEGMENTS, 'COLOR_CHECK_SEGMENTS_INVALID')
    result, seen, previous = [], set(), 0
    for item in value:
        exact_keys(item, ['id', 'start_frame', 'end_frame', 'space'], ['id', 'start_frame', 'end_frame'])
        sid, a, b = item['id'], item['start_frame'], item['end_frame']
        require(isinstance(sid, str) and sid.strip() and sid not in seen, 'COLOR_CHECK_SEGMENT_ID_INVALID')
        require(type(a) is int and type(b) is int and previous <= a < b <= frames,
                'COLOR_CHECK_SEGMENT_OUTSIDE_OR_UNSORTED: ' + sid)
        space = item.get('space')
        require(space is None or space in TRANSFERS, 'COLOR_CHECK_SEGMENT_SPACE_UNSUPPORTED: ' + sid)
        seen.add(sid)
        previous = b
        result.append({'id': sid, 'start_frame': a, 'end_frame': b, 'space': space})
    return result


def _box(box, pid):
    from editing_runtime import require, number
    require(isinstance(box, list) and len(box) == 4, 'COLOR_CHECK_REGION_BOX_INVALID: ' + pid)
    x0, y0, x1, y1 = (number(x, 'box', 0) for x in box)
    require(x0 < x1 <= 1 and y0 < y1 <= 1, 'COLOR_CHECK_REGION_BOX_INVALID: ' + pid)
    return [x0, y0, x1, y1]


def _box_mask(box, width, height):
    np = _numpy()
    x0, y0, x1, y1 = box
    grid = np.zeros((height, width), dtype=bool)
    grid[int(math.floor(y0 * height)):int(math.ceil(y1 * height)), int(math.floor(x0 * width)):int(math.ceil(x1 * width))] = True
    return grid.reshape(-1)


def _protections(value, segment_ids):
    from editing_runtime import exact_keys, require, number
    require(isinstance(value, dict) and len(value) <= MAX_PROTECTIONS, 'COLOR_CHECK_PROTECTIONS_INVALID')
    result = {}
    for pid, spec in value.items():
        require(isinstance(pid, str) and pid.strip() and isinstance(spec, dict), 'COLOR_CHECK_PROTECTION_ID_INVALID')
        kind = spec.get('kind')
        common = ['kind', 'segments', 'max_median_delta_e2000', 'action']
        if kind == 'hue-range':
            # An optional box limits the hue selection to a declared area (for example a face, not an orange suit).
            exact_keys(spec, common + ['hue_degrees', 'min_chroma', 'box'], common + ['hue_degrees', 'min_chroma'])
            hue = spec['hue_degrees']
            require(isinstance(hue, list) and len(hue) == 2, 'COLOR_CHECK_HUE_RANGE_INVALID: ' + pid)
            h0, h1 = (number(h, 'hue_degrees', 0) for h in hue)
            require(h0 < 360 and h1 < 360 and h0 != h1, 'COLOR_CHECK_HUE_RANGE_INVALID: ' + pid)
            chroma = number(spec['min_chroma'], 'min_chroma', 0)
            detail = {'hue_degrees': [h0, h1], 'min_chroma': chroma}
            if 'box' in spec:
                detail['box'] = _box(spec['box'], pid)
        elif kind == 'region':
            exact_keys(spec, common + ['box'], common + ['box'])
            detail = {'box': _box(spec['box'], pid)}
        else:
            require(False, 'COLOR_CHECK_PROTECTION_KIND_UNSUPPORTED: ' + pid)
        segments = spec['segments']
        require(isinstance(segments, list) and segments and len(set(segments)) == len(segments)
                and all(s in segment_ids for s in segments), 'COLOR_CHECK_PROTECTION_SEGMENTS_INVALID: ' + pid)
        threshold = number(spec['max_median_delta_e2000'], 'max_median_delta_e2000', 0)
        require(threshold > 0, 'COLOR_CHECK_THRESHOLD_INVALID: ' + pid)
        require(spec['action'] in ('fail', 'flag'), 'COLOR_CHECK_ACTION_INVALID: ' + pid)
        result[pid] = {'kind': kind, 'segments': list(segments), 'max_median_delta_e2000': threshold,
                       'action': spec['action'], **detail}
    return result


def _limits(value):
    from editing_runtime import exact_keys, require, number
    require(isinstance(value, dict), 'COLOR_CHECK_LIMITS_INVALID')
    exact_keys(value, list(LIMIT_KEYS))
    return {k: number(v, k, 0) for k, v in value.items()}


def _sample_frames(segment, count):
    a, b = segment['start_frame'], segment['end_frame']
    length = b - a
    picks = sorted({a + (2 * k + 1) * length // (2 * count) for k in range(count)})
    pairs = [(f, f + 1) for f in picks if f + 1 < b]
    return picks, pairs


def _luma_frames(path, indices, width, height, tools):
    """Decode exact frame numbers to limited-range 8-bit Y codes without range conversion."""
    import subprocess
    from editing_runtime import require
    picks = '+'.join('eq(n,%d)' % i for i in indices)
    vf = f"select='{picks}',scale={width}:{height}:flags=neighbor:in_range=tv:out_range=tv,format=gray"
    raw = subprocess.run([tools.binary('ffmpeg'), '-v', 'error', '-i', str(path), '-vf', vf, '-fps_mode', 'passthrough',
                          '-f', 'rawvideo', '-pix_fmt', 'gray', '-'], capture_output=True, check=True, timeout=600).stdout
    size = width * height
    require(len(raw) == size * len(indices), 'COLOR_CHECK_DECODE_INCOMPLETE')
    return [raw[k * size:(k + 1) * size] for k in range(len(indices))]


def _video(asset, input_color, tools):
    from editing_runtime import require
    from color_profile_ops import _validate_stream
    from color_ops import frame_clock
    media = tools.probe(asset['path'])
    videos = [s for s in media['streams'] if s.get('codec_type') == 'video']
    require(videos, 'VIDEO_STREAM_REQUIRED')
    stream = _validate_stream(videos[0], input_color)
    return {'width': int(videos[0]['width']), 'height': int(videos[0]['height']),
            'frames': len(frame_clock(asset['path'], tools)), **stream}


def _hue_mask(lab, h0, h1, min_chroma):
    np = _numpy()
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360
    inside = (hue >= h0) & (hue <= h1) if h0 < h1 else (hue >= h0) | (hue <= h1)
    return inside & (chroma >= min_chroma)


def check(request, directory, tools):
    from editing_runtime import exact_keys, require, source, write_json
    fields = ['operation', 'reference', 'candidate', 'input_color', 'segments', 'samples_per_segment',
              'protections', 'limits']
    exact_keys(request, fields, fields[:6])
    np = _numpy()
    reference, candidate = source(request['reference']), source(request['candidate'])
    ref_video = _video(reference, request['input_color'], tools)
    cand_video = _video(candidate, request['input_color'], tools)
    for key in ('width', 'height', 'frames'):
        require(ref_video[key] == cand_video[key], 'COLOR_CHECK_VIDEOS_NOT_ALIGNED: ' + key)
    segments = _segments(request['segments'], ref_video['frames'])
    count = request['samples_per_segment']
    require(type(count) is int and 1 <= count <= MAX_SAMPLES_PER_SEGMENT, 'COLOR_CHECK_SAMPLES_INVALID')
    protections = _protections(request.get('protections', {}), {s['id'] for s in segments})
    limits = _limits(request['limits']) if 'limits' in request else {}
    plan = {s['id']: _sample_frames(s, count) for s in segments}
    indices = sorted({f for picks, pairs in plan.values() for f in picks + [b for _, b in pairs]})
    require(len(indices) <= MAX_FRAMES, 'COLOR_CHECK_FRAME_LIMIT: %d frames, max %d' % (len(indices), MAX_FRAMES))
    from color_ops import _rgb_frames
    width = min(ANALYSIS_WIDTH, ref_video['width'])
    height = max(2, round(width * ref_video['height'] / ref_video['width'] / 2) * 2)
    rng = 'tv' if request['input_color']['range'] == 'limited' else 'pc'
    position = {f: k for k, f in enumerate(indices)}
    decoded = {}
    for name, asset in (('reference', reference), ('candidate', candidate)):
        frames = _rgb_frames(asset['path'], indices, width, height, rng, tools)
        decoded[name] = [np.frombuffer(f, dtype=np.uint8).reshape(-1, 3) for f in frames]
    luma = None
    if rng == 'tv':
        luma = [np.frombuffer(f, dtype=np.uint8) for f in _luma_frames(candidate['path'], indices, width, height, tools)]
    default_space = request['input_color']['space']
    labs = {}

    def lab(name, frame, segment):
        key = (name, frame)
        if key not in labs:
            transfer = TRANSFERS[segment['space'] or default_space]
            labs[key] = lab_from_rgb01(decoded[name][position[frame]] / 255.0, transfer)[0]
        return labs[key]

    rows, means = [], {}
    gate_failures, gate_flags = [], []
    for segment in segments:
        picks, pairs = plan[segment['id']]
        row = {'id': segment['id'], 'frames': [segment['start_frame'], segment['end_frame']],
               'space': segment['space'] or default_space, 'sampled_frames': picks}
        steps = {}
        for name in ('reference', 'candidate'):
            pixels = np.concatenate([decoded[name][position[f]] for f in picks])
            row[name] = {'highlight_clipped': _r(np.mean(pixels.max(axis=1) >= HIGHLIGHT_CODE), 6),
                         'shadow_crushed': _r(np.mean(pixels.max(axis=1) <= SHADOW_CODE), 6)}
            mean_lab = np.mean([lab(name, f, segment).mean(axis=0) for f in picks], axis=0)
            means.setdefault(name, []).append(mean_lab)
            row[name]['lab_mean'] = [_r(v) for v in mean_lab]
            steps[name] = [abs(lab(name, b, segment)[:, 0].mean() - lab(name, a, segment)[:, 0].mean()) for a, b in pairs]
            row[name]['flicker_max_delta_l'] = _r(max(steps[name])) if pairs else None
        row['clip_increase'] = {k: _r(row['candidate'][k] - row['reference'][k], 6) for k in ('highlight_clipped', 'shadow_crushed')}
        if pairs:
            # Pair by pair: a large natural change in one pair must not hide flicker the grade adds in another.
            row['flicker_increase'] = _r(max(c - r for r, c in zip(steps['reference'], steps['candidate'])))
        if luma is not None:
            y = np.concatenate([luma[position[f]] for f in picks])
            row['candidate']['out_of_range_fraction'] = _r(np.mean((y < LEGAL_Y[0]) | (y > LEGAL_Y[1])), 6)
        rows.append(row)
        if 'max_clip_increase' in limits and max(row['clip_increase'].values()) > limits['max_clip_increase']:
            gate_failures.append('clip increase in segment %s' % segment['id'])
        if 'max_flicker_increase' in limits and pairs and row['flicker_increase'] > limits['max_flicker_increase']:
            gate_failures.append('flicker increase in segment %s' % segment['id'])
        if ('max_out_of_range_fraction' in limits and luma is not None
                and row['candidate']['out_of_range_fraction'] > limits['max_out_of_range_fraction']):
            gate_failures.append('out-of-range luma in segment %s' % segment['id'])
    drift = []
    for i in range(len(segments) - 1):
        pair = {}
        for name in ('reference', 'candidate'):
            pair[name] = _r(ciede2000(np.array([means[name][i]]), np.array([means[name][i + 1]]))[0])
        entry = {'between': [segments[i]['id'], segments[i + 1]['id']], 'reference_delta_e2000': pair['reference'],
                 'candidate_delta_e2000': pair['candidate'], 'increase': _r(pair['candidate'] - pair['reference'])}
        drift.append(entry)
        if 'max_drift_increase' in limits and entry['increase'] > limits['max_drift_increase']:
            gate_failures.append('drift increase between %s and %s' % tuple(entry['between']))
    by_id = {s['id']: s for s in segments}
    protection_rows = {}
    for pid, spec in protections.items():
        deltas = []
        for sid in spec['segments']:
            segment = by_id[sid]
            for f in plan[sid][0]:
                ref_lab, cand_lab = lab('reference', f, segment), lab('candidate', f, segment)
                mask = _box_mask(spec['box'], width, height) if 'box' in spec else np.ones(len(ref_lab), dtype=bool)
                if spec['kind'] == 'hue-range':
                    mask &= _hue_mask(ref_lab, spec['hue_degrees'][0], spec['hue_degrees'][1], spec['min_chroma'])
                if mask.any():
                    deltas.append(ciede2000(ref_lab[mask], cand_lab[mask]))
        values = np.concatenate(deltas) if deltas else np.zeros(0)
        row = {**spec, 'protected_pixels': int(values.size)}
        if values.size < MIN_PROTECTED_PIXELS:
            row['status'] = 'UNMEASURED'
        else:
            row.update(median_delta_e2000=_r(np.median(values)), p95_delta_e2000=_r(np.percentile(values, 95)))
            row['status'] = 'VIOLATED' if row['median_delta_e2000'] > spec['max_median_delta_e2000'] else 'KEPT'
        if row['status'] != 'KEPT':
            (gate_failures if spec['action'] == 'fail' else gate_flags).append('protection %s %s' % (pid, row['status'].lower()))
        protection_rows[pid] = row
    source(request['reference'])
    source(request['candidate'])  # bytes must still match after decoding
    gate = 'FAILED' if gate_failures else 'FLAGGED' if gate_flags else 'PASSED'
    result = {'schema': SCHEMA, 'reference': reference, 'candidate': candidate, 'input_color': request['input_color'],
              'video': {k: ref_video[k] for k in ('width', 'height', 'frames')},
              'sampling': {'samples_per_segment': count, 'decoded_frames': len(indices), 'analysis_size': [width, height],
                           'downscale': 'swscale point sampling (no averaging)',
                           'flicker_pairs': 'each sampled frame with its next frame inside the segment; '
                                            'increase is the largest per-pair change in |mean L* step|',
                           'coverage': 'sampled frames only; unsampled frames are not observed'},
              'thresholds': {'highlight_channel_code': HIGHLIGHT_CODE, 'shadow_code': SHADOW_CODE,
                             'legal_luma': list(LEGAL_Y), 'min_protected_pixels': MIN_PROTECTED_PIXELS},
              'segments': rows, 'drift': drift, 'protections': protection_rows, 'limits': limits,
              'gate': gate, 'failures': gate_failures, 'flags': gate_flags,
              'hue_basis': 'CIELAB hue angle h_ab of reference pixels under each segment space',
              'aesthetic_judgement': 'NOT_PROVIDED', 'skin_detection': 'NOT_PERFORMED',
              'limits_of_evidence': ['Only sampled frames are measured; a passing gate does not cover unsampled frames.',
                                     'Protections compare the same pixel before and after grading; they keep a colour, '
                                     'they do not move it toward any target.',
                                     'Hue-range protections select reference pixels by hue and chroma only; '
                                     'they are not skin, face or object detection.']}
    write_json(directory / 'color-consistency.json', result)
    return result
