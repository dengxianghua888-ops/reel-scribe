"""Compile explicit presentation recipes into ordinary, scoped Work candidates.

This is not a style recommender, renderer, or semantic/content editor.
"""
import copy
import re

from editing_runtime import exact_keys, fingerprint, require, source, write_json
from work_ops import timeline_revise

CAPABILITIES = {'caption-style', 'audio-track-gain', 'caption-cue-style', 'audio-track-envelope'}


def mapped_equal(group,actual,declared):
    if group=='audio_gain_db':
        from editing_runtime import number
        a=number(actual,'gain_db');b=number(declared,'gain_db')
        require(-120<=a<=24 and -120<=b<=24,'GAIN_OUT_OF_RANGE')
        return a==b
    return fingerprint(actual)==fingerprint(declared)


def validate_envelope_binding(document):
    """Check compiler-shaped declarations for consistency, not author authenticity."""
    bindings=document['style_bindings']
    require(isinstance(bindings,dict) and set(bindings)=={'*'}, 'AUDIO_ENVELOPE_STYLE_BINDING_UNSUPPORTED')
    binding=bindings['*']
    require(isinstance(binding,dict) and set(binding)=={'family','style_id','version','card','parameters'},
            'AUDIO_ENVELOPE_STYLE_BINDING_UNSUPPORTED')
    record=binding['parameters']
    require(isinstance(record,dict) and {'recipe_id','recipe_version','recipe_sha256','presentation'}<=set(record)
            and isinstance(record['presentation'],dict), 'AUDIO_ENVELOPE_STYLE_BINDING_UNSUPPORTED')
    exact_keys(record,['recipe_id','recipe_version','recipe_sha256','presentation','layout_constraints'],
               ['recipe_id','recipe_version','recipe_sha256','presentation'])
    require(all(isinstance(record[k],str) and record[k].strip() for k in ['recipe_id','recipe_version']),'RECIPE_ID_REQUIRED')
    params=record['presentation']
    exact_keys(params,['caption_style','audio_gain_db','caption_overrides','audio_envelope'])
    require(bool(params),'RECIPE_PARAMETERS_REQUIRED')
    recipe={'schema':'style-recipe/1','id':record['recipe_id'],'version':record['recipe_version'],
            'style':{k:v for k,v in binding.items() if k!='parameters'},'parameters':params}
    if 'layout_constraints' in record:recipe['layout_constraints']=record['layout_constraints']
    require(fingerprint(recipe)==record['recipe_sha256'],'AUDIO_ENVELOPE_BINDING_HASH_CONFLICT')
    for group,values in params.items():
        require(isinstance(values,dict) and bool(values),'RECIPE_PARAMETERS_REQUIRED')
        if group=='caption_style':
            exact_keys(values,['font_size','margin_v','color_rgb'])
            require(isinstance(document['caption_style'],dict),'EXISTING_CAPTION_STYLE_REQUIRED')
            if 'font_size' in values:require(type(values['font_size']) is int and 8<=values['font_size']<=300,'FONT_SIZE_INVALID')
            if 'margin_v' in values:require(type(values['margin_v']) is int and values['margin_v']>=0,'MARGIN_INVALID')
            if 'color_rgb' in values:require(isinstance(values['color_rgb'],str) and re.fullmatch('[0-9A-Fa-f]{6}',values['color_rgb']),'COLOR_RGB_REQUIRED')
        for key,value in values.items():
            require(isinstance(key,str) and bool(key),'RECIPE_TARGET_INVALID')
            if group in ('audio_gain_db','audio_envelope'):
                require(key in document['audio_tracks'],'AUDIO_TARGET_UNKNOWN')
            if group=='audio_gain_db':
                from editing_runtime import number
                require(-120<=number(value,'gain_db')<=24,'GAIN_OUT_OF_RANGE')
            if group=='caption_overrides':
                require(key in document['captions'],'CAPTION_TARGET_UNKNOWN')
                from caption_style import validate_override
                validate_override(value,document['plan']['height'])
            if group=='audio_envelope':
                require(isinstance(value,dict) and key in document['audio_tracks'],'AUDIO_ENVELOPE_MAP_REQUIRED')
            actual=(document['caption_style'].get(key) if group=='caption_style' else
                    document['captions'].get(key,{}).get('style_override',{}) if group=='caption_overrides' else
                    document['audio_tracks'].get(key,{}).get('envelope' if group=='audio_envelope' else 'gain_db'))
            require(mapped_equal(group,actual,value),'AUDIO_ENVELOPE_BINDING_DIVERGED')
    for aid,track in document['audio_tracks'].items():
        if 'envelope' in track:
            require(aid in params.get('audio_envelope',{}),'AUDIO_ENVELOPE_UNMAPPED')
    return recipe


def envelope_recipe_guard(document,recipe,scope):
    if not document['style_bindings']:return
    old=validate_envelope_binding(document)
    require(old['style']==recipe['style'],'AUDIO_ENVELOPE_STYLE_IDENTITY_CONFLICT')
    require(old.get('layout_constraints')==recipe.get('layout_constraints'),'AUDIO_ENVELOPE_CONSTRAINTS_MUST_PERSIST')
    for group,values in old['parameters'].items():
        for key,value in values.items():
            require(key in recipe['parameters'].get(group,{}),'AUDIO_ENVELOPE_PARAMETERS_DROPPED')
            selected=(group=='audio_envelope' and key in scope.get('audio_ids',[])) or (group=='caption_overrides' and key in scope.get('caption_ids',[]))
            if not selected:
                require(fingerprint(recipe['parameters'][group][key])==fingerprint(value),'AUDIO_ENVELOPE_UNSELECTED_PARAMETER_CHANGED')


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
    for group in ['caption_style','audio_gain_db','audio_envelope']:
        if group in params:
            values=params[group];require(isinstance(values,dict) and values,'RECIPE_PARAMETERS_REQUIRED')
            for key,value in values.items():
                actual=document['caption_style'].get(key) if group=='caption_style' else document['audio_tracks'].get(key,{}).get('envelope' if group=='audio_envelope' else 'gain_db')
                require(mapped_equal(group,actual,value),'CUE_RECIPE_GLOBAL_CHANGE_FORBIDDEN')
    bindings=document['style_bindings']
    if bindings:
        require(set(bindings)=={'*'},'CUE_RECIPE_BINDING_UNSUPPORTED')
        old=bindings['*'];record=old.get('parameters',{});prior=record.get('presentation')
        require(isinstance(prior,dict) and prior and set(prior)<= {'caption_style','audio_gain_db','caption_overrides','audio_envelope'},'CUE_RECIPE_BINDING_UNSUPPORTED')
        require({k:v for k,v in old.items() if k!='parameters'}==recipe['style'],'CUE_RECIPE_STYLE_IDENTITY_CONFLICT')
        require(record.get('layout_constraints')==recipe.get('layout_constraints'),'CUE_RECIPE_CONSTRAINTS_MUST_PERSIST')
        for group,values in prior.items():
            require(isinstance(values,dict) and group in params,'CUE_RECIPE_BINDING_PARAMETERS_DROPPED')
            for key,value in values.items():
                actual=(document['captions'].get(key,{}).get('style_override',{}) if group=='caption_overrides' else
                        document['caption_style'].get(key) if group=='caption_style' else document['audio_tracks'].get(key,{}).get('envelope' if group=='audio_envelope' else 'gain_db'))
                require(mapped_equal(group,actual,value),'CUE_RECIPE_BINDING_DIVERGED')
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
    exact_keys(parameters, ['caption_style', 'audio_gain_db', 'caption_overrides', 'audio_envelope'])
    require(bool(parameters), 'RECIPE_PARAMETERS_REQUIRED')
    capabilities = request['capabilities']
    require(isinstance(capabilities, list) and all(isinstance(c, str) for c in capabilities)
            and len(set(capabilities)) == len(capabilities)
            and set(capabilities) <= CAPABILITIES, 'RECIPE_CAPABILITIES_INVALID')
    document = request['document']
    require(fingerprint(document) == request['expected_document_sha256'], 'DOCUMENT_REVISION_CONFLICT')
    if 'caption_overrides' not in parameters:
        require(not any('caption_overrides' in b.get('parameters',{}).get('presentation',{}) for b in document['style_bindings'].values()),'CUE_RECIPE_EXISTING_OVERRIDES_MUST_PERSIST')
    if 'audio_envelope' in parameters or any('envelope' in t for t in document['audio_tracks'].values()):
        envelope_recipe_guard(document,recipe,request['scope'])
    candidate = copy.deepcopy(document)
    required = []
    cue_targets=None
    if 'caption_overrides' in parameters:
        if request['scope'].get('caption_ids'):
            cue_targets=cue_recipe_guard(document,recipe,request['scope'])
        else:
            # An audio-only recipe may carry existing cue mappings unchanged.
            require('audio_envelope' in parameters,'CAPTION_OVERRIDE_SCOPE_REQUIRED')
            overrides=parameters['caption_overrides']
            require(isinstance(overrides,dict) and bool(overrides),'CAPTION_OVERRIDE_MAP_REQUIRED')
            for cid,values in overrides.items():
                require(cid in document['captions'] and fingerprint(values)==fingerprint(document['captions'][cid].get('style_override',{})),
                        'CUE_RECIPE_UNSELECTED_OVERRIDE_CHANGED')
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
    if 'audio_envelope' in parameters:
        if cue_targets is None:required.append('audio-track-envelope')
        values=parameters['audio_envelope']
        require(isinstance(values,dict) and values,'AUDIO_ENVELOPE_MAP_REQUIRED')
        for aid,value in values.items():
            require(isinstance(aid,str) and aid in candidate['audio_tracks'],'AUDIO_TARGET_UNKNOWN')
            candidate['audio_tracks'][aid]['envelope']=copy.deepcopy(value)
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
