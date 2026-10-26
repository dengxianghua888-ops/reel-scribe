"""Read-only, declared-dependency impact analysis for drama content candidates.

This module does not infer what a take actually contains, choose edits, mutate a
Work, or invalidate media. Story IDs in a report are not editor object IDs.
"""

import hashlib
import json

from drama_domain import _scene_context_inputs


COLLECTIONS = {
    'background': 'background_id', 'entities': 'entity_id',
    'propositions': 'proposition_id', 'events': 'event_id',
    'snapshots': 'snapshot_id', 'scenes': 'scene_id', 'beats': 'beat_id',
    'shots': 'shot_id', 'dialogues': 'dialogue_id', 'assets': 'asset_id',
}
KNOWN_FIELDS = {
    'background': {'background_id', 'basis', 'text'},
    'entities': {'entity_id', 'kind', 'name', 'invariants', 'variants'},
    'propositions': {'proposition_id', 'basis', 'story_layer', 'text', 'truth', 'valid_from_event'},
    'events': {'event_id', 'background_refs', 'basis', 'causes', 'description', 'effects',
               'scene_id', 'story_layer', 'current_physical_delta'},
    'snapshots': {'snapshot_id', 'authority', 'entity_state', 'foreshadow', 'knowledge',
                  'position_note', 'story_layer', 'story_position', 'state_scope'},
    'scenes': {'scene_id', 'candidate_dependencies', 'context_refs', 'delta',
               'estimated_duration_sec', 'location_id', 'location_semantics',
               'post_state', 'pre_state', 'purpose', 'reveal_position', 'story_layer',
               'story_position'},
    'beats': {'beat_id', 'change', 'event_refs', 'required', 'scene_id', 'scope'},
    'shots': {'shot_id', 'action', 'actual_duration_sec', 'asset_refs', 'audio_owner',
              'beat_refs', 'dialogue_refs', 'end', 'end_location_id',
              'estimated_duration_sec', 'location_id', 'media_form', 'occurrence',
              'planned_range_sec', 'purpose', 'reference_note', 'scene_id', 'start',
              'story_layer', 'visible_characters', 'variant_refs', 'story_position',
              'reveal_range_sec', 'description', 'boundary_state_ref', 'actual_binding'},
    'dialogues': {'dialogue_id', 'speaker_id', 'text', 'shot_refs',
                  'estimated_speech_sec', 'measured_speech_sec', 'estimate_basis',
                  'performance'},
    'assets': {'asset_id', 'kind', 'status', 'entity_or_shot_refs', 'control_scope',
               'version', 'actual_binding', 'requirement', 'selection_status',
               'presentation'},
}
METADATA = {'schema', 'content_revision', 'authority', 'work_binding',
            'document_views', 'review_scope'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _identity(content):
    return {
        'schema': content.get('schema'),
        'content_revision': content.get('content_revision'),
        'canonical_json_sha256': hashlib.sha256(
            _canonical(content).encode('utf-8')).hexdigest(),
        'hash_basis': 'canonical JSON object, not source file bytes',
        'work_binding': content.get('work_binding'),
    }


def _index(content, field):
    values = content.get(field, [])
    if not isinstance(values, list):
        raise ValueError('Expected list at ' + field)
    key = COLLECTIONS[field]
    result = {}
    for obj in values:
        # The frozen background uses background_id; no display-name fallback.
        if not isinstance(obj, dict) or not isinstance(obj.get(key), str):
            raise ValueError('Missing stable ID at ' + field + '.' + key)
        if obj[key] in result:
            raise ValueError('Duplicate stable ID: ' + obj[key])
        result[obj[key]] = obj
    return result


def _refs(value):
    """Exact declared references only; never mine narrative prose for IDs."""
    result = set()
    if isinstance(value, str):
        result.add(value)
        if '.' in value:
            result.add(value.split('.', 1)[0])
    elif isinstance(value, dict):
        for key, item in value.items():
            result.add(key)
            result.update(_refs(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_refs(item))
    return result


def _changed_fields(before, after):
    return sorted(key for key in set(before) | set(after)
                  if before.get(key) != after.get(key)
                  or (key in before) != (key in after))


class _Report:
    def __init__(self, before, after):
        self.before = before
        self.after = after
        self.old = {key: _index(before, key) for key in COLLECTIONS}
        self.new = {key: _index(after, key) for key in COLLECTIONS}
        self.all = {key: {**self.old[key], **self.new[key]}
                    for key in COLLECTIONS}
        self.direct = []
        self.semantic = []
        self.affected = {key: set() for key in COLLECTIONS}
        self.visual_shots = set()
        self.timing_shots = set()
        self.context_scenes = set()
        self.caption_assets = set()
        self.audio_assets = set()
        self.unknown = False

    def add(self, rule, refs, field, reason, semantic=False, evidence=None):
        item = {
            'rule_id': rule, 'object_refs': sorted(set(refs)), 'field': field,
            'result': 'UNCERTAIN' if semantic else 'PASS',
            'reason': reason,
            'evidence': evidence or {'kind': 'declared_dependencies'},
            'impact': 'review_required' if semantic else 'update_candidate_spec',
        }
        target = self.semantic if semantic else self.direct
        if item not in target:
            target.append(item)

    def assets_for(self, refs, kinds=None):
        return {key for key, asset in self.all['assets'].items()
                if refs.intersection(asset.get('entity_or_shot_refs', []))
                and (kinds is None or asset.get('kind') in kinds)}

    def mark_assets(self, ids, rule, reason):
        for aid in sorted(ids):
            asset = self.all['assets'][aid]
            self.affected['assets'].add(aid)
            if asset.get('kind') == 'caption':
                self.caption_assets.add(aid)
            if asset.get('kind') == 'dialogue_audio':
                self.audio_assets.add(aid)
            self.add(rule, [aid], 'assets', reason, evidence={
                'kind': 'declared_asset_dependency',
                'entity_or_shot_refs': asset.get('entity_or_shot_refs', []),
                'actual_binding_verified': False,
                'requirement': asset.get('requirement'),
                'selection_status': asset.get('selection_status'),
            })

    def mark_visual(self, shots, rule, reason):
        self.visual_shots.update(shots)
        self.affected['shots'].update(shots)
        self.mark_assets(self.assets_for(shots, {'shot_take'}), rule, reason)
        if shots:
            self.add(rule, shots, 'shots.visual_spec', reason)
            self.add('ACTUAL_VISUAL_CONSUMPTION_UNKNOWN', shots,
                     'shots.actual_binding',
                     'Review actual takes before reuse; declared visibility may '
                     'omit a sleeve, reflection or another real pixel consumer.',
                     semantic=True)

    def descendants(self, scene_ids):
        result = set(scene_ids)
        while True:
            added = set()
            all_scenes = list(self.old['scenes'].items()) + list(self.new['scenes'].items())
            post_states = {scene.get('post_state') for sid, scene in all_scenes
                           if sid in result and scene.get('post_state')}
            for sid, scene in all_scenes:
                if (result.intersection(_refs(scene.get('candidate_dependencies', [])))
                        or scene.get('pre_state') in post_states):
                    added.add(sid)
            if added <= result:
                return result
            result.update(added)

    def contexts(self, scenes, reason):
        scenes = self.descendants(scenes)
        self.refresh_contexts(scenes, reason)
        if scenes:
            self.add('STORY_CONSEQUENCES_REQUIRE_REVIEW', scenes,
                     'scenes.purpose/delta/dialogues',
                     'Review motivation, knowledge, causality and payoff. '
                     'No belief or physical state is automatically rewritten.',
                     semantic=True)

    def refresh_contexts(self, scenes, reason):
        """Rebuild embedded inputs without implying a change to story meaning."""
        self.context_scenes.update(scenes)
        self.affected['scenes'].update(scenes)
        if scenes:
            self.add('SCENE_CONTEXT_INPUT_CHANGED', scenes, 'scenes.context', reason)

    def context_consumers(self, object_id):
        """Use the assembler's exact prerequisite closure in both revisions."""
        consumers = set()
        for content in (self.before,self.after):
            for scene in content['scenes']:
                sid=scene['scene_id']
                if object_id in _scene_context_inputs(content,sid)['refs']:
                    consumers.add(sid)
        return consumers

    def entity_context_consumers(self, entity_id):
        return self.context_consumers(entity_id)

    def asset_context_consumers(self, asset_id):
        return {shot['scene_id'] for tables in (self.old, self.new)
                for shot in tables['shots'].values()
                if asset_id in shot.get('asset_refs', [])}

    def unknown_field(self, refs, field):
        self.unknown = True
        self.add('UNCLASSIFIED_CHANGE', refs, field,
                 'This changed field has no precise dependency rule; review its '
                 'scope before claiming preservation or reusing media.', semantic=True)

    def finish(self):
        changed = bool(self.direct or self.semantic)
        return {
            'schema': 'drama-impact-report/1',
            'status': 'UNCERTAIN' if self.unknown else 'PASS',
            'meaning': 'Impact enumeration only; PASS is not content or media acceptance.',
            'base': _identity(self.before), 'candidate': _identity(self.after),
            'deterministic_impacts': self.direct,
            'semantic_review_impacts': self.semantic,
            'unaffected': {
                'basis': 'IDs not marked for direct specification/dependency update. '
                         'Semantic-review entries may still apply; pixel/audio preservation is unverified.',
                'conclusive': not self.unknown,
                'conclusive_scope': 'Enumeration under the declared rules only.',
                'media_preservation': 'NOT_RUN',
                'objects': {key: sorted(set(self.all[key]) - self.affected[key])
                            for key in COLLECTIONS},
            },
            'scope_candidates': {
                'authority': 'proposal_only',
                'domain_note_keys': ['drama_domain_ref'] if changed else [],
                'visual_shot_ids': sorted(self.visual_shots),
                'timing_review_shot_ids': sorted(self.timing_shots),
                'context_scene_ids': sorted(self.context_scenes),
                'caption_asset_ids': sorted(self.caption_assets),
                'dialogue_audio_asset_ids': sorted(self.audio_assets),
                'work_scope': None,
                'work_scope_reason': 'Story IDs require explicit actual Work bindings. '
                                     'This report cannot authorize or populate clip_ids, '
                                     'source_ids, caption_ids or audio_ids.',
            },
            'media_actions': [], 'host_adoption': 'NOT_RUN',
            'semantic_review': 'NOT_RUN', 'media_review': 'NOT_RUN',
            'missing_evidence': [
                'Actual visual/audio consumption and measured duration have not been checked.',
                'Optional caption slots do not authorize subtitle generation or burn-in.',
                'A fresh Work version and exact allowed scope are required before adoption.',
            ],
        }


def _character_shots(report, entity_id, changed_variants=None):
    selected = set()
    for sid, shot in report.all['shots'].items():
        if entity_id not in shot.get('visible_characters', []):
            continue
        if changed_variants is None:
            selected.add(sid)
            continue
        scene = report.all['scenes'].get(shot.get('scene_id'), {})
        variants = set(shot.get('variant_refs', []))
        if not variants:
            for state_id in [scene.get('pre_state'), scene.get('post_state')]:
                for states in [report.old['snapshots'], report.new['snapshots']]:
                    state = states.get(state_id, {})
                    variant = state.get('entity_state', {}).get(entity_id, {}).get('variant_id')
                    if variant:
                        variants.add(variant)
        # If no selected variant is declared, retain the visible shot as a
        # conservative candidate; do not claim a proven exact media dependency.
        if not variants or variants.intersection(changed_variants):
            selected.add(sid)
    return selected


def _entity_change(report, oid, old, new, fields):
    entity = new or old
    kind = entity.get('kind')
    report.refresh_contexts(report.entity_context_consumers(oid),
                            'Scene context embeds this entity specification; '
                            'refresh the payload without inferring new story consequences.')
    if kind == 'character' and set(fields) <= {'variants', 'name'}:
        if 'variants' not in fields:
            return  # Display labels do not merge identities or regenerate media.
        old_vars = {x.get('variant_id'): x for x in old.get('variants', [])}
        new_vars = {x.get('variant_id'): x for x in new.get('variants', [])}
        changed = {vid for vid in set(old_vars) | set(new_vars)
                   if old_vars.get(vid) != new_vars.get(vid)}
        for vid in changed:
            for field in set(_changed_fields(old_vars.get(vid, {}), new_vars.get(vid, {}))) - {
                    'variant_id', 'description'}:
                report.unknown_field([oid, vid], 'entities.variants.' + field)
        refs = report.assets_for({oid}, {'character_reference'})
        report.mark_assets(refs, 'CHARACTER_VARIANT_REFERENCE',
                           'Visual variant specification changed; voice identity is preserved.')
        shots = _character_shots(report, oid, changed)
        report.mark_visual(shots, 'VISIBLE_CHARACTER_VARIANT',
                           'Character is declared visible and the changed variant is '
                           'selected or its exact selection is not declared.')
        report.add('VARIANT_VISUAL_JUDGMENT', [oid], 'entities.variants',
                   'Review color separation, prop visibility, light and any intended '
                   'costume continuity; words do not establish actual visual quality.',
                   semantic=True)
    elif kind == 'character':
        report.mark_assets(report.assets_for({oid}, {'character_reference'}),
                           'CHARACTER_IDENTITY_REFERENCE', 'Character identity specification changed.')
        report.mark_visual(_character_shots(report, oid), 'VISIBLE_CHARACTER_IDENTITY',
                           'Declared visible character identity requires candidate review.')
        report.add('IDENTITY_STORY_AND_VOICE_REVIEW', [oid], 'entities',
                   'Review whether changed identity affects characterization or voice; '
                   'do not replace the voice automatically.', semantic=True)
    else:
        kinds = {'location_reference'} if kind == 'location' else {'prop_reference'}
        refs = report.assets_for({oid}, kinds)
        report.mark_assets(refs, 'ENTITY_REFERENCE', 'Location or prop specification changed.')
        shots = {sid for sid, shot in report.all['shots'].items()
                 if refs.intersection(shot.get('asset_refs', []))
                 or oid in {shot.get('location_id'), shot.get('end_location_id')}}
        report.mark_visual(shots, 'DECLARED_ENTITY_VISUAL_DEPENDENCY',
                           'Planned entity visual dependency changed; actual consumption unknown.')
        report.add('ENTITY_CONTINUITY_REVIEW', [oid], 'entities',
                   'Review physical continuity and narrative consequences.', semantic=True)


def _dialogue_change(report, oid, old, new, fields):
    refs = set(old.get('shot_refs', [])) | set(new.get('shot_refs', []))
    text_or_voice = {'text', 'speaker_id', 'performance'}
    if text_or_voice.intersection(fields) or not old or not new:
        report.mark_assets(report.assets_for({oid}, {'dialogue_audio'}),
                           'DIALOGUE_AUDIO_DEPENDENCY', 'Text, speaker or performance changed.')
    if 'text' in fields or not old or not new:
        report.mark_assets(report.assets_for({oid}, {'caption'}),
                           'DIALOGUE_CAPTION_TEXT', 'Caption text requirement follows changed dialogue.')
    report.timing_shots.update(refs)
    report.affected['shots'].update(refs)
    report.add('DIALOGUE_TIMING_REVIEW', refs | {oid}, 'shots.dialogue_refs',
               'Re-estimate and measure speech before changing shot duration or later positions.')
    report.add('CONDITIONAL_LIPSYNC_DEPENDENCY', refs | {oid}, 'shots.actual_binding',
               'Only actual lip-sync, performance or timing consumption can establish '
               'whether picture takes need replacement.', semantic=True)
    scenes = {report.all['shots'][sid].get('scene_id') for sid in refs
              if sid in report.all['shots']}
    report.contexts(scenes - {None}, 'Dialogue changed in a scene or its candidate predecessor.')


def _story_change(report, field, oid, old, new):
    refs = {oid}
    scenes = set()
    if field == 'scenes':
        scenes.add(oid)
    else:
        if field in {'background','propositions','events'}:
            scenes.update(report.context_consumers(oid))
        scenes.update(obj.get('scene_id') for obj in [old, new] if obj.get('scene_id'))
        all_scenes = list(report.old['scenes'].items()) + list(report.new['scenes'].items())
        for sid, scene in all_scenes:
            if refs.intersection(_refs(scene)):
                scenes.add(sid)
        # Knowledge and event evidence can be carried by an explicit state even
        # when the scene omits that proposition from context_refs.
        states = {sid for sid, state in list(report.old['snapshots'].items()) + list(report.new['snapshots'].items())
                  if refs.intersection(_refs(state))}
        for sid, scene in all_scenes:
            if states.intersection({scene.get('pre_state'), scene.get('post_state')}):
                scenes.add(sid)
    report.contexts(scenes, 'Explicit story fact, state, event or candidate-chain dependency changed.')
    if not scenes:
        report.add('STORY_CHANGE_WITHOUT_CONSUMER', [oid], field,
                   'No declared scene consumer found; review missing dependencies.', semantic=True)


def _variant_impact(before, variant):
    # Variant projection is local and explicit; the caller's dictionaries remain
    # unchanged. This is not a timeline compiler or a state adoption operation.
    if variant.get('base_content_revision') != before.get('content_revision'):
        return _failure('VARIANT_BASE_CONFLICT', 'Variant revision does not match content baseline.')
    target = variant.get('edit', {}).get('replaces_shot_ref')
    if (variant.get('edit', {}).get('composition') != 'replace_with_leaf_shots'
            or variant.get('edit', {}).get('count_source_group_duration') is not False
            or not variant.get('leaf_shots')):
        return _failure('VARIANT_COMPOSITION_UNSUPPORTED', 'Expected nonempty leaf replacement without parent double counting.')
    source = {s['shot_id']: s for s in before.get('shots', [])}.get(target)
    if source is None:
        return _failure('VARIANT_TARGET_MISSING', 'Variant source shot is not in baseline.')
    projected = json.loads(_canonical(before))
    projected['shots'] = [leaf for shot in before['shots']
                          for leaf in (variant.get('leaf_shots', [])
                                       if shot['shot_id'] == target else [shot])]
    for field, additions in [('assets', 'new_assets'), ('beats', 'new_beats'),
                             ('events', 'new_events')]:
        projected[field] = before.get(field, []) + variant.get(additions, [])
    report = _Report(before, projected)
    for field in set(variant) - {'schema', 'variant_id', 'status', 'base_content_revision',
                                'adoption_receipt', 'request', 'target', 'new_assets',
                                'invariants', 'golden', 'edit', 'leaf_shots', 'boundary_states',
                                'new_beats', 'new_events', 'dialogue_rebindings'}:
        report.unknown_field([variant.get('variant_id', 'variant')], field)
    leaves = {s['shot_id'] for s in variant.get('leaf_shots', [])}
    report.affected['shots'].update(leaves | {target})
    report.mark_visual(leaves | {target}, 'VARIANT_PRESENTATION_REPLACEMENT',
                       'Source group is replaced by leaf shots; do not count both.')
    report.timing_shots.update(leaves | {target})
    report.add('VARIANT_TEMPORAL_BOUNDARY', leaves | {target}, 'variant.boundary_states',
               'Review return-to-present boundary, knowledge and reveal order; '
               'historical entity state does not replace present scene state.', semantic=True)
    report.mark_assets({a['asset_id'] for a in variant.get('new_assets', [])},
                       'VARIANT_NEW_ASSET', 'Explicit candidate asset requirement.')
    for field, additions, key in [('beats', 'new_beats', 'beat_id'),
                                  ('events', 'new_events', 'event_id')]:
        ids = {v[key] for v in variant.get(additions, [])}
        report.affected[field].update(ids)
        if ids:
            report.add('VARIANT_SCOPED_STORY', ids, additions,
                       'New presentation-layer objects belong to this candidate only.')
    for binding in variant.get('dialogue_rebindings', []):
        did = binding['dialogue_id']
        report.affected['dialogues'].add(did)
        report.add('DIALOGUE_PRESENTATION_REBIND', [did], 'dialogue_rebindings',
                   'Move declared presentation anchor; do not duplicate parent and child audio.')
        report.mark_assets(report.assets_for({did}, {'caption'}),
                           'CAPTION_PRESENTATION_REBIND', 'Caption placement follows leaf anchor.')
        original = report.old['dialogues'].get(did, {})
        if (not binding.get('text_unchanged', False)
                or binding.get('speaker_id') != original.get('speaker_id')):
            report.mark_assets(report.assets_for({did}, {'dialogue_audio'}),
                               'VARIANT_DIALOGUE_TEXT_REVIEW', 'Variant does not preserve dialogue text.')
    result = report.finish()
    result['candidate'] = _identity(variant)
    result['candidate']['variant_id'] = variant.get('variant_id')
    result['candidate']['projection_is_not_adopted_content'] = True
    result['missing_evidence'].append('validate_variant must separately validate the proposed composition.')
    return result


def _failure(rule, reason):
    return {'schema': 'drama-impact-report/1', 'status': 'FAIL',
            'deterministic_impacts': [],
            'semantic_review_impacts': [{'rule_id': rule, 'object_refs': [],
                                        'field': '$', 'result': 'FAIL', 'reason': reason}],
            'unaffected': {'conclusive': False, 'objects': {}},
            'scope_candidates': None, 'media_actions': [], 'host_adoption': 'NOT_RUN',
            'semantic_review': 'NOT_RUN', 'media_review': 'NOT_RUN'}


def analyze_impact(before, after):
    """Return declared impacts between content candidates, or for a variant.

    Inputs must be JSON objects with stable IDs. Domain validation and actual
    byte verification are separate prerequisites; this function does no I/O.
    """
    if not isinstance(before, dict) or not isinstance(after, dict):
        return _failure('IMPACT_INPUT_INVALID', 'Both inputs must be JSON objects.')
    try:
        _canonical(before)
        _canonical(after)
        if not str(before.get('schema', '')).startswith('drama-content/'):
            return _failure('IMPACT_INPUT_INVALID', 'Baseline must declare a drama-content schema.')
        if str(after.get('schema', '')).startswith('drama-variant/'):
            return _variant_impact(before, after)
        if not str(after.get('schema', '')).startswith('drama-content/'):
            return _failure('IMPACT_INPUT_INVALID', 'Candidate must declare a drama-content schema.')
        report = _Report(before, after)
        for key in _changed_fields(before, after):
            if key in COLLECTIONS:
                old_map, new_map = report.old[key], report.new[key]
                old_order, new_order = list(old_map), list(new_map)
                if set(old_order) == set(new_order) and old_order != new_order:
                    report.add('COLLECTION_ORDER_CHANGE', new_order, key,
                               'Declared object order changed; preserve stable identities.')
                    if key in {'shots', 'scenes'}:
                        report.add('PRESENTATION_ORDER_REVIEW', new_order, key,
                                   'Review narrative timing and reveal order before reuse.', semantic=True)
                        if key == 'shots':
                            report.timing_shots.update(new_order)
                            report.affected['shots'].update(new_order)
                for oid in sorted(set(old_map) | set(new_map)):
                    old, new = old_map.get(oid, {}), new_map.get(oid, {})
                    if old == new:
                        continue
                    fields = _changed_fields(old, new)
                    report.affected[key].add(oid)
                    report.add('DECLARED_OBJECT_CHANGE', [oid], key + '.' + ','.join(fields),
                               'Stable-ID object fields changed.', evidence={
                                   'kind': 'object_diff', 'changed_fields': fields,
                                   'before_exists': bool(old), 'after_exists': bool(new)})
                    for unknown in set(fields) - KNOWN_FIELDS.get(key, set(fields)):
                        report.unknown_field([oid], key + '.' + unknown)
                    if key == 'entities':
                        _entity_change(report, oid, old, new, fields)
                    elif key == 'dialogues':
                        _dialogue_change(report, oid, old, new, fields)
                    elif key == 'assets':
                        report.refresh_contexts(report.asset_context_consumers(oid),
                                                'Scene context embeds the changed asset specification.')
                        kind = (new or old).get('kind')
                        if kind == 'caption':
                            report.caption_assets.add(oid)
                            report.add('CAPTION_LEGIBILITY_REVIEW', [oid], 'assets.presentation',
                                       'Review safe area against actual action, text and frame; '
                                       'optional slots are not selected automatically.', semantic=True)
                        elif kind == 'dialogue_audio':
                            report.audio_assets.add(oid)
                            refs = set(old.get('entity_or_shot_refs', [])) | set(new.get('entity_or_shot_refs', []))
                            shots = refs.intersection(report.all['shots'])
                            report.timing_shots.update(shots)
                            report.affected['shots'].update(shots)
                        else:
                            shots = {sid for sid, shot in report.all['shots'].items()
                                     if oid in shot.get('asset_refs', [])}
                            report.add('ASSET_CONSUMPTION_REVIEW', shots | {oid}, 'assets',
                                       'Reference lists are context requirements; inspect actual '
                                       'consumption before replacing takes.', semantic=True)
                    elif key == 'shots':
                        report.mark_visual({oid}, 'SHOT_SPECIFICATION_CHANGE',
                                           'Declared shot specification changed.')
                        report.timing_shots.add(oid)
                        report.contexts({(new or old).get('scene_id')} - {None},
                                        'Shot specification changed; review its scene consequences.')
                    else:
                        _story_change(report, key, oid, old, new)
            elif key == 'style_ref':
                old, new = before.get(key, {}), after.get(key, {})
                style_fields = _changed_fields(old, new)
                report.add('STYLE_DECLARATION_CHANGE', [], 'style_ref', 'Style declaration changed.')
                report.refresh_contexts(set(report.all['scenes']),
                                        'Every scene context embeds style_ref; refresh style inputs '
                                        'without implying dialogue, physical-state or picture changes.')
                if set(style_fields) <= {'caption_style'}:
                    captions = {aid for aid, a in report.all['assets'].items() if a.get('kind') == 'caption'}
                    report.mark_assets(captions, 'CAPTION_STYLE_DEPENDENCY',
                                       'Only caption presentation requirements changed.')
                    report.add('CAPTION_LAYOUT_REVIEW', captions, 'style_ref.caption_style',
                               'Actual frame geometry and action must be checked for legibility '
                               'and occlusion; no audio or character rerender is implied.', semantic=True)
                else:
                    report.add('STYLE_SCOPE_REVIEW', list(report.all['shots']), 'style_ref',
                               'Reference change does not reveal which creative dimensions '
                               'changed; compare style content before deciding take reuse.', semantic=True)
            elif key == 'task':
                report.add('TASK_CONSTRAINT_CHANGE', [], 'task', 'Task requirements changed.')
                report.contexts(set(report.all['scenes']), 'Task constraints are mandatory scene context.')
            elif key in METADATA:
                report.add('CONTENT_METADATA_CHANGE', [], key,
                           'Candidate provenance or report metadata changed; no media action inferred.')
                if key in {'schema', 'work_binding', 'authority'}:
                    report.add('AUTHORITY_CHANGE_REVIEW', [], key,
                               'Metadata does not prove real adoption; verify actual Work receipt.', semantic=True)
            else:
                report.unknown_field([], key)
        return report.finish()
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        return _failure('IMPACT_INPUT_INVALID', str(exc))
