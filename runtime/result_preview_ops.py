"""Explicit later-result preview, not result discovery or causal/quality certification."""
import copy
from fractions import Fraction
from pathlib import Path


def protection_shift(base, candidate, duration, directory, tools):
    """Ordinary declared-range proof; never promotes preview to an occurrence."""
    from editing_runtime import require, fingerprint, write_json
    from work_ops import validate_document
    from evidence_ops import compile_evidence
    require(candidate.get('evidence_protection') == base['evidence_protection'],
            'RESULT_PREVIEW_PROTECTION_CHANGED')
    require(candidate['plan']['clips'][1:] == base['plan']['clips'] and
            candidate['plan']['sources'] == base['plan']['sources'],
            'RESULT_PREVIEW_ORIGINAL_CONTENT_CHANGED')
    declaration = base['evidence_protection']
    reports = []
    norms = []
    for doc in (base, candidate):
        normalized = validate_document(doc, tools)
        norms.append(normalized[0])
        reports.append(compile_evidence({'operation': 'evidence-plan-compile',
            'document': doc, 'expected_document_sha256': fingerprint(doc),
            **{k: declaration[k] for k in ('units', 'required_units', 'occurrences', 'chapters')}},
            None, tools, normalized_document=normalized, validation_mode='ordinary_protection'))
    old_norm, new_norm = norms
    require(old_norm['fps'] == new_norm['fps'], 'RESULT_PREVIEW_OUTPUT_CLOCK_CHANGED')
    frame_shift = duration * Fraction(old_norm['fps'])
    require(frame_shift.denominator == 1, 'RESULT_PREVIEW_FRAME_GRID_REQUIRED')
    new_clips = {c['id']: c for c in new_norm['clips']}
    for clip in old_norm['clips']:
        require(all(new_clips[clip['id']][k] - clip[k] == int(frame_shift)
                    for k in ('output_start_frame', 'output_end_frame')),
                'RESULT_PREVIEW_CLIP_FRAME_SHIFT_MISMATCH')
    before, after = reports
    old = {o['id']: o for o in before['occurrences']}
    new = {o['id']: o for o in after['occurrences']}
    require(old.keys() == new.keys(), 'RESULT_PREVIEW_OCCURRENCES_CHANGED')
    for oid, occurrence in old.items():
        shifted = new[oid]
        require(len(occurrence['parts']) == len(shifted['parts']), 'RESULT_PREVIEW_PARTS_CHANGED')
        for a, b in zip(occurrence['parts'], shifted['parts']):
            require(a['carrier'] == b['carrier'], 'RESULT_PREVIEW_CARRIER_CHANGED')
            ca, cb = a['clock_rational'], b['clock_rational']
            require(all(Fraction(ca[k]) == Fraction(cb[k]) for k in ('source_start', 'source_end', 'speed')),
                    'RESULT_PREVIEW_SOURCE_CLOCK_CHANGED')
            require(all(Fraction(cb[k]) == Fraction(ca[k]) + duration for k in ('output_start', 'output_end')),
                    'RESULT_PREVIEW_PROTECTION_SHIFT_MISMATCH')
    write_json(directory / 'base-protection-map.json', before)
    write_json(directory / 'candidate-protection-map.json', after)
    return {'status': 'DECLARED_SOURCE_RANGES_PRESERVED_WITH_EXPLICIT_SHIFT',
            'declaration_sha256': fingerprint(declaration),
            'candidate_document_sha256': fingerprint(candidate),
            'shift_rational': str(duration), 'original_carriers_preserved': True,
            'preview_registered_as_evidence': False, 'validation_mode': 'ordinary_protection',
            'source_complete': 'NOT_GRANTED', 'semantic_review': 'NOT_RUN', 'listening_review': 'NOT_RUN'}


def execute(request, directory, tools):
    from editing_runtime import exact_keys, require, fingerprint, source, span, write_json
    from work_ops import connect, load, validate_document, timeline_revise
    from tutorial_ops import compile_tutorial
    exact_keys(request, ['operation', 'store', 'expected_version', 'mechanism_card',
                         'tutorial', 'preview', 'shift_clip_ids', 'scope'],
                        ['operation', 'store', 'expected_version', 'mechanism_card',
                         'tutorial', 'preview', 'shift_clip_ids', 'scope'])
    db = connect(request['store'])
    try:
        state = load(db)
    finally:
        db.close()
    require(state['version'] == request['expected_version'], 'WORK_VERSION_CONFLICT')
    base = state['document']
    norm, _, _ = validate_document(base, tools)
    # Output-time layers/protection need a separately reviewed remapping implementation.
    require(not base['audio_tracks'] and not base.get('visual_layers'),
            'RESULT_PREVIEW_DEPENDENT_MAPPING_UNSUPPORTED')
    protected = 'evidence_protection' in base
    require(not protected or request['scope'].get('evidence_mapping') is True,
            'RESULT_PREVIEW_PROTECTION_SHIFT_SCOPE_REQUIRED')
    require(all(Fraction(str(c.get('speed', 1))) == 1 for c in base['plan']['clips']),
            'RESULT_PREVIEW_RETIME_UNSUPPORTED')
    require('result_preview' not in base['notes'], 'RESULT_PREVIEW_NOTE_EXISTS')
    card = source(request['mechanism_card'])
    expected_card = Path(__file__).resolve().parents[1] / 'styles/reference/consequence-first.md'
    require(Path(card['path']).resolve() == expected_card and
            card['sha256'] == source({'path': str(expected_card), 'sha256': card['sha256']})['sha256'],
            'RESULT_PREVIEW_MECHANISM_CARD_REQUIRED')
    shifted = request['shift_clip_ids']
    old_ids = [c['id'] for c in base['plan']['clips']]
    require(isinstance(shifted, list) and all(isinstance(x, str) for x in shifted) and
            len(shifted) == len(set(shifted)) and set(shifted) == set(old_ids),
            'RESULT_PREVIEW_EXPLICIT_SHIFT_REQUIRED')
    tutorial = request['tutorial']
    exact_keys(tutorial, ['steps', 'result_cues'], ['steps', 'result_cues'])
    before_dir = directory / 'base-tutorial'; before_dir.mkdir()
    compile_tutorial({'operation': 'tutorial-plan-compile', 'plan': base['plan'],
                      'expected_revision': fingerprint(base['plan']), **tutorial}, before_dir, tools)
    p = request['preview']
    exact_keys(p, ['id', 'step_id', 'start', 'end', 'label', 'return_label', 'return_label_seconds'],
                  ['id', 'step_id', 'start', 'end', 'label', 'return_label', 'return_label_seconds'])
    require(isinstance(p['id'], str) and p['id'] and p['id'] not in old_ids,
            'RESULT_PREVIEW_CLIP_ID_CONFLICT')
    steps = {s['id']: s for s in tutorial['steps']}
    require(p['step_id'] in steps, 'RESULT_PREVIEW_STEP_UNKNOWN')
    result = steps[p['step_id']]['result']
    clips = {c['id']: c for c in base['plan']['clips']}
    carrier = clips[result['clip_id']]
    a, b = span(p['start'], p['end'], result['end'])
    require(result['start'] <= a < b <= result['end'], 'RESULT_PREVIEW_OUTSIDE_RESULT')
    fps = Fraction(norm['fps'])
    require((Fraction(str(a))*fps).denominator == 1 and
            (Fraction(str(b))*fps).denominator == 1, 'RESULT_PREVIEW_FRAME_GRID_REQUIRED')
    exact_duration = Fraction(str(b)) - Fraction(str(a))
    duration = float(exact_duration)
    require(p['label'] == '后段画面预览 · 非当前操作已成功' and
            isinstance(p['return_label'], str) and p['return_label'].startswith('回到原流程') and
            len(p['return_label']) <= 100 and not any(c in p['return_label'] for c in '{}\\\r\n\t'), 'RESULT_PREVIEW_VISIBLE_LABEL_REQUIRED')
    _, return_end = span(0, p['return_label_seconds'], norm['duration'])
    require(return_end <= 10, 'RESULT_PREVIEW_RETURN_LABEL_TOO_LONG')
    caption_ids = [p['id'] + '-label', p['id'] + '-return-label']
    require(not set(caption_ids) & set(base['captions']), 'RESULT_PREVIEW_CAPTION_ID_CONFLICT')
    require(base['caption_style'] is not None, 'RESULT_PREVIEW_CAPTION_STYLE_REQUIRED')
    candidate = copy.deepcopy(base)
    new_clip = copy.deepcopy(carrier)
    new_clip.update(id=p['id'], start=a, end=b)
    candidate['plan']['clips'].insert(0, new_clip)
    candidate['plan']['allow_source_reuse'] = True
    candidate['captions'][caption_ids[0]] = {'clip_id': p['id'], 'start': 0, 'end': duration, 'text': p['label']}
    candidate['captions'][caption_ids[1]] = {'clip_id': old_ids[0], 'start': 0, 'end': return_end, 'text': p['return_label']}
    shifted_tutorial = copy.deepcopy(tutorial)
    for cue in shifted_tutorial['result_cues']:
        cue['start'] += duration
        cue['end'] += duration
    after_dir = directory / 'candidate-tutorial'; after_dir.mkdir()
    proof = compile_tutorial({'operation': 'tutorial-plan-compile', 'plan': candidate['plan'],
                              'expected_revision': fingerprint(candidate['plan']), **shifted_tutorial}, after_dir, tools)
    # The preview deliberately isn't a result_cue: those certify only declared result windows.
    candidate['notes']['result_preview'] = {
        'schema': 'result-preview/1', 'basis': 'authored-mechanism-only',
        'mechanism_card': card, 'step_id': p['step_id'], 'source_id': carrier['source_id'],
        'source_window': [a, b], 'shift_seconds': duration, 'shift_clip_ids': shifted,
        'base_document_sha256': state['document_sha256'],
        'tutorial_input_sha256': fingerprint(tutorial),
        'candidate_tutorial': proof, 'claim': 'information-order change only; not causal proof',
        'reference_video_adaptation': 'NOT_PERFORMED', 'content_and_listening_review': 'NOT_RUN'}
    protection_report = {'status': 'NOT_PRESENT'}
    if protected:
        protection_report = protection_shift(base, candidate, exact_duration, directory, tools)
    diff = timeline_revise({'operation': 'timeline-revise', 'base_version': state['version'],
        'document': base, 'expected_document_sha256': state['document_sha256'],
        'candidate': candidate, 'scope': request['scope']}, directory, tools)
    if protected:
        require(candidate['evidence_protection'] == base['evidence_protection'],
                'RESULT_PREVIEW_PROTECTION_CHANGED')
        require(candidate['plan']['clips'][1:] == base['plan']['clips'] and
                candidate['plan']['sources'] == base['plan']['sources'],
                'RESULT_PREVIEW_ORIGINAL_CONTENT_CHANGED')
    source(request["mechanism_card"])
    # Recheck tutorial evidence after compilation, before publishing a success report.
    for step in tutorial['steps']:
        for role in ['before', 'action', 'result']:
            source(step[role]['evidence'])
    if protected:
        for unit in base['evidence_protection']['units']:
            source(unit['source']); source(unit['evidence'])
    db = connect(request['store'])
    try:
        require(load(db)['version'] == state['version'], 'WORK_VERSION_CONFLICT')
    finally:
        db.close()
    report = {'schema': 'result-preview-compile/1', 'base_version': state['version'],
        'candidate_document_sha256': fingerprint(candidate), 'changes': diff,
        'shift_seconds': duration, 'preserved_clip_ids': old_ids,
        'basis': 'authored-mechanism-only', 'render': 'NOT_RUN', 'committed': False,
        'reference_video_adaptation': 'NOT_PERFORMED', 'semantic_quality': 'NOT_VERIFIED', 'protection_shift': protection_report}
    write_json(directory / 'result-preview.json', report)
    return report
