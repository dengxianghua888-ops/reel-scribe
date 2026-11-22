"""Experimental Blender Color Balance bridge for Reel color grades (Blender 4.3 and 5.3 series).

Apply: a color-grade/1 grade made of exactly one ASC CDL op (saturation 1, full strength)
becomes an Offset/Power/Slope Color Balance modifier on named movie strips of a project made
by blender_cut_import.py, saved to a NEW .blend.
Read:  Color Balance modifiers on movie strips, in either Offset/Power/Slope or Lift/Gamma/Gain
mode, read back as color-grade/1 grades with one cdl op.
Anything Color Balance cannot express exactly is rejected, never approximated.

Blender: -b --disable-autoexec PROJECT --python-exit-code 1 --python THIS -- apply ASSIGNMENTS.json NEW.blend
Blender: -b --disable-autoexec PROJECT --python-exit-code 1 --python THIS -- read INTERPRETATION NEW.json
No rendering, publication, GUI acceptance or cut changes; the opened project is never saved over.
"""
import hashlib
import json
import math
from pathlib import Path
import sys

SCHEMA = 'blender-color-balance/1'
ASSIGNMENTS_SCHEMA = 'blender-color-balance-assignments/1'
# Major/minor series -> strip collection. Color Balance math is the same in both (see the contract).
SUPPORTED_SERIES = {(4, 3): 'sequences_all', (5, 3): 'strips_all'}
INTERPRETATIONS = ('bt709-sdr-display', 'srgb-sdr-display')
# Same bounds as color-grade-compile's cdl op, so every read-back grade compiles.
LIMITS = {'slope': (0.0, 4.0), 'offset': (-1.0, 1.0), 'power': (0.1, 4.0)}
TOLERANCE = 1e-6  # Blender stores float32
MODIFIER_NAME = 'reel-grade'


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def unique(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, 'DUPLICATE_JSON_KEY')
        out[key] = value
    return out


def number(value, name):
    require(not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value), 'INVALID_NUMBER: ' + name)
    return float(value)


def triple(value, name):
    require(isinstance(value, (list, tuple)) and len(value) == 3, 'TRIPLE_REQUIRED: ' + name)
    return [number(v, name) for v in value]


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def validate_grade(grade):
    """A color-grade/1 grade Color Balance can carry exactly; returns its cdl op."""
    require(isinstance(grade, dict) and set(grade) <= {'schema', 'id', 'interpretation', 'ops', 'strength'}
            and {'schema', 'id', 'interpretation', 'ops'} <= set(grade), 'GRADE_FIELDS_INVALID')
    require(grade['schema'] == 'color-grade/1', 'GRADE_SCHEMA_UNSUPPORTED')
    require(isinstance(grade['id'], str) and grade['id'] and not set(grade['id']) & {'"', '\n', '\r', '#'}, 'GRADE_ID_INVALID')
    require(grade['interpretation'] in INTERPRETATIONS, 'GRADE_INTERPRETATION_UNSUPPORTED')
    reasons = []
    if 'strength' in grade and number(grade['strength'], 'strength') != 1:
        reasons.append('strength below 1 blends with the source')
    ops = grade['ops']
    require(isinstance(ops, list), 'GRADE_OPS_INVALID')
    if len(ops) != 1 or not isinstance(ops[0], dict) or ops[0].get('type') != 'cdl':
        reasons.append('Color Balance carries exactly one ASC CDL op; got %s'
                       % [op.get('type') if isinstance(op, dict) else None for op in ops])
    else:
        op = ops[0]
        require(set(op) == {'type', 'slope', 'offset', 'power', 'saturation'}, 'CDL_FIELDS_INVALID')
        if number(op['saturation'], 'saturation') != 1:
            reasons.append('Color Balance has no saturation stage')
    require(not reasons, 'BLENDER_GRADE_NOT_REPRESENTABLE: ' + '; '.join(reasons))
    op = {'type': 'cdl', 'slope': triple(ops[0]['slope'], 'slope'), 'offset': triple(ops[0]['offset'], 'offset'),
          'power': triple(ops[0]['power'], 'power'), 'saturation': 1.0}
    for name, (low, high) in LIMITS.items():
        require(all(low <= v <= high for v in op[name]), 'VALUE_OUT_OF_RANGE: ' + name)
    return op


def grade_to_settings(grade):
    """Offset/Power/Slope settings as Blender's UI stores them: offset is shifted by 1, power is inverted."""
    op = validate_grade(grade)
    return {'correction_method': 'OFFSET_POWER_SLOPE', 'slope': op['slope'], 'offset': [v + 1 for v in op['offset']],
            'power': [1 / v for v in op['power']], 'invert_slope': False, 'invert_offset': False,
            'invert_power': False, 'color_multiply': 1.0}


def _reciprocal(value, name):
    require(value > 0, 'VALUE_OUT_OF_RANGE: %s must be above 0' % name)  # 4.3 and 5.x treat 0 differently
    return 1 / value


def effective_cdl(settings):
    """Per-channel slope, offset and power that Blender applies, from either mode (Blender source semantics).

    Lift/Gamma/Gain computes ((x - 1) * lift + 1) * gain, clamps below 0 and raises to gamma:
    the same as an ASC CDL with slope = lift * gain, offset = (1 - lift) * gain, power = gamma.
    """
    method = settings['correction_method']
    require(abs(number(settings['color_multiply'], 'color_multiply') - 1) <= TOLERANCE,
            'BLENDER_SETTING_NOT_REPRESENTABLE: color_multiply scales after the power stage')
    slope, offset, power = [], [], []
    for c in range(3):
        if method == 'OFFSET_POWER_SLOPE':
            s = number(settings['slope'][c], 'slope')
            s = _reciprocal(s, 'slope') if settings['invert_slope'] else s
            o = number(settings['offset'][c], 'offset') - 1
            o = -o if settings['invert_offset'] else o
            p = number(settings['power'][c], 'power')
            p = p if settings['invert_power'] else _reciprocal(p, 'power')
        else:
            require(method == 'LIFT_GAMMA_GAIN', 'BLENDER_METHOD_UNSUPPORTED: %s' % method)
            lift = 2 - number(settings['lift'][c], 'lift')
            if settings['invert_lift']:
                if lift > 1:
                    lift = (lift - 1) ** 2 + 1
                lift = 2 - lift
            gain = number(settings['gain'][c], 'gain')
            gain = _reciprocal(gain, 'gain') if settings['invert_gain'] else gain
            gamma = number(settings['gamma'][c], 'gamma')
            gamma = gamma if settings['invert_gamma'] else _reciprocal(gamma, 'gamma')
            s, o, p = lift * gain, (1 - lift) * gain, gamma
        slope.append(s); offset.append(o); power.append(p)
    return slope, offset, power


def settings_to_grade(settings, grade_id, interpretation):
    """color-grade/1 grade with one cdl op; values rounded to 1e-6 (float32 storage)."""
    require(interpretation in INTERPRETATIONS, 'GRADE_INTERPRETATION_UNSUPPORTED')
    slope, offset, power = effective_cdl(settings)
    op = {'type': 'cdl', 'slope': [round(v, 6) for v in slope], 'offset': [round(v, 6) for v in offset],
          'power': [round(v, 6) for v in power], 'saturation': 1.0}
    for name, (low, high) in LIMITS.items():
        require(all(low <= v <= high for v in op[name]), 'BLENDER_VALUE_OUT_OF_RANGE: %s %s' % (name, op[name]))
    grade = {'schema': 'color-grade/1', 'id': grade_id, 'interpretation': interpretation, 'ops': [op]}
    validate_grade(grade)
    return grade


def blender_reference(settings, x):
    """Blender's float-path Color Balance on one channel triple (reference for tests and checks)."""
    slope, offset, power = effective_cdl(settings)
    return [max(x[c] * slope[c] + offset[c], 0.0) ** power[c] for c in range(3)]


# --- host side --------------------------------------------------------------------------

def series(bpy):
    version = tuple(bpy.app.version)
    require(version[:2] in SUPPORTED_SERIES, 'HOST_VERSION_UNSUPPORTED: %s' % (version,))
    return version


def scene_strips(bpy):
    """Movie strips of a scene made by blender_cut_import, keyed by Reel instance id."""
    version = series(bpy)
    scene = bpy.context.scene
    require(scene.get('reel_adapter') == 'experimental-blender-cut/1', 'HOST_ADAPTER_BINDING')
    # Keyframed modifier values would change the grade over time; the bridge reads one static grade.
    require(not scene.animation_data, 'HOST_ANIMATION_UNSUPPORTED')
    require(scene.sequencer_colorspace_settings.name == 'sRGB' and scene.view_settings.view_transform == 'Standard'
            and scene.view_settings.look == 'None' and scene.view_settings.exposure == 0
            and scene.view_settings.gamma == 1 and not scene.view_settings.use_curve_mapping, 'HOST_COLOR_PROCESSING')
    seq = scene.sequence_editor
    require(seq is not None, 'HOST_SEQUENCE_REQUIRED')
    strips = {}
    for strip in getattr(seq, SUPPORTED_SERIES[version[:2]]):
        if strip.type != 'MOVIE':
            continue
        sid = strip.get('reel_instance_id')
        require(isinstance(sid, str) and sid and sid not in strips, 'HOST_STRIP_ID_INVALID')
        # Code values pass unchanged only when the strip and the sequencer share sRGB.
        require(strip.colorspace_settings.name == 'sRGB', 'HOST_SOURCE_COLOR_CHANGED: ' + sid)
        require(not getattr(strip, 'use_linear_modifiers', False), 'HOST_LINEAR_MODIFIERS_UNSUPPORTED: ' + sid)
        require(strip.color_multiply == 1 and strip.color_saturation == 1, 'HOST_STRIP_COLOR_UNSUPPORTED: ' + sid)
        strips[sid] = strip
    return version, strips


def modifier_settings(modifier):
    cb = modifier.color_balance
    keys = ('lift', 'gamma', 'gain', 'slope', 'offset', 'power')
    return {'correction_method': cb.correction_method, **{k: [float(v) for v in getattr(cb, k)] for k in keys},
            **{'invert_' + k: bool(getattr(cb, 'invert_' + k)) for k in keys}, 'color_multiply': float(modifier.color_multiply)}


def _plain_modifier(modifier, sid):
    require(modifier.type == 'COLOR_BALANCE', 'HOST_MODIFIER_UNSUPPORTED: %s %s' % (sid, modifier.type))
    require(not modifier.mute and getattr(modifier, 'enable', True), 'HOST_MODIFIER_DISABLED: ' + sid)
    require(modifier.input_mask_strip is None and modifier.input_mask_id is None, 'HOST_MODIFIER_MASK_UNSUPPORTED: ' + sid)


def read_grades(bpy, interpretation):
    version, strips = scene_strips(bpy)
    rows = {}
    for sid, strip in sorted(strips.items()):
        mods = list(strip.modifiers)
        if not mods:
            continue
        require(len(mods) == 1, 'HOST_MODIFIER_STACK_UNSUPPORTED: ' + sid)
        _plain_modifier(mods[0], sid)
        settings = modifier_settings(mods[0])
        rows[sid] = {'mode': settings['correction_method'], 'blender_settings': settings,
                     'grade': settings_to_grade(settings, 'blender-' + sid, interpretation)}
    return {'schema': SCHEMA, 'direction': 'read', 'host_version': list(version), 'interpretation': interpretation,
            'grades': rows, 'ungraded_strips': sorted(set(strips) - set(rows)),
            'limits': ['Only Color Balance modifiers are read; any other modifier, a stack or a mask is rejected.',
                       'Grades describe the strip code values in the sRGB sequencer space; no render is checked here.']}


def read_assignments(path):
    raw = Path(path).read_bytes()
    data = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(data, dict) and set(data) == {'schema', 'grades'} and data['schema'] == ASSIGNMENTS_SCHEMA,
            'ASSIGNMENTS_SCHEMA_UNSUPPORTED')
    require(isinstance(data['grades'], dict) and data['grades'], 'ASSIGNMENTS_EMPTY')
    return data['grades'], hashlib.sha256(raw).hexdigest()


def apply_grades(bpy, grades, output):
    """Validate every grade and strip before the first host change, then save a new project."""
    output = Path(output).absolute()
    require(output.suffix == '.blend' and output.parent.is_dir() and not output.exists() and not output.is_symlink(),
            'OUTPUT_UNSAFE_OR_EXISTS')
    version, strips = scene_strips(bpy)
    planned = {}
    for sid, grade in grades.items():
        require(sid in strips, 'HOST_STRIP_MISSING: %s' % sid)
        require(not list(strips[sid].modifiers), 'HOST_MODIFIER_PRESENT: %s' % sid)
        planned[sid] = grade_to_settings(grade)
    rows = {}
    for sid, settings in planned.items():
        modifier = strips[sid].modifiers.new(name=MODIFIER_NAME, type='COLOR_BALANCE')
        cb = modifier.color_balance
        cb.correction_method = settings['correction_method']
        for key in ('slope', 'offset', 'power'):
            setattr(cb, key, settings[key])
        for key in ('invert_slope', 'invert_offset', 'invert_power'):
            setattr(cb, key, settings[key])
        modifier.color_multiply = settings['color_multiply']
        _plain_modifier(modifier, sid)
        stored = modifier_settings(modifier)
        expected = validate_grade(grades[sid])
        effective = effective_cdl(stored)
        for index, name in enumerate(('slope', 'offset', 'power')):
            require(all(abs(a - b) <= TOLERANCE * max(1, abs(b)) for a, b in zip(effective[index], expected[name])),
                    'HOST_READBACK_MISMATCH: %s %s' % (sid, name))
        strips[sid]['reel_grade_sha256'] = hashlib.sha256(canonical(grades[sid]).encode()).hexdigest()
        rows[sid] = {'grade_id': grades[sid]['id'], 'blender_settings': stored}
    require(not output.exists(), 'OUTPUT_EXISTS')
    bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=True, copy=True)
    return {'schema': SCHEMA, 'direction': 'apply', 'host_version': list(version), 'output': str(output),
            'strips': rows, 'limits': ['Saved as a copy; the opened project is unchanged on disk.',
                                       'No render is checked here; see the contract for the verified host runs.']}


def main(argv, bpy):
    require(argv and argv[0] in ('apply', 'read'), 'EXPECTED_APPLY_OR_READ')
    if argv[0] == 'apply':
        require(len(argv) == 3, 'EXPECTED_ASSIGNMENTS_AND_OUTPUT')
        grades, digest = read_assignments(argv[1])
        result = apply_grades(bpy, grades, argv[2])
        result['assignments_sha256'] = digest
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return result
    require(len(argv) == 3, 'EXPECTED_INTERPRETATION_AND_OUTPUT')
    output = Path(argv[2]).absolute()
    require(output.suffix == '.json' and output.parent.is_dir() and not output.exists(), 'OUTPUT_UNSAFE_OR_EXISTS')
    result = read_grades(bpy, argv[1])
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True), encoding='utf-8')
    return result


if __name__ == '__main__':
    import bpy
    main(sys.argv[sys.argv.index('--') + 1:], bpy)
