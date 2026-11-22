"""Blender Color Balance bridge without a host: mapping, equivalence and stub-host rules.

The equivalence tests compare the bridge with color-grade-compile's own chain and with an
independent transcription of Blender's Lift/Gamma/Gain math. Stub hosts are NOT real-host
acceptance; test_blender_color_balance_host.py runs the real bpy module when it is installed.
"""
import copy
import importlib.util
import json
from pathlib import Path
import random
import sys
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('color_balance', ROOT / 'tools/editor-adapters/blender_color_balance.py')
cb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cb)

WARM = {'schema': 'color-grade/1', 'id': 'warm', 'interpretation': 'srgb-sdr-display',
        'ops': [{'type': 'cdl', 'slope': [1.1, 1.0, 0.9], 'offset': [0.02, 0.0, -0.03], 'power': [0.9, 1.0, 1.2],
                 'saturation': 1}]}


def grade(**op):
    value = copy.deepcopy(WARM)
    value['ops'][0].update(op)
    return value


def float32(settings):
    """Blender stores the settings as float32."""
    import struct
    f = lambda v: struct.unpack('f', struct.pack('f', v))[0]  # noqa: E731
    return {k: ([f(x) for x in v] if isinstance(v, list) else f(v) if isinstance(v, float) else v) for k, v in settings.items()}


def stored(settings):
    full = {'lift': [1.0] * 3, 'gamma': [1.0] * 3, 'gain': [1.0] * 3, 'invert_lift': False, 'invert_gamma': False,
            'invert_gain': False, **settings}
    return float32(full)


def test_apply_settings_follow_blenders_ui_storage():
    settings = cb.grade_to_settings(WARM)
    assert settings['correction_method'] == 'OFFSET_POWER_SLOPE'
    assert settings['offset'] == pytest.approx([1.02, 1.0, 0.97])  # Blender subtracts 1
    assert settings['power'] == pytest.approx([1 / 0.9, 1.0, 1 / 1.2])  # Blender inverts unless invert_power
    back = cb.settings_to_grade(stored(settings), 'warm', 'srgb-sdr-display')['ops'][0]
    # Slope and power come back as set; offsets as Blender applies them (stored as offset + 1 in float32).
    assert back['slope'] == [1.1, 1.0, 0.9] and back['power'] == [0.9, 1.0, 1.2]
    assert back['offset'] == [0.01999998, 0.0, -0.029999971]


@pytest.mark.parametrize('change,reason', [
    (lambda g: g['ops'][0].update(saturation=0.9), 'no saturation stage'),
    (lambda g: g.update(strength=0.8), 'strength below 1'),
    (lambda g: g['ops'].append({'type': 'exposure', 'stops': 1}), 'exactly one ASC CDL'),
    (lambda g: g.update(ops=[{'type': 'curves', 'master': [[0, 0], [1, 1]]}]), 'exactly one ASC CDL'),
])
def test_grades_color_balance_cannot_express_are_refused(change, reason):
    value = copy.deepcopy(WARM)
    change(value)
    with pytest.raises(ValueError, match='BLENDER_GRADE_NOT_REPRESENTABLE: .*' + reason):
        cb.grade_to_settings(value)


@pytest.mark.parametrize('change,error', [
    (lambda g: g['ops'][0].update(offset=[1.5, 0, 0]), 'VALUE_OUT_OF_RANGE: offset'),
    (lambda g: g['ops'][0].update(power=[0, 1, 1]), 'VALUE_OUT_OF_RANGE: power'),
    (lambda g: g.update(interpretation='linear'), 'GRADE_INTERPRETATION_UNSUPPORTED'),
    (lambda g: g.update(id='a#b'), 'GRADE_ID_INVALID'),
    (lambda g: g['ops'][0].update(extra=1), 'CDL_FIELDS_INVALID'),
    (lambda g: g['ops'][0].update(slope=[1, True, 1]), 'INVALID_NUMBER'),
])
def test_grade_validation(change, error):
    value = copy.deepcopy(WARM)
    change(value)
    with pytest.raises(ValueError, match=error):
        cb.grade_to_settings(value)


def test_color_multiply_and_zero_reciprocals_are_refused_on_read():
    settings = stored(cb.grade_to_settings(WARM))
    with pytest.raises(ValueError, match='color_multiply'):
        cb.settings_to_grade({**settings, 'color_multiply': 1.2}, 'g', 'srgb-sdr-display')
    with pytest.raises(ValueError, match='power must be above 0'):
        cb.settings_to_grade({**settings, 'power': [0.0, 1.0, 1.0]}, 'g', 'srgb-sdr-display')
    lgg = stored({'correction_method': 'LIFT_GAMMA_GAIN', 'lift': [1.0, 1.0, 1.0], 'gain': [3.0, 1.0, 1.0],
                  'gamma': [1.0] * 3, 'slope': [1.0] * 3, 'offset': [1.0] * 3, 'power': [1.0] * 3,
                  'invert_slope': False, 'invert_offset': False, 'invert_power': False, 'color_multiply': 1.0})
    assert cb.settings_to_grade(lgg, 'g', 'srgb-sdr-display')['ops'][0]['slope'] == [3.0, 1.0, 1.0]
    with pytest.raises(ValueError, match='BLENDER_VALUE_OUT_OF_RANGE: slope'):
        cb.settings_to_grade({**lgg, 'gain': [5.0, 1.0, 1.0]}, 'g', 'srgb-sdr-display')  # beyond the cdl bounds


def blender_lgg(settings, x):
    """Independent transcription of Blender's Lift/Gamma/Gain (sequencer modifier, 4.3 and 5.x)."""
    out = []
    for c in range(3):
        lift = 2.0 - settings['lift'][c]
        if settings['invert_lift']:
            if lift > 1.0:
                lift = (lift - 1.0) ** 2 + 1.0
            lift = 2.0 - lift
        gain = 1.0 / settings['gain'][c] if settings['invert_gain'] else settings['gain'][c]
        gamma = settings['gamma'][c] if settings['invert_gamma'] else 1.0 / settings['gamma'][c]
        v = max(((x[c] - 1.0) * lift + 1.0) * gain, 0.0) ** gamma
        out.append(min(max(v, 0.0), 1.0))
    return out


def runtime_evaluate(grade_value, points):
    np = pytest.importorskip('numpy')
    sys.path.insert(0, str(ROOT / 'runtime'))
    import color_grade_ops
    spec_value, luts = color_grade_ops.normalize(grade_value)
    return color_grade_ops.evaluate(spec_value, luts, np.array(points))


def test_offset_power_slope_equals_the_runtime_cdl_after_the_final_clamp():
    rng = random.Random(7)
    points = [[rng.random() for _ in range(3)] for _ in range(400)] + [[0, 0, 0], [1, 1, 1], [0.999, 0.001, 0.5]]
    for _ in range(25):
        value = grade(slope=[rng.uniform(0.2, 2.5) for _ in range(3)], offset=[rng.uniform(-0.3, 0.3) for _ in range(3)],
                      power=[rng.uniform(0.3, 3) for _ in range(3)])
        settings = cb.grade_to_settings(value)
        expected = runtime_evaluate(value, points)
        for p, e in zip(points, expected):
            got = [min(max(v, 0.0), 1.0) for v in cb.blender_reference(settings, p)]
            assert got == pytest.approx(list(e), abs=1e-6)  # Blender stores and computes in float32


@pytest.mark.parametrize('inverts', [(False, False, False), (True, True, True), (True, False, True)])
def test_lift_gamma_gain_reads_back_as_an_equivalent_cdl(inverts):
    rng = random.Random(11)
    points = [[rng.random() for _ in range(3)] for _ in range(300)]
    for _ in range(15):
        settings = stored({'correction_method': 'LIFT_GAMMA_GAIN', 'lift': [rng.uniform(0.85, 1.15) for _ in range(3)],
                           'gamma': [rng.uniform(0.6, 1.6) for _ in range(3)], 'gain': [rng.uniform(0.7, 1.4) for _ in range(3)],
                           'invert_lift': inverts[0], 'invert_gamma': inverts[1], 'invert_gain': inverts[2],
                           'slope': [1.0] * 3, 'offset': [1.0] * 3, 'power': [1.0] * 3, 'invert_slope': False,
                           'invert_offset': False, 'invert_power': False, 'color_multiply': 1.0})
        value = cb.settings_to_grade(settings, 'lgg', 'bt709-sdr-display')
        expected = runtime_evaluate(value, points)
        for p, e in zip(points, expected):
            assert blender_lgg(settings, p) == pytest.approx(list(e), abs=1e-6)  # float32 storage


# --- stub host: argument and state rules, not Blender behaviour ---------------------------

class Mods(list):
    def new(self, name, type):
        cbd = NS(correction_method='LIFT_GAMMA_GAIN', **{k: [1.0] * 3 for k in ('lift', 'gamma', 'gain', 'slope', 'offset', 'power')},
                 **{'invert_' + k: False for k in ('lift', 'gamma', 'gain', 'slope', 'offset', 'power')})
        m = NS(name=name, type=type, mute=False, input_mask_strip=None, input_mask_id=None, color_balance=cbd, color_multiply=1.0)
        self.append(m)
        return m


class Strip(dict):
    def __init__(self, sid, kind='MOVIE'):
        super().__init__(reel_instance_id=sid)
        self.type, self.modifiers = kind, Mods()
        self.colorspace_settings, self.use_linear_modifiers = NS(name='sRGB'), False
        self.color_multiply = self.color_saturation = 1.0


class Scene(dict):
    def __init__(self, strips):
        super().__init__(reel_adapter='experimental-blender-cut/1')
        self.animation_data = None
        self.sequencer_colorspace_settings = NS(name='sRGB')
        self.view_settings = NS(view_transform='Standard', look='None', exposure=0, gamma=1, use_curve_mapping=False)
        self.sequence_editor = NS(sequences_all=strips, strips_all=strips)


def host(version=(4, 3, 2), strips=None):
    strips = strips if strips is not None else [Strip('one'), Strip('two'), Strip('voice', 'SOUND')]
    saved = []
    save = lambda filepath, **kw: (saved.append(kw), Path(filepath).write_bytes(b'blend'))  # noqa: E731
    return NS(app=NS(version=version), context=NS(scene=Scene(strips)), ops=NS(wm=NS(save_as_mainfile=save)), saved=saved)


def test_stub_apply_then_read(tmp_path):
    bpy = host()
    result = cb.apply_grades(bpy, {'one': WARM}, tmp_path / 'graded.blend')
    assert (tmp_path / 'graded.blend').exists() and bpy.saved == [{'check_existing': True, 'copy': True}]
    one = bpy.context.scene.sequence_editor.sequences_all[0]
    assert one.modifiers[0].color_balance.correction_method == 'OFFSET_POWER_SLOPE' and 'reel_grade_sha256' in one
    assert result['strips']['one']['grade_id'] == 'warm'
    read = cb.read_grades(bpy, 'srgb-sdr-display')
    assert read['grades']['one']['grade']['ops'][0]['power'] == [0.9, 1.0, 1.2] and read['ungraded_strips'] == ['two']


@pytest.mark.parametrize('setup,call,error', [
    (lambda b: None, lambda b, p: cb.apply_grades(b, {'missing': WARM}, p), 'HOST_STRIP_MISSING'),
    (lambda b: b.context.scene.sequence_editor.sequences_all[0].modifiers.new('x', 'CURVES'),
     lambda b, p: cb.apply_grades(b, {'one': WARM}, p), 'HOST_MODIFIER_PRESENT'),
    (lambda b: setattr(b.app, 'version', (4, 2, 0)), lambda b, p: cb.apply_grades(b, {'one': WARM}, p), 'HOST_VERSION_UNSUPPORTED'),
    (lambda b: b.context.scene.pop('reel_adapter'), lambda b, p: cb.read_grades(b, 'srgb-sdr-display'), 'HOST_ADAPTER_BINDING'),
    (lambda b: setattr(b.context.scene, 'animation_data', object()), lambda b, p: cb.read_grades(b, 'srgb-sdr-display'),
     'HOST_ANIMATION_UNSUPPORTED'),
    (lambda b: setattr(b.context.scene.sequencer_colorspace_settings, 'name', 'Linear Rec.709'),
     lambda b, p: cb.read_grades(b, 'srgb-sdr-display'), 'HOST_COLOR_PROCESSING'),
    (lambda b: setattr(b.context.scene.sequence_editor.sequences_all[0], 'use_linear_modifiers', True),
     lambda b, p: cb.read_grades(b, 'srgb-sdr-display'), 'HOST_LINEAR_MODIFIERS_UNSUPPORTED'),
    (lambda b: b.context.scene.sequence_editor.sequences_all[0].modifiers.new('x', 'CURVES'),
     lambda b, p: cb.read_grades(b, 'srgb-sdr-display'), 'HOST_MODIFIER_UNSUPPORTED: one CURVES'),
    (lambda b: [b.context.scene.sequence_editor.sequences_all[0].modifiers.new('x', 'COLOR_BALANCE') for _ in range(2)],
     lambda b, p: cb.read_grades(b, 'srgb-sdr-display'), 'HOST_MODIFIER_STACK_UNSUPPORTED'),
    (lambda b: setattr(b.context.scene.sequence_editor.sequences_all[0].modifiers.new('x', 'COLOR_BALANCE'),
                       'input_mask_strip', object()), lambda b, p: cb.read_grades(b, 'srgb-sdr-display'),
     'HOST_MODIFIER_MASK_UNSUPPORTED'),
    (lambda b: setattr(b.context.scene.sequence_editor.sequences_all[0].modifiers.new('x', 'COLOR_BALANCE'), 'mute', True),
     lambda b, p: cb.read_grades(b, 'srgb-sdr-display'), 'HOST_MODIFIER_DISABLED'),
])
def test_stub_host_rules(tmp_path, setup, call, error):
    bpy = host()
    setup(bpy)
    with pytest.raises(ValueError, match=error):
        call(bpy, tmp_path / 'out.blend')
    assert not (tmp_path / 'out.blend').exists()


def test_stub_apply_validates_every_grade_before_changing_the_host(tmp_path):
    bpy = host()
    with pytest.raises(ValueError, match='BLENDER_GRADE_NOT_REPRESENTABLE'):
        cb.apply_grades(bpy, {'one': WARM, 'two': grade(saturation=0.8)}, tmp_path / 'out.blend')
    assert all(not s.modifiers for s in bpy.context.scene.sequence_editor.sequences_all)


def test_stub_apply_refuses_an_existing_output(tmp_path):
    (tmp_path / 'out.blend').write_bytes(b'x')
    with pytest.raises(ValueError, match='OUTPUT_UNSAFE_OR_EXISTS'):
        cb.apply_grades(host(), {'one': WARM}, tmp_path / 'out.blend')


def test_cli_assignments_schema(tmp_path):
    path = tmp_path / 'a.json'
    path.write_text(json.dumps({'schema': cb.ASSIGNMENTS_SCHEMA, 'grades': {'one': WARM}}))
    assert cb.read_assignments(path)[0] == {'one': WARM}
    path.write_text('{"schema": "x", "schema": "y"}')
    with pytest.raises(ValueError, match='DUPLICATE_JSON_KEY'):
        cb.read_assignments(path)


def test_small_offsets_keep_their_effect_on_read():
    """A tiny offset under a low power lifts black visibly; read-back must not round it away."""
    # Set in Blender's UI (apply itself refuses this grade: float32 storage moves its output, see below).
    settings = stored({'correction_method': 'OFFSET_POWER_SLOPE', 'slope': [1.0] * 3, 'offset': [1.0000004, 1.0, 1.0],
                       'power': [10.0, 1.0, 1.0], 'invert_slope': False, 'invert_offset': False, 'invert_power': False,
                       'color_multiply': 1.0})
    value = cb.settings_to_grade(settings, 'tiny', 'srgb-sdr-display')
    # 1.0000004 is stored in float32 as 1 + 3.5762787e-07, which is the offset Blender applies.
    assert value['ops'][0]['offset'] == [3.5762787e-07, 0.0, 0.0] and value['ops'][0]['power'] == [0.1, 1.0, 1.0]
    black = cb.blender_reference(settings, [0.0, 0.0, 0.0])[0]
    assert black * 255 == pytest.approx(57.8, abs=0.1)  # Blender lifts black to about 58/255
    assert runtime_evaluate(value, [[0.0, 0.0, 0.0]])[0][0] == pytest.approx(black, abs=1e-6)


def test_read_back_values_apply_again_to_the_same_effect():
    """Slope and offset come back to the identical float32; power is stored as a reciprocal, so it may move one ulp."""
    rng = random.Random(3)
    checked = 0
    for _ in range(200):
        value = grade(slope=[round(rng.uniform(0.2, 2.5), rng.randint(1, 8)) for _ in range(3)],
                      offset=[rng.uniform(-0.3, 0.3) * 10 ** -rng.randint(0, 7) for _ in range(3)],
                      power=[round(rng.uniform(0.3, 3), rng.randint(1, 8)) for _ in range(3)])
        try:
            first = stored(cb.grade_to_settings(value))
        except ValueError as error:  # tiny offsets that float32 cannot store are refused on apply
            assert 'BLENDER_STORAGE_CHANGES_GRADE' in str(error)
            continue
        checked += 1
        again = stored(cb.grade_to_settings(cb.settings_to_grade(first, 'g', 'srgb-sdr-display')))
        before, after = cb.effective_cdl(first), cb.effective_cdl(again)
        assert after[0] == before[0] and after[1] == before[1]
        assert after[2] == pytest.approx(before[2], rel=2.4e-7)
    assert checked >= 100


@pytest.mark.parametrize('strip_id,expected', [
    ('one', 'blender-one'),
    ('shot#1', None),  # '#' starts a comment in .cube titles
    ('x' * 120, None),  # 'blender-' + 120 characters is over the 120-character limit
    ('say "hi"', None),
])
def test_grade_ids_are_compilable_for_any_instance_id(strip_id, expected):
    grade_id = cb.grade_id_for(strip_id)
    assert cb.valid_id(grade_id) and (grade_id == expected if expected else len(grade_id) == len('blender-') + 16)
    np = pytest.importorskip('numpy')  # noqa: F841 - color_grade_ops needs numpy
    sys.path.insert(0, str(ROOT / 'runtime'))
    import color_grade_ops
    color_grade_ops.normalize({**WARM, 'id': grade_id})


def test_stub_read_uses_safe_grade_ids(tmp_path):
    bpy = host(strips=[Strip('shot#1'), Strip('two')])
    cb.apply_grades(bpy, {'shot#1': WARM}, tmp_path / 'graded.blend')
    row = cb.read_grades(bpy, 'srgb-sdr-display')['grades']['shot#1']
    assert row['grade']['id'] == cb.grade_id_for('shot#1') and '#' not in row['grade']['id']


@pytest.mark.parametrize('offset,power,accepted', [
    (4e-8, 0.1, False),  # 1 + 4e-8 stores as exactly 1: black would drop from about 46/255 to 0
    (-4e-8, 0.1, True),  # the offset is clamped away at black anyway
    (1e-5, 0.1, True),  # stored as 1.0000100136: the output moves by about 4e-5
    (0.02, 0.9, True),
])
def test_float32_storage_that_changes_the_output_is_refused(offset, power, accepted):
    value = grade(slope=[1.0] * 3, offset=[offset, 0.0, 0.0], power=[power, 1.0, 1.0])
    if accepted:
        settings = cb.grade_to_settings(value)
        assert cb.output_difference(cb.validate_grade(value), stored(settings)) <= cb.OUTPUT_TOLERANCE
    else:
        with pytest.raises(ValueError, match='BLENDER_STORAGE_CHANGES_GRADE'):
            cb.grade_to_settings(value)
        assert (4e-8) ** 0.1 * 255 == pytest.approx(46.4, abs=0.1)


def test_stub_apply_refuses_storage_loss_before_changing_the_host(tmp_path):
    bpy = host()
    with pytest.raises(ValueError, match='BLENDER_STORAGE_CHANGES_GRADE'):
        cb.apply_grades(bpy, {'one': grade(slope=[1.0] * 3, offset=[4e-8, 0.0, 0.0], power=[0.1, 1.0, 1.0])},
                        tmp_path / 'out.blend')
    assert all(not s.modifiers for s in bpy.context.scene.sequence_editor.sequences_all)
    result = cb.apply_grades(bpy, {'one': WARM}, tmp_path / 'ok.blend')
    assert result['strips']['one']['max_output_difference'] <= cb.OUTPUT_TOLERANCE


@pytest.mark.parametrize('offset', [
    -0.501960793999176,  # black point just above code 128: storage moves it below, so code 128 jumps to 45/255
    -128 / 255,  # black point exactly on code 128
])
def test_storage_that_moves_a_low_power_black_point_across_a_code_level_is_refused(offset):
    value = grade(slope=[1.0] * 3, offset=[offset, 0.0, 0.0], power=[0.1, 1.0, 1.0])
    settings = stored({**{k: v for k, v in cb.grade_to_settings(grade()).items()},
                       'offset': [offset + 1, 1.0, 1.0], 'power': [10.0, 1.0, 1.0], 'slope': [1.0, 1.0, 1.0]})
    s, o, p = cb.effective_cdl(settings)
    x = 128 / 255
    moved = abs(max(x + offset, 0) ** 0.1 - max(x * s[0] + o[0], 0) ** p[0])
    if moved > cb.OUTPUT_TOLERANCE:
        with pytest.raises(ValueError, match='BLENDER_STORAGE_CHANGES_GRADE'):
            cb.grade_to_settings(value)
    else:  # storage kept the black point on the same side of every code level
        cb.grade_to_settings(value)
    assert offset != -0.501960793999176 or moved > 0.17  # the reported case: about 45 8-bit code values


def test_threshold_levels_cover_every_depth_near_the_threshold():
    levels = cb._threshold_levels([128 / 255])
    assert 128 / 255 in levels and 513 / 1023 in levels and 2056 / 4095 in levels and 32896 / 65535 in levels
    assert all(abs(v - 128 / 255) <= cb.THRESHOLD_WINDOW + 1 / 255 for v in levels)
