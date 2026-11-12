"""Compile explicit presentation recipes into ordinary, scoped Work candidates.

This is not a style recommender, renderer, or semantic/content editor.
"""
import copy
import re

from editing_runtime import exact_keys, fingerprint, require, source, write_json
from work_ops import timeline_revise

CAPABILITIES = {'caption-style', 'audio-track-gain'}


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
    exact_keys(parameters, ['caption_style', 'audio_gain_db'])
    require(bool(parameters), 'RECIPE_PARAMETERS_REQUIRED')
    capabilities = request['capabilities']
    require(isinstance(capabilities, list) and all(isinstance(c, str) for c in capabilities)
            and len(set(capabilities)) == len(capabilities)
            and set(capabilities) <= CAPABILITIES, 'RECIPE_CAPABILITIES_INVALID')
    document = request['document']
    require(fingerprint(document) == request['expected_document_sha256'], 'DOCUMENT_REVISION_CONFLICT')
    candidate = copy.deepcopy(document)
    required = []
    if 'caption_style' in parameters:
        required.append('caption-style')
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
        required.append('audio-track-gain')
        values = parameters['audio_gain_db']
        require(isinstance(values, dict) and values, 'AUDIO_GAIN_MAP_REQUIRED')
        from editing_runtime import number
        for track_id, gain in values.items():
            require(isinstance(track_id, str) and track_id in candidate['audio_tracks'], 'AUDIO_TARGET_UNKNOWN')
            value = number(gain, 'gain_db')
            require(-120 <= value <= 24, 'GAIN_OUT_OF_RANGE')
            candidate['audio_tracks'][track_id]['gain_db'] = value
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
              'content_selection': 'UNCHANGED', 'unsupported_fallbacks': [],
              'invalidated': diff['invalidated'], 'caption_layout': layout_report}
    write_json(directory / 'style-recipe.json', report)
    return report
