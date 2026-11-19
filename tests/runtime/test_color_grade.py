"""color-grade-compile, shared color numerics and color-lut-apply strength.

Reference values come from independent formulas in this file, the published
CIEDE2000 test pairs (Sharma, Wu and Dalal 2005) and, when installed, an
OpenColorIO evaluation of the exported files. Synthetic media only; nothing
here judges whether a grade looks good.
"""
import hashlib
import math
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
np = pytest.importorskip('numpy')
import color_media as cm
import color_grade_ops as cg
import color_numerics as cn
import editing_runtime as rt
from editing_runtime import ContractError


def ref(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def grade(ops, strength=None, gid='fixture'):
    value = {'schema': 'color-grade/1', 'id': gid, 'interpretation': 'bt709-sdr-display', 'ops': ops}
    if strength is not None:
        value['strength'] = strength
    return value


def compile_run(tmp_path, spec, size=33, exports=('cube',), name='run'):
    return rt.run({'operation': 'color-grade-compile', 'grade': spec, 'lut_size': size, 'exports': list(exports)},
                  tmp_path / name, rt.Tools())


CDL = {'type': 'cdl', 'slope': [1.1, 1.0, 0.9], 'offset': [0.02, 0.0, -0.01], 'power': [0.95, 1.0, 1.05], 'saturation': 0.85}


# --- numerics ---------------------------------------------------------------

@pytest.mark.parametrize('lab1,lab2,expected', [  # Sharma, Wu and Dalal (2005) test data.
    ((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485), 2.0425),
    ((50.0, 3.1571, -77.2803), (50.0, 0.0, -82.7485), 2.8615),
    ((50.0, 2.8361, -74.0200), (50.0, 0.0, -82.7485), 3.4412),
    ((50.0, 0.0, 0.0), (50.0, -1.0, 2.0), 2.3669),
    ((50.0, 2.5, 0.0), (73.0, 25.0, -18.0), 27.1492),
    ((60.2574, -34.0099, 36.2677), (60.4626, -34.1751, 39.4387), 1.2644),
    ((63.0109, -31.0961, -5.8663), (62.8187, -29.7946, -4.0864), 1.2630),
    ((2.0776, 0.0795, -1.1350), (0.9033, -0.0636, -0.5514), 0.9082),
])
def test_ciede2000_matches_published_pairs(lab1, lab2, expected):
    assert float(cn.ciede2000(np.array(lab1), np.array(lab2))[0]) == pytest.approx(expected, abs=1e-4)
    assert float(cn.ciede2000(np.array(lab2), np.array(lab1))[0]) == pytest.approx(expected, abs=1e-4)


@pytest.mark.parametrize('method', ['tetrahedral', 'trilinear'])
def test_interpolation_is_exact_for_affine_tables_and_at_nodes(method):
    size = 5
    identity = cn.identity_table(size)
    affine = identity @ np.array([[0.5, 0.1, 0.0], [0.2, 0.6, 0.1], [0.0, 0.1, 0.7]]) + 0.05
    points = np.random.default_rng(3).random((500, 3))
    expected = points @ np.array([[0.5, 0.1, 0.0], [0.2, 0.6, 0.1], [0.0, 0.1, 0.7]]) + 0.05
    assert np.allclose(cn.interpolate(affine, points, method), expected, atol=1e-12)
    nodes = identity.reshape(-1, 3)
    curved = identity ** 2.2
    assert np.allclose(cn.interpolate(curved, nodes, method), curved.reshape(-1, 3), atol=1e-12)


def test_cube_text_round_trips_through_the_shared_parser_in_red_fastest_order():
    table = cn.identity_table(3) ** np.array([1.0, 2.0, 0.5])
    info, rows = cn.parse_cube_text(cn.cube_text(table, 'round trip'))
    assert info['size'] == 3 and rows[1] == pytest.approx([0.5, 0.0, 0.0], abs=1e-6)
    assert np.allclose(cn.table_from_rows(rows, 3), table, atol=1e-6)


# --- grade arithmetic --------------------------------------------------------

def reference_chain(rgb, ops, strength=1.0):
    """Independent per-pixel implementation of the documented chain."""
    x = [min(max(c, 0.0), 1.0) for c in rgb]
    out = list(x)
    for op in ops:
        if op['type'] in ('exposure', 'white_balance'):
            gains = [2 ** op['stops']] * 3 if op['type'] == 'exposure' else list(op['gains'])
            if op['type'] == 'white_balance' and op['preserve_luminance']:
                scale = 0.2126 * gains[0] + 0.7152 * gains[1] + 0.0722 * gains[2]
                gains = [g / scale for g in gains]
            out = [min(max(c ** 2.4 * g, 0.0), 1.0) ** (1 / 2.4) for c, g in zip(out, gains)]
        elif op['type'] == 'cdl':
            sop = [min(max(c * s + o, 0.0), 1.0) ** p for c, s, o, p in zip(out, op['slope'], op['offset'], op['power'])]
            luma = 0.2126 * sop[0] + 0.7152 * sop[1] + 0.0722 * sop[2]
            out = [min(max(luma + op['saturation'] * (c - luma), 0.0), 1.0) for c in sop]
    return [a + strength * (b - a) for a, b in zip(x, out)]


@pytest.mark.parametrize('ops,strength', [
    ([{'type': 'exposure', 'stops': 1}], 1.0),
    ([{'type': 'exposure', 'stops': -1.5}], 1.0),
    ([{'type': 'white_balance', 'gains': [1.2, 1.0, 0.8], 'preserve_luminance': True}], 1.0),
    ([{'type': 'white_balance', 'gains': [1.2, 1.0, 0.8], 'preserve_luminance': False}], 1.0),
    ([CDL], 1.0),
    ([{'type': 'exposure', 'stops': 0.5}, CDL], 0.4),
])
def test_compiled_chain_matches_independent_reference(tmp_path, ops, strength):
    spec, luts = cg.normalize(grade(ops, strength))
    points = np.random.default_rng(11).random((300, 3))
    got = cg.evaluate(spec, luts, points)
    expected = np.array([reference_chain(p, ops, strength) for p in points])
    assert np.allclose(got, expected, atol=1e-12)


def test_white_balance_with_luminance_preservation_keeps_gray_luminance():
    spec, luts = cg.normalize(grade([{'type': 'white_balance', 'gains': [1.3, 1.0, 0.7], 'preserve_luminance': True}]))
    gray = np.array([[0.5, 0.5, 0.5]])
    out = cg.evaluate(spec, luts, gray)
    linear_in, linear_out = gray ** 2.4, out ** 2.4
    weights = np.array(cn.LUMA_709)
    assert (linear_out @ weights)[0] == pytest.approx((linear_in @ weights)[0], abs=1e-9)
    assert out[0, 0] > out[0, 1] > out[0, 2]  # Warmer, with the declared gains.


def test_identity_and_zero_strength_compile_to_identity(tmp_path):
    for name, spec in [('exposure-zero', grade([{'type': 'exposure', 'stops': 0}])),
                       ('strength-zero', grade([CDL], strength=0))]:
        receipt = compile_run(tmp_path, spec, size=17, name=name)
        assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
        assert receipt['result']['compiled_is_identity'] is True
        assert receipt['result']['accuracy']['delta_e2000']['max'] < 1e-6


def test_accuracy_self_report_meets_plan_thresholds(tmp_path):
    spec = grade([{'type': 'exposure', 'stops': 0.5},
                  {'type': 'white_balance', 'gains': [1.1, 1.0, 0.85], 'preserve_luminance': True}, CDL])
    receipt = compile_run(tmp_path, spec, size=65)
    accuracy = receipt['result']['accuracy']
    assert accuracy['points'] == 4096 and 'off the LUT grid' in accuracy['point_set']
    assert accuracy['delta_e2000']['median'] < 0.5 and accuracy['delta_e2000']['max'] < 2.0
    assert receipt['result']['applied_to_media'] is False and receipt['result']['look_selection'] == 'NOT_PROVIDED'


def test_embedded_lut_uses_verified_bytes_and_mix(tmp_path, monkeypatch):
    invert = 1.0 - cn.identity_table(5)
    cube = tmp_path / 'invert.cube'
    cube.write_text(cn.cube_text(invert, 'invert'), encoding='utf-8')
    spec, luts = cg.normalize(grade([{'type': 'lut', 'source': ref(cube), 'interpolation': 'trilinear', 'mix': 0.5}]))
    assert np.allclose(cg.evaluate(spec, luts, np.random.default_rng(1).random((50, 3))), 0.5, atol=1e-12)
    original_source = rt.source

    def swap_after_hash(value, *args, **kwargs):
        result = original_source(value, *args, **kwargs)
        cube.write_text(cn.cube_text(cn.identity_table(5), 'swapped'), encoding='utf-8')
        return result

    reference = ref(cube)
    monkeypatch.setattr(rt, 'source', swap_after_hash)
    with pytest.raises(ContractError, match='SOURCE_HASH_MISMATCH'):
        cg.normalize(grade([{'type': 'lut', 'source': reference, 'interpolation': 'tetrahedral'}]))


@pytest.mark.parametrize('ops,strength,error', [
    ([{'type': 'exposure', 'stops': 5}], None, 'COLOR_GRADE_VALUE_OUT_OF_RANGE: stops'),
    ([{'type': 'white_balance', 'gains': [1, 1], 'preserve_luminance': True}], None, 'COLOR_GRADE_TRIPLE_REQUIRED'),
    ([{'type': 'cdl', 'slope': [1, 1, 1], 'offset': [0, 0, 0], 'power': [0, 1, 1], 'saturation': 1}], None, 'power'),
    ([{'type': 'curves'}], None, 'COLOR_GRADE_OP_UNSUPPORTED'),
    ([{'type': 'exposure', 'stops': 1, 'extra': 1}], None, 'UNKNOWN_FIELDS'),
    ([{'type': 'exposure', 'stops': 1}], 1.5, 'COLOR_GRADE_STRENGTH_OUT_OF_RANGE'),
    ([], None, 'COLOR_GRADE_OPS_INVALID'),
])
def test_grade_validation(tmp_path, ops, strength, error):
    receipt = compile_run(tmp_path, grade(ops, strength))
    assert receipt['status'] == 'FAILED' and error in receipt['error']
    assert not (tmp_path / 'run' / 'grade.cube').exists()


def test_cdl_export_only_when_exactly_representable(tmp_path):
    receipt = compile_run(tmp_path, grade([{'type': 'exposure', 'stops': 1}, CDL]), exports=['cube', 'cc'])
    assert receipt['status'] == 'FAILED' and 'COLOR_GRADE_CDL_NOT_REPRESENTABLE' in receipt['error']
    assert not (tmp_path / 'run' / 'grade.cube').exists()
    ok = compile_run(tmp_path, grade([CDL]), exports=['cube', 'cc'], name='cdl')
    assert ok['status'] == 'SUCCEEDED' and 'without clamping' in ok['result']['files']['cc']['semantics']
    text = (tmp_path / 'cdl' / 'grade.cc').read_text(encoding='utf-8')
    assert '<Slope>1.1 1 0.9</Slope>' in text and '<Saturation>0.85</Saturation>' in text


# --- exchange files against OpenColorIO, when installed ------------------------

def _ocio_apply(path, points, cdl_style=None):
    ocio = pytest.importorskip('PyOpenColorIO')
    transform = ocio.FileTransform(src=str(path), interpolation=ocio.INTERP_TETRAHEDRAL)
    if cdl_style:
        transform.setCDLStyle(getattr(ocio, cdl_style))
    buffer = points.astype(np.float32).copy()
    ocio.Config.CreateRaw().getProcessor(transform).getDefaultCPUProcessor().applyRGB(buffer)
    return buffer


def test_exports_evaluate_identically_in_opencolorio(tmp_path):
    pytest.importorskip('PyOpenColorIO')
    look = tmp_path / 'look.cube'
    look.write_text(cn.cube_text(np.clip(cn.identity_table(9) ** np.array([0.9, 1.0, 1.1]), 0, 1), 'look'), encoding='utf-8')
    points = np.random.default_rng(7).random((2000, 3))
    chain = grade([{'type': 'exposure', 'stops': 0.5},
                   {'type': 'white_balance', 'gains': [1.08, 1.0, 0.9], 'preserve_luminance': True}, CDL,
                   {'type': 'lut', 'source': ref(look), 'interpolation': 'tetrahedral'}])
    receipt = compile_run(tmp_path, chain, exports=['cube', 'clf'])
    assert receipt['result']['files']['clf']['mode'] == 'parametric'
    spec, luts = cg.normalize(chain)
    analytic = cg.evaluate(spec, luts, points)
    assert np.abs(_ocio_apply(receipt['result']['files']['clf']['path'], points) - analytic).max() < 1e-4
    cdl = compile_run(tmp_path, grade([CDL]), exports=['cube', 'cc'], name='cdl')
    spec, luts = cg.normalize(grade([CDL]))
    analytic = cg.evaluate(spec, luts, points)
    assert np.abs(_ocio_apply(cdl['result']['files']['cc']['path'], points, 'CDL_ASC') - analytic).max() < 1e-4
    baked = compile_run(tmp_path, grade([CDL], strength=0.6), exports=['cube', 'clf'], name='baked')
    assert baked['result']['files']['clf']['mode'] == 'baked-compiled-cube'
    via_clf = _ocio_apply(baked['result']['files']['clf']['path'], points)
    via_cube = _ocio_apply(baked['result']['files']['cube']['path'], points)
    assert np.abs(via_clf - via_cube).max() < 1e-4


# --- color-lut-apply strength and end-to-end measurement ----------------------

needs_media = pytest.mark.skipif(not cm.available(), reason='FFmpeg/ffprobe required')


def lut_apply(tmp_path, video, cube, name, **extra):
    request = {'operation': 'color-lut-apply', 'source': ref(video), 'lut': ref(cube),
               'input_color': {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'},
               'interpolation': 'tetrahedral', **extra}
    return rt.run(request, tmp_path / name, rt.Tools())


def profile(tmp_path, video, name):
    request = {'operation': 'color-profile-scan', 'source': ref(video), 'start': 0, 'end': 1,
               'samples': {'mode': 'times', 'times': [0.5]}, 'analysis_size': [48, 32],
               'input_color': {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'},
               'palette_colors': 1, 'max_samples': 1}
    receipt = rt.run(request, tmp_path / name, rt.Tools())
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    return receipt['result']['aggregate']


@needs_media
def test_lut_strength_derives_a_bound_cube_and_blends_on_media(tmp_path):
    png = cm.image(tmp_path / 'chart.png', [((200, 30, 30), 0.5), ((30, 40, 200), 0.5)])
    video = cm.encode_sdr(png, tmp_path / 'chart.mp4', seconds=1)
    invert = tmp_path / 'invert.cube'
    invert.write_text(cn.cube_text(1.0 - cn.identity_table(17), 'invert'), encoding='utf-8')
    full = lut_apply(tmp_path, video, invert, 'full')
    assert full['status'] == 'SUCCEEDED' and 'strength' not in full['result']
    assert (tmp_path / 'full' / 'selected.cube').read_bytes() == invert.read_bytes()
    half = lut_apply(tmp_path, video, invert, 'half', strength=0.5)
    assert half['status'] == 'SUCCEEDED', half.get('error')
    applied = half['result']['strength']['applied_cube']
    assert applied['sha256'] == hashlib.sha256(Path(applied['path']).read_bytes()).hexdigest()
    # identity + 0.5 * (invert - identity) == 0.5 everywhere: the chart becomes flat mid gray.
    stats = profile(tmp_path, tmp_path / 'half' / 'graded.mp4', 'measure-half')
    assert stats['chroma']['mean'] < 2.0 and abs(stats['luma']['p50'] - 0.5) < 3 / 255
    bad = lut_apply(tmp_path, video, invert, 'bad', strength=0)
    assert bad['status'] == 'FAILED' and 'LUT_STRENGTH_OUT_OF_RANGE' in bad['error']


@needs_media
def test_compile_apply_measure_round_trip_matches_analytic_exposure(tmp_path):
    png = cm.image(tmp_path / 'gray.png', [((100, 100, 100), 1)])
    video = cm.encode_sdr(png, tmp_path / 'gray.mp4', seconds=1)
    compiled = compile_run(tmp_path, grade([{'type': 'exposure', 'stops': 1}]), size=65, name='compile')
    applied = lut_apply(tmp_path, video, compiled['result']['files']['cube']['path'], 'apply')
    assert applied['status'] == 'SUCCEEDED', applied.get('error')
    stats = profile(tmp_path, tmp_path / 'apply' / 'graded.mp4', 'measure')
    expected_code = min(1.0, (100 / 255) ** 2.4 * 2) ** (1 / 2.4)
    expected_lab = cn.lab_from_rgb01(np.array([[expected_code] * 3]))[0][0]
    measured = np.array([stats['lab_mean'][k] for k in 'Lab'])
    assert float(cn.ciede2000(measured, expected_lab)[0]) < 1.5
    assert math.isclose(stats['luma']['p50'], expected_code, abs_tol=2.5 / 255)
