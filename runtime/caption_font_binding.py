"""Process-local, one-file font provider for explicit line-break renders only."""
import os
from pathlib import Path
import re
import shutil
from xml.sax.saxutils import escape


def prepare(font_path, directory, family):
    from editing_runtime import exec_tool, require, sha256
    font_path=Path(font_path).resolve()
    directory=Path(directory).resolve()
    directory.mkdir(exist_ok=False)
    query=shutil.which('fc-query')
    require(query is not None,'CAPTION_FONT_QUERY_UNAVAILABLE')
    metadata=exec_tool([query,'--index=0','--format=%{postscriptname}\\n%{family}',str(font_path)]).stdout.splitlines()
    require(len(metadata)>=2 and metadata[0].strip(),'CAPTION_FONT_METADATA_UNVERIFIED')
    names=set(metadata[0].split(','))
    require(family in metadata[1].split(','),'CAPTION_FONT_FAMILY_MISMATCH')
    # No system config include, default directories or global environment mutation.
    cache=directory/'cache';cache.mkdir()
    config=directory/'fonts.conf'
    config.write_text('<?xml version="1.0"?><!DOCTYPE fontconfig SYSTEM "urn:fontconfig:fonts.dtd"><fontconfig><dir>'+
                      escape(str(font_path.parent))+'</dir><cachedir>'+escape(str(cache))+'</cachedir></fontconfig>',encoding='utf-8')
    env=dict(os.environ)
    env.pop('FONTCONFIG_SYSROOT',None)
    env.update(FONTCONFIG_FILE=str(config),FONTCONFIG_PATH=str(directory))
    return {'env':env,'font_path':str(font_path),'font_sha256':sha256(font_path),'names':names,'directory':directory}


def verify(stderr, binding, label):
    from editing_runtime import require, sha256
    (binding['directory']/(label+'.log')).write_text(stderr,encoding='utf-8')
    require(sha256(binding['font_path'])==binding['font_sha256'],'CAPTION_FONT_CHANGED')
    require('Using font provider fontconfig' in stderr,'CAPTION_FONT_PROVIDER_UNVERIFIED')
    require(not re.search(r'failed to find.*glyph|glyph.*not found|fontselect:.*failed|no usable font|selecting one more font',stderr,re.I),
            'CAPTION_FONT_FALLBACK_REFUSED')
    selections=re.findall(r'fontselect:.*? -> (.*?), (\d+), ([^\r\n]+)',stderr)
    require(bool(selections),'CAPTION_FONT_SELECTION_UNVERIFIED')
    for selected,index,postscript in selections:
        valid_selected=selected in binding['names'] or Path(selected).resolve()==Path(binding['font_path'])
        require(index=='0' and postscript.strip() in binding['names'] and valid_selected,'CAPTION_FONT_FALLBACK_REFUSED')
    return {'status':'ISOLATED_FONT_FACE_VERIFIED','font_sha256':binding['font_sha256'],'face_index':0,
            'selection_log':str(binding['directory']/(label+'.log'))}
