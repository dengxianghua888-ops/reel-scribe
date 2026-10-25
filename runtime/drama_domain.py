"""Provider-free checks for declared drama plans, never media or aesthetic QA.

The input is a candidate, not an instruction to an editor. These pure functions
do not adopt it, mutate it, load a model, inspect media or certify prose meaning.
Unknown semantics remain review work. Character names are never identity keys.
"""
import copy
import hashlib
import json
import math
import re


CONTENT_SCHEMAS = {'drama-content/0.1-design', 'drama-content/0.1'}
VARIANT_SCHEMAS = {'drama-variant/0.1-design', 'drama-variant/0.1'}
TABLES = {'background': 'background_id', 'entities': 'entity_id',
          'propositions': 'proposition_id', 'events': 'event_id',
          'snapshots': 'snapshot_id', 'scenes': 'scene_id', 'beats': 'beat_id',
          'shots': 'shot_id', 'dialogues': 'dialogue_id', 'assets': 'asset_id'}
BASIS_KINDS = {'authored', 'observed', 'inferred', 'unknown'}
ATTITUDES = {'believes_true', 'believes_false', 'unknown'}


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False)


def _number(value, minimum=0):
    return type(value) in (int, float) and math.isfinite(value) and value >= minimum


def _finding(rule, refs, field, result, evidence, impact=None):
    return {'rule_id': rule, 'object_refs': list(dict.fromkeys(str(x) for x in refs)),
            'field': field, 'method': 'semantic-declaration' if result == 'UNCERTAIN' else 'structure',
            'result': result, 'evidence': evidence,
            'impact': impact or ('revise_declared_plan' if result == 'FAIL' else 'requires_review')}


def _report(findings, **extra):
    return {'schema': 'drama-validation-report/0.1',
            'status': 'FAIL' if any(f['result'] == 'FAIL' for f in findings) else
                      'UNCERTAIN' if any(f['result'] == 'UNCERTAIN' for f in findings) else 'PASS',
            'findings': findings, 'semantic_review': 'NOT_RUN',
            'media_review': 'NOT_RUN', 'host_adoption': 'NOT_RUN', **extra}


def _shape(content):
    """Validate container shape before traversing. No malformed input tracebacks."""
    findings = []
    def fail(path, expected):
        findings.append(_finding('SHAPE', [], path, 'FAIL', 'Expected ' + expected))
    def fields(obj, path, spec):
        if not isinstance(obj, dict):
            fail(path, 'object'); return
        for key, kind in spec.items():
            val = obj.get(key)
            if kind == 'str' and (not isinstance(val, str) or not val): fail(path+'.'+key, 'nonempty string')
            elif kind == 'list' and not isinstance(val, list): fail(path+'.'+key, 'array')
            elif kind == 'dict' and not isinstance(val, dict): fail(path+'.'+key, 'object')
            elif kind == 'number' and not _number(val): fail(path+'.'+key, 'finite nonnegative number')
            elif kind == 'bool' and type(val) is not bool: fail(path+'.'+key, 'boolean')
    if not isinstance(content, dict):
        fail('$', 'object'); return findings
    fields(content, '$', {'schema':'str', 'content_revision':'str', 'authority':'str',
                         'work_binding':'dict', 'task':'dict', 'style_ref':'dict'})
    fields(content.get('task'), 'task', {'mode':'str', 'title':'str', 'constraints':'list',
                                      'preserve':'list', 'target_duration_sec':'number'})
    fields(content.get('style_ref'), 'style_ref', {'profile_id':'str','version':'str','path':'str'})
    fields(content.get('work_binding'), 'work_binding', {'authority_kind':'str'})
    specs = {
        'entities': {'kind':'str', 'name':'str', 'invariants':'list', 'variants':'list'},
        'propositions': {'text':'str', 'story_layer':'str', 'basis':'dict'},
        'events': {'scene_id':'str', 'description':'str', 'causes':'list', 'effects':'list'},
        'snapshots': {'story_position':'number', 'story_layer':'str', 'authority':'str',
                      'entity_state':'dict', 'knowledge':'list', 'foreshadow':'list'},
        'scenes': {'location_id':'str', 'story_position':'number', 'reveal_position':'number',
                   'story_layer':'str', 'purpose':'str', 'pre_state':'str', 'post_state':'str',
                   'context_refs':'list', 'candidate_dependencies':'list', 'delta':'list',
                   'estimated_duration_sec':'number'},
        'beats': {'scene_id':'str', 'required':'bool', 'event_refs':'list'},
        'shots': {'scene_id':'str', 'beat_refs':'list', 'dialogue_refs':'list', 'asset_refs':'list',
                  'visible_characters':'list', 'purpose':'str', 'start':'str', 'action':'str',
                  'end':'str', 'audio_owner':'str', 'estimated_duration_sec':'number'},
        'dialogues': {'speaker_id':'str', 'text':'str', 'shot_refs':'list', 'estimated_speech_sec':'number'},
        'assets': {'kind':'str', 'status':'str', 'entity_or_shot_refs':'list', 'control_scope':'list', 'version':'str'},
        'background': {'text':'str', 'basis':'dict'},
    }
    for table, id_key in TABLES.items():
        rows = content.get(table)
        if not isinstance(rows, list):
            fail(table, 'array'); continue
        for i, row in enumerate(rows):
            path = '%s[%d]' % (table, i)
            fields(row, path, {id_key:'str', **specs[table]})
            if not isinstance(row, dict): continue
            for key in ('causes', 'background_refs', 'context_refs', 'candidate_dependencies',
                        'event_refs', 'beat_refs', 'dialogue_refs', 'asset_refs', 'shot_refs',
                        'visible_characters', 'entity_or_shot_refs', 'control_scope'):
                if key in row and (not isinstance(row[key], list) or
                                   not all(isinstance(x, str) and x for x in row[key])):
                    fail(path+'.'+key, 'array of nonempty strings')
            if table == 'entities':
                for j, variant in enumerate(row.get('variants', []) if isinstance(row.get('variants'), list) else []):
                    fields(variant, path+'.variants[%d]' % j, {'variant_id':'str'})
            if table == 'snapshots':
                for eid, state in (row.get('entity_state', {}).items() if isinstance(row.get('entity_state'), dict) else []):
                    if not isinstance(state, dict): fail(path+'.entity_state.'+str(eid), 'object')
                    else:
                        for key in ('custodian','location_id','variant_id'):
                            if key in state and not isinstance(state[key],str): fail(path+'.entity_state.'+str(eid)+'.'+key,'string')
                for j, item in enumerate(row.get('knowledge', []) if isinstance(row.get('knowledge'), list) else []):
                    fields(item, path+'.knowledge[%d]' % j,
                           {'holder_id':'str', 'proposition_id':'str', 'attitude':'str', 'basis_kind':'str', 'basis_event_refs':'list'})
                    if isinstance(item, dict) and isinstance(item.get('basis_event_refs'), list) and not all(isinstance(x, str) for x in item['basis_event_refs']):
                        fail(path+'.knowledge.basis_event_refs', 'array of strings')
                for j, item in enumerate(row.get('foreshadow', []) if isinstance(row.get('foreshadow'), list) else []):
                    fields(item, path+'.foreshadow[%d]' % j, {'foreshadow_id':'str', 'status':'str', 'event_refs':'list'})
                    if isinstance(item,dict) and isinstance(item.get('event_refs'),list) and not all(isinstance(x,str) for x in item['event_refs']):
                        fail(path+'.foreshadow.event_refs','array of strings')
            if table == 'scenes':
                for j, delta in enumerate(row.get('delta', []) if isinstance(row.get('delta'), list) else []):
                    fields(delta, path+'.delta[%d]' % j, {'target':'str', 'event_refs':'list', 'story_layer':'str'})
                    if isinstance(delta, dict) and ('before' not in delta or 'after' not in delta):
                        fail(path+'.delta[%d]' % j, 'before and after values')
                    if isinstance(delta,dict) and isinstance(delta.get('event_refs'),list) and not all(isinstance(x,str) for x in delta['event_refs']):
                        fail(path+'.delta.event_refs','array of strings')
    return findings


def _state_value(snapshot, target):
    owner, _, field = target.partition('.')
    if owner in snapshot['entity_state'] and field in snapshot['entity_state'][owner]:
        return True, snapshot['entity_state'][owner][field]
    for item in snapshot['knowledge']:
        if item['holder_id'] == owner and item['proposition_id'] == field:
            return True, item['attitude']
    for item in snapshot['foreshadow']:
        if item['foreshadow_id'] == owner and field in item:
            return True, item[field]
    return False, None


def _binding_shape(binding):
    return (isinstance(binding, dict) and isinstance(binding.get('path'), str)
            and bool(binding['path']) and isinstance(binding.get('sha256'), str)
            and bool(re.fullmatch(r'[0-9a-f]{64}', binding['sha256']))
            and type(binding.get('size_bytes')) is int and binding['size_bytes'] >= 0)


def validate_content(content):
    """Check declared identity, references, state, chronology and planning budgets.

    An actual binding is checked for shape only. Its bytes and media must be
    checked at the adoption/media boundary. PASS never promotes review_scope.
    """
    findings = _shape(content)
    if findings: return _report(findings)
    def add(rule, refs, field, evidence, result='FAIL'):
        findings.append(_finding(rule, refs, field, result, evidence))
    try:
        _canonical(content)
    except (ValueError, TypeError):
        add('JSON_VALUE', [], '$', 'Input must contain finite JSON values')
        return _report(findings)
    if content['schema'] not in CONTENT_SCHEMAS:
        add('SCHEMA', [], 'schema', 'Unsupported content schema')
    for table in ('scenes','shots'):
        if not content[table]: add('EMPTY_PLAN', [], table, 'A complete drama plan requires scenes and shots')
    if content['work_binding'].get('authority_kind')=='unbound_design' and any(content['work_binding'].get(k) is not None for k in ('work_id','revision_id','adoption_receipt')):
        add('WORK_BINDING_CONTRADICTION', [], 'work_binding', 'Unbound design cannot claim actual work adoption')
    tables, ids = {}, set()
    for table, id_key in TABLES.items():
        tables[table] = {}
        for row in content[table]:
            ident = row[id_key]
            if ident in ids: add('DUPLICATE_ID', [ident], table, 'Stable IDs must be unique across typed objects')
            ids.add(ident); tables[table][ident] = row
    entities = tables['entities']; scenes = tables['scenes']; snapshots = tables['snapshots']
    events = tables['events']; shots = tables['shots']; assets = tables['assets']
    propositions = tables['propositions']; beats = tables['beats']; dialogues = tables['dialogues']
    variants = {}
    for eid, ent in entities.items():
        if ent['kind'] not in {'character', 'location', 'prop'}: add('ENTITY_KIND', [eid], 'kind', 'Unsupported entity kind')
        for variant in ent['variants']:
            vid = variant['variant_id']
            if vid in ids or vid in variants: add('DUPLICATE_ID', [vid], 'variants', 'Duplicate variant ID')
            variants[vid] = eid
    foreshadow_ids = {f['foreshadow_id'] for s in snapshots.values() for f in s['foreshadow']}
    all_refs = ids | set(variants) | foreshadow_ids
    def ref(value, pool, owner, field, kind=None):
        if not isinstance(value, str) or value not in pool:
            add('DANGLING_REFERENCE', [owner, value], field, 'Reference does not resolve in expected object table'); return False
        if kind and pool[value].get('kind') != kind:
            add('REFERENCE_KIND', [owner, value], field, 'Expected '+kind); return False
        return True
    for table in ('background', 'propositions', 'events'):
        for obj in tables[table].values():
            basis = obj.get('basis')
            if basis is not None and (not isinstance(basis, dict) or basis.get('kind') not in BASIS_KINDS):
                add('BASIS_KIND', [obj[TABLES[table]]], 'basis', 'Explicit authored/observed/inferred/unknown basis required')
            elif isinstance(basis, dict):
                if basis.get('reference') is not None: ref(basis['reference'], all_refs, obj[TABLES[table]], 'basis.reference')
                if basis.get('kind') == 'observed' and not _binding_shape(basis.get('actual_binding')):
                    add('OBSERVATION_UNBOUND', [obj[TABLES[table]]], 'basis', 'Observed media claim lacks byte-bound evidence', 'UNCERTAIN')
    for pid, prop in propositions.items():
        if prop.get('truth') not in (True, False, 'unknown') or type(prop.get('truth')) not in (bool, str):
            add('TRUTH_VALUE', [pid], 'truth', 'Use boolean true/false or unknown, separately from holder attitude')
        if prop.get('valid_from_event') is not None: ref(prop['valid_from_event'], events, pid, 'valid_from_event')
    for eid, event in events.items():
        ref(event['scene_id'], scenes, eid, 'scene_id')
        for causal in event['causes']: ref(causal, events, eid, 'causes')
        for bg in event.get('background_refs', []): ref(bg, tables['background'], eid, 'background_refs')
    # Cycles cannot be resolved by a forward-only context closure. Narrative
    # nonlinear presentation is expressed by reveal_position, not causal loops.
    def visit_event(eid, path, complete):
        if eid in path:
            add('CAUSAL_CYCLE', path+[eid], 'events.causes', 'Causal dependency cycle'); return
        if eid in complete or eid not in events: return
        for cause in events[eid]['causes']: visit_event(cause,path+[eid],complete)
        complete.add(eid)
    complete=set()
    for eid in events: visit_event(eid,[],complete)
    for bid, beat in beats.items():
        ref(beat['scene_id'], scenes, bid, 'scene_id')
        for event in beat['event_refs']: ref(event, events, bid, 'event_refs')
    for aid, asset in assets.items():
        for target in asset['entity_or_shot_refs']: ref(target, all_refs, aid, 'entity_or_shot_refs')
        if asset['status'] not in {'planned', 'reference_available', 'take_candidate', 'selected'}:
            add('ASSET_STATUS', [aid], 'status', 'Unsupported asset status')
        binding = asset.get('actual_binding')
        if asset['status'] == 'planned' and binding is not None:
            add('PLANNED_BINDING', [aid], 'actual_binding', 'Planned requirements cannot claim actual media binding')
        if asset['status'] != 'planned' and not _binding_shape(binding):
            add('ASSET_BINDING_REQUIRED', [aid], 'actual_binding', 'Actual asset needs path, sha256 and size_bytes; a path string is insufficient')
    covered = set()
    dialogue_uses = {did: set() for did in dialogues}
    planned_cursor=0
    for sid, shot in shots.items():
        ref(shot['scene_id'], scenes, sid, 'scene_id')
        for bid in shot['beat_refs']:
            if ref(bid, beats, sid, 'beat_refs'):
                covered.add(bid)
                if beats[bid]['scene_id'] != shot['scene_id']: add('BEAT_SCENE', [sid, bid], 'beat_refs', 'Beat belongs to a different scene')
        for did in shot['dialogue_refs']:
            if ref(did, dialogues, sid, 'dialogue_refs'): dialogue_uses[did].add(sid)
        for aid in shot['asset_refs']: ref(aid, assets, sid, 'asset_refs')
        for cid in shot.get('visible_characters', []): ref(cid, entities, sid, 'visible_characters', 'character')
        for field in ('location_id', 'end_location_id'):
            if field in shot: ref(shot[field], entities, sid, field, 'location')
        if not _number(shot['estimated_duration_sec'], 1e-12): add('DURATION_POSITIVE', [sid], 'estimated_duration_sec', 'Shot duration must be positive')
        ranges = shot.get('planned_range_sec')
        if ranges is not None and (not isinstance(ranges, list) or len(ranges) != 2 or
                not all(_number(x) for x in ranges) or abs(ranges[1]-ranges[0]-shot['estimated_duration_sec']) > 1e-6):
            add('SHOT_RANGE', [sid], 'planned_range_sec', 'Range must match estimated shot duration')
        elif ranges is not None and abs(ranges[0]-planned_cursor)>1e-6:
            add('SHOT_RANGE_ORDER', [sid], 'planned_range_sec',
                {'expected_start':planned_cursor,'declared_start':ranges[0],
                 'reason':'A complete ordered shot plan cannot overlap or silently leave an uncovered gap'})
        planned_cursor+=shot['estimated_duration_sec']
        actual = shot.get('actual_duration_sec')
        media = [a for a in assets.values() if a['kind']=='shot_take' and sid in a['entity_or_shot_refs'] and _binding_shape(a.get('actual_binding'))]
        if actual is not None and (not _number(actual, 1e-12) or not (media or _binding_shape(shot.get('actual_binding')))):
            add('MEASUREMENT_UNBOUND', [sid], 'actual_duration_sec', 'Actual duration requires a byte-bound take and valid duration')
        bindings = shot.get('reference_bindings', [])
        if not isinstance(bindings, list):
            add('REFERENCE_BINDING_SHAPE', [sid], 'reference_bindings', 'Expected list'); bindings=[]
        for binding in bindings:
            if not isinstance(binding, dict): add('REFERENCE_BINDING_SHAPE', [sid], 'reference_bindings', 'Expected object'); continue
            aid, eid = binding.get('asset_id'), binding.get('entity_id')
            if ref(aid, assets, sid, 'reference_bindings.asset_id') and ref(eid, entities, sid, 'reference_bindings.entity_id'):
                scope = binding.get('control_scope', [])
                if not isinstance(scope, list) or not all(isinstance(x,str) for x in scope):
                    add('REFERENCE_BINDING_SHAPE', [sid, aid], 'control_scope', 'Expected string list'); continue
                if not set(scope).issubset(assets[aid]['control_scope']): add('REFERENCE_CONTROL_SCOPE', [sid, aid], 'control_scope', 'Binding requests undeclared control dimensions')
                if set(scope) & {'identity', 'costume', 'prop_identity', 'voice_identity'} and eid not in assets[aid]['entity_or_shot_refs']:
                    add('REFERENCE_IDENTITY_MISMATCH', [sid, eid, aid], 'reference_bindings', 'Declared controlled entity differs from reference owner')
    for bid, beat in beats.items():
        if beat['required'] and bid not in covered: add('REQUIRED_BEAT_UNCOVERED', [bid], 'beat_refs', 'Required beat has no shot coverage')
    for did, dialogue in dialogues.items():
        ref(dialogue['speaker_id'], entities, did, 'speaker_id', 'character')
        for sid in dialogue['shot_refs']: ref(sid, shots, did, 'shot_refs')
        if set(dialogue['shot_refs']) != dialogue_uses[did]: add('DIALOGUE_BACKREFERENCE', [did], 'shot_refs', 'Dialogue and shot references must agree')
        measured = dialogue.get('measured_speech_sec')
        media = [a for a in assets.values() if a['kind']=='dialogue_audio' and did in a['entity_or_shot_refs'] and _binding_shape(a.get('actual_binding'))]
        if measured is not None and (not _number(measured) or not media): add('MEASUREMENT_UNBOUND', [did], 'measured_speech_sec', 'Measured speech needs byte-bound dialogue audio')
    for sid, shot in shots.items():
        # Only fully contained lines can be summed without double-counting split lines.
        contained = [dialogues[d] for d in shot['dialogue_refs'] if d in dialogues and dialogues[d]['shot_refs']==[sid]]
        speech = sum(d['estimated_speech_sec'] for d in contained)
        if speech > shot['estimated_duration_sec']+1e-6:
            add('SPEECH_PLAN_CAPACITY', [sid]+[d['dialogue_id'] for d in contained], 'estimated_speech_sec',
                {'estimated_speech_sec':speech, 'shot_budget_sec':shot['estimated_duration_sec'],
                 'action':'Reconsider duration, wording or performance; do not silently truncate or speed up.'}, 'UNCERTAIN')
    for sid, scene in scenes.items():
        ref(scene['location_id'], entities, sid, 'location_id', 'location')
        for target in scene['context_refs']: ref(target, all_refs, sid, 'context_refs')
        for target in scene['candidate_dependencies']:
            if ref(target, scenes, sid, 'candidate_dependencies') and scenes[target]['reveal_position'] >= scene['reveal_position']:
                add('CANDIDATE_DEPENDENCY_ORDER', [sid,target], 'candidate_dependencies', 'Candidate dependencies must precede this scene')
        pre_ok = ref(scene['pre_state'], snapshots, sid, 'pre_state'); post_ok = ref(scene['post_state'], snapshots, sid, 'post_state')
        if pre_ok and post_ok:
            pre, post = snapshots[scene['pre_state']], snapshots[scene['post_state']]
            if pre['story_layer'] != scene['story_layer'] or post['story_layer'] != scene['story_layer']:
                add('SCENE_STATE_LAYER', [sid, pre['snapshot_id'], post['snapshot_id']], 'story_layer', 'Scene state must use its own narrative layer')
            if pre['story_position']>=scene['story_position'] or post['story_position']!=scene['story_position']:
                add('SCENE_STATE_POSITION',[sid,pre['snapshot_id'],post['snapshot_id']],'story_position',
                    {'pre':pre['story_position'],'scene':scene['story_position'],'post':post['story_position'],
                     'convention':'Pre-state precedes the scene; post-state marks this scene story position'})
            if pre['authority']=='candidate_dependency':
                producers={s['scene_id'] for s in scenes.values() if s['post_state']==pre['snapshot_id'] and s['scene_id']!=sid}
                if len(producers)!=1 or not producers.issubset(scene['candidate_dependencies']):
                    add('CANDIDATE_PRESTATE_DEPENDENCY',[sid,pre['snapshot_id']]+sorted(producers),
                        'candidate_dependencies','A candidate pre-state needs one declared producing scene in this candidate chain')
            targets = set()
            for delta in scene['delta']:
                target = delta['target']
                if target in targets: add('DUPLICATE_DELTA', [sid,target], 'delta', 'A field must have one scene-level net delta')
                targets.add(target)
                if delta['story_layer'] != scene['story_layer']: add('DELTA_LAYER', [sid,target], 'delta.story_layer', 'Delta cannot silently update another narrative layer')
                for event in delta['event_refs']: ref(event, events, sid, 'delta.event_refs')
                for label, snapshot in (('before', pre), ('after', post)):
                    found, value = _state_value(snapshot, target)
                    if not found or value != delta[label]:
                        add('STATE_DELTA_MISMATCH', [sid, snapshot['snapshot_id'], target.split('.')[0]]+delta['event_refs'],
                            'delta.'+label, {'target':target,'declared':delta[label],'snapshot_value':value,'field_present':found})
            for eid in set(pre['entity_state']) & set(post['entity_state']):
                before_fields,after_fields=pre['entity_state'][eid],post['entity_state'][eid]
                for field in set(before_fields) & set(after_fields):
                    target=eid+'.'+field
                    if before_fields[field]!=after_fields[field] and target not in targets:
                        add('STATE_CHANGE_WITHOUT_DELTA',[sid,eid,pre['snapshot_id'],post['snapshot_id']],
                            'delta',{'target':target,'before':before_fields[field],'after':after_fields[field],
                                     'reason':'A changed physical field shared by both snapshots needs an explicit scene delta'})
                if set(before_fields)!=set(after_fields):
                    add('STATE_FIELD_COVERAGE_CHANGED',[sid,eid],'entity_state',
                        {'added':sorted(set(after_fields)-set(before_fields)),
                         'removed':sorted(set(before_fields)-set(after_fields)),
                         'reason':'New or omitted state fields do not establish a known before/after change'},'UNCERTAIN')
        actual_sum = sum(s['estimated_duration_sec'] for s in shots.values() if s['scene_id']==sid)
        if abs(actual_sum-scene['estimated_duration_sec']) > 1e-6:
            add('SCENE_DURATION', [sid], 'estimated_duration_sec', {'shot_total':actual_sum,'scene_total':scene['estimated_duration_sec']})
    total = sum(s['estimated_duration_sec'] for s in shots.values())
    if abs(total-content['task']['target_duration_sec']) > 1e-6:
        add('TOTAL_DURATION_PLAN', [], 'task.target_duration_sec', {'shot_total':total,'target':content['task']['target_duration_sec']}, 'UNCERTAIN')
    for sid, snapshot in snapshots.items():
        if snapshot['authority'] not in {'fixture_assumed','candidate_dependency','bound_revision'}: add('SNAPSHOT_AUTHORITY', [sid], 'authority', 'Unknown authority kind')
        if snapshot['authority']=='bound_revision' and not all(content['work_binding'].get(k) for k in ('work_id','revision_id','adoption_receipt')):
            add('UNBOUND_AUTHORITY', [sid], 'authority', 'Bound revision requires explicit work and adoption provenance')
        for eid, state in snapshot['entity_state'].items():
            ref(eid, entities, sid, 'entity_state')
            if 'custodian' in state: ref(state['custodian'], entities, sid, 'entity_state.custodian', 'character')
            if 'location_id' in state: ref(state['location_id'], entities, sid, 'entity_state.location_id', 'location')
            if 'variant_id' in state and (state['variant_id'] not in variants or variants[state['variant_id']] != eid):
                add('VARIANT_OWNER', [sid, eid, state['variant_id']], 'entity_state.variant_id', 'Variant belongs to another or missing entity')
        seen_knowledge = set()
        for knowledge in snapshot['knowledge']:
            holder, pid = knowledge['holder_id'], knowledge['proposition_id']; key=(holder,pid)
            if key in seen_knowledge: add('DUPLICATE_KNOWLEDGE', [sid,holder,pid], 'knowledge', 'One attitude per holder/proposition/snapshot')
            seen_knowledge.add(key)
            if holder != 'AUDIENCE': ref(holder, entities, sid, 'knowledge.holder_id', 'character')
            ref(pid, propositions, sid, 'knowledge.proposition_id')
            if knowledge['attitude'] not in ATTITUDES: add('ATTITUDE', [sid,holder,pid], 'knowledge.attitude', 'Invalid attitude')
            if knowledge['basis_kind'] not in BASIS_KINDS: add('BASIS_KIND', [sid,holder,pid], 'knowledge.basis_kind', 'Invalid basis kind')
            for eid in knowledge['basis_event_refs']:
                if not ref(eid, events, sid, 'knowledge.basis_event_refs'): continue
                event_scene=scenes.get(events[eid]['scene_id'])
                if event_scene and event_scene['story_layer']==snapshot['story_layer'] and event_scene['story_position'] > snapshot['story_position']:
                    add('FUTURE_EVENT_AS_EVIDENCE', [sid,holder,pid,eid], 'knowledge.basis_event_refs', 'A future event cannot be evidence already available at this snapshot')
                if knowledge['basis_kind']=='observed' and holder!='AUDIENCE':
                    associated = {b['beat_id'] for b in beats.values() if eid in b['event_refs']}
                    visible = {c for sh in shots.values() if associated.intersection(sh['beat_refs']) for c in sh.get('visible_characters',[])}
                    # Visibility in a shot that also covers the event does not
                    # establish who witnessed its particular instant.
                    if holder not in visible or not _binding_shape(knowledge.get('observation_evidence')):
                        add('WITNESS_NOT_ESTABLISHED', [sid,holder,pid,eid], 'knowledge.basis_event_refs',
                            'Declared direct observation is not established by shot visibility; inspect background, offscreen access and source evidence.', 'UNCERTAIN')
            certainty = knowledge.get('certainty')
            if holder=='AUDIENCE' and certainty in ('certain','proven') and knowledge['attitude']!='unknown':
                if knowledge['basis_kind'] in {'inferred','unknown'} or not knowledge.get('certainty_evidence'):
                    add('AUDIENCE_CERTAINTY_UNSUPPORTED', [sid,holder,pid], 'knowledge.certainty', 'A declared certainty needs explicit evidence and semantic adjudication; author truth alone is insufficient.', 'UNCERTAIN')
        for f in snapshot['foreshadow']:
            for eid in f['event_refs']: ref(eid, events, sid, 'foreshadow.event_refs')
    return _report(findings, counts={table:len(content[table]) for table in TABLES},
                   estimated_duration_sec=total, binding_validation='SHAPE_ONLY',
                   limitations=['No free-text causal or character-intent adjudication',
                                'No image, voice, performance or aesthetic inspection',
                                'No media bytes verified; no adoption performed'])


def assemble_context(content, scene_id, budget_chars, source_sha256=None, resources=None):
    """Assemble one scene with complete hard context; never silently trim it.

    Unicode codepoints in canonical compact JSON are the budget unit, not tokens.
    A rejected payload is still returned intact for inspection, with sendable=False.
    The caller-supplied byte hash is provenance, not verified by this pure function.
    """
    validation = validate_content(content)
    if validation['status']=='FAIL': return {**validation, 'sendable':False, 'payload':None}
    findings=copy.deepcopy(validation['findings'])
    if type(budget_chars) is not int or budget_chars < 0:
        return _report([_finding('CONTEXT_BUDGET', [], 'budget_chars', 'FAIL', 'Nonnegative integer required')], sendable=False, payload=None)
    scenes = {s['scene_id']:s for s in content['scenes']}
    if scene_id not in scenes:
        return _report([_finding('CONTEXT_SCENE', [scene_id], 'scene_id', 'FAIL', 'Unknown scene')], sendable=False, payload=None)
    if source_sha256 is not None and (not isinstance(source_sha256,str) or not re.fullmatch(r'[0-9a-f]{64}', source_sha256)):
        return _report([_finding('SOURCE_SHA256', [], 'source_sha256', 'FAIL', 'Expected SHA256 hex')], sendable=False, payload=None)
    scene=scenes[scene_id]; snapshots={s['snapshot_id']:s for s in content['snapshots']}
    pre=snapshots[scene['pre_state']]
    # The first assembler deliberately supports a bounded set of cross-scene
    # dependencies. Other declared context objects are rejected, never silently
    # treated as optional/excluded. Callers may split the task or extend this
    # contract explicitly rather than hiding an unsupported required reference.
    supported_context={r[TABLES[table]] for table in ('background','entities','propositions','events') for r in content[table]}
    supported_context.update(f['foreshadow_id'] for f in pre['foreshadow'])
    unsupported=set(scene['context_refs'])-supported_context
    if unsupported:
        findings.append(_finding('CONTEXT_REFERENCE_UNSUPPORTED',[scene_id]+sorted(unsupported),'context_refs','FAIL',
                                 'Required cross-scene shot/scene/asset/dialogue/snapshot context is not supported by this assembler; no context was emitted.'))
        return _report(findings,scene_id=scene_id,sendable=False,ready_for_generation=False,payload=None,
                       unsupported_required_refs=sorted(unsupported),excluded=[])
    refs=set(scene['context_refs']) | set(pre['entity_state']) | {scene['location_id']}
    selected_shots=[s for s in content['shots'] if s['scene_id']==scene_id]
    asset_ids={aid for s in selected_shots for aid in s['asset_refs']}
    selected_assets=[a for a in content['assets'] if a['asset_id'] in asset_ids]
    refs.update(r for a in selected_assets for r in a['entity_or_shot_refs'])
    refs.update(v['location_id'] for v in pre['entity_state'].values() if 'location_id' in v)
    refs.update(k['proposition_id'] for k in pre['knowledge'])
    required_events={e for k in pre['knowledge'] for e in k['basis_event_refs']}
    required_events.update(e['event_id'] for e in content['events'] if e['event_id'] in scene['context_refs'])
    required_events.update(e for f in pre['foreshadow'] for e in f['event_refs'])
    required_events.update(e['event_id'] for e in content['events'] if e['scene_id']==scene_id)
    events={e['event_id']:e for e in content['events']}
    supported_objects={r[TABLES[table]]:r for table in ('background','entities','propositions','events') for r in content[table]}
    pending=list(refs | required_events)
    visited=set()
    while pending:
        ident=pending.pop()
        if ident in visited: continue
        visited.add(ident)
        obj=supported_objects.get(ident)
        if obj is None: continue
        refs.add(ident)
        if ident in events: required_events.add(ident)
        required=[]
        if isinstance(obj.get('basis'),dict) and obj['basis'].get('reference') is not None:
            required.append(obj['basis']['reference'])
        if ident in events:
            required.extend(obj['causes']);required.extend(obj.get('background_refs',[]))
        for target in required:
            if target not in supported_context:
                findings.append(_finding('CONTEXT_REFERENCE_UNSUPPORTED',[scene_id,ident,str(target)],'basis.reference','FAIL',
                                         'A required source reference is unsupported; no partially assembled context was emitted.'))
            elif target not in visited:
                pending.append(target)
    if any(f['result']=='FAIL' for f in findings):
        return _report(findings,scene_id=scene_id,sendable=False,ready_for_generation=False,payload=None,excluded=[])
    prior=[scenes[x] for x in scene['candidate_dependencies']]
    payload={'task':content['task'], 'work_binding':content['work_binding'], 'scene':scene,
             'pre_state':pre, 'planned_post_state':snapshots[scene['post_state']],
             'candidate_dependencies':[{'scene_id':s['scene_id'],'pre_state':s['pre_state'],
                 'post_state':s['post_state'],'delta':s['delta']} for s in prior],
             'background':[x for x in content['background'] if x['background_id'] in refs],
             'entities':[x for x in content['entities'] if x['entity_id'] in refs],
             'propositions':[x for x in content['propositions'] if x['proposition_id'] in refs],
             'events':[x for x in content['events'] if x['event_id'] in required_events],
             'event_availability':[{'event_id':eid,
                                    'availability':'future_authored_plan_not_current_evidence' if
                                    scenes[events[eid]['scene_id']]['story_layer']==pre['story_layer'] and
                                    scenes[events[eid]['scene_id']]['story_position']>pre['story_position'] else
                                    'declared_story_context_not_verified_media'} for eid in sorted(required_events)],
             'beats':[x for x in content['beats'] if x['scene_id']==scene_id],
             'shots':selected_shots,
             'dialogues':[x for x in content['dialogues'] if set(x['shot_refs']) & {s['shot_id'] for s in selected_shots}],
             'assets':selected_assets, 'style_ref':content['style_ref']}
    style_path=content['style_ref'].get('path')
    resources=resources if isinstance(resources,dict) else {}
    style_text=resources.get(style_path) if isinstance(style_path,str) else None
    missing_resources=[]
    if not isinstance(style_text,str) or not style_text.strip():
        missing_resources.append(style_path)
        findings.append(_finding('CONTEXT_RESOURCE_REQUIRED',[scene_id],'style_ref.path','UNCERTAIN',
                                 'Load the referenced style mechanisms as UTF8 text before generation; a path is not the document.'))
    else:
        payload['style_document']={'path':style_path,'text':style_text,'encoding':'utf-8',
                                  'sha256':hashlib.sha256(style_text.encode('utf-8')).hexdigest(),
                                  'size_bytes':len(style_text.encode('utf-8'))}
    payload=copy.deepcopy(payload)
    encoded=_canonical(payload); measured=len(encoded)
    if measured>budget_chars:
        findings.append(_finding('CONTEXT_BUDGET_EXCEEDED', [scene_id], 'budget_chars', 'FAIL',
                        {'required_chars':measured,'budget_chars':budget_chars,'excess_chars':measured-budget_chars,
                         'action':'Increase the budget or explicitly split the scene; required context was not removed.'}))
    kept={r[TABLES[k]] for k in TABLES if k in payload and isinstance(payload[k],list)
          for r in payload[k] if TABLES[k] in r}
    excluded=[{'object_ref':r[TABLES[k]],'reason':'Outside this scene and its declared prerequisite closure'}
              for k in TABLES for r in content[k] if r[TABLES[k]] not in kept and
              r[TABLES[k]] not in {scene_id,scene['pre_state'],scene['post_state']}]
    return _report(findings, schema='drama-context-receipt/0.1', scene_id=scene_id,
                   source={'content_revision':content['content_revision'], 'sha256':source_sha256,
                           'sha256_kind':'caller_supplied_file_bytes_unverified' if source_sha256 else 'not_provided',
                           'canonical_content_sha256':hashlib.sha256(_canonical(content).encode('utf-8')).hexdigest()},
                   authority=pre['authority'], payload=payload, sendable=not findings,
                   budget={'unit':'unicode_codepoints_compact_sorted_json','limit':budget_chars,
                           'actual':measured,'truncated':False}, excluded=excluded,
                   required_refs=sorted(kept | {scene_id,scene['pre_state'],scene['post_state']}),
                   source_validation=validation['status'],
                   ready_for_generation=not findings,
                   needs_external_resources=missing_resources,
                   generation_readiness_reason='Declared required context assembled; creative quality remains unreviewed' if not findings else 'Resolve reported context or source issues',
                   external_resources=[{'path':style_path,
                                        'status':'LOADED_UTF8_TEXT' if not missing_resources else 'REFERENCE_ONLY_NOT_LOADED',
                                        'purpose':'Style mechanisms for creative generation'}])


def validate_variant(content, variant):
    """Validate a local leaf replacement without rewriting the current world."""
    base=validate_content(content)
    if base['status']=='FAIL': return base
    findings=copy.deepcopy(base['findings'])
    def add(rule, refs, field, evidence, result='FAIL'):
        findings.append(_finding(rule, refs, field, result, evidence))
    if not isinstance(variant,dict) or not isinstance(variant.get('schema'),str) or variant.get('schema') not in VARIANT_SCHEMAS:
        return _report([_finding('VARIANT_SCHEMA', [], 'schema', 'FAIL', 'Unsupported variant schema')])
    if variant.get('base_content_revision') != content['content_revision']:
        add('VARIANT_BASE_CONFLICT', [], 'base_content_revision', 'Variant must be rebased on this content revision')
    edit=variant.get('edit'); leaves=variant.get('leaf_shots'); states=variant.get('boundary_states')
    if not isinstance(edit,dict) or not isinstance(leaves,list) or not leaves or not isinstance(states,list):
        add('VARIANT_SHAPE', [], 'edit/leaf_shots/boundary_states', 'Expected edit object, nonempty leaf list and boundary state list'); return _report(findings)
    if not isinstance(edit.get('replaces_shot_ref'),str):
        add('VARIANT_SHAPE', [], 'edit.replaces_shot_ref', 'Expected source ID string'); return _report(findings)
    required=('shot_id','scene_id','location_id','story_layer','boundary_state_ref','estimated_duration_sec','reveal_range_sec','beat_refs','dialogue_refs','asset_refs')
    for leaf in leaves:
        if not isinstance(leaf,dict) or any(k not in leaf for k in required):
            add('VARIANT_LEAF_SHAPE', [], 'leaf_shots', 'Missing leaf fields'); return _report(findings)
        if not all(isinstance(leaf[k],str) for k in required[:5]) or not _number(leaf['estimated_duration_sec'],1e-12):
            add('VARIANT_LEAF_SHAPE', [], 'leaf_shots', 'Invalid leaf identifiers or duration'); return _report(findings)
        for key in ('beat_refs','dialogue_refs','asset_refs'):
            if not isinstance(leaf[key],list) or not all(isinstance(x,str) for x in leaf[key]):
                add('VARIANT_LEAF_SHAPE', [], key, 'Expected string list'); return _report(findings)
    if any(not isinstance(s,dict) or not isinstance(s.get('snapshot_id'),str) or not isinstance(s.get('entity_state'),dict) for s in states):
        add('BOUNDARY_SHAPE', [], 'boundary_states', 'Expected identified state objects'); return _report(findings)
    shots={s['shot_id']:s for s in content['shots']}; source=shots.get(edit.get('replaces_shot_ref'))
    if source is None:
        add('VARIANT_SOURCE', [], 'edit.replaces_shot_ref', 'Missing source shot'); return _report(findings)
    source_id=source['shot_id']; scene=next(s for s in content['scenes'] if s['scene_id']==source['scene_id'])
    if edit.get('composition')!='replace_with_leaf_shots' or edit.get('count_source_group_duration') is not False or edit.get('source_group_id')!=source_id:
        add('VARIANT_DOUBLE_COUNT', [source_id], 'edit', 'Replace source with leaves; never count the source group again')
    leaf_ids=[s['shot_id'] for s in leaves]
    if len(set(leaf_ids))!=len(leaf_ids) or set(leaf_ids)&set(shots):
        add('VARIANT_DUPLICATE_ID', leaf_ids, 'leaf_shots.shot_id', 'Leaf IDs must be unique and separate from source IDs')
    boundary={s['snapshot_id']:s for s in states}
    if len(boundary)!=len(states): add('BOUNDARY_DUPLICATE', [], 'boundary_states', 'Duplicate boundary ID')
    new_beats=variant.get('new_beats',[]); new_events=variant.get('new_events',[]); new_assets=variant.get('new_assets',[])
    for key,rows,id_key in (('new_beats',new_beats,'beat_id'),('new_events',new_events,'event_id'),('new_assets',new_assets,'asset_id')):
        if not isinstance(rows,list) or any(not isinstance(x,dict) or not isinstance(x.get(id_key),str) for x in rows):
            add('VARIANT_EXTENSION_SHAPE', [], key, 'Expected identified objects'); return _report(findings)
        known={x[id_key] for x in content[{'new_beats':'beats','new_events':'events','new_assets':'assets'}[key]]}
        added=[x[id_key] for x in rows]
        if len(set(added))!=len(added) or set(added)&known: add('VARIANT_DUPLICATE_ID', added, key, 'New IDs overlap or repeat')
    global_base_ids={row[id_key] for table,id_key in TABLES.items() for row in content[table]}
    global_base_ids.update(v['variant_id'] for e in content['entities'] for v in e['variants'])
    global_base_ids.update(f['foreshadow_id'] for s in content['snapshots'] for f in s['foreshadow'])
    extension_ids=leaf_ids+[s['snapshot_id'] for s in states]+[b['beat_id'] for b in new_beats]+[e['event_id'] for e in new_events]+[a['asset_id'] for a in new_assets]
    if len(set(extension_ids))!=len(extension_ids) or global_base_ids.intersection(extension_ids):
        add('VARIANT_GLOBAL_ID_COLLISION',sorted(set(extension_ids)),'variant',
            'Every new leaf, boundary, beat, event and asset needs a globally distinct stable ID')
    global_refs=global_base_ids|set(extension_ids)
    for beat in new_beats:
        if not isinstance(beat.get('event_refs'),list) or not all(isinstance(x,str) for x in beat['event_refs']):
            add('VARIANT_EXTENSION_SHAPE',[beat['beat_id']],'event_refs','Expected event ID list'); return _report(findings)
        if beat.get('scene_id')!=source['scene_id']:
            add('VARIANT_SCENE',[beat['beat_id'],str(beat.get('scene_id'))],'new_beats.scene_id','New local-insert beat must belong to the source scene')
    for event in new_events:
        eid=event['event_id']
        if event.get('scene_id')!=source['scene_id']:
            add('VARIANT_SCENE',[eid,str(event.get('scene_id'))],'new_events.scene_id','New local-insert event must belong to the source scene')
        basis=event.get('basis')
        if not isinstance(basis,dict) or basis.get('kind') not in BASIS_KINDS:
            add('BASIS_KIND',[eid],'new_events.basis','New event needs explicit authored/observed/inferred/unknown basis')
        elif basis.get('reference') is not None:
            value=basis['reference']
            if not isinstance(value,str) or value not in global_refs:
                add('DANGLING_REFERENCE',[eid,str(value)],'new_events.basis.reference','Unresolved new event source')
        if not isinstance(event.get('story_layer'),str) or not event['story_layer']:
            add('VARIANT_EXTENSION_SHAPE',[eid],'new_events.story_layer','New event must declare its narrative layer')
    for asset in new_assets:
        status=asset.get('status');binding=asset.get('actual_binding')
        if status not in ('planned','reference_available','take_candidate','selected') or (status!='planned' and not _binding_shape(binding)):
            add('ASSET_BINDING_REQUIRED',[asset['asset_id']],'actual_binding','Actual asset requires byte binding; unknown status rejected')
        if status=='planned' and binding is not None:
            add('PLANNED_BINDING',[asset['asset_id']],'actual_binding','Planned asset cannot claim actual binding')
    beat_ids={b['beat_id'] for b in content['beats']+new_beats}
    asset_ids={a['asset_id'] for a in content['assets']+new_assets}
    event_ids={e['event_id'] for e in content['events']+new_events}
    dialogue_ids={d['dialogue_id'] for d in content['dialogues']}
    locations={e['entity_id'] for e in content['entities'] if e['kind']=='location'}
    for leaf in leaves:
        lid=leaf['shot_id']; state=boundary.get(leaf['boundary_state_ref'])
        if leaf['scene_id']!=source['scene_id']: add('VARIANT_SCENE', [lid], 'scene_id', 'A local replacement stays in its source scene')
        if leaf['location_id'] not in locations: add('DANGLING_REFERENCE',[lid,leaf['location_id']],'location_id','Unknown location')
        for key,pool in (('beat_refs',beat_ids),('asset_refs',asset_ids),('dialogue_refs',dialogue_ids)):
            for ref in leaf[key]:
                if ref not in pool: add('DANGLING_REFERENCE',[lid,ref],key,'Unresolved variant reference')
        if state is None or state.get('story_layer')!=leaf['story_layer'] or state.get('story_position')!=leaf.get('story_position'):
            add('BOUNDARY_LAYER', [lid,leaf['boundary_state_ref']], 'boundary_state_ref', 'Boundary must describe the leaf temporal layer and position')
        if leaf.get('actual_duration_sec') is not None and (not _binding_shape(leaf.get('actual_binding')) or not _number(leaf.get('actual_duration_sec'),1e-12)):
            add('MEASUREMENT_UNBOUND',[lid],'actual_duration_sec','No actual leaf media binding')
    for state in states:
        if state.get('state_scope')!='partial':
            add('BOUNDARY_SCOPE',[state['snapshot_id']],'state_scope','This local-insert contract supports explicitly partial boundaries only')
        entity_map={e['entity_id']:e for e in content['entities']}
        variant_owners={v['variant_id']:e['entity_id'] for e in content['entities'] for v in e['variants']}
        for eid,fields in state['entity_state'].items():
            if eid not in entity_map: add('DANGLING_REFERENCE',[state['snapshot_id'],eid],'entity_state','Unknown entity')
            if not isinstance(fields,dict):
                add('BOUNDARY_SHAPE',[state['snapshot_id'],eid],'entity_state','Expected object fields')
                continue
            for field,kind in (('custodian','character'),('location_id','location')):
                if field in fields:
                    value=fields[field]
                    if not isinstance(value,str) or value not in entity_map or entity_map[value]['kind']!=kind:
                        add('BOUNDARY_ENTITY_REFERENCE',[state['snapshot_id'],eid,str(value)],'entity_state.'+field,
                            'Boundary references must resolve to the declared entity kind')
            if 'variant_id' in fields:
                value=fields['variant_id']
                if not isinstance(value,str) or variant_owners.get(value)!=eid:
                    add('VARIANT_OWNER',[state['snapshot_id'],eid,str(value)],'entity_state.variant_id',
                        'Boundary variant must belong to this entity')
    ranges=[s['reveal_range_sec'] for s in leaves]
    valid_ranges=all(isinstance(x,list) and len(x)==2 and all(_number(y) for y in x) for x in ranges)
    if not valid_ranges:
        add('VARIANT_RANGE',leaf_ids,'reveal_range_sec','Expected finite range pairs')
    else:
        for leaf,rng in zip(leaves,ranges):
            if abs(rng[1]-rng[0]-leaf['estimated_duration_sec'])>1e-6: add('VARIANT_RANGE',[leaf['shot_id']],'reveal_range_sec','Range and duration differ')
        if any(abs(a[1]-b[0])>1e-6 for a,b in zip(ranges,ranges[1:])): add('VARIANT_RANGE',leaf_ids,'reveal_range_sec','Leaves must be contiguous')
        if source.get('planned_range_sec') and [ranges[0][0],ranges[-1][1]]!=source['planned_range_sec']:
            add('VARIANT_RANGE',[source_id],'reveal_range_sec','Replacement must preserve source range')
    duration=sum(s['estimated_duration_sec'] for s in leaves)
    if abs(duration-source['estimated_duration_sec'])>1e-6: add('VARIANT_DURATION',[source_id],'leaf_shots','Replacement changes source duration; explicit broader pacing revision required')
    active_count=len(content['shots'])-1+len(leaves)
    if edit.get('active_leaf_count')!=active_count: add('VARIANT_LEAF_COUNT',[source_id],'edit.active_leaf_count',{'actual':active_count,'declared':edit.get('active_leaf_count')})
    main_layer=source.get('story_layer',scene['story_layer'])
    current_leaves=[l for l in leaves if l['story_layer']==main_layer]
    # Cross-check unchanged/current fields against the main plan. A field whose
    # changing event spans the source shot is intentionally not inferred from
    # prose. A later explicit handoff, however, cannot have occurred already.
    pre=next(s for s in content['snapshots'] if s['snapshot_id']==scene['pre_state'])
    source_index=next(i for i,s in enumerate(content['shots']) if s['shot_id']==source_id)
    event_positions={}
    for event in content['events']:
        event_beats={b['beat_id'] for b in content['beats'] if event['event_id'] in b['event_refs']}
        event_positions[event['event_id']]=[i for i,s in enumerate(content['shots']) if event_beats.intersection(s['beat_refs'])]
    for leaf in current_leaves:
        state=boundary.get(leaf['boundary_state_ref'],{})
        for eid,fields in state.get('entity_state',{}).items():
            if not isinstance(fields,dict): continue
            for field,value in fields.items():
                target=eid+'.'+field
                found,expected=_state_value(pre,target)
                ambiguous=False
                for delta in scene['delta']:
                    if delta['target']!=target: continue
                    positions=[p for e in delta['event_refs'] for p in event_positions.get(e,[])]
                    if not positions or min(positions)<=source_index<=max(positions): ambiguous=True
                    elif max(positions)<source_index: expected=delta['after'];found=True
                if found and not ambiguous and value!=expected:
                    add('BOUNDARY_CURRENT_BASE_MISMATCH',[leaf['shot_id'],eid],
                        'boundary_state_ref',{'target':target,'expected':expected,'declared':value,
                                              'basis':'Main pre-state plus only fully prior declared events'})
    # A no-present-delta insert must return to the same named partial state.
    if current_leaves:
        before=boundary.get(current_leaves[0]['boundary_state_ref'],{}).get('entity_state',{})
        for leaf in current_leaves[1:]:
            after=boundary.get(leaf['boundary_state_ref'],{}).get('entity_state',{})
            if after!=before:
                add('RECALL_CONTAMINATES_CURRENT_STATE',[leaf['shot_id']]+sorted(set(before)|set(after)),
                    'boundary_state_ref','Returning from another narrative layer cannot change present physical state without an explicit present event')
    for event in new_events:
        if event.get('story_layer')!=main_layer and event.get('current_physical_delta'):
            add('RECALL_CONTAMINATES_CURRENT_STATE',[event['event_id']],'current_physical_delta','A recalled event cannot write present physical state')
    for beat in new_beats:
        for ref in beat.get('event_refs',[]):
            if ref not in event_ids: add('DANGLING_REFERENCE',[beat['beat_id'],ref],'event_refs','Unknown event')
        if beat.get('required') and not any(beat['beat_id'] in l['beat_refs'] for l in leaves):
            add('REQUIRED_BEAT_UNCOVERED',[beat['beat_id']],'beat_refs','New required beat has no leaf')
    active_beats={b for s in content['shots'] if s['shot_id']!=source_id for b in s['beat_refs']} | {b for s in leaves for b in s['beat_refs']}
    for beat in content['beats']:
        if beat['required'] and beat['beat_id'] not in active_beats: add('REQUIRED_BEAT_UNCOVERED',[beat['beat_id']],'beat_refs','Replacement removed required beat')
    rebindings=variant.get('dialogue_rebindings',[])
    if not isinstance(rebindings,list) or any(not isinstance(r,dict) for r in rebindings):
        add('DIALOGUE_REBINDING_SHAPE',[],'dialogue_rebindings','Expected objects'); return _report(findings)
    dialogues={d['dialogue_id']:d for d in content['dialogues']}
    seen=set()
    for rebinding in rebindings:
        did=rebinding.get('dialogue_id')
        if not isinstance(did,str):
            add('DIALOGUE_REBINDING_SHAPE',[],'dialogue_id','Expected string');continue
        d=dialogues.get(did)
        if did in seen or d is None:
            add('DIALOGUE_REBINDING_ID',[did],'dialogue_id','Duplicate or unknown dialogue'); continue
        seen.add(did)
        target_shots=[l['shot_id'] for l in leaves if did in l['dialogue_refs']]
        if rebinding.get('from_shot_refs')!=[source_id] or rebinding.get('to_shot_refs')!=target_shots or not target_shots:
            add('DIALOGUE_REBINDING_TARGET',[did],'to_shot_refs','Rebinding must replace the parent and exactly match leaf dialogue references')
        if rebinding.get('speaker_id')!=d['speaker_id'] or rebinding.get('text_unchanged') is not True:
            add('DIALOGUE_IDENTITY_CHANGED',[did],'speaker_id/text_unchanged','This local insert preserves dialogue and voice owner')
    expected=set(source['dialogue_refs'])
    if seen!=expected or {did for l in leaves for did in l['dialogue_refs']}!=expected:
        add('DIALOGUE_REBINDING_COVERAGE',[source_id],'dialogue_rebindings','Every source dialogue must be rebound exactly; no undeclared new line')
    for leaf in leaves:
        speech=sum(dialogues[d]['estimated_speech_sec'] for d in leaf['dialogue_refs'] if d in dialogues)
        if speech>leaf['estimated_duration_sec']+1e-6:
            add('SPEECH_PLAN_CAPACITY',[leaf['shot_id']],'estimated_speech_sec',{'speech':speech,'budget':leaf['estimated_duration_sec']},'UNCERTAIN')
    return _report(findings, active_leaf_count=active_count,
                   estimated_duration_sec=base['estimated_duration_sec']-source['estimated_duration_sec']+duration,
                   source_group_counted=False, state_coverage='NAMED_PARTIAL_FIELDS_ONLY',
                   content_revision=content['content_revision'])
