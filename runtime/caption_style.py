"""Pure per-cue presentation merge. No text, timing, font or scope authority."""
import copy
import re
import hashlib
import unicodedata


def validate_override(value, height, text=None):
    from editing_runtime import exact_keys, require
    exact_keys(value,['font_size','color_rgb','margin_v','line_breaks'],[])
    require(bool(value),'CAPTION_STYLE_OVERRIDE_EMPTY')
    if 'font_size' in value:
        require(type(value['font_size']) is int and 8<=value['font_size']<=300 and value['font_size']<=height,'CAPTION_OVERRIDE_FONT_SIZE_INVALID')
    if 'margin_v' in value:
        require(type(value['margin_v']) is int and 0<=value['margin_v']<height,'CAPTION_OVERRIDE_MARGIN_INVALID')
    if 'color_rgb' in value:
        require(isinstance(value['color_rgb'],str) and re.fullmatch('[0-9A-Fa-f]{6}',value['color_rgb']) is not None,'CAPTION_OVERRIDE_COLOR_INVALID')
    if "line_breaks" in value:
        validate_line_breaks(value["line_breaks"], text)
    return copy.deepcopy(value)


def effective_style(global_style, override, height):
    from editing_runtime import require
    require(isinstance(global_style,dict),'CAPTION_GLOBAL_STYLE_REQUIRED')
    result=copy.deepcopy(global_style)
    result.update(validate_override(override,height))
    return result


def validate_line_breaks(value, text=None):
    """Validate explicit presentation offsets, never a replacement transcript."""
    from editing_runtime import exact_keys, require
    exact_keys(value, ['text_sha256', 'offsets'], ['text_sha256', 'offsets'])
    require(isinstance(value['text_sha256'], str) and re.fullmatch('[0-9a-f]{64}', value['text_sha256']), 'CAPTION_BREAK_TEXT_HASH_INVALID')
    offsets=value['offsets']
    require(isinstance(offsets,list) and len(offsets)<=255 and all(type(x) is int and x>0 for x in offsets)
            and offsets==sorted(set(offsets)), 'CAPTION_BREAK_OFFSETS_INVALID')
    if text is None:return
    require(isinstance(text,str) and hashlib.sha256(text.encode('utf-8')).hexdigest()==value['text_sha256'], 'CAPTION_BREAK_TEXT_CHANGED')
    require(len(text)<=4096 and all(x<len(text) for x in offsets), 'CAPTION_BREAK_OFFSETS_INVALID')
    # Conservative grapheme support: no guesses around combining marks, joiners,
    # variation selectors, emoji modifiers or regional-indicator flag pairs.
    def complex_char(ch):
        return unicodedata.category(ch).startswith('M') or ch in '\u200c\u200d' or 0x1f3fb<=ord(ch)<=0x1f3ff or 0x1f1e6<=ord(ch)<=0x1f1ff
    latin=lambda ch: ch.isascii() and ch.isalnum()
    opening='([{（【《「『“‘'
    closing=')]},.!?:;，。！？：；、）】》」』”’'
    for x in offsets:
        a,b=text[x-1],text[x]
        require(a!='\n' and b!='\n' and not complex_char(a) and not complex_char(b), 'CAPTION_BREAK_UNSAFE_BOUNDARY')
        require(a not in opening and b not in closing, 'CAPTION_BREAK_PUNCTUATION_BOUNDARY')
        require(not(latin(a) and latin(b)), 'CAPTION_BREAK_TOKEN_SPLIT')
        require(not(a in ".'-’" and x>=2 and latin(text[x-2]) and latin(b)) and
                not(b in ".'-’" and x+1<len(text) and latin(a) and latin(text[x+1])), 'CAPTION_BREAK_TOKEN_SPLIT')


def presentation_text(text, override):
    """Materialize line breaks only at render boundaries; source text stays intact."""
    if not override or 'line_breaks' not in override:return text
    value=override['line_breaks'];validate_line_breaks(value,text)
    positions=set(value['offsets'])
    return ''.join(('\n' if i in positions else '')+ch for i,ch in enumerate(text))
