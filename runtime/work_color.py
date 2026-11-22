"""WorkDocument color section (work-color/1): declared inputs, ordered grades, clip targets.

Grades are explicit parameters; this module chooses no look and judges nothing.
Rendering compiles each grade with color-grade-compile and applies all of them
after the timeline (before audio mix, visual layers and captions) with
color-lut-apply layers, so captions and overlays are never graded. Then
color-consistency-check compares the timeline and the graded picture; optional
caller-declared protections and limits turn that comparison into a gate. An
optional texture (film-texture-apply effects) acts on the whole graded picture
after that gate, still before audio mix, visual layers and captions.
"""
from fractions import Fraction

SCHEMA = 'work-color/1'
SPACES = ('bt709-sdr', 'srgb-sdr')
SPACE_INTERPRETATION = {'bt709-sdr': 'bt709-sdr-display', 'srgb-sdr': 'srgb-sdr-display'}
MAX_GRADES = 16
MAX_CHECK_FRAMES = 512
TEXTURE_READBACK_CLIPS = 4


def lut_references(document):
    """External cube files referenced by grade ops (render resources for source binding)."""
    color = document.get('color')
    refs = []
    if isinstance(color, dict) and isinstance(color.get('grades'), dict):
        for grade in color['grades'].values():
            for op in (grade.get('ops') if isinstance(grade, dict) and isinstance(grade.get('ops'), list) else []):
                if isinstance(op, dict) and op.get('type') == 'lut' and isinstance(op.get('source'), dict):
                    refs.append(op['source'])
    return refs


def _check_input(sid, declared, media):
    from editing_runtime import exact_keys, require
    from color_ops import SPACE_TRANSFER
    exact_keys(declared, ['space', 'range', 'basis'], ['space', 'range', 'basis'])
    require(declared['space'] in SPACES, 'WORK_COLOR_SPACE_UNSUPPORTED: ' + sid)
    require(declared['range'] in ('limited', 'full'), 'WORK_COLOR_RANGE_REQUIRED: ' + sid)
    require(declared['basis'] in ('verified-metadata', 'caller-declared'), 'WORK_COLOR_BASIS_REQUIRED: ' + sid)
    video = next((s for s in media['streams'] if s.get('codec_type') == 'video'), None)
    require(video is not None, 'VIDEO_STREAM_REQUIRED: ' + sid)
    require(video.get('color_transfer') not in ('arib-std-b67', 'smpte2084'), 'WORK_COLOR_HDR_SOURCE_UNSUPPORTED: %s; convert it first with color-input-transform' % sid)
    expected = {'color_space': 'bt709', 'color_primaries': 'bt709', 'color_transfer': SPACE_TRANSFER[declared['space']],
                'color_range': 'tv' if declared['range'] == 'limited' else 'pc'}
    unknown = (None, 'unknown', 'unspecified')
    for key, value in expected.items():
        observed = video.get(key)
        require(observed in unknown or observed == value, 'WORK_COLOR_METADATA_CONFLICT: %s.%s' % (sid, key))
        if declared['basis'] == 'verified-metadata':
            require(observed == value, 'WORK_COLOR_METADATA_REQUIRED: %s.%s' % (sid, key))


def frame_ranges(norm, clip_ids):
    """Merged [start, end) output frame ranges of the given clips, in output order."""
    ranges = []
    for clip in norm['clips']:
        if clip['id'] not in clip_ids:
            continue
        a, b = clip['output_start_frame'], clip['output_end_frame']
        if ranges and ranges[-1][1] == a:
            ranges[-1][1] = b
        else:
            ranges.append([a, b])
    return ranges


def target_clips(grade, norm):
    return [c['id'] for c in norm['clips']] if grade['targets'] == '*' else list(grade['targets'])


def coverage(norm, clip_ids):
    """Source content a grade covers, keyed by clip; a change means the graded picture is new material.

    Keyed by clip ID, not timeline order: moving covered clips is not new material,
    while adding, removing or changing a covered clip is.
    """
    return {c['id']: (c['source_id'], norm['sources'][c['source_id']]['sha256'], round(c['start'], 8),
                      round(c['effective_source_end'], 8), str(Fraction(c['speed'])))
            for c in norm['clips'] if c['id'] in clip_ids}


def validate(doc, norm, tools):
    """Validate doc['color'] against the normalized plan; return grades in application order."""
    from editing_runtime import exact_keys, require
    from color_grade_ops import normalize, LUT_SIZES
    color = doc['color']
    exact_keys(color, ['schema', 'inputs', 'grades', 'order', 'protections', 'limits', 'texture'],
               ['schema', 'inputs', 'grades', 'order'])
    require(color['schema'] == SCHEMA, 'WORK_COLOR_SCHEMA_UNSUPPORTED')
    require(isinstance(color['inputs'], dict) and isinstance(color['grades'], dict), 'WORK_COLOR_ID_MAP_REQUIRED')
    require(len(color['grades']) <= MAX_GRADES, 'WORK_COLOR_TOO_MANY_GRADES')
    sources = norm['sources']
    for sid, declared in color['inputs'].items():
        require(sid in sources, 'WORK_COLOR_INPUT_UNKNOWN_SOURCE: ' + str(sid))
        _check_input(sid, declared, sources[sid]['media'])
    order = color['order']
    require(isinstance(order, list) and len(set(order)) == len(order) and set(order) == set(color['grades']),
            'WORK_COLOR_ORDER_MUST_LIST_EVERY_GRADE_ONCE')
    clips = {c['id']: c for c in norm['clips']}
    planned = []
    for gid in order:
        grade = color['grades'][gid]
        exact_keys(grade, ['targets', 'interpretation', 'ops', 'strength', 'lut_size'],
                   ['targets', 'interpretation', 'ops', 'lut_size'])
        targets = grade['targets']
        require(targets == '*' or (isinstance(targets, list) and targets and len(set(targets)) == len(targets)
                                   and all(isinstance(t, str) for t in targets)), 'WORK_COLOR_TARGETS_INVALID: ' + gid)
        require(targets == '*' or all(t in clips for t in targets), 'WORK_COLOR_TARGET_MISSING: ' + gid)
        require(grade['lut_size'] in LUT_SIZES and type(grade['lut_size']) is int, 'COLOR_GRADE_LUT_SIZE_UNSUPPORTED: ' + gid)
        spec = {'schema': 'color-grade/1', 'id': gid, 'interpretation': grade['interpretation'], 'ops': grade['ops']}
        if 'strength' in grade:
            spec['strength'] = grade['strength']
        normalized, _ = normalize(spec)
        ids = target_clips(grade, norm)
        for cid in ids:
            sid = clips[cid]['source_id']
            require(sid in color['inputs'], 'WORK_COLOR_INPUT_DECLARATION_REQUIRED: %s (clip %s)' % (sid, cid))
            require(SPACE_INTERPRETATION[color['inputs'][sid]['space']] == normalized['interpretation'],
                    'WORK_COLOR_INTERPRETATION_MISMATCH: grade %s, clip %s' % (gid, cid))
        planned.append({'id': gid, 'spec': spec, 'lut_size': grade['lut_size'], 'clip_ids': ids,
                        'ranges': frame_ranges(norm, set(ids))})
    _checks(color, norm)
    texture_plan(doc, norm)
    return planned


def pipeline_space(doc, norm, tag):
    """Space the picture steps declare for the timeline output, from its transfer tag.

    The timeline inherits its first frames' tag. When that tag is missing, one space
    declared for every clip is the best evidence; otherwise BT.709 as before.
    """
    if tag == 'iec61966-2-1':
        return 'srgb-sdr'
    if tag == 'bt709':
        return 'bt709-sdr'
    inputs = doc['color']['inputs']
    spaces = {inputs[c['source_id']]['space'] if c['source_id'] in inputs else None for c in norm['clips']}
    return next(iter(spaces)) if len(spaces) == 1 and None not in spaces else 'bt709-sdr'


def texture_plan(doc, norm):
    """film-texture-apply effects, space and readback frames for the whole picture, or None.

    The texture covers every clip, so every clip's source needs a declared input and all
    of them must share one space: halation and vignette are computed in that space's linear light.
    """
    from editing_runtime import exact_keys, require
    from texture_ops import _validate
    color = doc.get('color') or {}
    if 'texture' not in color:
        return None
    texture = color['texture']
    exact_keys(texture, ['effects'], ['effects'])
    effects = _validate(texture['effects'])
    spaces = set()
    for clip in norm['clips']:
        declared = color['inputs'].get(clip['source_id'])
        require(declared is not None, 'WORK_TEXTURE_INPUT_DECLARATION_REQUIRED: %s (clip %s)' % (clip['source_id'], clip['id']))
        spaces.add(declared['space'])
    require(len(spaces) == 1, 'WORK_TEXTURE_SPACES_MIXED: %s' % ', '.join(sorted(spaces)))
    clips = norm['clips']
    count = min(TEXTURE_READBACK_CLIPS, len(clips))
    # Middle frames of up to four clips spread over the timeline; derived, so edits never leave stale frame numbers.
    picks = sorted({round(i * (len(clips) - 1) / (count - 1)) for i in range(count)} if count > 1 else {0})
    frames = sorted({(clips[i]['output_start_frame'] + clips[i]['output_end_frame'] - 1) // 2 for i in picks})
    return {'effects': effects, 'space': spaces.pop(), 'readback_frames': frames,
            'readback_clip_ids': [clips[i]['id'] for i in picks]}


def _checks(color, norm):
    """Validate optional protections and limits; return (protections keyed to clip IDs, limits)."""
    from editing_runtime import exact_keys, require
    from color_check_ops import _protections, _limits
    clips = {c['id']: c for c in norm['clips']}
    value = color.get('protections', {})
    require(isinstance(value, dict), 'WORK_COLOR_PROTECTIONS_INVALID')
    shaped = {}
    for pid, spec in value.items():
        require(isinstance(spec, dict) and 'targets' in spec, 'WORK_COLOR_PROTECTION_TARGETS_REQUIRED: ' + str(pid))
        exact_keys(spec, ['kind', 'targets', 'hue_degrees', 'min_chroma', 'box', 'max_median_delta_e2000', 'action'])
        targets = spec['targets']
        require(targets == '*' or (isinstance(targets, list) and targets and len(set(targets)) == len(targets)
                                   and all(isinstance(t, str) for t in targets)), 'WORK_COLOR_TARGETS_INVALID: ' + pid)
        require(targets == '*' or all(t in clips for t in targets), 'WORK_COLOR_TARGET_MISSING: ' + pid)
        ids = [c['id'] for c in norm['clips']] if targets == '*' else list(targets)
        for cid in ids:
            sid = clips[cid]['source_id']
            require(sid in color['inputs'], 'WORK_COLOR_INPUT_DECLARATION_REQUIRED: %s (clip %s)' % (sid, cid))
        shaped[pid] = {**{k: v for k, v in spec.items() if k != 'targets'}, 'segments': ids}
    protections = _protections(shaped, set(clips))
    limits = _limits(color['limits']) if 'limits' in color else {}
    return protections, limits


def check_request(doc, norm, reference, candidate, space):
    """color-consistency-check request for the graded picture: one segment per clip with a declared input."""
    from editing_runtime import require
    color = doc['color']
    protections, limits = _checks(color, norm)
    segments = []
    for c in norm['clips']:
        declared = color['inputs'].get(c['source_id'])
        if declared is not None:
            (a, b), = frame_ranges(norm, {c['id']})
            segments.append({'id': c['id'], 'start_frame': a, 'end_frame': b, 'space': declared['space']})
    require(segments and len(segments) * 2 <= MAX_CHECK_FRAMES, 'WORK_COLOR_CHECK_SEGMENTS_UNSUPPORTED: %d clips' % len(segments))
    samples = max(1, min(3, MAX_CHECK_FRAMES // (2 * len(segments))))
    request = {'operation': 'color-consistency-check', 'reference': reference, 'candidate': candidate,
               'input_color': {'space': space, 'range': 'limited', 'basis': 'caller-declared'},
               'segments': segments, 'samples_per_segment': samples}
    if protections:
        request['protections'] = protections
    if limits:
        request['limits'] = limits
    return request


def revision_changes(base, candidate, scope, old_norm, new_norm):
    """Scope checks for color edits and for picture changes under existing grades."""
    from editing_runtime import require
    old, new = base.get('color'), candidate.get('color')
    old_grades = old['grades'] if old else {}
    new_grades = new['grades'] if new else {}
    changed = sorted(g for g in set(old_grades) | set(new_grades)
                     if g not in old_grades or g not in new_grades or old_grades[g] != new_grades[g])
    require(set(changed) <= set(scope['grade_ids']), 'OUTSIDE_SCOPE: color.grades')
    inputs_changed = (old['inputs'] if old else {}) != (new['inputs'] if new else {})
    require(not inputs_changed or scope['color_inputs'], 'OUTSIDE_SCOPE: color.inputs')
    old_order, new_order = (old['order'] if old else []), (new['order'] if new else [])
    kept_old = [g for g in old_order if g in new_order]
    kept_new = [g for g in new_order if g in old_order]
    reordered = sorted(g for i, g in enumerate(kept_new) if kept_old[i] != g)
    require(set(reordered) <= set(scope['grade_ids']), 'OUTSIDE_SCOPE: color.order')
    # A grade that did not change still needs review when the picture it covers is new material.
    affected = sorted(g for g in set(old_grades) & set(new_grades) if g not in changed and
                      coverage(old_norm, set(target_clips(old_grades[g], old_norm))) !=
                      coverage(new_norm, set(target_clips(new_grades[g], new_norm))))
    require(set(affected) <= set(scope['grade_ids']), 'COLOR_REVIEW_SCOPE_REQUIRED')
    checks = [{k: (c or {}).get(k) for k in ('protections', 'limits')} for c in (old, new)]
    checks_changed = checks[0] != checks[1]
    require(not checks_changed or scope['color_checks'], 'OUTSIDE_SCOPE: color.protections or color.limits')
    texture_changed = (old or {}).get('texture') != (new or {}).get('texture')
    require(not texture_changed or scope['color_texture'], 'OUTSIDE_SCOPE: color.texture')
    return {'color_texture_changed': texture_changed,
            'color_textured': 'texture' in (old or {}) or 'texture' in (new or {}),
            'color_checks_changed': checks_changed, 'color_grades': changed, 'color_inputs_changed': inputs_changed, 'color_order_changed': bool(reordered) or
            ([g for g in old_order if g in new_order] != [g for g in new_order if g in old_order]),
            'color_revalidation_declared': affected}
