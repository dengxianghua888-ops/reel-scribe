"""Pure per-cue presentation merge. No text, timing, font or scope authority."""
import copy
import re


def validate_override(value, height):
    from editing_runtime import exact_keys, require
    exact_keys(value,['font_size','color_rgb','margin_v'],[])
    require(bool(value),'CAPTION_STYLE_OVERRIDE_EMPTY')
    if 'font_size' in value:
        require(type(value['font_size']) is int and 8<=value['font_size']<=300 and value['font_size']<=height,'CAPTION_OVERRIDE_FONT_SIZE_INVALID')
    if 'margin_v' in value:
        require(type(value['margin_v']) is int and 0<=value['margin_v']<height,'CAPTION_OVERRIDE_MARGIN_INVALID')
    if 'color_rgb' in value:
        require(isinstance(value['color_rgb'],str) and re.fullmatch('[0-9A-Fa-f]{6}',value['color_rgb']) is not None,'CAPTION_OVERRIDE_COLOR_INVALID')
    return copy.deepcopy(value)


def effective_style(global_style, override, height):
    from editing_runtime import require
    require(isinstance(global_style,dict),'CAPTION_GLOBAL_STYLE_REQUIRED')
    result=copy.deepcopy(global_style)
    result.update(validate_override(override,height))
    return result
