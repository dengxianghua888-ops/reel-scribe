"""Measured color statistics of explicitly sampled SDR frames; no aesthetic judgement.

Every number is an observation of decoded, downscaled sample frames under the
recorded interpretation. Nothing here ranks looks, detects skin or faces,
chooses a style, or certifies that unsampled frames share these statistics.
"""
import hashlib
import math

from color_numerics import LUMA_709, lab_from_rgb01, rgb01_from_lab, numpy as _numpy

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
PERCENTILES = (1, 5, 50, 95, 99)
# Y' * 255 * 10000 is an exact integer for 8-bit codes, so pooled luma
# percentiles come from an exact histogram rather than from retained pixels.
LUMA_KEY = (2126, 7152, 722)
LUMA_KEY_MAX = 255 * 10000
CHROMA_BIN = 1.0 / 1024
CHROMA_BINS = 192 * 1024  # BT.709 gamut chroma stays below ~134
# Declared input space -> (display transfer, expected transfer tag, recorded interpretation).
SPACES = {
    'bt709-sdr': ('bt1886', 'bt709',
                  "BT.709 Y'CbCr decoded by FFmpeg swscale (area downscale) to full-range 8-bit R'G'B'; "
                  "BT.1886 display EOTF with gamma 2.4 (Lw=1, Lb=0) to linear light; BT.709 primaries to CIE XYZ D65; CIELAB"),
    'srgb-sdr': ('srgb', 'iec61966-2-1',
                 "BT.709-matrix Y'CbCr decoded by FFmpeg swscale (area downscale) to full-range 8-bit R'G'B'; "
                 "IEC 61966-2-1 sRGB piecewise EOTF to linear light; BT.709/sRGB primaries to CIE XYZ D65; CIELAB"),
}


def _r(value, digits=6):
    return None if value is None else round(float(value), digits)


def lab_from_rgb8(rgb, transfer='bt1886'):
    """rgb: (N,3) uint8 array of display-referred code values under the declared transfer."""
    np = _numpy()
    return lab_from_rgb01(rgb.astype(np.float64) / 255.0, transfer)


def rgb8_hex_from_lab(lab, transfer='bt1886'):
    np = _numpy()
    code = np.round(rgb01_from_lab(np.asarray(lab, dtype=float)[None, :], transfer)[0] * 255).astype(int)
    return '#%02X%02X%02X' % tuple(int(x) for x in code)


def frame_stats(rgb, lab, chroma):
    """Statistics of one sample's pixels (bounded by analysis_size)."""
    np = _numpy()
    v = rgb.astype(np.float64) / 255.0
    luma = v @ np.array(LUMA_709)
    p = np.percentile(luma, PERCENTILES)
    rgbf = rgb.astype(np.float64)
    rg = rgbf[:, 0] - rgbf[:, 1]
    yb = 0.5 * (rgbf[:, 0] + rgbf[:, 1]) - rgbf[:, 2]
    colorfulness = math.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * math.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    return {
        'pixels': int(len(rgb)),
        'luma': {'mean': _r(luma.mean()), **{'p%02d' % q: _r(x) for q, x in zip(PERCENTILES, p)}},
        'clipping': {'highlight_channel_ratio': _r((rgb >= HIGHLIGHT_CODE).any(axis=1).mean()),
                     'shadow_crush_ratio': _r((rgb <= SHADOW_CODE).all(axis=1).mean())},
        'lab_mean': {'L': _r(lab[:, 0].mean()), 'a': _r(lab[:, 1].mean()), 'b': _r(lab[:, 2].mean())},
        'chroma': {'mean': _r(chroma.mean()), 'p50': _r(np.percentile(chroma, 50)), 'p95': _r(np.percentile(chroma, 95))},
        'colorfulness_hasler_susstrunk': _r(colorfulness),
    }


def histogram_percentiles(counts, value_of_bin, percentiles):
    """np.percentile(method='linear') over the multiset a histogram describes."""
    np = _numpy()
    cumulative = np.cumsum(counts)
    n = int(cumulative[-1])
    values = []
    for q in percentiles:
        position = q / 100.0 * (n - 1)
        low = math.floor(position)
        a = value_of_bin(int(np.searchsorted(cumulative, low, side='right')))
        b = value_of_bin(int(np.searchsorted(cumulative, min(low + 1, n - 1), side='right')))
        values.append(a + (b - a) * (position - low))
    return values


def _variance(total, squares, n):
    return (n * squares - total * total) / (n * n)  # exact integers until this division


class PooledStats:
    """Pooled statistics over all sampled pixels with memory independent of sample count.

    Sums are exact integers where the quantity is integral; luma percentiles use
    an exact integer-key histogram; chroma percentiles use CHROMA_BIN-wide bins;
    the palette keeps the same fixed-stride subsample of the pooled pixel order.
    """

    def __init__(self, total_pixels):
        np = self.np = _numpy()
        self.n = 0
        self.luma_hist = np.zeros(LUMA_KEY_MAX + 1, dtype=np.int64)
        self.chroma_hist = np.zeros(CHROMA_BINS, dtype=np.int64)
        self.luma_key_sum = self.highlight = self.shadow = 0
        self.rg = [0, 0]
        self.yb2 = [0, 0]  # 2 * yb = R + G - 2B keeps the sums integral
        self.lab_sum, self.linear_sum, self.neutral_ab = np.zeros(3), np.zeros(3), np.zeros(2)
        self.chroma_sum = 0.0
        self.neutral = self.chromatic = 0
        self.hue = np.zeros(HUE_BINS, dtype=np.int64)
        self.palette_index = (None if total_pixels <= PALETTE_POINTS else
                              np.linspace(0, total_pixels - 1, PALETTE_POINTS).round().astype(np.int64))
        self.palette_parts = []

    def add(self, rgb, lab, linear, chroma):
        from editing_runtime import require
        np = self.np
        r, g, b = (rgb[:, i].astype(np.int64) for i in range(3))
        key = LUMA_KEY[0] * r + LUMA_KEY[1] * g + LUMA_KEY[2] * b
        self.luma_hist += np.bincount(key, minlength=LUMA_KEY_MAX + 1)
        self.luma_key_sum += int(key.sum())
        bins = np.floor(chroma / CHROMA_BIN).astype(np.int64)
        require(int(bins.max()) < CHROMA_BINS, 'COLOR_PROFILE_CHROMA_OUT_OF_RANGE')
        self.chroma_hist += np.bincount(bins, minlength=CHROMA_BINS)
        self.chroma_sum += float(chroma.sum())
        self.highlight += int((rgb >= HIGHLIGHT_CODE).any(axis=1).sum())
        self.shadow += int((rgb <= SHADOW_CODE).all(axis=1).sum())
        for acc, term in ((self.rg, r - g), (self.yb2, r + g - 2 * b)):
            acc[0] += int(term.sum())
            acc[1] += int((term * term).sum())
        self.lab_sum += lab.sum(axis=0)
        self.linear_sum += linear.sum(axis=0)
        neutral = (chroma < NEUTRAL_CHROMA_MAX) & (lab[:, 0] >= NEUTRAL_L_RANGE[0]) & (lab[:, 0] <= NEUTRAL_L_RANGE[1])
        self.neutral += int(neutral.sum())
        self.neutral_ab += lab[neutral, 1:].sum(axis=0)
        chromatic = chroma >= CHROMATIC_MIN
        hue = np.degrees(np.arctan2(lab[chromatic, 2], lab[chromatic, 1])) % 360.0
        self.hue += np.bincount((hue // (360.0 / HUE_BINS)).astype(int) % HUE_BINS, minlength=HUE_BINS)
        self.chromatic += int(chromatic.sum())
        if self.palette_index is None:
            self.palette_parts.append(lab.copy())
        else:
            local = self.palette_index[(self.palette_index >= self.n) & (self.palette_index < self.n + len(lab))] - self.n
            self.palette_parts.append(lab[local])
        self.n += len(rgb)

    def palette_points(self):
        return self.np.concatenate(self.palette_parts)

    def result(self):
        n = self.n
        luma = histogram_percentiles(self.luma_hist, lambda i: i / LUMA_KEY_MAX, PERCENTILES)
        chroma = histogram_percentiles(self.chroma_hist, lambda i: (i + 0.5) * CHROMA_BIN, (50, 95))
        lab_mean = self.lab_sum / n
        means = self.linear_sum / n
        colorfulness = (math.sqrt(_variance(*self.rg, n) + _variance(*self.yb2, n) / 4)
                        + 0.3 * math.hypot(self.rg[0] / n, self.yb2[0] / (2 * n)))
        return {
            'pixels': n,
            'luma': {'mean': _r(self.luma_key_sum / LUMA_KEY_MAX / n),
                     **{'p%02d' % q: _r(x) for q, x in zip(PERCENTILES, luma)}},
            'clipping': {'highlight_channel_ratio': _r(self.highlight / n), 'shadow_crush_ratio': _r(self.shadow / n)},
            'lab_mean': {'L': _r(lab_mean[0]), 'a': _r(lab_mean[1]), 'b': _r(lab_mean[2])},
            'chroma': {'mean': _r(self.chroma_sum / n), 'p50': _r(chroma[0]), 'p95': _r(chroma[1])},
            'colorfulness_hasler_susstrunk': _r(colorfulness),
            'neutral_estimate': {'pixel_share': _r(self.neutral / n),
                                 'a_mean': _r(self.neutral_ab[0] / self.neutral) if self.neutral else None,
                                 'b_mean': _r(self.neutral_ab[1] / self.neutral) if self.neutral else None,
                                 'reading': 'positive b* = yellow/warm, negative = blue/cool; positive a* = magenta, negative = green'},
            'gray_world_linear_ratio': {'r_over_g': _r(means[0] / means[1]) if means[1] > 0 else None,
                                        'b_over_g': _r(means[2] / means[1]) if means[1] > 0 else None},
            'hue_histogram': {'bin_degrees': 360 // HUE_BINS, 'chromatic_min_chroma': CHROMATIC_MIN,
                              'chromatic_share': _r(self.chromatic / n),
                              'shares': [_r(c / self.chromatic) if self.chromatic else 0.0 for c in self.hue.tolist()]},
            'precision': {'pooling': 'streamed per sample; memory does not grow with samples x pixels',
                          'luma_percentiles': "exact: histogram of the integer key 2126R'+7152G'+722B'",
                          'chroma_percentiles': 'histogram bin centers; bin width %s chroma units' % CHROMA_BIN},
        }


def palette(points, k, transfer='bt1886'):
    """Deterministic maximin-initialized k-means on the pooled fixed-stride subsample."""
    np = _numpy()
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
             'display_hex': rgb8_hex_from_lab(c, transfer)} for c, s in zip(centers, shares) if s > 0]
    rows.sort(key=lambda row: -row['share'])
    return {'method': 'k-means in CIELAB; maximin initialization; fixed-stride subsample',
            'requested_colors': k, 'found_colors': len(rows), 'points': int(len(points)),
            'max_iterations': PALETTE_ITERATIONS, 'colors': rows}


def region_stats(count, rgb_sum, lab_sum):
    """Mean R'G'B' and mean CIELAB of a caller-declared region pooled over samples."""
    np = _numpy()
    v = np.asarray(rgb_sum, dtype=np.float64) / count / 255.0
    y = float(v @ np.array(LUMA_709))
    cb, cr = (v[2] - y) / 1.8556, (v[0] - y) / 1.5748
    angle = math.degrees(math.atan2(cr, cb)) % 360.0
    mean = lab_sum / count
    return {'pixels': int(count), 'lab_mean': {'L': _r(mean[0]), 'a': _r(mean[1]), 'b': _r(mean[2])},
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
    require(input_color['space'] in SPACES, 'COLOR_PROFILE_SPACE_UNSUPPORTED')
    require(input_color['range'] in ('limited', 'full'), 'COLOR_PROFILE_RANGE_REQUIRED')
    require(input_color['basis'] in ('verified-metadata', 'caller-declared'), 'COLOR_PROFILE_BASIS_REQUIRED')
    transfer, primaries = video.get('color_transfer'), video.get('color_primaries')
    require(transfer not in HDR_TRANSFERS, 'COLOR_PROFILE_HDR_TRANSFER_UNSUPPORTED: %s; convert to declared SDR BT.709 first' % transfer)
    require(primaries not in WIDE_PRIMARIES, 'COLOR_PROFILE_WIDE_GAMUT_UNSUPPORTED: %s' % primaries)
    pix_fmt = video.get('pix_fmt')
    require(pix_fmt in SDR_PIXEL_FORMATS, 'COLOR_PROFILE_PIXEL_FORMAT_UNSUPPORTED: %s' % pix_fmt)
    if pix_fmt.startswith('yuvj'):
        require(input_color['range'] == 'full', 'COLOR_PROFILE_METADATA_CONFLICT: full-range pixel format')
    expected = {'color_transfer': SPACES[input_color['space']][1], 'color_primaries': 'bt709', 'color_space': 'bt709',
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
    transfer = SPACES[request['input_color']['space']][0]
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
    samples, means = [], []
    pooled = PooledStats(len(times) * width * height)
    region_sums = {rid: [0, np.zeros(3, dtype=np.int64), np.zeros(3)] for rid in regions}
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
        lab, linear = lab_from_rgb8(flat, transfer)
        chroma = np.hypot(lab[:, 1], lab[:, 2])
        stats = frame_stats(flat, lab, chroma)
        samples.append({'requested_time': _r(t), 'rgb24_sha256': hashlib.sha256(payload).hexdigest(), **stats})
        pooled.add(flat, lab, linear, chroma)
        means.append([stats['lab_mean'][key] for key in 'Lab'])
        lab_grid = lab.reshape(height, width, 3)
        for rid, spec in regions.items():
            c0, r0, c1, r1 = spec['pixels']
            acc = region_sums[rid]
            acc[0] += (r1 - r0) * (c1 - c0)
            acc[1] += grid[r0:r1, c0:c1].reshape(-1, 3).sum(axis=0, dtype=np.int64)
            acc[2] += lab_grid[r0:r1, c0:c1].reshape(-1, 3).sum(axis=0)
    folder.rmdir()
    aggregate = pooled.result()
    temporal = {'basis': 'per-sample mean CIELAB; sample-level drift, not per-frame flicker', 'samples': len(means)}
    if len(means) >= 2:
        array = np.array(means)
        steps = np.sqrt(((array[1:] - array[:-1]) ** 2).sum(axis=1))
        temporal.update({'max_consecutive_delta_e76': _r(steps.max()), 'mean_consecutive_delta_e76': _r(steps.mean()),
                         'std': {'L': _r(array[:, 0].std()), 'a': _r(array[:, 1].std()), 'b': _r(array[:, 2].std())}})
    region_rows = {rid: {'box': regions[rid]['box'], 'declared_by': 'caller', **region_stats(*acc)}
                   for rid, acc in region_sums.items()}
    source(request['source'])  # Bytes must still match after all decoding.
    result = {'schema': SCHEMA, 'source': asset, 'stream': {'index': videos[0].get('index'), 'selector': 'v:0', **stream},
              'input_color': request['input_color'], 'interpretation': SPACES[request['input_color']['space']][2],
              'sampling': {'mode': request['samples']['mode'], 'count': len(times), 'requested_times': [_r(t) for t in times],
                           'analysis_size': [width, height], 'downscale': 'swscale area',
                           'time_precision': 'decoder-selected frame at or after requested timestamp',
                           'coverage': 'sampled frames only; unsampled frames are not observed',
                           'temporary_raw_frames_removed': True},
              'thresholds': {'highlight_channel_code': HIGHLIGHT_CODE, 'shadow_code': SHADOW_CODE,
                             'chromatic_min_chroma': CHROMATIC_MIN, 'neutral_max_chroma': NEUTRAL_CHROMA_MAX,
                             'neutral_l_range': list(NEUTRAL_L_RANGE), 'skin_line_reference_degrees': SKIN_LINE_DEGREES},
              'aggregate': aggregate, 'palette': palette(pooled.palette_points(), k, transfer), 'temporal': temporal, 'regions': region_rows,
              'samples': samples, 'aesthetic_judgement': 'NOT_PROVIDED', 'skin_detection': 'NOT_PERFORMED',
              'limits': ['Statistics describe sampled, downscaled frames under the recorded interpretation only.',
                         'The display transfer (BT.1886 gamma 2.4 or sRGB) is the declared assumption, not a measured display.',
                         'Skin-line offsets apply only to caller-declared regions; the line is a guide, not a target.',
                         'HDR, log, wide-gamut and inputs whose tags contradict the declared space are refused rather than reinterpreted.']}
    write_json(directory / 'color-profile.json', result)
    return result
