"""Shared, explicit color arithmetic: display model, CIELAB, CIEDE2000, LUTs.

Working space for grading and measurement is display-referred BT.709 R'G'B'
code values normalized to [0, 1]. Linear light uses the BT.1886 EOTF with
gamma 2.4 (Lw=1, Lb=0); this is a declared assumption, not a measured display.
"""
import math

DISPLAY_GAMMA = 2.4
# Linear BT.709/sRGB primaries to CIE XYZ (D65); white is the matrix row sum.
RGB_TO_XYZ = ((0.4123908, 0.3575843, 0.1804808),
              (0.2126390, 0.7151687, 0.0721923),
              (0.0193308, 0.1191948, 0.9505322))
LUMA_709 = (0.2126, 0.7152, 0.0722)
MAX_CUBE_BYTES = 16 * 1024 * 1024


def numpy():
    from editing_runtime import ContractError
    try:
        import numpy as np
    except ImportError as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE: numpy; run with the declared analysis environment') from exc
    return np


def lab_from_rgb01(rgb):
    """(N,3) display-referred BT.709 R'G'B' in [0,1] -> (CIELAB (N,3), linear RGB (N,3))."""
    np = numpy()
    linear = np.clip(rgb, 0.0, 1.0) ** DISPLAY_GAMMA
    matrix = np.array(RGB_TO_XYZ)
    t = (linear @ matrix.T) / matrix.sum(axis=1)
    delta = 6.0 / 29.0
    f = np.where(t > delta ** 3, np.cbrt(t), t / (3 * delta ** 2) + 4.0 / 29.0)
    lab = np.stack([116.0 * f[:, 1] - 16.0, 500.0 * (f[:, 0] - f[:, 1]), 200.0 * (f[:, 1] - f[:, 2])], axis=1)
    return lab, linear


def ciede2000(lab1, lab2):
    """Vectorized CIEDE2000 (Sharma, Wu and Dalal 2005), kL = kC = kH = 1."""
    np = numpy()
    lab1, lab2 = np.atleast_2d(lab1).astype(float), np.atleast_2d(lab2).astype(float)
    l1, a1, b1 = lab1.T
    l2, a2, b2 = lab2.T
    c_bar = (np.hypot(a1, b1) + np.hypot(a2, b2)) / 2
    g = 0.5 * (1 - np.sqrt(c_bar ** 7 / (c_bar ** 7 + 25.0 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.where(c1p == 0, 0.0, np.degrees(np.arctan2(b1, a1p)) % 360)
    h2p = np.where(c2p == 0, 0.0, np.degrees(np.arctan2(b2, a2p)) % 360)
    zero = c1p * c2p == 0
    dh = h2p - h1p
    dh = np.where(zero, 0.0, np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh)))
    d_l, d_c = l2 - l1, c2p - c1p
    d_h = 2 * np.sqrt(c1p * c2p) * np.sin(np.radians(dh / 2))
    l_bar, cp_bar = (l1 + l2) / 2, (c1p + c2p) / 2
    total = h1p + h2p
    h_bar = np.where(zero, total, np.where(np.abs(h1p - h2p) <= 180, total / 2,
                                           np.where(total < 360, (total + 360) / 2, (total - 360) / 2)))
    t = (1 - 0.17 * np.cos(np.radians(h_bar - 30)) + 0.24 * np.cos(np.radians(2 * h_bar))
         + 0.32 * np.cos(np.radians(3 * h_bar + 6)) - 0.20 * np.cos(np.radians(4 * h_bar - 63)))
    d_theta = 30 * np.exp(-(((h_bar - 275) / 25) ** 2))
    r_c = 2 * np.sqrt(cp_bar ** 7 / (cp_bar ** 7 + 25.0 ** 7))
    s_l = 1 + 0.015 * (l_bar - 50) ** 2 / np.sqrt(20 + (l_bar - 50) ** 2)
    s_c, s_h = 1 + 0.045 * cp_bar, 1 + 0.015 * cp_bar * t
    r_t = -np.sin(np.radians(2 * d_theta)) * r_c
    return np.sqrt((d_l / s_l) ** 2 + (d_c / s_c) ** 2 + (d_h / s_h) ** 2 + r_t * (d_c / s_c) * (d_h / s_h))


def parse_cube_text(text):
    """Parse a 3D .cube (rows red fastest, then green, then blue) into rows.

    Accepts exactly the subset color-lut-apply has always accepted: TITLE,
    LUT_3D_SIZE 2-65, DOMAIN 0-1, finite values in [0,1], exactly N^3 rows.
    """
    from editing_runtime import require
    size = None
    rows, seen, data_started = [], set(), False
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        key = parts[0]
        if key in ['TITLE', 'LUT_3D_SIZE', 'DOMAIN_MIN', 'DOMAIN_MAX']:
            require(not data_started and key not in seen, 'LUT_DUPLICATE_OR_LATE_HEADER')
            seen.add(key)
            if key == 'TITLE':
                require(line.startswith('TITLE "') and line.endswith('"'), 'LUT_TITLE_INVALID')
            elif key == 'LUT_3D_SIZE':
                require(len(parts) == 2, 'LUT_SIZE_INVALID')
                size = int(parts[1])
                require(2 <= size <= 65, 'LUT_SIZE_UNSUPPORTED')
            else:
                require(len(parts) == 4, 'LUT_DOMAIN_INVALID')
                values = [float(x) for x in parts[1:]]
                require(values == ([0., 0., 0.] if key == 'DOMAIN_MIN' else [1., 1., 1.]), 'LUT_DOMAIN_UNSUPPORTED')
        else:
            require(size is not None, 'LUT_SIZE_REQUIRED_BEFORE_DATA')
            data_started = True
            require(len(parts) == 3, 'LUT_ROW_INVALID')
            values = [float(x) for x in parts]
            require(all(math.isfinite(x) and 0 <= x <= 1 for x in values), 'LUT_VALUE_OUT_OF_RANGE')
            rows.append(values)
            require(len(rows) <= size ** 3, 'LUT_TOO_MANY_ROWS')
    require(size is not None and len(rows) == size ** 3, 'LUT_INCOMPLETE')
    return {'size': size, 'rows': len(rows), 'domain': [0, 1],
            'ordering': 'red fastest, then green, then blue; caller supplies intended mapping'}, rows


def table_from_rows(rows, size):
    """Rows (red fastest) -> table indexed [r][g][b] with shape (N, N, N, 3)."""
    np = numpy()
    return np.array(rows, dtype=float).reshape(size, size, size, 3).transpose(2, 1, 0, 3)


def identity_table(size):
    np = numpy()
    axis = np.linspace(0.0, 1.0, size)
    r, g, b = np.meshgrid(axis, axis, axis, indexing='ij')
    return np.stack([r, g, b], axis=-1)


def cube_text(table, title):
    from editing_runtime import require
    np = numpy()
    size = table.shape[0]
    require(table.shape == (size, size, size, 3) and 2 <= size <= 65, 'LUT_SIZE_UNSUPPORTED')
    require(bool(np.isfinite(table).all()), 'LUT_VALUE_NONFINITE')
    require('"' not in title and '\n' not in title, 'LUT_TITLE_INVALID')
    values = np.clip(table, 0.0, 1.0).transpose(2, 1, 0, 3).reshape(-1, 3)
    lines = [f'TITLE "{title}"', f'LUT_3D_SIZE {size}', 'DOMAIN_MIN 0.0 0.0 0.0', 'DOMAIN_MAX 1.0 1.0 1.0']
    lines += ['%.6f %.6f %.6f' % tuple(row) for row in values]
    return '\n'.join(lines) + '\n'


def interpolate(table, rgb, method='tetrahedral'):
    """Sample a [r][g][b] table at (N,3) points in [0,1] (reference implementation)."""
    from editing_runtime import require
    require(method in ('tetrahedral', 'trilinear'), 'LUT_INTERPOLATION_UNSUPPORTED')
    np = numpy()
    size = table.shape[0]
    x = np.clip(rgb, 0.0, 1.0) * (size - 1)
    i = np.minimum(np.floor(x).astype(int), size - 2)
    f = x - i
    r0, g0, b0 = i[:, 0], i[:, 1], i[:, 2]
    fr, fg, fb = f[:, 0:1], f[:, 1:2], f[:, 2:3]

    def c(dr, dg, db):
        return table[r0 + dr, g0 + dg, b0 + db]

    if method == 'trilinear':
        c00 = c(0, 0, 0) * (1 - fr) + c(1, 0, 0) * fr
        c10 = c(0, 1, 0) * (1 - fr) + c(1, 1, 0) * fr
        c01 = c(0, 0, 1) * (1 - fr) + c(1, 0, 1) * fr
        c11 = c(0, 1, 1) * (1 - fr) + c(1, 1, 1) * fr
        return (c00 * (1 - fg) + c10 * fg) * (1 - fb) + (c01 * (1 - fg) + c11 * fg) * fb
    c000, c111 = c(0, 0, 0), c(1, 1, 1)
    cases = [
        ((fr >= fg) & (fg >= fb), (1 - fr) * c000 + (fr - fg) * c(1, 0, 0) + (fg - fb) * c(1, 1, 0) + fb * c111),
        ((fr >= fb) & (fb > fg), (1 - fr) * c000 + (fr - fb) * c(1, 0, 0) + (fb - fg) * c(1, 0, 1) + fg * c111),
        ((fb > fr) & (fr >= fg), (1 - fb) * c000 + (fb - fr) * c(0, 0, 1) + (fr - fg) * c(1, 0, 1) + fg * c111),
        ((fg > fr) & (fr >= fb), (1 - fg) * c000 + (fg - fr) * c(0, 1, 0) + (fr - fb) * c(1, 1, 0) + fb * c111),
        ((fg >= fb) & (fb > fr), (1 - fg) * c000 + (fg - fb) * c(0, 1, 0) + (fb - fr) * c(0, 1, 1) + fr * c111),
    ]
    result = (1 - fb) * c000 + (fb - fg) * c(0, 0, 1) + (fg - fr) * c(0, 1, 1) + fr * c111  # fb > fg > fr
    for mask, value in reversed(cases):
        result = np.where(mask, value, result)
    return result
