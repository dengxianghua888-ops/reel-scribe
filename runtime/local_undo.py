"""Three-way, field-limited undo preparation. SQLite Work remains authoritative."""
import copy


def prepare(db, current, request, tools):
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
    changed = fingerprint(candidate) != current['document_sha256']
    # A recipe's parameters/constraints cannot silently remain an endorsement of
    # altered values. Binding changes require a separate explicit operation.
    require(not changed or not candidate['style_bindings'], 'UNDO_STYLE_BINDING_REQUIRES_EXPLICIT_RESOLUTION')
    diff = revision_diff(current['document'], candidate, request['scope'], tools)
    bundle = {'schema': 'work-candidate/1', 'base_version': current['version'],
              'base_document_sha256': current['document_sha256'], 'document': candidate, 'scope': request['scope']}
    report = {'status': 'CANDIDATE_PREPARED' if changed else 'NO_OP', 'applied_to_work': False,
              'undo_sequence': sequence, 'fields': records, 'diff': diff,
              'history': {label: {k: state[k] for k in ['sequence', 'version', 'document_sha256']}
                         for label, state in [('before', before), ('after', after), ('current', current)]},
              'semantic_review': 'NOT_RUN', 'render': 'NOT_RUN'}
    return report, bundle if changed else None
