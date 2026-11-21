"""Fit editable grade parameters that move target frames toward a reference's color statistics.

Statistical transfer (Reinhard in CIELAB, Pitie's multivariate Gaussian / MKL
map, or per-channel histogram matching) defines an ideal per-pixel result; the
op fits that result to editable parameters (ASC CDL or per-channel curves) that
color-grade-compile accepts. It reports distances before, ideal and after, and
the fit residual. It adopts nothing, chooses no look and never claims the result
looks like the reference: a smaller distribution distance is not a judgement.
Methods are implemented from the published formulas (no GPL color-matcher code).
"""
from color_numerics import LUMA_709, lab_from_rgb01, rgb01_from_lab, ciede2000, numpy as _numpy

SCHEMA = 'color-reference-fit/1'
METHODS = {'reinhard-lab': 'cdl', 'mvgd': 'cdl', 'histogram': 'curves'}
TRANSFERS = {'bt709-sdr': 'bt1886', 'srgb-sdr': 'srgb'}
INTERPRETATIONS = {'bt709-sdr': 'bt709-sdr-display', 'srgb-sdr': 'srgb-sdr-display'}
MAX_FRAMES = 32
ANALYSIS_WIDTH = 256
FIT_PIXELS = 20000
SLICES = 64
SEED = 20261121
CURVE_POINTS = 17
SIGMA_FLOOR = 0.5  # CIELAB units; a flat target channel is not stretched without bound
COV_EPSILON = 1e-6
JS_BINS = {'L': (0.0, 100.0, 50), 'a': (-100.0, 100.0, 50), 'b': (-100.0, 100.0, 50)}
# Widest allowed bounds: color-grade-compile's CDL ranges, the saturation search range, any curve shift.
DEFAULT_BOUNDS = {'slope': (0.0, 4.0), 'offset': (-1.0, 1.0), 'saturation': (0.05, 2.0), 'curve_max_shift': 1.0}
CDL_BOUNDS = ('slope', 'offset', 'saturation')


def _r(value, digits=4):
    return round(float(value), digits)


def _side(spec, name, tools):
    from editing_runtime import exact_keys, require, source
    from color_check_ops import _video
    exact_keys(spec, ['source', 'input_color', 'frames'], ['source', 'input_color', 'frames'])
    asset = source(spec['source'])
    video = _video(asset, spec['input_color'], tools)
    frames = spec['frames']
    require(isinstance(frames, list) and 1 <= len(frames) <= MAX_FRAMES and all(type(f) is int for f in frames)
            and len(set(frames)) == len(frames) and all(0 <= f < video['frames'] for f in frames),
            'COLOR_FIT_FRAMES_INVALID: ' + name)
    return asset, video, sorted(frames)


def _pixels(asset, video, frames, input_color, tools):
    from color_ops import _rgb_frames
    np = _numpy()
    width = min(ANALYSIS_WIDTH, video['width'])
    height = max(2, round(width * video['height'] / video['width'] / 2) * 2)
    rng = 'tv' if input_color['range'] == 'limited' else 'pc'
    raw = _rgb_frames(asset['path'], frames, width, height, rng, tools)
    rgb = np.concatenate([np.frombuffer(f, dtype=np.uint8).reshape(-1, 3) for f in raw]) / 255.0
    return rgb, [width, height]


def _subsample(values, count):
    """Deterministic evenly strided subsample; keeps every pixel when there are fewer."""
    np = _numpy()
    if len(values) <= count:
        return values
    return values[np.linspace(0, len(values) - 1, count).round().astype(int)]


def _sqrtm(matrix):
    np = _numpy()
    values, vectors = np.linalg.eigh(matrix)
    return (vectors * np.sqrt(np.clip(values, 0.0, None))) @ vectors.T


def _ideal(method, target, reference, transfer):
    """Per-pixel statistical transfer of target code values toward the reference (both in the target's domain)."""
    np = _numpy()
    if method == 'reinhard-lab':
        t_lab, r_lab = lab_from_rgb01(target, transfer)[0], lab_from_rgb01(reference, transfer)[0]
        mu_t, mu_r = t_lab.mean(axis=0), r_lab.mean(axis=0)
        scale = r_lab.std(axis=0) / np.maximum(t_lab.std(axis=0), SIGMA_FLOOR)
        return np.clip(rgb01_from_lab((t_lab - mu_t) * scale + mu_r, transfer), 0.0, 1.0), {
            'target_lab_mean': [_r(v) for v in mu_t], 'reference_lab_mean': [_r(v) for v in mu_r],
            'lab_std_scale': [_r(v) for v in scale]}
    if method == 'mvgd':
        mu_t, mu_r = target.mean(axis=0), reference.mean(axis=0)
        eye = np.eye(3) * COV_EPSILON
        cov_t, cov_r = np.cov(target.T) + eye, np.cov(reference.T) + eye
        root = _sqrtm(cov_t)
        inverse_root = np.linalg.inv(root)
        transform = inverse_root @ _sqrtm(root @ cov_r @ root) @ inverse_root
        return np.clip((target - mu_t) @ transform.T + mu_r, 0.0, 1.0), {
            'linear_map': [[_r(v, 6) for v in row] for row in transform]}
    # Histogram: each channel's target quantile maps to the same reference quantile.
    out = np.empty_like(target)
    for c in range(3):
        order = np.argsort(target[:, c], kind='stable')
        ranks = np.empty(len(order))
        ranks[order] = (np.arange(len(order)) + 0.5) / len(order)
        out[:, c] = np.quantile(reference[:, c], ranks)
    return out, {}


def _apply_cdl(rgb, slope, offset, saturation):
    np = _numpy()
    sop = np.clip(rgb * slope + offset, 0.0, 1.0)
    luma = (sop @ np.array(LUMA_709))[:, None]
    return np.clip(luma + saturation * (sop - luma), 0.0, 1.0)


def _bounds(value):
    from editing_runtime import require, number
    require(isinstance(value, dict) and value and set(value) <= set(DEFAULT_BOUNDS), 'COLOR_FIT_BOUNDS_INVALID')
    result = dict(DEFAULT_BOUNDS)
    for name in CDL_BOUNDS:
        if name in value:
            pair = value[name]
            require(isinstance(pair, list) and len(pair) == 2, 'COLOR_FIT_BOUNDS_INVALID: ' + name)
            low, high = (number(x, name) for x in pair)
            wide = DEFAULT_BOUNDS[name]
            require(wide[0] <= low <= high <= wide[1], 'COLOR_FIT_BOUNDS_INVALID: ' + name)
            result[name] = (low, high)
    if 'curve_max_shift' in value:
        shift = number(value['curve_max_shift'], 'curve_max_shift')
        require(0 < shift <= 1, 'COLOR_FIT_BOUNDS_INVALID: curve_max_shift')
        result['curve_max_shift'] = shift
    return result


def _fit_cdl(target, ideal, transfer, bounds=DEFAULT_BOUNDS):
    """Golden-section search on saturation; for each candidate, slope and offset come from least squares.

    Slope and saturation are confounded (both widen per-channel spread), so the inner
    solve is redone for every saturation instead of alternating between them. Bounds
    clip the slope, re-solve the offset for the clipped slope, then clip the offset.
    """
    np = _numpy()
    ideal_lab = lab_from_rgb01(ideal, transfer)[0]
    luma = (ideal @ np.array(LUMA_709))[:, None]
    design = [np.stack([target[:, c], np.ones(len(target))], axis=1) for c in range(3)]

    def solve(saturation, report=None):
        goal = luma + (ideal - luma) / saturation  # undo the saturation step, then fit the per-channel line
        raw_slope, raw_offset = np.ones(3), np.zeros(3)
        for c in range(3):
            (raw_slope[c], raw_offset[c]), *_ = np.linalg.lstsq(design[c], goal[:, c], rcond=None)
        slope = np.clip(raw_slope, *bounds['slope'])
        refit = np.where(slope != raw_slope, (goal - slope * target).mean(axis=0), raw_offset)
        offset = np.clip(refit, *bounds['offset'])
        if report is not None:
            report.update(slope=[bool(x) for x in slope != raw_slope], offset=[bool(x) for x in offset != refit])
        return slope, offset

    def error(saturation):
        slope, offset = solve(saturation)
        fitted = lab_from_rgb01(_apply_cdl(target, slope, offset, saturation), transfer)[0]
        return float(((fitted - ideal_lab) ** 2).sum(axis=1).mean())

    low, high = bounds['saturation']
    golden = (5 ** 0.5 - 1) / 2
    a, b = high - golden * (high - low), low + golden * (high - low)
    fa, fb = error(a), error(b)
    for _ in range(40):
        if fa < fb:
            high, b, fb = b, a, fa
            a = high - golden * (high - low)
            fa = error(a)
        else:
            low, a, fa = a, b, fb
            b = low + golden * (high - low)
            fb = error(b)
    saturation = (low + high) / 2
    clipped = {}
    slope, offset = solve(saturation, clipped)
    edges = bounds['saturation']
    clipped['saturation'] = bool(edges != DEFAULT_BOUNDS['saturation'] and min(abs(saturation - e) for e in edges) < 1e-3)
    op = {'type': 'cdl', 'slope': [_r(v, 6) for v in slope], 'offset': [_r(v, 6) for v in offset],
          'power': [1.0, 1.0, 1.0], 'saturation': _r(saturation, 6)}
    return op, _apply_cdl(target, np.array(op['slope']), np.array(op['offset']), op['saturation']), clipped


def _fit_curves(target, ideal, bounds=DEFAULT_BOUNDS):
    """Per-channel monotone curves through the matched quantile mapping at fixed code values."""
    from color_numerics import pchip
    np = _numpy()
    xs = np.linspace(0.0, 1.0, CURVE_POINTS)
    op = {'type': 'curves'}
    shift = bounds['curve_max_shift']
    clipped = {}
    for c, name in enumerate(('red', 'green', 'blue')):
        order = np.argsort(target[:, c], kind='stable')
        source, mapped = target[order, c], ideal[order, c]
        raw = np.interp(xs, source, mapped)  # outside the observed range: hold the nearest mapped value
        ys = np.clip(raw, xs - shift, xs + shift)
        clipped[name] = int(np.sum(ys != raw))
        ys = np.clip(np.maximum.accumulate(ys), 0.0, 1.0)
        op[name] = [[_r(x, 6), _r(y, 6)] for x, y in zip(xs, ys)]
    fitted = target.copy()
    for c, name in enumerate(('red', 'green', 'blue')):
        px, py = zip(*op[name])
        fitted[:, c] = pchip(px, py, target[:, c])
    return op, np.clip(fitted, 0.0, 1.0), {'points_clamped': clipped}


def _distances(reference_lab, candidate_lab):
    np = _numpy()
    mean = ciede2000(reference_lab.mean(axis=0)[None, :], candidate_lab.mean(axis=0)[None, :])[0]
    rng = np.random.default_rng(SEED)
    directions = rng.normal(size=(SLICES, 3))
    directions /= np.linalg.norm(directions, axis=1, keepdims=True)
    n = min(len(reference_lab), len(candidate_lab))
    a, b = _subsample(reference_lab, n), _subsample(candidate_lab, n)
    sliced = float(np.mean([np.abs(np.sort(a @ d) - np.sort(b @ d)).mean() for d in directions]))
    js = []
    for index, (low, high, bins) in enumerate(JS_BINS.values()):
        p = np.histogram(reference_lab[:, index], bins=bins, range=(low, high))[0].astype(float) + 1e-12
        q = np.histogram(candidate_lab[:, index], bins=bins, range=(low, high))[0].astype(float) + 1e-12
        p, q = p / p.sum(), q / q.sum()
        m = (p + q) / 2
        js.append(0.5 * (p * np.log2(p / m)).sum() + 0.5 * (q * np.log2(q / m)).sum())
    return {'mean_color_delta_e2000': _r(mean), 'sliced_wasserstein_lab': _r(sliced),
            'js_divergence_lab': _r(float(np.mean(js)), 6)}


def fit(request, directory, tools):
    from editing_runtime import exact_keys, require, source, write_json
    fields = ['operation', 'reference', 'target', 'method', 'grade_id']
    exact_keys(request, fields + ['bounds'], fields)
    bounds = _bounds(request['bounds']) if 'bounds' in request else dict(DEFAULT_BOUNDS)
    np = _numpy()
    method = request['method']
    require(method in METHODS, 'COLOR_FIT_METHOD_UNSUPPORTED')
    gid = request['grade_id']
    require(isinstance(gid, str) and gid.strip() and len(gid) <= 120 and not set(gid) & {'"', '\n', '\r', '#'},
            'COLOR_GRADE_ID_INVALID')
    r_asset, r_video, r_frames = _side(request['reference'], 'reference', tools)
    t_asset, t_video, t_frames = _side(request['target'], 'target', tools)
    r_space, t_space = request['reference']['input_color']['space'], request['target']['input_color']['space']
    transfer = TRANSFERS[t_space]
    reference, r_size = _pixels(r_asset, r_video, r_frames, request['reference']['input_color'], tools)
    target, t_size = _pixels(t_asset, t_video, t_frames, request['target']['input_color'], tools)
    reference_lab = lab_from_rgb01(reference, TRANSFERS[r_space])[0]
    if r_space != t_space:
        # Express the reference in the target's code values so every method works in one domain.
        reference = np.clip(rgb01_from_lab(reference_lab, transfer), 0.0, 1.0)
    reference, target = _subsample(reference, FIT_PIXELS), _subsample(target, FIT_PIXELS)
    reference_lab = lab_from_rgb01(reference, transfer)[0]
    ideal, details = _ideal(method, target, reference, transfer)
    op, fitted, clipped = (_fit_cdl(target, ideal, transfer, bounds) if METHODS[method] == 'cdl'
                           else _fit_curves(target, ideal, bounds))
    applied = [k for k in ((CDL_BOUNDS) if METHODS[method] == 'cdl' else ('curve_max_shift',)) if k in request.get('bounds', {})]
    target_lab, ideal_lab, fitted_lab = (lab_from_rgb01(x, transfer)[0] for x in (target, ideal, fitted))
    residual = ciede2000(ideal_lab, fitted_lab)
    grade = {'schema': 'color-grade/1', 'id': gid, 'interpretation': INTERPRETATIONS[t_space], 'ops': [op]}
    from color_grade_ops import normalize, evaluate
    spec = normalize(grade)
    check = ciede2000(lab_from_rgb01(evaluate(*spec, target), transfer)[0], fitted_lab)
    require(float(np.max(check)) < 0.05, 'COLOR_FIT_GRADE_MISMATCH')  # the suggested grade reproduces the fit
    source(request['reference']['source'])
    source(request['target']['source'])  # bytes must still match after decoding
    result = {'schema': SCHEMA, 'method': method, 'model': METHODS[method],
              'reference': {'source': r_asset, 'input_color': request['reference']['input_color'], 'frames': r_frames,
                            'analysis_size': r_size},
              'target': {'source': t_asset, 'input_color': request['target']['input_color'], 'frames': t_frames,
                         'analysis_size': t_size},
              'pixels': {'reference': int(len(reference)), 'target': int(len(target)),
                         'sampling': 'point-sampled frames, then an evenly strided subsample of at most %d pixels' % FIT_PIXELS},
              'method_details': details, 'grade': grade, 'adopted': False, 'strength': 'NOT_CHOSEN',
              'bounds': {'applied': {k: list(bounds[k]) if isinstance(bounds[k], tuple) else bounds[k] for k in applied},
                         'ignored': sorted(set(request.get('bounds', {})) - set(applied)), 'hit': clipped},
              'distances_to_reference': {'before': _distances(reference_lab, target_lab),
                                         'ideal_transfer': _distances(reference_lab, ideal_lab),
                                         'fitted_grade': _distances(reference_lab, fitted_lab)},
              'fit_residual_delta_e2000': {'median': _r(np.median(residual)), 'p95': _r(np.percentile(residual, 95))},
              'domain': ('reference converted through CIELAB into the target interpretation' if r_space != t_space
                         else 'shared interpretation'),
              'aesthetic_judgement': 'NOT_PROVIDED',
              'limits': ['Distances compare color distributions of the sampled frames; smaller is not "looks like".',
                         'Statistics ignore content and layout: different scenes with matched statistics can still look unrelated.',
                         'histogram matches channels independently and can shift hues; mvgd mixes channels, which a CDL '
                         'approximates only through saturation, so its fit residual is reported.',
                         'The grade is a candidate for color-grade-compile; adoption, strength and protections stay with the caller.']}
    write_json(directory / 'color-reference-fit.json', result)
    return result
