"""Read-only, digest-bound impact planning for the existing Work revision gate.

This is not a cache executor, a QA approval, or a replacement Work authority.
"""
from editing_runtime import exact_keys, fingerprint, require, write_json
from work_ops import revision_diff

STAGES = ('source-analysis', 'content-plan', 'timeline', 'caption-layout',
          'audio-mix', 'visual-composition', 'render')


def analyze(base, candidate, scope, tools, *, expected_base_sha256,
            expected_candidate_sha256):
    """Validate the full revision, then conservatively plan downstream work.

    Unchanged input dependencies are only hints. Existing QA invalidations are
    retained verbatim; no receipt is promoted or inherited by this function.
    """
    require(fingerprint(base) == expected_base_sha256, 'DOCUMENT_REVISION_CONFLICT')
    require(fingerprint(candidate) == expected_candidate_sha256, 'CANDIDATE_REVISION_CONFLICT')
    diff = revision_diff(base, candidate, scope, tools)
    reasons = {stage: [] for stage in STAGES}
    categories = []

    def affect(category, stages):
        categories.append(category)
        for stage in stages:
            reasons[stage].append(category)

    # Source identity includes bytes, not just pathname. Both documents have
    # already passed source hashing and Work scope/clock/protection checks.
    if diff['sources']:
        affect('source-identity', STAGES)
    clips_changed = bool(diff['changed_clip_ids'] or diff['shifted_clip_ids'] or
                         diff['old_order'] != diff['new_order'])
    if clips_changed:
        affect('clip-content-or-timing', STAGES[1:])
    if diff['output_fields']:
        # fps/geometry can change sampling, overlays, cue layout and mux timing.
        affect('output-specification', STAGES[1:])
    if diff['captions']:
        text_changed = any(base['captions'].get(key, {}).get('text') !=
                           candidate['captions'].get(key, {}).get('text')
                           for key in diff['captions'])
        presentation_only = all(key in base['captions'] and key in candidate['captions'] and
            {k:v for k,v in base['captions'][key].items() if k!='style_override'} ==
            {k:v for k,v in candidate['captions'][key].items() if k!='style_override'} for key in diff['captions'])
        affect('caption-text' if text_changed else 'caption-local-presentation' if presentation_only else 'caption-placement',
               ('caption-layout', 'visual-composition', 'render'))
    if diff['caption_style_changed']:
        affect('caption-presentation', ('caption-layout', 'visual-composition', 'render'))
    # Audio/overlay assets live outside plan.sources. New, removed or replaced
    # references change media understanding, not merely gain/opacity. Do not
    # label analysis/content inputs unchanged just because plan.sources match.
    for field, category in [('audio_tracks', 'audio-source-identity'),
                            ('visual_layers', 'visual-source-identity')]:
        before = base.get(field, {})
        after = candidate.get(field, {})
        if any(before.get(key, {}).get('source') != after.get(key, {}).get('source')
               for key in diff[field]):
            affect(category, STAGES)
        window_fields = ('start', 'end') if field == 'audio_tracks' else ('source_start_frame', 'duration_frames')
        if any(key in before and key in after and
               any(before[key].get(part) != after[key].get(part) for part in window_fields)
               for key in diff[field]):
            affect('audio-source-window' if field == 'audio_tracks' else 'visual-source-window', STAGES)
    if diff['audio_tracks'] or diff['audio_mapping_changed']:
        affect('audio-track-or-mapping', ('audio-mix', 'render'))
    if diff['visual_layers'] or diff['visual_mapping_changed']:
        affect('visual-layer-or-mapping', ('visual-composition', 'render'))
    if diff['evidence_mapping_changed']:
        affect('evidence-mapping', ('content-plan',))
    if diff['style_bindings']:
        categories.append('style-metadata')
    if diff['notes']:
        categories.append('notes-metadata')
    invalidated = list(diff['invalidated'])
    # The legacy gate deliberately uses broad review invalidation. Do not
    # weaken that gate merely because a narrower execution plan is possible.
    report = {
        'schema': 'revision-impact/1',
        'base_document_sha256': diff['before_document_sha256'],
        'candidate_document_sha256': diff['document_sha256'],
        'scope_sha256': fingerprint(scope),
        'classification': sorted(set(categories)),
        'required_stages': [stage for stage in STAGES if reasons[stage]],
        'unchanged_dependency_stages': [stage for stage in STAGES if not reasons[stage]],
        'stage_reasons': {stage: sorted(set(items)) for stage, items in reasons.items() if items},
        'invalidated_reviews': sorted(set(invalidated)),
        'changed_clip_ids': diff['changed_clip_ids'],
        'shifted_clip_ids': diff['shifted_clip_ids'],
        'affected_range_policy': 'whole-work-conservative; no partial-render boundary proven',
        'cache_reuse': 'NOT_AUTHORIZED',
        'qa_status': 'NOT_RUN',
        'prior_whole_document_qa': 'STALE' if base != candidate else 'NOT_VERIFIED',
        'applied_to_work': False,
        'limitations': [
            'Unchanged dependencies do not validate cached bytes, backend/model/prompt identity, or QA receipts.',
            'Caption text is display text; no narration generation or transcript truth is inferred.',
            'No content understanding, real-media quality, listening or editor acceptance is established.',
        ],
    }
    report['impact_sha256'] = fingerprint(report)
    return report


def execute(request, directory, tools):
    fields = ['operation', 'document', 'candidate', 'scope',
              'expected_document_sha256', 'expected_candidate_sha256']
    exact_keys(request, fields, fields)
    require(request['operation'] == 'revision-impact-inspect', 'OPERATION_UNSUPPORTED')
    result = analyze(request['document'], request['candidate'], request['scope'], tools,
                     expected_base_sha256=request['expected_document_sha256'],
                     expected_candidate_sha256=request['expected_candidate_sha256'])
    write_json(directory / 'revision-impact.json', result)
    return result
