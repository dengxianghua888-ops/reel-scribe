"""Apply bounded, named adjustment steps (warmer, more contrast, ...) to an explicit grade.

The caller (usually an Agent reading the feedback table in the contract) turns a
viewer's words into cumulative steps per dimension; this op turns steps into fixed
parameter increments appended after the base grade, checks on fixed probe colors
that every non-zero step moved the picture in its named direction, and reports the
change. It interprets no language, chooses no look and adopts nothing.
"""
from color_numerics import lab_from_rgb01, ciede2000, numpy as _numpy

SCHEMA = 'color-grade-adjust/1'
DIMENSIONS = ('warmth', 'tint', 'exposure', 'contrast', 'saturation')
MAX_STEPS = 3
WARMTH_STEP = 0.025     # white-balance gain on R up and B down per step, luminance preserved
TINT_STEP = 0.02        # white-balance gain on G per step (+ greener, - more magenta), luminance preserved
EXPOSURE_STEP = 1 / 6   # stops per step
CONTRAST_STEP = 0.02    # S-curve displacement at code values 0.25 and 0.75 per step
SATURATION_STEP = 0.08  # CDL saturation per step
PROBES = {'mid-gray': (0.5, 0.5, 0.5), 'shadow-gray': (0.2, 0.2, 0.2), 'highlight-gray': (0.8, 0.8, 0.8),
          'skin-like': (0.76, 0.57, 0.47), 'sky-like': (0.40, 0.58, 0.82), 'foliage-like': (0.30, 0.48, 0.22)}


def _r(value, digits=4):
    return round(float(value), digits)


def adjustment_ops(steps):
    """Fixed parameter increments for the given cumulative steps, in a fixed order."""
    ops = []
    warmth, tint = steps.get('warmth', 0), steps.get('tint', 0)
    if warmth or tint:
        ops.append({'type': 'white_balance', 'preserve_luminance': True,
                    'gains': [_r(1 + WARMTH_STEP * warmth, 6), _r(1 + TINT_STEP * tint, 6), _r(1 - WARMTH_STEP * warmth, 6)]})
    if steps.get('exposure', 0):
        ops.append({'type': 'exposure', 'stops': _r(EXPOSURE_STEP * steps['exposure'], 6)})
    if steps.get('contrast', 0):
        d = CONTRAST_STEP * steps['contrast']
        ops.append({'type': 'curves', 'master': [[0, 0], [0.25, _r(0.25 - d, 6)], [0.5, 0.5], [0.75, _r(0.75 + d, 6)], [1, 1]]})
    if steps.get('saturation', 0):
        ops.append({'type': 'cdl', 'slope': [1, 1, 1], 'offset': [0, 0, 0], 'power': [1, 1, 1],
                    'saturation': _r(1 + SATURATION_STEP * steps['saturation'], 6)})
    return ops


def _steps(value, caps):
    from editing_runtime import require
    require(isinstance(value, dict) and value, 'COLOR_ADJUST_STEPS_REQUIRED')
    require(set(value) <= set(DIMENSIONS), 'COLOR_ADJUST_DIMENSION_UNSUPPORTED')
    for name, step in value.items():
        require(type(step) is int, 'COLOR_ADJUST_STEP_INTEGER_REQUIRED: ' + name)
        require(abs(step) <= caps.get(name, MAX_STEPS), 'COLOR_ADJUST_STEP_OVER_CAP: %s %d (cap %d)'
                % (name, step, caps.get(name, MAX_STEPS)))
    return {name: value[name] for name in DIMENSIONS if value.get(name)}


def _caps(value):
    from editing_runtime import require
    require(isinstance(value, dict) and set(value) <= set(DIMENSIONS), 'COLOR_ADJUST_CAPS_INVALID')
    require(all(type(v) is int and 0 <= v <= MAX_STEPS for v in value.values()), 'COLOR_ADJUST_CAPS_INVALID')
    return dict(value)


def _direction_checks(steps, before_lab, after_lab):
    """Each non-zero dimension must move the probes in its named direction."""
    np = _numpy()
    names = list(PROBES)
    b = dict(zip(names, before_lab))
    a = dict(zip(names, after_lab))
    chroma = lambda lab: float(np.hypot(lab[1], lab[2]))  # noqa: E731
    sign = lambda x: (float(x) > 0) - (float(x) < 0)  # noqa: E731
    checks = {}
    if 'warmth' in steps:
        checks['warmth'] = sign(a['mid-gray'][2] - b['mid-gray'][2]) == sign(steps['warmth'])
    if 'tint' in steps:  # positive tint is greener: a* goes down
        checks['tint'] = sign(b['mid-gray'][1] - a['mid-gray'][1]) == sign(steps['tint'])
    if 'exposure' in steps:
        checks['exposure'] = sign(a['mid-gray'][0] - b['mid-gray'][0]) == sign(steps['exposure'])
    if 'contrast' in steps:
        spread = (a['highlight-gray'][0] - a['shadow-gray'][0]) - (b['highlight-gray'][0] - b['shadow-gray'][0])
        checks['contrast'] = sign(spread) == sign(steps['contrast'])
    if 'saturation' in steps:
        change = sum(chroma(a[k]) - chroma(b[k]) for k in ('skin-like', 'sky-like', 'foliage-like'))
        checks['saturation'] = sign(change) == sign(steps['saturation'])
    return checks


def adjust(request, directory, tools):
    from editing_runtime import exact_keys, require, write_json
    from color_grade_ops import normalize, evaluate, INTERPRETATIONS, MAX_OPS
    exact_keys(request, ['operation', 'grade', 'steps', 'caps', 'adjusted_id'], ['operation', 'grade', 'steps', 'adjusted_id'])
    np = _numpy()
    base_spec, luts = normalize(request['grade'])
    caps = _caps(request['caps']) if 'caps' in request else {}
    steps = _steps(request['steps'], caps)
    require(steps, 'COLOR_ADJUST_ALL_STEPS_ZERO')
    added = adjustment_ops(steps)
    require(len(base_spec['ops']) + len(added) <= MAX_OPS, 'COLOR_ADJUST_TOO_MANY_OPS')
    adjusted = {**{k: v for k, v in request['grade'].items() if k != 'ops'}, 'id': request['adjusted_id'],
                'ops': list(request['grade']['ops']) + added}
    adjusted_spec, adjusted_luts = normalize(adjusted)
    transfer = INTERPRETATIONS[base_spec['interpretation']]
    probes = np.array(list(PROBES.values()))
    before = lab_from_rgb01(evaluate(base_spec, luts, probes), transfer)[0]
    after = lab_from_rgb01(evaluate(adjusted_spec, adjusted_luts, probes), transfer)[0]
    # Check each dimension alone on the base grade: combined steps can mask one another
    # (warmer and brighter raise chroma even when saturation goes down).
    checks = {}
    for name, step in steps.items():
        alone, alone_luts = normalize({**adjusted, 'ops': list(request['grade']['ops']) + adjustment_ops({name: step})})
        checks.update(_direction_checks({name: step}, before,
                                        lab_from_rgb01(evaluate(alone, alone_luts, probes), transfer)[0]))
    require(all(checks.values()), 'COLOR_ADJUST_DIRECTION_NOT_OBSERVED: ' + ','.join(k for k, v in checks.items() if not v))
    delta = ciede2000(before, after)
    result = {'schema': SCHEMA, 'base_grade_id': base_spec['id'], 'grade': adjusted, 'steps': steps,
              'caps': {name: caps.get(name, MAX_STEPS) for name in DIMENSIONS}, 'appended_ops': added,
              'step_sizes': {'warmth': 'white balance gains R x(1+%.3fk), B x(1-%.3fk), luminance preserved' % (WARMTH_STEP, WARMTH_STEP),
                             'tint': 'white balance gain G x(1+%.3fk), luminance preserved; + greener, - more magenta' % TINT_STEP,
                             'exposure': '%.4f stop per step' % EXPOSURE_STEP,
                             'contrast': 'master S-curve, code values 0.25 and 0.75 moved by %.3f per step' % CONTRAST_STEP,
                             'saturation': 'CDL saturation 1 + %.2fk' % SATURATION_STEP},
              'probe_effect': {name: {'delta_L': _r(a[0] - b[0]), 'delta_a': _r(a[1] - b[1]), 'delta_b': _r(a[2] - b[2]),
                                      'delta_chroma': _r(np.hypot(a[1], a[2]) - np.hypot(b[1], b[2])),
                                      'delta_e2000': _r(d)}
                               for name, b, a, d in zip(PROBES, before, after, delta)},
              'direction_checks': checks, 'direction_basis': 'each dimension alone on the base grade; probe_effect is the combined change',
              'adopted': False,
              'limits': ['Steps are fixed increments on fixed probe colors, not perceptual units; footage response varies.',
                         'Mapping words to steps is the caller\'s interpretation; the op only applies and checks the steps.',
                         'The adjusted grade is a candidate: compile, preview and protections decide adoption.']}
    write_json(directory / 'color-grade-adjust.json', result)
    return result
