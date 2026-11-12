"""Three-way, field-limited undo preparation. SQLite Work remains authoritative."""
import copy


def prepare(db, current, request, tools, *, directory=None):
    from editing_runtime import exact_keys, require, fingerprint
    from work_ops import load, revision_diff
    sequence = request['undo_sequence']
    require(type(sequence) is int and 0 < sequence <= current['sequence'], 'UNDO_SEQUENCE_INVALID')
    row = db.execute('SELECT parent,action FROM revisions WHERE sequence=?', (sequence,)).fetchone()
    require(row is not None and row['parent'] == sequence - 1 and row['action'] == 'commit',
            'UNDO_REQUIRES_ORDINARY_COMMIT_PARENT')
    # Walk the authoritative linear ancestry, validating every retained document.
    for seq in range(current['sequence'], sequence - 1, -1):
        load(db, seq)
        parent = db.execute('SELECT parent FROM revisions WHERE sequence=?', (seq,)).fetchone()
        require(parent is not None and parent['parent'] == seq - 1, 'UNDO_HISTORY_PARENT_INVALID')
    before = load(db, row['parent'])
    after = load(db, sequence)
    fields = request['fields']
    require(isinstance(fields, list) and bool(fields), 'UNDO_FIELDS_REQUIRED')
    candidate = copy.deepcopy(current['document'])
    records = []
    seen = set()
    for selection in fields:
        require(isinstance(selection, dict), 'UNDO_FIELD_INVALID')
        kind = selection.get('kind')
        if kind == 'caption_override':
            exact_keys(selection, ['kind','id','field'], ['kind','id','field'])
            cid, key = selection['id'], selection['field']
            require(isinstance(cid,str) and cid and key in ['font_size','margin_v','color_rgb'], 'UNDO_FIELD_UNSUPPORTED')
            path = ('captions',cid,'style_override',key)
            require(path not in seen, 'UNDO_FIELD_DUPLICATE');seen.add(path)
            cues = [state['document']['captions'].get(cid) for state in [before,after,current]]
            require(all(isinstance(c,dict) for c in cues), 'UNDO_FIELD_MISSING')
            identities = [{k:v for k,v in c.items() if k!='style_override'} for c in cues]
            require(identities[0]==identities[1]==identities[2], 'UNDO_CAPTION_IDENTITY_CONFLICT')
            cells = [{'present':key in c.get('style_override',{}),
                      'value':c.get('style_override',{}).get(key)} for c in cues]
            old, edited, now = cells
            require(fingerprint(now) in [fingerprint(old),fingerprint(edited)], 'UNDO_FIELD_CONFLICT: '+'.'.join(path))
            target = candidate['captions'][cid]
            if old['present']:
                target.setdefault('style_override',{})[key]=copy.deepcopy(old['value'])
            elif 'style_override' in target:
                target['style_override'].pop(key,None)
                if not target['style_override']:target.pop('style_override')
            records.append({'selection':selection,'before':old['value'],'after':edited['value'],'current':now['value'],
                'presence':{'before':old['present'],'after':edited['present'],'current':now['present']},
                'restored_effective_value':target.get('style_override',{}).get(key,current['document']['caption_style'][key]),
                'inheritance':'current-global-not-historical-appearance' if not old['present'] else 'explicit-override',
                'status':'ALREADY_RESTORED' if fingerprint(old)==fingerprint(now) else 'RESTORE_BEFORE'})
            continue
        if kind == 'caption_style':
            exact_keys(selection, ['kind', 'field'], ['kind', 'field'])
            key = selection['field']
            require(key in ['font_size', 'margin_v', 'color_rgb'], 'UNDO_FIELD_UNSUPPORTED')
            path = ('caption_style', key)
        elif kind == 'audio_track':
            exact_keys(selection, ['kind', 'id', 'field'], ['kind', 'id', 'field'])
            require(isinstance(selection['id'], str) and selection['id'] and selection['field'] == 'gain_db',
                    'UNDO_FIELD_UNSUPPORTED')
            path = ('audio_tracks', selection['id'], 'gain_db')
        else:
            require(False, 'UNDO_FIELD_UNSUPPORTED')
        require(path not in seen, 'UNDO_FIELD_DUPLICATE')
        seen.add(path)
        containers = []
        for state in [before, after, current]:
            value = state['document']
            for part in path[:-1]:
                require(isinstance(value, dict) and part in value, 'UNDO_FIELD_MISSING')
                value = value[part]
            require(isinstance(value, dict) and path[-1] in value, 'UNDO_FIELD_MISSING')
            containers.append(value)
        if kind == 'audio_track':
            identities = []
            for state, track in zip([before, after, current], containers):
                identity = {k: v for k, v in track.items() if k != 'gain_db'}
                anchor = track.get('anchor_clip_id')
                if anchor is not None:
                    clips = state['document']['plan']['clips']
                    clip = next((c for c in clips if c['id'] == anchor), None)
                    require(clip is not None, 'UNDO_AUDIO_IDENTITY_CONFLICT')
                    identity['anchor_clip'] = clip
                    identity['anchor_source'] = state['document']['plan']['sources'].get(clip['source_id'])
                identities.append(identity)
            require(identities[0] == identities[1] == identities[2], 'UNDO_AUDIO_IDENTITY_CONFLICT')
        old, edited, now = [v[path[-1]] for v in containers]
        # Canonical comparison preserves types as well as values (1 is not true).
        eq = lambda a, b: fingerprint(a) == fingerprint(b)
        require(eq(now, edited) or eq(now, old), 'UNDO_FIELD_CONFLICT: ' + '.'.join(path))
        changed = not eq(now, old)
        target = candidate
        for part in path[:-1]:
            target = target[part]
        target[path[-1]] = copy.deepcopy(old)
        records.append({'selection': selection, 'before': old, 'after': edited, 'current': now,
                        'status': 'RESTORE_BEFORE' if changed else 'ALREADY_RESTORED'})
    # Resolve inherited appearance after ALL selected fields, independent of order.
    for record in records:
        selection=record['selection']
        if selection['kind']=='caption_override':
            record['restored_effective_value']=candidate['captions'][selection['id']].get('style_override',{}).get(selection['field'],candidate['caption_style'][selection['field']])
    changed = fingerprint(candidate) != current['document_sha256']
    # A recipe's parameters/constraints cannot silently remain an endorsement of
    # altered values. Binding changes require a separate explicit operation.
    binding_report = None
    if changed and candidate['style_bindings']:
        require('binding_resolution' in request, 'UNDO_STYLE_BINDING_REQUIRES_EXPLICIT_RESOLUTION')
        require('*' in request['scope'].get('style_keys', []), 'UNDO_BINDING_SCOPE_REQUIRED')
        binding_report = resolve_binding(current['document'], candidate, records, request['binding_resolution'], tools, directory)
    elif 'binding_resolution' in request:
        require(not changed, 'UNDO_BINDING_RESOLUTION_WITHOUT_BINDING')
    diff = revision_diff(current['document'], candidate, request['scope'], tools)
    bundle = {'schema': 'work-candidate/1', 'base_version': current['version'],
              'base_document_sha256': current['document_sha256'], 'document': candidate, 'scope': request['scope']}
    report = {'status': 'CANDIDATE_PREPARED' if changed else 'NO_OP', 'applied_to_work': False,
              'undo_sequence': sequence, 'fields': records, 'diff': diff,
              'history': {label: {k: state[k] for k in ['sequence', 'version', 'document_sha256']}
                         for label, state in [('before', before), ('after', after), ('current', current)]},
              'semantic_review': 'NOT_RUN', 'render': 'NOT_RUN'}
    if binding_report is not None:
        report['binding_resolution'] = binding_report
    return report, bundle if changed else None


def resolve_binding(current, candidate, records, resolution, tools, directory):
    """Derive a new explicit recipe, never relabel the old recipe as still applied."""
    from editing_runtime import exact_keys, require, fingerprint, source, number
    exact_keys(resolution, ['recipe', 'expected_recipe_sha256', 'derived_recipe_id', 'derived_recipe_version'],
               ['recipe', 'expected_recipe_sha256', 'derived_recipe_id', 'derived_recipe_version'])
    recipe = resolution['recipe']
    exact_keys(recipe, ['schema', 'id', 'version', 'style', 'parameters', 'layout_constraints'],
               ['schema', 'id', 'version', 'style', 'parameters'])
    require(recipe['schema'] == 'style-recipe/1', 'UNDO_RECIPE_SCHEMA_UNSUPPORTED')
    require(fingerprint(recipe) == resolution['expected_recipe_sha256'], 'UNDO_RECIPE_HASH_CONFLICT')
    require(all(isinstance(recipe[k], str) and recipe[k].strip() for k in ['id', 'version']), 'UNDO_RECIPE_ID_REQUIRED')
    style = recipe['style']
    exact_keys(style, ['family', 'style_id', 'version', 'card'], ['family', 'style_id', 'version', 'card'])
    card_identity = source(style['card'])
    expected = {**copy.deepcopy(style), 'parameters': {
        'recipe_id': recipe['id'], 'recipe_version': recipe['version'],
        'recipe_sha256': fingerprint(recipe), 'presentation': copy.deepcopy(recipe['parameters'])}}
    if 'layout_constraints' in recipe:
        expected['parameters']['layout_constraints'] = copy.deepcopy(recipe['layout_constraints'])
    require(fingerprint(current['style_bindings']) == fingerprint({'*': expected}), 'UNDO_BINDING_RECIPE_MISMATCH')
    parameters = recipe['parameters']
    exact_keys(parameters, ['caption_style', 'audio_gain_db', 'caption_overrides'])
    require(bool(parameters), 'UNDO_RECIPE_PARAMETERS_REQUIRED')
    if 'caption_style' in parameters:
        values = parameters['caption_style']
        exact_keys(values, ['font_size', 'margin_v', 'color_rgb'])
        require(bool(values) and isinstance(current['caption_style'], dict), 'UNDO_RECIPE_PARAMETERS_REQUIRED')
        require(all(fingerprint(current['caption_style'].get(k)) == fingerprint(v) for k, v in values.items()),
                'UNDO_BINDING_ALREADY_DIVERGED')
    if 'audio_gain_db' in parameters:
        values = parameters['audio_gain_db']
        require(isinstance(values, dict) and bool(values), 'UNDO_RECIPE_PARAMETERS_REQUIRED')
        require(all(isinstance(k, str) and k in current['audio_tracks'] and
                    current['audio_tracks'][k]['gain_db'] == number(v, 'gain_db') for k, v in values.items()), 'UNDO_BINDING_ALREADY_DIVERGED')
    if 'caption_overrides' in parameters:
        overrides = parameters['caption_overrides']
        require(isinstance(overrides,dict) and bool(overrides), 'UNDO_RECIPE_PARAMETERS_REQUIRED')
        for cid, values in overrides.items():
            require(isinstance(cid,str) and cid in current['captions'], 'UNDO_BINDING_ALREADY_DIVERGED')
            exact_keys(values, ['font_size','margin_v','color_rgb'])
            require(bool(values), 'UNDO_RECIPE_PARAMETERS_REQUIRED')
            stored=current['captions'][cid].get('style_override',{})
            require(all(k in stored and fingerprint(stored[k])==fingerprint(v) for k,v in values.items()), 'UNDO_BINDING_ALREADY_DIVERGED')
    derived = copy.deepcopy(recipe)
    for key, target in [('id', 'derived_recipe_id'), ('version', 'derived_recipe_version')]:
        require(isinstance(resolution[target], str) and resolution[target].strip(), 'UNDO_DERIVED_RECIPE_ID_REQUIRED')
        derived[key] = resolution[target]
    require((derived['id'], derived['version']) != (recipe['id'], recipe['version']), 'UNDO_DERIVED_RECIPE_ID_MUST_CHANGE')
    for record in records:
        selection = record['selection']
        if selection['kind']=='caption_override':
            cid,key=selection['id'],selection['field']
            require(cid in parameters.get('caption_overrides',{}) and key in parameters['caption_overrides'][cid], 'UNDO_SELECTED_FIELD_NOT_RECIPE_MAPPED')
            values=derived['parameters']['caption_overrides'][cid]
            if record['presence']['before']:values[key]=copy.deepcopy(record['before'])
            else:values.pop(key)
            if not values:derived['parameters']['caption_overrides'].pop(cid)
            if not derived['parameters']['caption_overrides']:derived['parameters'].pop('caption_overrides')
            continue
        group = 'caption_style' if selection['kind'] == 'caption_style' else 'audio_gain_db'
        key = selection['field'] if group == 'caption_style' else selection['id']
        require(group in parameters and key in parameters[group], 'UNDO_SELECTED_FIELD_NOT_RECIPE_MAPPED')
        derived['parameters'][group][key] = copy.deepcopy(record['before'])
    require(bool(derived['parameters']), 'UNDO_EMPTY_DERIVED_RECIPE_UNSUPPORTED')
    binding = copy.deepcopy(expected)
    binding['parameters'].update(recipe_id=derived['id'], recipe_version=derived['version'],
                                 recipe_sha256=fingerprint(derived), presentation=copy.deepcopy(derived['parameters']))
    candidate['style_bindings']['*'] = binding
    layout = {'status': 'NOT_APPLICABLE', 'reason': 'Original recipe has no layout constraints'}
    if 'layout_constraints' in derived:
        require(directory is not None, 'UNDO_LAYOUT_OUTPUT_REQUIRED')
        from caption_layout import check
        current_layout = check(current, recipe['layout_constraints'], directory/'undo-current-layout', tools)
        layout = {'current': current_layout,
                  'candidate': check(candidate, derived['layout_constraints'], directory/'undo-layout', tools)}
    require(source(style['card']) == card_identity, 'UNDO_RECIPE_CARD_CHANGED_DURING_VALIDATION')
    return {'policy': 'EXPLICIT_DERIVED_RECIPE', 'original_recipe_sha256': fingerprint(recipe),
            'derived_recipe_sha256': fingerprint(derived), 'derived_recipe': derived,
            'derived_from': {'recipe_id': recipe['id'], 'recipe_version': recipe['version'],
                             'recipe_sha256': fingerprint(recipe)},
            'original_binding_sha256': fingerprint(expected), 'derived_binding_sha256': fingerprint(binding),
            'constraints_preserved': True, 'caption_layout': layout, 'style_effect': 'NOT_VERIFIED'}
