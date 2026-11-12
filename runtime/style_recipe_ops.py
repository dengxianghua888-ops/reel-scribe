"""Compile explicit presentation recipes into ordinary, scoped Work candidates.

This is not a style recommender, renderer, or semantic/content editor.
"""
import copy
import re

from editing_runtime import exact_keys, fingerprint, require, source, write_json
from work_ops import timeline_revise

CAPABILITIES = {'caption-style', 'audio-track-gain', 'caption-cue-style'}


def cue_recipe_guard(document, recipe, scope):
    """Local-only edit: preserve existing compiler declarations, never discard them."""
    params=recipe['parameters'];overrides=params['caption_overrides']
    require(isinstance(overrides,dict) and bool(overrides),'CAPTION_OVERRIDE_MAP_REQUIRED')
    targets=scope.get('caption_ids')
    require(isinstance(targets,list) and targets and all(isinstance(x,str) for x in targets)
            and len(targets)==len(set(targets)) and set(targets)<=set(overrides),'CAPTION_OVERRIDE_SCOPE_REQUIRED')
    require(scope.get('caption_style') is False,'CUE_RECIPE_GLOBAL_SCOPE_FORBIDDEN')
    for cid,values in overrides.items():
        require(isinstance(cid,str) and cid in document['captions'],'CAPTION_TARGET_UNKNOWN')
        if cid not in targets:
            require(values==document['captions'][cid].get('style_override',{}),'CUE_RECIPE_UNSELECTED_OVERRIDE_CHANGED')
    for group in ['caption_style','audio_gain_db']:
        if group in params:
            values=params[group];require(isinstance(values,dict) and values,'RECIPE_PARAMETERS_REQUIRED')
            for key,value in values.items():
                actual=document['caption_style'].get(key) if group=='caption_style' else document['audio_tracks'].get(key,{}).get('gain_db')
                require(fingerprint(actual)==fingerprint(value),'CUE_RECIPE_GLOBAL_CHANGE_FORBIDDEN')
    bindings=document['style_bindings']
    if bindings:
        require(set(bindings)=={'*'},'CUE_RECIPE_BINDING_UNSUPPORTED')
        old=bindings['*'];record=old.get('parameters',{});prior=record.get('presentation')
        require(isinstance(prior,dict) and prior and set(prior)<= {'caption_style','audio_gain_db','caption_overrides'},'CUE_RECIPE_BINDING_UNSUPPORTED')
        require({k:v for k,v in old.items() if k!='parameters'}==recipe['style'],'CUE_RECIPE_STYLE_IDENTITY_CONFLICT')
        require(record.get('layout_constraints')==recipe.get('layout_constraints'),'CUE_RECIPE_CONSTRAINTS_MUST_PERSIST')
        for group,values in prior.items():
            require(isinstance(values,dict) and group in params,'CUE_RECIPE_BINDING_PARAMETERS_DROPPED')
            for key,value in values.items():
                actual=(document['captions'].get(key,{}).get('style_override',{}) if group=='caption_overrides' else
                        document['caption_style'].get(key) if group=='caption_style' else document['audio_tracks'].get(key,{}).get('gain_db'))
                require(fingerprint(actual)==fingerprint(value),'CUE_RECIPE_BINDING_DIVERGED')
                require(key in params[group],'CUE_RECIPE_BINDING_PARAMETERS_DROPPED')
                if group!='caption_overrides' or key not in targets:
                    require(params[group][key]==value,'CUE_RECIPE_BINDING_PARAMETERS_CHANGED')
                else:
                    require(set(value)<=set(params[group][key]),'CUE_RECIPE_BINDING_PARAMETERS_DROPPED')
    return targets


def execute(request, directory, tools):
    fields = ['operation', 'base_version', 'document', 'expected_document_sha256',
              'recipe', 'expected_recipe_sha256', 'capabilities', 'scope']
    exact_keys(request, fields, fields)
    require(request['operation'] == 'style-recipe-compile', 'STYLE_OPERATION_UNSUPPORTED')
    recipe = request['recipe']
    require(fingerprint(recipe) == request['expected_recipe_sha256'], 'RECIPE_REVISION_CONFLICT')
    exact_keys(recipe, ['schema', 'id', 'version', 'style', 'parameters', 'layout_constraints'],
               ['schema', 'id', 'version', 'style', 'parameters'])
    require(recipe['schema'] == 'style-recipe/1', 'RECIPE_SCHEMA_UNSUPPORTED')
    require(all(isinstance(recipe[k], str) and recipe[k].strip() for k in ['id', 'version']),
            'RECIPE_ID_REQUIRED')
    style = recipe['style']
    exact_keys(style, ['family', 'style_id', 'version', 'card'], ['family', 'style_id', 'version', 'card'])
    require(all(isinstance(style[k], str) and style[k].strip()
                for k in ['family', 'style_id', 'version']), 'STYLE_ID_REQUIRED')
    source(style['card'])
    parameters = recipe['parameters']
    exact_keys(parameters, ['caption_style', 'audio_gain_db', 'caption_overrides'])
    require(bool(parameters), 'RECIPE_PARAMETERS_REQUIRED')
    capabilities = request['capabilities']
    require(isinstance(capabilities, list) and all(isinstance(c, str) for c in capabilities)
            and len(set(capabilities)) == len(capabilities)
            and set(capabilities) <= CAPABILITIES, 'RECIPE_CAPABILITIES_INVALID')
    document = request['document']
    require(fingerprint(document) == request['expected_document_sha256'], 'DOCUMENT_REVISION_CONFLICT')
    if 'caption_overrides' not in parameters:
        require(not any('caption_overrides' in b.get('parameters',{}).get('presentation',{}) for b in document['style_bindings'].values()),'CUE_RECIPE_EXISTING_OVERRIDES_MUST_PERSIST')
    candidate = copy.deepcopy(document)
    required = []
    cue_targets=cue_recipe_guard(document,recipe,request['scope']) if 'caption_overrides' in parameters else None
    if 'caption_style' in parameters:

        if cue_targets is None:required.append('caption-style')
        values = parameters['caption_style']
        exact_keys(values, ['font_size', 'margin_v', 'color_rgb'])
        require(bool(values), 'RECIPE_PARAMETERS_REQUIRED')
        require(isinstance(candidate.get('caption_style'), dict), 'EXISTING_CAPTION_STYLE_REQUIRED')
        # Existing Work validation enforces size, viewport and color bounds;
        # reject types here too, including bool-as-int and non-finite values.
        if 'font_size' in values:
            require(type(values['font_size']) is int and 8 <= values['font_size'] <= 300, 'FONT_SIZE_INVALID')
        if 'margin_v' in values:
            require(type(values['margin_v']) is int and values['margin_v'] >= 0, 'MARGIN_INVALID')
        if 'color_rgb' in values:
            require(isinstance(values['color_rgb'], str)
                    and re.fullmatch('[0-9A-Fa-f]{6}', values['color_rgb']), 'COLOR_RGB_REQUIRED')
        candidate['caption_style'].update(copy.deepcopy(values))
    if 'audio_gain_db' in parameters:

        if cue_targets is None:required.append('audio-track-gain')
        values = parameters['audio_gain_db']
        require(isinstance(values, dict) and values, 'AUDIO_GAIN_MAP_REQUIRED')
        from editing_runtime import number
        for track_id, gain in values.items():
            require(isinstance(track_id, str) and track_id in candidate['audio_tracks'], 'AUDIO_TARGET_UNKNOWN')
            value = number(gain, 'gain_db')
            require(-120 <= value <= 24, 'GAIN_OUT_OF_RANGE')
            candidate['audio_tracks'][track_id]['gain_db'] = value
    if cue_targets is not None:
        from caption_style import validate_override
        required.append('caption-cue-style')
        for cid,values in parameters['caption_overrides'].items():
            validated=validate_override(values,document['plan']['height'])
            previous=candidate['captions'][cid].get('style_override',{})
            require(set(previous)<=set(validated),'CUE_RECIPE_OVERRIDE_FIELDS_DROPPED')
            candidate['captions'][cid]['style_override']=copy.deepcopy(validated)
    require(set(required) <= set(capabilities), 'RECIPE_CAPABILITY_UNAVAILABLE')
    # Global binding records precisely what this compiler can map. It never
    # certifies the source card's broader narrative or perceptual intentions.
    candidate['style_bindings']['*'] = {**copy.deepcopy(style), 'parameters': {
        'recipe_id': recipe['id'], 'recipe_version': recipe['version'],
        'recipe_sha256': request['expected_recipe_sha256'], 'presentation': copy.deepcopy(parameters)}}
    layout_report = {'status': 'UNKNOWN', 'reason': 'No explicit layout constraints supplied'}
    if 'layout_constraints' in recipe:
        from caption_layout import check
        from work_ops import revision_diff
        candidate['style_bindings']['*']['parameters']['layout_constraints'] = copy.deepcopy(recipe['layout_constraints'])
        revision_diff(document, candidate, request['scope'], tools)
        layout_report = check(candidate, recipe['layout_constraints'], directory/'layout', tools)
    # Validate all changes before producing any candidate. Work commit rechecks
    # the scope against the authoritative store and rejects a stale base version.
    diff = timeline_revise({'operation': 'timeline-revise', 'base_version': request['base_version'],
        'document': document, 'expected_document_sha256': request['expected_document_sha256'],
        'candidate': candidate, 'scope': request['scope']}, directory, tools)
    report = {'schema': 'style-recipe-result/1', 'status': 'CANDIDATE_COMPILED',
              'recipe_id': recipe['id'], 'recipe_version': recipe['version'],
              'recipe_sha256': request['expected_recipe_sha256'],
              'document_sha256': diff['document_sha256'],
              'mapped_parameters': copy.deepcopy(parameters), 'required_capabilities': required,
              'capabilities_evidence': 'CALLER_DECLARED_NOT_PROBED',
              'applied_to_work': False, 'render': 'NOT_RUN', 'style_effect': 'NOT_VERIFIED',
              'caption_target_ids': sorted(cue_targets) if cue_targets is not None else [],
              'caption_mapping_scope': 'Explicit cue overrides; global caption_style is a default, not an assertion every cue uses it' if cue_targets is not None else 'Global defaults; existing cue overrides remain authoritative',
              'content_selection': 'UNCHANGED', 'unsupported_fallbacks': [],
              'invalidated': diff['invalidated'], 'caption_layout': layout_report}
    write_json(directory / 'style-recipe.json', report)
    return report
