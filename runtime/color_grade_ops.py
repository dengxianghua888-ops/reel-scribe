"""Compile explicit color-grade parameters to a 3D LUT and exchange files.

Every operation is defined on display-referred BT.709 R'G'B' code values in
[0, 1]; exposure and white balance act in BT.1886 gamma-2.4 linear light;
curves act on code values; hsl selects hue bands on the RGB hexcone and edits
CIELAB L*, C*ab and h_ab. Each operation clamps to [0, 1]. This module chooses no look, measures no footage
and does not apply anything to media; color-lut-apply consumes the cube.
"""
import json
from xml.sax.saxutils import escape

SCHEMA = 'color-grade/1'
INTERPRETATION = 'bt709-sdr-display'
LUT_SIZES = (17, 33, 65)
EXPORTS = ('cube', 'cc', 'clf')
MAX_OPS = 16
ACCURACY_POINTS = 4096
# Additive recurrence (Kronecker) offsets: deterministic and never aligned to 17/33/65 grids.
ACCURACY_STEPS = (0.6180339887498949, 0.4142135623730951, 0.7320508075688772)
CURVE_CHANNELS = ('master', 'red', 'green', 'blue')
MAX_CURVE_POINTS = 32
# Band centers on the RGB hexcone hue circle (degrees), as editors name them.
HSL_BANDS = (('red', 0.0), ('orange', 30.0), ('yellow', 60.0), ('green', 120.0),
             ('aqua', 180.0), ('blue', 240.0), ('purple', 270.0), ('magenta', 300.0))
HSL_LIMITS = {'hue': (-30.0, 30.0), 'saturation': (0.0, 2.0), 'lightness': (-30.0, 30.0)}
HSL_NEUTRAL_CHROMA = (2.0, 12.0)  # C*ab ramp: no edit below the first value, full edit above the second
CHAIN_MODEL = ("Operations apply in listed order to display-referred BT.709 R'G'B' in [0,1]; exposure and "
               "white_balance use BT.1886 gamma 2.4 linear light; curves map code values with monotone cubic "
               "(PCHIP) interpolation, master before per-channel; hsl weights hexcone-hue bands with cos^2 "
               "cross-fades that sum to 1, ramps the edit in by CIELAB chroma, then rotates h_ab, scales C*ab "
               "and shifts L*; every operation clamps to [0,1]; strength blends input and chain output in code values.")


def _triple(value, name, low, high):
    from editing_runtime import require, number
    require(isinstance(value, list) and len(value) == 3, 'COLOR_GRADE_TRIPLE_REQUIRED: ' + name)
    values = [number(x, name) for x in value]
    require(all(low <= x <= high for x in values), 'COLOR_GRADE_VALUE_OUT_OF_RANGE: ' + name)
    return values


def _curve(points, name):
    from editing_runtime import require, number
    require(isinstance(points, list) and 2 <= len(points) <= MAX_CURVE_POINTS, 'COLOR_GRADE_CURVE_POINTS_INVALID: ' + name)
    pairs = []
    for point in points:
        require(isinstance(point, list) and len(point) == 2, 'COLOR_GRADE_CURVE_POINT_INVALID: ' + name)
        x, y = (number(v, name) for v in point)
        require(0 <= x <= 1 and 0 <= y <= 1, 'COLOR_GRADE_VALUE_OUT_OF_RANGE: ' + name)
        pairs.append([x, y])
    require(all(a[0] < b[0] for a, b in zip(pairs, pairs[1:])), 'COLOR_GRADE_CURVE_X_NOT_INCREASING: ' + name)
    require(pairs[0][0] == 0 and pairs[-1][0] == 1, 'COLOR_GRADE_CURVE_DOMAIN_INCOMPLETE: ' + name)
    return pairs


def _hsl_bands(bands):
    from editing_runtime import exact_keys, require, number
    names = [name for name, _ in HSL_BANDS]
    require(isinstance(bands, dict) and bands and set(bands) <= set(names), 'COLOR_GRADE_HSL_BANDS_INVALID')
    result = {}
    for name in names:
        if name not in bands:
            continue
        band = bands[name]
        exact_keys(band, list(HSL_LIMITS), [])
        require(band, 'COLOR_GRADE_HSL_BAND_EMPTY: ' + name)
        values = {'hue': 0.0, 'saturation': 1.0, 'lightness': 0.0}
        for key, (low, high) in HSL_LIMITS.items():
            if key in band:
                values[key] = number(band[key], key)
                require(low <= values[key] <= high, 'COLOR_GRADE_VALUE_OUT_OF_RANGE: %s.%s' % (name, key))
        result[name] = values
    return result


def normalize(grade):
    """Validate a grade specification; LUT ops load their verified cube bytes."""
    from editing_runtime import exact_keys, require, number
    exact_keys(grade, ['schema', 'id', 'interpretation', 'ops', 'strength'], ['schema', 'id', 'interpretation', 'ops'])
    require(grade['schema'] == SCHEMA, 'COLOR_GRADE_SCHEMA_UNSUPPORTED')
    require(isinstance(grade['id'], str) and grade['id'].strip() and len(grade['id']) <= 120
            and '"' not in grade['id'] and '\n' not in grade['id'], 'COLOR_GRADE_ID_INVALID')
    require(grade['interpretation'] == INTERPRETATION, 'COLOR_GRADE_INTERPRETATION_UNSUPPORTED')
    require(isinstance(grade['ops'], list) and 1 <= len(grade['ops']) <= MAX_OPS, 'COLOR_GRADE_OPS_INVALID')
    strength = number(grade.get('strength', 1), 'strength')
    require(0 <= strength <= 1, 'COLOR_GRADE_STRENGTH_OUT_OF_RANGE')
    ops, luts = [], {}
    for index, op in enumerate(grade['ops']):
        require(isinstance(op, dict) and op.get('type') in ('exposure', 'white_balance', 'cdl', 'lut', 'curves', 'hsl'),
                'COLOR_GRADE_OP_UNSUPPORTED: %d' % index)
        kind = op['type']
        if kind == 'exposure':
            exact_keys(op, ['type', 'stops'], ['type', 'stops'])
            stops = number(op['stops'], 'stops')
            require(-4 <= stops <= 4, 'COLOR_GRADE_VALUE_OUT_OF_RANGE: stops')
            ops.append({'type': kind, 'stops': stops})
        elif kind == 'white_balance':
            exact_keys(op, ['type', 'gains', 'preserve_luminance'], ['type', 'gains', 'preserve_luminance'])
            require(type(op['preserve_luminance']) is bool, 'COLOR_GRADE_BOOLEAN_REQUIRED: preserve_luminance')
            ops.append({'type': kind, 'gains': _triple(op['gains'], 'gains', 0.25, 4),
                        'preserve_luminance': op['preserve_luminance']})
        elif kind == 'cdl':
            exact_keys(op, ['type', 'slope', 'offset', 'power', 'saturation'],
                       ['type', 'slope', 'offset', 'power', 'saturation'])
            saturation = number(op['saturation'], 'saturation', 0)
            require(saturation <= 4, 'COLOR_GRADE_VALUE_OUT_OF_RANGE: saturation')
            ops.append({'type': kind, 'slope': _triple(op['slope'], 'slope', 0, 4),
                        'offset': _triple(op['offset'], 'offset', -1, 1),
                        'power': _triple(op['power'], 'power', 0.1, 4), 'saturation': saturation})
        elif kind == 'curves':
            exact_keys(op, ['type', *CURVE_CHANNELS], ['type'])
            require(len(op) > 1, 'COLOR_GRADE_CURVE_REQUIRED')
            ops.append({'type': kind, **{name: _curve(op[name], name) for name in CURVE_CHANNELS if name in op}})
        elif kind == 'hsl':
            exact_keys(op, ['type', 'bands'], ['type', 'bands'])
            ops.append({'type': kind, 'bands': _hsl_bands(op['bands'])})
        else:
            exact_keys(op, ['type', 'source', 'interpolation', 'mix'], ['type', 'source', 'interpolation'])
            require(op['interpolation'] in ('tetrahedral', 'trilinear'), 'LUT_INTERPOLATION_UNSUPPORTED')
            mix = number(op.get('mix', 1), 'mix')
            require(0 <= mix <= 1, 'COLOR_GRADE_VALUE_OUT_OF_RANGE: mix')
            from color_ops import verified_cube
            from color_numerics import table_from_rows
            artifact, info, rows, _ = verified_cube(op['source'])
            luts[index] = table_from_rows(rows, info['size'])
            ops.append({'type': kind, 'source': {'path': artifact['path'], 'sha256': artifact['sha256']},
                        'size': info['size'], 'interpolation': op['interpolation'], 'mix': mix})
    return {'schema': SCHEMA, 'id': grade['id'], 'interpretation': INTERPRETATION,
            'ops': ops, 'strength': strength}, luts


def _luminance_gains(gains):
    from color_numerics import LUMA_709
    scale = sum(w * g for w, g in zip(LUMA_709, gains))
    return [g / scale for g in gains]


def _apply_curves(op, x):
    from color_numerics import numpy, pchip
    np = numpy()
    out = x
    if 'master' in op:
        xs, ys = zip(*op['master'])
        out = pchip(xs, ys, out)
    for channel, name in enumerate(('red', 'green', 'blue')):
        if name in op:
            xs, ys = zip(*op[name])
            out = out.copy()
            out[:, channel] = pchip(xs, ys, out[:, channel])
    return np.clip(out, 0.0, 1.0)


def hsl_weights(hue):
    """(N,) hexcone hue in degrees -> (N, 8) band weights; cos^2 cross-fades between adjacent centers."""
    from color_numerics import numpy
    np = numpy()
    centers = np.array([c for _, c in HSL_BANDS] + [360.0])
    index = np.clip(np.searchsorted(centers, hue, side='right') - 1, 0, len(HSL_BANDS) - 1)
    t = (hue - centers[index]) / (centers[index + 1] - centers[index])
    weights = np.zeros((len(hue), len(HSL_BANDS)))
    rows = np.arange(len(hue))
    weights[rows, index] = np.cos(np.pi * t / 2) ** 2
    weights[rows, (index + 1) % len(HSL_BANDS)] += np.sin(np.pi * t / 2) ** 2
    return weights


def _apply_hsl(op, x):
    from color_numerics import numpy, lab_from_rgb01, rgb01_from_lab, hexcone_hue
    np = numpy()
    adjust = np.array([[op['bands'].get(name, {}).get(key, default) for key, default in
                        (('hue', 0.0), ('saturation', 1.0), ('lightness', 0.0))] for name, _ in HSL_BANDS])
    lab, _ = lab_from_rgb01(x)
    chroma = np.hypot(lab[:, 1], lab[:, 2])
    low, high = HSL_NEUTRAL_CHROMA
    ramp = np.clip((chroma - low) / (high - low), 0.0, 1.0)
    ramp = ramp * ramp * (3 - 2 * ramp)  # smoothstep keeps near-neutral pixels continuous
    per_pixel = hsl_weights(hexcone_hue(x)) @ adjust
    hue = np.arctan2(lab[:, 2], lab[:, 1]) + np.radians(ramp * per_pixel[:, 0])
    chroma = chroma * (1 + ramp * (per_pixel[:, 1] - 1))
    lightness = np.clip(lab[:, 0] + ramp * per_pixel[:, 2], 0.0, 100.0)
    edited = np.stack([lightness, chroma * np.cos(hue), chroma * np.sin(hue)], axis=1)
    return np.clip(rgb01_from_lab(edited), 0.0, 1.0)


def evaluate(spec, luts, rgb):
    """Analytic chain on (N,3) code values; the reference the LUT is checked against."""
    from color_numerics import numpy, DISPLAY_GAMMA, LUMA_709, interpolate
    np = numpy()
    x = np.clip(np.asarray(rgb, dtype=float), 0.0, 1.0)
    out = x
    for index, op in enumerate(spec['ops']):
        if op['type'] in ('exposure', 'white_balance'):
            gains = ([2.0 ** op['stops']] * 3 if op['type'] == 'exposure' else
                     _luminance_gains(op['gains']) if op['preserve_luminance'] else op['gains'])
            linear = np.clip(out ** DISPLAY_GAMMA * np.array(gains), 0.0, 1.0)
            out = linear ** (1.0 / DISPLAY_GAMMA)
        elif op['type'] == 'cdl':
            sop = np.clip(out * np.array(op['slope']) + np.array(op['offset']), 0.0, 1.0) ** np.array(op['power'])
            luma = (sop @ np.array(LUMA_709))[:, None]
            out = np.clip(luma + op['saturation'] * (sop - luma), 0.0, 1.0)
        elif op['type'] == 'curves':
            out = _apply_curves(op, out)
        elif op['type'] == 'hsl':
            out = _apply_hsl(op, out)
        else:
            mapped = interpolate(luts[index], out, op['interpolation'])
            out = np.clip(out + op['mix'] * (mapped - out), 0.0, 1.0)
    return np.clip(x + spec['strength'] * (out - x), 0.0, 1.0)


def _accuracy(spec, luts, table):
    from color_numerics import numpy, lab_from_rgb01, ciede2000, interpolate
    np = numpy()
    n = np.arange(1, ACCURACY_POINTS + 1)[:, None]
    points = (n * np.array(ACCURACY_STEPS)) % 1.0
    analytic = evaluate(spec, luts, points)
    sampled = interpolate(table, points, 'tetrahedral')
    delta = ciede2000(lab_from_rgb01(analytic)[0], lab_from_rgb01(sampled)[0])
    return {'method': 'CIEDE2000 between the analytic chain and numpy tetrahedral sampling of the compiled cube',
            'points': int(len(points)), 'point_set': 'additive-recurrence sequence, off the LUT grid',
            'delta_e2000': {'median': round(float(np.median(delta)), 4), 'p95': round(float(np.percentile(delta, 95)), 4),
                            'max': round(float(delta.max()), 4)},
            'max_abs_code_difference': round(float(np.abs(analytic - sampled).max()), 6),
            'scope': 'numpy reference interpolation; FFmpeg lut3d is a separate implementation'}


def _fmt(values):
    return ' '.join('%.10g' % v for v in values)


def _cdl_nodes(op, indent):
    pad = ' ' * indent
    return (f'{pad}<SOPNode>\n{pad}  <Slope>{_fmt(op["slope"])}</Slope>\n{pad}  <Offset>{_fmt(op["offset"])}</Offset>\n'
            f'{pad}  <Power>{_fmt(op["power"])}</Power>\n{pad}</SOPNode>\n'
            f'{pad}<SatNode>\n{pad}  <Saturation>{"%.10g" % op["saturation"]}</Saturation>\n{pad}</SatNode>\n')


def cc_text(spec):
    from editing_runtime import require
    require(len(spec['ops']) == 1 and spec['ops'][0]['type'] == 'cdl' and spec['strength'] == 1,
            'COLOR_GRADE_CDL_NOT_REPRESENTABLE: a .cc carries exactly one ASC CDL at full strength')
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<ColorCorrection id="{escape(spec["id"], {chr(34): "&quot;"})}">\n'
            + _cdl_nodes(spec['ops'][0], 2) + '</ColorCorrection>\n')


def _clf_lut3d(table, interpolation, pad):
    from color_numerics import numpy
    np = numpy()
    size = table.shape[0]
    rows = np.clip(table, 0.0, 1.0).reshape(-1, 3)  # [r][g][b]: blue changes fastest, as CLF requires.
    body = '\n'.join(pad + '    ' + ' '.join('%.6f' % v for v in row) for row in rows)
    return (f'{pad}<LUT3D inBitDepth="32f" outBitDepth="32f" interpolation="{interpolation}">\n'
            f'{pad}  <Array dim="{size} {size} {size} 3">\n{body}\n{pad}  </Array>\n{pad}</LUT3D>\n')


def clf_text(spec, luts, table):
    """Parametric ProcessList when exactly representable, else the compiled cube baked as LUT3D."""
    from color_numerics import DISPLAY_GAMMA
    pad = '  '
    parametric = spec['strength'] == 1 and all(op['type'] in ('exposure', 'white_balance', 'cdl')
                                               or (op['type'] == 'lut' and op['mix'] == 1) for op in spec['ops'])
    nodes = []
    if parametric:
        for index, op in enumerate(spec['ops']):
            if op['type'] in ('exposure', 'white_balance'):
                gains = ([2.0 ** op['stops']] * 3 if op['type'] == 'exposure' else
                         _luminance_gains(op['gains']) if op['preserve_luminance'] else op['gains'])
                matrix = [gains[0], 0, 0, 0, gains[1], 0, 0, 0, gains[2]]
                nodes.append(
                    f'{pad}<Exponent inBitDepth="32f" outBitDepth="32f" style="basicFwd">\n'
                    f'{pad}  <ExponentParams exponent="{DISPLAY_GAMMA}"/>\n{pad}</Exponent>\n'
                    f'{pad}<Matrix inBitDepth="32f" outBitDepth="32f">\n{pad}  <Array dim="3 3">{_fmt(matrix)}</Array>\n{pad}</Matrix>\n'
                    f'{pad}<Range inBitDepth="32f" outBitDepth="32f" style="Clamp">\n'
                    f'{pad}  <minInValue>0</minInValue>\n{pad}  <maxInValue>1</maxInValue>\n'
                    f'{pad}  <minOutValue>0</minOutValue>\n{pad}  <maxOutValue>1</maxOutValue>\n{pad}</Range>\n'
                    f'{pad}<Exponent inBitDepth="32f" outBitDepth="32f" style="basicRev">\n'
                    f'{pad}  <ExponentParams exponent="{DISPLAY_GAMMA}"/>\n{pad}</Exponent>\n')
            elif op['type'] == 'cdl':
                nodes.append(f'{pad}<ASC_CDL inBitDepth="32f" outBitDepth="32f" style="Fwd">\n'
                             + _cdl_nodes(op, 4) + f'{pad}</ASC_CDL>\n')
            else:
                nodes.append(_clf_lut3d(luts[index], op['interpolation'], pad))
    else:
        nodes.append(_clf_lut3d(table, 'tetrahedral', pad))
    mode = 'parametric' if parametric else 'baked-compiled-cube'
    text = ('<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<ProcessList compCLFversion="3" id="{escape(spec["id"], {chr(34): "&quot;"})}">\n'
            f'{pad}<Description>reel-scribe color-grade/1 ({mode})</Description>\n'
            f"{pad}<InputDescriptor>display-referred BT.709 R'G'B' code values in [0,1]</InputDescriptor>\n"
            f"{pad}<OutputDescriptor>display-referred BT.709 R'G'B' code values in [0,1]</OutputDescriptor>\n"
            + ''.join(nodes) + '</ProcessList>\n')
    return text, mode


def compile_grade(request, directory, tools):
    from editing_runtime import exact_keys, require, sha256, write_json, fingerprint
    from color_numerics import numpy, identity_table, cube_text
    exact_keys(request, ['operation', 'grade', 'lut_size', 'exports'], ['operation', 'grade', 'lut_size', 'exports'])
    require(request['lut_size'] in LUT_SIZES and type(request['lut_size']) is int, 'COLOR_GRADE_LUT_SIZE_UNSUPPORTED')
    exports = request['exports']
    require(isinstance(exports, list) and 'cube' in exports and len(set(exports)) == len(exports)
            and set(exports) <= set(EXPORTS), 'COLOR_GRADE_EXPORTS_INVALID')
    np = numpy()
    spec, luts = normalize(request['grade'])
    size = request['lut_size']
    identity = identity_table(size)
    table = evaluate(spec, luts, identity.reshape(-1, 3)).reshape(size, size, size, 3)
    # Check the representations before writing anything.
    cc = cc_text(spec) if 'cc' in exports else None
    clf = clf_text(spec, luts, table) if 'clf' in exports else None
    files = {}
    (directory / 'grade.cube').write_text(cube_text(table, spec['id']), encoding='utf-8')
    files['cube'] = {'path': str(directory / 'grade.cube'), 'sha256': sha256(directory / 'grade.cube'),
                     'size': size, 'ordering': 'red fastest, then green, then blue'}
    if cc is not None:
        (directory / 'grade.cc').write_text(cc, encoding='utf-8')
        files['cc'] = {'path': str(directory / 'grade.cc'), 'sha256': sha256(directory / 'grade.cc'),
                       'semantics': ('ASC CDL v1.2 parameters; this chain clamps SOP and saturation to [0,1] '
                                     '(CLF ASC_CDL style Fwd). Hosts that apply CDL without clamping '
                                     '(for example OpenColorIO CDL_NO_CLAMP) differ wherever values leave [0,1].')}
    if clf is not None:
        (directory / 'grade.clf').write_text(clf[0], encoding='utf-8')
        files['clf'] = {'path': str(directory / 'grade.clf'), 'sha256': sha256(directory / 'grade.clf'),
                        'mode': clf[1], 'version': 'CLF v3'}
    for index, op in enumerate(spec['ops']):  # Consumed LUT bytes must still match after compilation.
        if op['type'] == 'lut':
            require(sha256(op['source']['path']) == op['source']['sha256'], 'SOURCE_HASH_MISMATCH: ' + op['source']['path'])
    identity_check = bool(np.allclose(table, identity, atol=0.5e-6))
    result = {'schema': 'color-grade-compile/1', 'grade': spec, 'grade_sha256': fingerprint(spec),
              'chain_model': CHAIN_MODEL, 'files': files, 'accuracy': _accuracy(spec, luts, table),
              'compiled_is_identity': identity_check, 'applied_to_media': False, 'look_selection': 'NOT_PROVIDED',
              'effect_review': 'NOT_RUN',
              'limits': ['Grades are defined on display-referred BT.709 SDR code values only; no HDR/log/wide gamut.',
                         'Clamping after each operation discards out-of-range values; it is not a soft roll-off.',
                         'hsl bands are hexcone hue regions, not skin, sky or object detection; edits that leave '
                         'the BT.709 gamut are clipped per channel, which can shift hue near the gamut boundary; near a '
                         'clipped channel the gamma-2.4 toe is steep, so use lut_size 65 and read the accuracy report.',
                         'Exchange files describe this chain; host applications may interpolate or clamp differently.']}
    write_json(directory / 'color-grade.json', json.loads(json.dumps(result)))
    return result
