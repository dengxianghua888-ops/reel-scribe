"""Measured color statistics of explicitly sampled SDR frames; no aesthetic judgement.

Every number is an observation of decoded, downscaled sample frames under the
recorded interpretation. Nothing here ranks looks, detects skin or faces,
chooses a style, or certifies that unsampled frames share these statistics.
"""
import hashlib
import math

SCHEMA = 'color-profile/1'
MAX_SAMPLES = 600
MAX_SIDE = 512
MIN_SIDE = 8
MAX_REGIONS = 16
SKIN_LINE_DEGREES = 123.0
HUE_BINS = 12
CHROMATIC_MIN = 8.0
NEUTRAL_CHROMA_MAX = 10.0
NEUTRAL_L_RANGE = (20.0, 90.0)
HIGHLIGHT_CODE = 254
SHADOW_CODE = 1
PALETTE_POINTS = 20000
PALETTE_ITERATIONS = 25
SDR_PIXEL_FORMATS = {'yuv420p', 'yuv422p', 'yuv444p', 'yuvj420p', 'yuvj422p', 'yuvj444p',
                     'yuv420p10le', 'yuv422p10le', 'yuv444p10le'}
HDR_TRANSFERS = {'arib-std-b67', 'smpte2084'}
WIDE_PRIMARIES = {'bt2020', 'smpte431', 'smpte432'}
UNKNOWN = {None, 'unknown', 'unspecified'}
# Linear BT.709/sRGB primaries to CIE XYZ (D65); white is the matrix row sum.
RGB_TO_XYZ = ((0.4123908, 0.3575843, 0.1804808),
              (0.2126390, 0.7151687, 0.0721923),
              (0.0193308, 0.1191948, 0.9505322))
LUMA_709 = (0.2126, 0.7152, 0.0722)
INTERPRETATION = ("BT.709 Y'CbCr decoded by FFmpeg swscale (area downscale) to full-range 8-bit R'G'B'; "
                  "BT.1886 display EOTF with gamma 2.4 (Lw=1, Lb=0) to linear light; BT.709 primaries to CIE XYZ D65; CIELAB")


def _numpy():
    from editing_runtime import ContractError
    try:
        import numpy as np
    except ImportError as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE: numpy; run with the declared analysis environment') from exc
    return np


def _r(value, digits=6):
    return None if value is None else round(float(value), digits)


def lab_from_rgb8(rgb):
    """rgb: (N,3) uint8 array of display-referred BT.709 code values."""
    np = _numpy()
    v = rgb.astype(np.float64) / 255.0
    linear = v ** 2.4
    xyz = linear @ np.array(RGB_TO_XYZ).T
    white = np.array(RGB_TO_XYZ).sum(axis=1)
    t = xyz / white
    delta = 6.0 / 29.0
    f = np.where(t > delta ** 3, np.cbrt(t), t / (3 * delta ** 2) + 4.0 / 29.0)
    lab = np.stack([116.0 * f[:, 1] - 16.0, 500.0 * (f[:, 0] - f[:, 1]), 200.0 * (f[:, 1] - f[:, 2])], axis=1)
    return lab, linear


def rgb8_hex_from_lab(lab):
    np = _numpy()
    delta = 6.0 / 29.0
    fy = (lab[0] + 16.0) / 116.0
    fx, fz = fy + lab[1] / 500.0, fy - lab[2] / 200.0
    f = np.array([fx, fy, fz])
    t = np.where(f > delta, f ** 3, 3 * delta ** 2 * (f - 4.0 / 29.0))
    xyz = t * np.array(RGB_TO_XYZ).sum(axis=1)
    linear = np.linalg.solve(np.array(RGB_TO_XYZ), xyz)
    code = np.round(np.clip(linear, 0.0, 1.0) ** (1 / 2.4) * 255).astype(int)
    return '#%02X%02X%02X' % tuple(int(x) for x in code)


def frame_stats(rgb, *, full=True):
    np = _numpy()
    lab, linear = lab_from_rgb8(rgb)
    v = rgb.astype(np.float64) / 255.0
    luma = v @ np.array(LUMA_709)
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    p = np.percentile(luma, [1, 5, 50, 95, 99])
    rgbf = rgb.astype(np.float64)
    rg = rgbf[:, 0] - rgbf[:, 1]
    yb = 0.5 * (rgbf[:, 0] + rgbf[:, 1]) - rgbf[:, 2]
    colorfulness = math.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * math.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    stats = {
        'pixels': int(len(rgb)),
        'luma': {'mean': _r(luma.mean()), 'p01': _r(p[0]), 'p05': _r(p[1]), 'p50': _r(p[2]),
                 'p95': _r(p[3]), 'p99': _r(p[4])},
        'clipping': {'highlight_channel_ratio': _r((rgb >= HIGHLIGHT_CODE).any(axis=1).mean()),
                     'shadow_crush_ratio': _r((rgb <= SHADOW_CODE).all(axis=1).mean())},
        'lab_mean': {'L': _r(lab[:, 0].mean()), 'a': _r(lab[:, 1].mean()), 'b': _r(lab[:, 2].mean())},
        'chroma': {'mean': _r(chroma.mean()), 'p50': _r(np.percentile(chroma, 50)), 'p95': _r(np.percentile(chroma, 95))},
        'colorfulness_hasler_susstrunk': _r(colorfulness),
    }
    if not full:
        return stats, lab
    neutral = (chroma < NEUTRAL_CHROMA_MAX) & (lab[:, 0] >= NEUTRAL_L_RANGE[0]) & (lab[:, 0] <= NEUTRAL_L_RANGE[1])
    means = linear.mean(axis=0)
    hue = np.degrees(np.arctan2(lab[:, 2], lab[:, 1])) % 360.0
    chromatic = chroma >= CHROMATIC_MIN
    bins = np.bincount((hue[chromatic] // (360.0 / HUE_BINS)).astype(int) % HUE_BINS, minlength=HUE_BINS)
    total = int(chromatic.sum())
    stats.update({
        'neutral_estimate': {'pixel_share': _r(neutral.mean()),
                             'a_mean': _r(lab[neutral, 1].mean()) if neutral.any() else None,
                             'b_mean': _r(lab[neutral, 2].mean()) if neutral.any() else None,
                             'reading': 'positive b* = yellow/warm, negative = blue/cool; positive a* = magenta, negative = green'},
        'gray_world_linear_ratio': {'r_over_g': _r(means[0] / means[1]) if means[1] > 0 else None,
                                    'b_over_g': _r(means[2] / means[1]) if means[1] > 0 else None},
        'hue_histogram': {'bin_degrees': 360 // HUE_BINS, 'chromatic_min_chroma': CHROMATIC_MIN,
                          'chromatic_share': _r(total / len(rgb)),
                          'shares': [_r(c / total) if total else 0.0 for c in bins.tolist()]},
    })
    return stats, lab


def palette(lab, k):
    """Deterministic maximin-initialized k-means on a fixed stride subsample."""
    np = _numpy()
    points = lab if len(lab) <= PALETTE_POINTS else lab[np.linspace(0, len(lab) - 1, PALETTE_POINTS).round().astype(int)]
    centers = [points[np.argmin(((points - points.mean(axis=0)) ** 2).sum(axis=1))]]
    while len(centers) < k:
        distance = np.min([((points - c) ** 2).sum(axis=1) for c in centers], axis=0)
        centers.append(points[int(np.argmax(distance))])
    centers = np.array(centers)
    assignment = None
    for _ in range(PALETTE_ITERATIONS):
        new = np.argmin(((points[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2), axis=1)
        if assignment is not None and np.array_equal(new, assignment):
            break
        assignment = new
        for index in range(k):
            members = points[assignment == index]
            if len(members):
                centers[index] = members.mean(axis=0)
    shares = np.bincount(assignment, minlength=k) / len(points)
    rows = [{'lab': {'L': _r(c[0], 3), 'a': _r(c[1], 3), 'b': _r(c[2], 3)}, 'share': _r(s),
             'display_hex': rgb8_hex_from_lab(c)} for c, s in zip(centers, shares) if s > 0]
    rows.sort(key=lambda row: -row['share'])
    return {'method': 'k-means in CIELAB; maximin initialization; fixed-stride subsample',
            'requested_colors': k, 'found_colors': len(rows), 'points': int(len(points)),
            'max_iterations': PALETTE_ITERATIONS, 'colors': rows}


def region_stats(rgb, lab):
    np = _numpy()
    v = rgb.astype(np.float64).mean(axis=0) / 255.0
    y = float(v @ np.array(LUMA_709))
    cb, cr = (v[2] - y) / 1.8556, (v[0] - y) / 1.5748
    angle = math.degrees(math.atan2(cr, cb)) % 360.0
    mean = lab.mean(axis=0)
    return {'pixels': int(len(rgb)), 'lab_mean': {'L': _r(mean[0]), 'a': _r(mean[1]), 'b': _r(mean[2])},
            'chroma_of_mean': _r(math.hypot(mean[1], mean[2])),
            'hue_of_mean_degrees': _r(math.degrees(math.atan2(mean[2], mean[1])) % 360.0),
            'vectorscope': {'cb': _r(cb), 'cr': _r(cr), 'angle_degrees': _r(angle),
                            'skin_line_offset_degrees': _r(((angle - SKIN_LINE_DEGREES + 180.0) % 360.0) - 180.0)}}


def _sample_times(spec, start, end, limit):
    from editing_runtime import exact_keys, require, number
    exact_keys(spec, ['mode', 'interval_seconds', 'times'], ['mode'])
    require(spec['mode'] in ('interval', 'times'), 'COLOR_PROFILE_SAMPLE_MODE_UNSUPPORTED')
    if spec['mode'] == 'interval':
        require('times' not in spec and 'interval_seconds' in spec, 'COLOR_PROFILE_SAMPLE_FIELDS_INVALID')
        step = number(spec['interval_seconds'], 'interval_seconds', 0)
        require(step >= 0.01, 'COLOR_PROFILE_INTERVAL_TOO_SMALL')
        count = math.ceil((end - start) / step - 1e-9)
        require(count <= limit, 'COLOR_PROFILE_SAMPLE_LIMIT: %d samples requested, max_samples=%d' % (count, limit))
        times = [start + k * step for k in range(count)]
    else:
        require('interval_seconds' not in spec and isinstance(spec.get('times'), list) and spec['times'],
                'COLOR_PROFILE_SAMPLE_FIELDS_INVALID')
        times = [number(t, 'time', 0) for t in spec['times']]
        require(len(times) <= limit, 'COLOR_PROFILE_SAMPLE_LIMIT: %d samples requested, max_samples=%d' % (len(times), limit))
        require(all(a < b for a, b in zip(times, times[1:])), 'COLOR_PROFILE_TIMES_NOT_INCREASING')
    require(times and all(start <= t < end for t in times), 'COLOR_PROFILE_TIME_OUTSIDE_RANGE')
    return times


def _validate_stream(video, input_color):
    from editing_runtime import exact_keys, require
    exact_keys(input_color, ['space', 'range', 'basis'], ['space', 'range', 'basis'])
    require(input_color['space'] == 'bt709-sdr', 'COLOR_PROFILE_SPACE_UNSUPPORTED')
    require(input_color['range'] in ('limited', 'full'), 'COLOR_PROFILE_RANGE_REQUIRED')
    require(input_color['basis'] in ('verified-metadata', 'caller-declared'), 'COLOR_PROFILE_BASIS_REQUIRED')
    transfer, primaries = video.get('color_transfer'), video.get('color_primaries')
    require(transfer not in HDR_TRANSFERS, 'COLOR_PROFILE_HDR_TRANSFER_UNSUPPORTED: %s; convert to declared SDR BT.709 first' % transfer)
    require(primaries not in WIDE_PRIMARIES, 'COLOR_PROFILE_WIDE_GAMUT_UNSUPPORTED: %s' % primaries)
    pix_fmt = video.get('pix_fmt')
    require(pix_fmt in SDR_PIXEL_FORMATS, 'COLOR_PROFILE_PIXEL_FORMAT_UNSUPPORTED: %s' % pix_fmt)
    if pix_fmt.startswith('yuvj'):
        require(input_color['range'] == 'full', 'COLOR_PROFILE_METADATA_CONFLICT: full-range pixel format')
    expected = {'color_transfer': 'bt709', 'color_primaries': 'bt709', 'color_space': 'bt709',
                'color_range': 'tv' if input_color['range'] == 'limited' else 'pc'}
    observed = {key: video.get(key) for key in expected}
    for key, value in expected.items():
        require(observed[key] in UNKNOWN or observed[key] == value, 'COLOR_PROFILE_METADATA_CONFLICT: ' + key)
        if input_color['basis'] == 'verified-metadata':
            require(observed[key] == value, 'COLOR_PROFILE_METADATA_REQUIRED: ' + key)
    return {'pix_fmt': pix_fmt, 'observed_tags': observed,
            'unobserved_tags': sorted(k for k, v in observed.items() if v in UNKNOWN)}


def _regions(value, width, height):
    from editing_runtime import require, number
    require(isinstance(value, dict) and 0 < len(value) <= MAX_REGIONS, 'COLOR_PROFILE_REGIONS_INVALID')
    result = {}
    for rid, box in value.items():
        require(isinstance(rid, str) and rid.strip(), 'COLOR_PROFILE_REGION_ID_INVALID')
        require(isinstance(box, list) and len(box) == 4, 'COLOR_PROFILE_REGION_BOX_INVALID: ' + rid)
        x0, y0, x1, y1 = (number(x, 'region', 0) for x in box)
        require(x0 < x1 <= 1 and y0 < y1 <= 1, 'COLOR_PROFILE_REGION_BOX_INVALID: ' + rid)
        c0, c1 = int(math.floor(x0 * width)), int(math.ceil(x1 * width))
        r0, r1 = int(math.floor(y0 * height)), int(math.ceil(y1 * height))
        require(c1 > c0 and r1 > r0, 'COLOR_PROFILE_REGION_EMPTY: ' + rid)
        result[rid] = {'box': [x0, y0, x1, y1], 'pixels': [c0, r0, c1, r1]}
    return result


def scan(request, directory, tools):
    from editing_runtime import exact_keys, require, source, span, write_json
    fields = ['operation', 'source', 'start', 'end', 'samples', 'analysis_size', 'input_color',
              'palette_colors', 'max_samples', 'regions']
    exact_keys(request, fields, fields[:-1])
    np = _numpy()
    asset = source(request['source'])
    media = tools.probe(asset['path'])
    videos = [s for s in media['streams'] if s.get('codec_type') == 'video']
    require(videos, 'VIDEO_STREAM_REQUIRED')
    stream = _validate_stream(videos[0], request['input_color'])
    start, end = span(request['start'], request['end'], media['duration'])
    limit = request['max_samples']
    require(type(limit) is int and 1 <= limit <= MAX_SAMPLES, 'COLOR_PROFILE_MAX_SAMPLES_INVALID')
    times = _sample_times(request['samples'], start, end, limit)
    size = request['analysis_size']
    require(isinstance(size, list) and len(size) == 2 and all(type(x) is int and MIN_SIDE <= x <= MAX_SIDE for x in size),
            'COLOR_PROFILE_ANALYSIS_SIZE_INVALID')
    width, height = size
    k = request['palette_colors']
    require(type(k) is int and 1 <= k <= 8, 'COLOR_PROFILE_PALETTE_COLORS_INVALID')
    regions = _regions(request['regions'], width, height) if 'regions' in request else {}
    in_range = 'tv' if request['input_color']['range'] == 'limited' else 'pc'
    vf = f'scale={width}:{height}:flags=area:in_color_matrix=bt709:in_range={in_range}:out_range=pc,format=rgb24'
    folder = directory / 'samples'
    folder.mkdir()
    samples, pooled, region_pixels, means = [], [], {rid: [] for rid in regions}, []
    for index, t in enumerate(times):
        raw = folder / f'{index:04d}.rgb'
        tools.ff(['-ss', f'{t:.6f}', '-i', asset['path'], '-map', '0:v:0', '-frames:v', '1', '-vf', vf,
                  '-f', 'rawvideo', '-pix_fmt', 'rgb24', str(raw)])
        require(raw.is_file(), 'COLOR_PROFILE_FRAME_NOT_DECODED: %.6f' % t)
        payload = raw.read_bytes()
        raw.unlink()
        require(len(payload) == width * height * 3, 'COLOR_PROFILE_FRAME_SIZE_INVALID: %.6f' % t)
        grid = np.frombuffer(payload, dtype=np.uint8).reshape(height, width, 3)
        flat = grid.reshape(-1, 3)
        stats, lab = frame_stats(flat, full=False)
        samples.append({'requested_time': _r(t), 'rgb24_sha256': hashlib.sha256(payload).hexdigest(), **stats})
        pooled.append(flat)
        means.append([stats['lab_mean'][key] for key in 'Lab'])
        for rid, spec in regions.items():
            c0, r0, c1, r1 = spec['pixels']
            region_pixels[rid].append(grid[r0:r1, c0:c1].reshape(-1, 3))
    folder.rmdir()
    allpix = np.concatenate(pooled)
    aggregate, lab = frame_stats(allpix, full=True)
    temporal = {'basis': 'per-sample mean CIELAB; sample-level drift, not per-frame flicker', 'samples': len(means)}
    if len(means) >= 2:
        array = np.array(means)
        steps = np.sqrt(((array[1:] - array[:-1]) ** 2).sum(axis=1))
        temporal.update({'max_consecutive_delta_e76': _r(steps.max()), 'mean_consecutive_delta_e76': _r(steps.mean()),
                         'std': {'L': _r(array[:, 0].std()), 'a': _r(array[:, 1].std()), 'b': _r(array[:, 2].std())}})
    region_rows = {}
    for rid, chunks in region_pixels.items():
        pixels = np.concatenate(chunks)
        region_lab, _ = lab_from_rgb8(pixels)
        region_rows[rid] = {'box': regions[rid]['box'], 'declared_by': 'caller', **region_stats(pixels, region_lab)}
    source(request['source'])  # Bytes must still match after all decoding.
    result = {'schema': SCHEMA, 'source': asset, 'stream': {'index': videos[0].get('index'), 'selector': 'v:0', **stream},
              'input_color': request['input_color'], 'interpretation': INTERPRETATION,
              'sampling': {'mode': request['samples']['mode'], 'count': len(times), 'requested_times': [_r(t) for t in times],
                           'analysis_size': [width, height], 'downscale': 'swscale area',
                           'time_precision': 'decoder-selected frame at or after requested timestamp',
                           'coverage': 'sampled frames only; unsampled frames are not observed',
                           'temporary_raw_frames_removed': True},
              'thresholds': {'highlight_channel_code': HIGHLIGHT_CODE, 'shadow_code': SHADOW_CODE,
                             'chromatic_min_chroma': CHROMATIC_MIN, 'neutral_max_chroma': NEUTRAL_CHROMA_MAX,
                             'neutral_l_range': list(NEUTRAL_L_RANGE), 'skin_line_reference_degrees': SKIN_LINE_DEGREES},
              'aggregate': aggregate, 'palette': palette(lab, k), 'temporal': temporal, 'regions': region_rows,
              'samples': samples, 'aesthetic_judgement': 'NOT_PROVIDED', 'skin_detection': 'NOT_PERFORMED',
              'limits': ['Statistics describe sampled, downscaled frames under the recorded interpretation only.',
                         'Display-referred BT.1886 gamma 2.4 is an explicit assumption, not a measured display.',
                         'Skin-line offsets apply only to caller-declared regions; the line is a guide, not a target.',
                         'HDR, log, wide-gamut and non-BT.709 inputs are refused rather than reinterpreted.']}
    write_json(directory / 'color-profile.json', result)
    return result
