"""Explicit revision scopes, local SQLite compare-and-swap, and snapshot rendering.

These operations never select clips, infer intent, or choose editorial treatments.
"""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
from fractions import Fraction


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def validate_document(doc,tools):
    from editing_runtime import exact_keys,require,normalize_plan,number,source,span,audio_intersection,windowed_mix_clock
    exact_keys(doc,['schema','plan','captions','caption_style','audio_tracks','style_bindings','notes','visual_layers','evidence_protection'],
               ['schema','plan','captions','caption_style','audio_tracks','style_bindings','notes'])
    require(doc['schema']=='work-document/1','WORK_SCHEMA_UNSUPPORTED')
    norm=normalize_plan(doc['plan'],tools);clips={c['id']:c for c in norm['clips']}
    for field in ['captions','audio_tracks','style_bindings','notes']:
        require(isinstance(doc[field],dict),'ID_MAP_REQUIRED: '+field)
        require(all(isinstance(k,str) and k for k in doc[field]),'RESOURCE_ID_REQUIRED')
    cues=[]
    for cid,cue in doc['captions'].items():
        exact_keys(cue,['clip_id','start','end','text'],['clip_id','start','end','text'])
        require(cue['clip_id'] in clips,'CAPTION_ANCHOR_MISSING: '+cid)
        clip=clips[cue['clip_id']]
        # A complete sentence may legitimately span more than one picture clip.
        a,b=span(cue['start'],cue['end'],norm['duration']-clip['output_start'])
        require(isinstance(cue['text'],str) and cue['text'].strip(),'CUE_TEXT_REQUIRED')
        cues.append({'id':cid,'start':clip['output_start']+a,'end':clip['output_start']+b,'text':cue['text']})
    cues.sort(key=lambda x:(x['start'],x['end']))
    require(all(a['end']<=b['start'] for a,b in zip(cues,cues[1:])),'OVERLAPPING_CAPTIONS')
    style=doc['caption_style']
    if style is not None:
        exact_keys(style,['font','font_family','font_size','margin_v','color_rgb'],['font','font_family','font_size','margin_v','color_rgb'])
        source(style['font'])
        require(isinstance(style['font_family'],str) and style['font_family'].strip(),'FONT_FAMILY_REQUIRED')
        require(type(style['font_size']) is int and 8<=style['font_size']<=300,'FONT_SIZE_INVALID')
        require(type(style['margin_v']) is int and 0<=style['margin_v']<norm['height'],'MARGIN_INVALID')
        require(isinstance(style['color_rgb'],str) and re.fullmatch('[0-9A-Fa-f]{6}',style['color_rgb']),'COLOR_RGB_REQUIRED')
    require(not cues or style is not None,'CAPTION_STYLE_REQUIRED')
    tracks=[]
    for aid,track in doc['audio_tracks'].items():
        exact_keys(track,['source','start','end','anchor_clip_id','offset','gain_db'],['source','start','end','anchor_clip_id','offset','gain_db'])
        asset=source(track['source']);media=tools.probe(asset['path'])
        require(any(s['codec_type']=='audio' for s in media['streams']),'AUDIO_STREAM_REQUIRED')
        a,b=span(track['start'],track['end'],media['duration'])
        audio_intersection(windowed_mix_clock(tools,asset['path'],media,b,kind='audio',start=a,playback=True),a,b,require_full=True,playback=True)
        anchor=track['anchor_clip_id'];require(anchor is None or anchor in clips,'AUDIO_ANCHOR_MISSING: '+aid)
        start=(clips[anchor]['output_start'] if anchor is not None else 0)+number(track['offset'],'offset')
        require(start>=0 and start+b-a<=norm['duration']+1e-8,'AUDIO_TRACK_OUTSIDE_WORK: '+aid)
        gain=number(track['gain_db'],'gain_db');require(-120<=gain<=24,'GAIN_OUT_OF_RANGE')
        tracks.append({'source':track['source'],'start':a,'end':b,'output_start':start,'gain_db':gain})
    for key,binding in doc['style_bindings'].items():
        require(key=='*' or key in clips,'STYLE_ANCHOR_MISSING: '+key)
        exact_keys(binding,['family','style_id','version','card','parameters'],['family','style_id','version','card','parameters'])
        require(all(isinstance(binding[k],str) and binding[k] for k in ['family','style_id','version']),'STYLE_ID_REQUIRED')
        require(isinstance(binding['parameters'],dict),'STYLE_PARAMETERS_REQUIRED');source(binding['card'])
    from overlay_ops import work_layers
    work_layers(doc,norm,tools)
    canonical(doc)  # Reject NaN and non-JSON state instead of silently coercing it.
    if 'evidence_protection' in doc:
        from editing_runtime import fingerprint
        from evidence_ops import compile_evidence
        protection=doc['evidence_protection']
        fields=['schema','units','required_units','occurrences','chapters']
        exact_keys(protection,fields,fields)
        require(protection['schema']=='work-evidence-protection/1','WORK_PROTECTION_SCHEMA_UNSUPPORTED')
        compile_evidence({'operation':'evidence-plan-compile','document':doc,
            'expected_document_sha256':fingerprint(doc),
            **{key:protection[key] for key in fields if key!='schema'}},None,tools,
            normalized_document=(norm,cues,tracks),validation_mode='ordinary_protection')
    return norm,cues,tracks


def revision_diff(base,candidate,scope,tools):
    from editing_runtime import exact_keys,require,fingerprint
    fields=['clip_ids','source_ids','caption_ids','audio_ids','style_keys','note_keys','output_fields','caption_style',
            'freeze_positions','freeze_duration']
    exact_keys(scope,fields+['visual_ids','evidence_mapping'],fields)
    scope={**scope,'visual_ids':scope.get('visual_ids',[]),'evidence_mapping':scope.get('evidence_mapping',False)}
    fields=fields+['visual_ids','evidence_mapping']
    for k in fields:
        if k in ['caption_style','freeze_duration','evidence_mapping']:
            require(type(scope[k]) is bool,'BOOLEAN_SCOPE_REQUIRED: '+k)
        else:
            require(isinstance(scope[k],list) and all(isinstance(x,str) for x in scope[k]) and len(set(scope[k]))==len(scope[k]),'ID_SCOPE_REQUIRED: '+k)
    # At commit base is loaded from SQLite, never trusted from a candidate's
    # self-supplied checkpoint. Ordinary edits cannot re-author protections.
    require(('evidence_protection' in base)==('evidence_protection' in candidate),'WORK_PROTECTION_MEMBERSHIP_FROZEN')
    old,old_cues,old_tracks=validate_document(base,tools);new,new_cues,new_tracks=validate_document(candidate,tools)
    before_clips={c['id']:c for c in base['plan']['clips']}
    after_clips={c['id']:c for c in candidate['plan']['clips']}
    speed_changed=sorted(cid for cid in before_clips.keys()&after_clips.keys()
                         if Fraction(str(before_clips[cid].get('speed',1)))!=
                            Fraction(str(after_clips[cid].get('speed',1))))
    old_protection=base.get('evidence_protection');new_protection=candidate.get('evidence_protection')
    mapping_changed=False
    if old_protection is not None:
        require(all(old_protection[key]==new_protection[key] for key in ['schema','units','required_units']),
                'WORK_PROTECTION_DECLARATION_FROZEN')
        mapping_changed=any(old_protection[key]!=new_protection[key] for key in ['occurrences','chapters'])
        require(not mapping_changed or scope['evidence_mapping'],'WORK_PROTECTION_MAPPING_SCOPE_REQUIRED')
        # Speed changes the evidence source/output clock even when the declared
        # occurrence IDs are identical. Revalidate under an explicit scope.
        require(not speed_changed or scope['evidence_mapping'],'WORK_SPEED_EVIDENCE_REVIEW_SCOPE_REQUIRED')
    require(set(scope['output_fields'])<=set(['fps','width','height','fit','allow_source_reuse']),'OUTPUT_SCOPE_UNKNOWN')
    before={c['id']:c for c in base['plan']['clips']};after={c['id']:c for c in candidate['plan']['clips']}
    allowed=set(scope['clip_ids']);require(allowed<=set(before)|set(after),'SCOPE_CLIP_UNKNOWN')
    frozen=[x for x in before if x not in allowed]
    require(frozen==[x for x in after if x not in allowed],'FROZEN_CLIP_ORDER_OR_MEMBERSHIP_CHANGED')
    require(all(before[x]==after[x] for x in frozen),'FROZEN_CLIP_CONTENT_CHANGED')
    def changes(a,b):return sorted(k for k in set(a)|set(b) if (k not in a or k not in b or a[k]!=b[k]))
    result={}
    for field,authorized,a,b in [
        ('sources','source_ids',base['plan']['sources'],candidate['plan']['sources']),
        ('captions','caption_ids',base['captions'],candidate['captions']),
        ('audio_tracks','audio_ids',base['audio_tracks'],candidate['audio_tracks']),
        ('style_bindings','style_keys',base['style_bindings'],candidate['style_bindings']),
        ('notes','note_keys',base['notes'],candidate['notes']),
        ('visual_layers','visual_ids',base.get('visual_layers',{}),candidate.get('visual_layers',{}))]:
        modified=changes(a,b);require(set(modified)<=set(scope[authorized]),'OUTSIDE_SCOPE: '+field)
        result[field]=modified
    source_changes=set(result['sources'])
    require(all(c['id'] in allowed for c in base['plan']['clips']+candidate['plan']['clips'] if c['source_id'] in source_changes),'FROZEN_CLIP_SOURCE_CHANGED')
    # Check the whole covered source interval, including captions/VO spanning multiple clips.
    # An unchanged anchor cannot prove that the later part of a sentence still matches picture.
    def coverage(norm,a,b):
        parts=[]
        for c in norm['clips']:
            left=max(a,c['output_start']);right=min(b,c['output_end'])
            if left>=right:continue
            speed=float(Fraction(c['speed']))
            parts.append((c['source_id'],norm['sources'][c['source_id']]['sha256'],
                          round(c['start']+(left-c['output_start'])*speed,8),
                          round(min(c['effective_source_end'],c['start']+(right-c['output_start'])*speed),8)))
        return parts
    old_cue_map={c['id']:c for c in old_cues};new_cue_map={c['id']:c for c in new_cues}
    affected_captions=[cid for cid,c in new_cue_map.items() if cid in old_cue_map and
                      coverage(old,old_cue_map[cid]['start'],old_cue_map[cid]['end'])!=coverage(new,c['start'],c['end'])]
    old_audio_map=dict(zip(base['audio_tracks'],old_tracks));new_audio_map=dict(zip(candidate['audio_tracks'],new_tracks))
    affected_audio=[aid for aid,a in new_audio_map.items() if aid in old_audio_map and
                    coverage(old,old_audio_map[aid]['output_start'],old_audio_map[aid]['output_start']+old_audio_map[aid]['end']-old_audio_map[aid]['start'])!=
                    coverage(new,a['output_start'],a['output_start']+a['end']-a['start'])]
    require(set(affected_captions)<=set(scope['caption_ids']),'CAPTION_REVIEW_SCOPE_REQUIRED')
    require(set(affected_audio)<=set(scope['audio_ids']),'AUDIO_REVIEW_SCOPE_REQUIRED')
    from overlay_ops import work_layers
    old_visual={x['id']:x for x in work_layers(base,old,tools)}
    new_visual={x['id']:x for x in work_layers(candidate,new,tools)}
    def visual_coverage(norm,layer):
        fps=float(Fraction(norm['fps']))
        return coverage(norm,layer['start_frame']/fps,layer['end_frame']/fps)
    affected_visual=[lid for lid in old_visual.keys()&new_visual.keys()
                     if visual_coverage(old,old_visual[lid])!=visual_coverage(new,new_visual[lid])]
    require(set(affected_visual)<=set(scope['visual_ids']),'VISUAL_REVIEW_SCOPE_REQUIRED')
    geometry=[k for k in ['fps','width','height','fit','allow_source_reuse'] if base['plan'].get(k)!=candidate['plan'].get(k)]
    require(set(geometry)<=set(scope['output_fields']),'OUTPUT_OUTSIDE_SCOPE')
    require(not set(geometry).intersection(['fps','width','height','fit']) or
            (set(old_visual)|set(new_visual))<=set(scope['visual_ids']),'VISUAL_GEOMETRY_REVIEW_REQUIRED')
    require(not set(geometry).intersection(['fps','width','height','fit']) or not frozen,'OUTPUT_AFFECTS_FROZEN_CLIPS')
    require(base['caption_style']==candidate['caption_style'] or scope['caption_style'],'CAPTION_STYLE_FROZEN')
    old_positions={c['id']:(c['output_start_frame'],c['output_end_frame']) for c in old['clips']}
    new_positions={c['id']:(c['output_start_frame'],c['output_end_frame']) for c in new['clips']}
    require(set(scope['freeze_positions'])<=set(old_positions),'FROZEN_POSITION_UNKNOWN')
    for cid in scope['freeze_positions']:
        require(old['fps']==new['fps'] and old_positions[cid]==new_positions.get(cid),'FROZEN_POSITION_CHANGED: '+cid)
    if scope['freeze_duration']:
        require(old['fps']==new['fps'] and old['total_frames']==new['total_frames'],'WORK_DURATION_FROZEN')
    modified=changes(before,after)
    require(set(modified)<=allowed,'CLIP_OUTSIDE_SCOPE')
    # A target may move even when its source range and parameters are unchanged.
    shifted=[cid for cid in before if cid in after and (old_positions[cid]!=new_positions[cid] or old['fps']!=new['fps'])]
    plan_changed=base['plan']!=candidate['plan']
    media_changed=plan_changed or any(base[k]!=candidate[k] for k in ['captions','caption_style','audio_tracks']) or bool(result['visual_layers'])
    result.update(changed_clip_ids=modified,shifted_clip_ids=shifted,output_fields=geometry,
        old_order=list(before),new_order=list(after),caption_style_changed=base['caption_style']!=candidate['caption_style'],
        old_frames=old['total_frames'],new_frames=new['total_frames'],
        before_document_sha256=fingerprint(base),document_sha256=fingerprint(candidate),
        caption_mapping_changed=old_cues!=new_cues,audio_mapping_changed=old_tracks!=new_tracks,
        caption_revalidation_declared=affected_captions,audio_revalidation_declared=affected_audio,
        visual_mapping_changed=old_visual!=new_visual,visual_revalidation_declared=sorted(affected_visual),
        speed_changed_clip_ids=speed_changed,
        evidence_mapping_changed=mapping_changed or bool(speed_changed and old_protection is not None),
        evidence_mapping_revalidation_declared=scope['evidence_mapping'],
        invalidated=(['render','technical-qc','content-review','visual-review','listening-review'] if media_changed else
                     ['content-review','style-review'] if base['style_bindings']!=candidate['style_bindings'] else
                     ['evidence-map','content-review'] if mapping_changed else []),
        style_application='metadata only; visual/audio changes must be explicit in the document')
    if old_protection is not None and base!=candidate and 'evidence-map' not in result['invalidated']:
        # An exported evidence map binds the entire document, even if only an
        # unrelated note/caption changed; current validation does not refresh it.
        result['invalidated'].append('evidence-map')
    if base['notes'].get('drama_domain_ref') != candidate['notes'].get('drama_domain_ref'):
        # Domain review binds the attachment identity; unchanged media remains reusable.
        for check in ('content-review', 'drama-domain-review'):
            if check not in result['invalidated']:
                result['invalidated'].append(check)
    return result


def token(work_id,seq,digest):
    from editing_runtime import fingerprint
    return fingerprint({'work_id':work_id,'sequence':seq,'document_sha256':digest})


def connect(path):
    from editing_runtime import require,ContractError
    p=Path(path);require(p.is_absolute() and p.is_file(),'WORK_STORE_NOT_FOUND')
    try:
        db=sqlite3.connect(p.resolve().as_uri()+'?mode=rw',uri=True,timeout=0)
        db.row_factory=sqlite3.Row
        if db.execute('PRAGMA user_version').fetchone()[0]!=1:
            db.close();raise ContractError('WORK_STORE_SCHEMA_UNSUPPORTED')
        return db
    except sqlite3.Error as exc:raise ContractError('WORK_STORE_ERROR: '+str(exc)) from exc


def load(db,sequence=None):
    from editing_runtime import require,fingerprint
    meta=dict(db.execute('SELECT key,value FROM metadata'))
    seq=int(meta['head']) if sequence is None else sequence
    row=db.execute('SELECT * FROM revisions WHERE sequence=?',(seq,)).fetchone()
    require(row is not None,'WORK_REVISION_NOT_FOUND')
    doc=json.loads(row['document']);require(fingerprint(doc)==row['digest'],'WORK_DOCUMENT_HASH_MISMATCH')
    require(row['version']==token(meta['work_id'],seq,row['digest']),'WORK_VERSION_HASH_MISMATCH')
    return {'work_id':meta['work_id'],'sequence':seq,'version':row['version'],'document_sha256':row['digest'],'document':doc}


def append(db,current,document,action,message,author,extra):
    from editing_runtime import fingerprint,require
    require(isinstance(message,str) and message.strip(),'REVISION_MESSAGE_REQUIRED')
    require(author in ['agent','human'],'AUTHOR_REQUIRED')
    seq=current['sequence']+1;digest=fingerprint(document);version=token(current['work_id'],seq,digest)
    db.execute('INSERT INTO revisions VALUES(?,?,?,?,?,?,?,?,?,?)',
               (seq,current['sequence'],version,digest,canonical(document),action,message,author,canonical(extra),None))
    db.execute('UPDATE metadata SET value=? WHERE key=?',(str(seq),'head'))
    return {'work_id':current['work_id'],'sequence':seq,'version':version,'document_sha256':digest,'document':document}


def _style_target(reference):
    """Observe a prepared regular file; no symlinks, source aliases or old-path reads."""
    from editing_runtime import exact_keys, require, source
    exact_keys(reference,['path','sha256'],['path','sha256'])
    require(isinstance(reference['path'],str) and Path(reference['path']).is_absolute(),
            'ABSOLUTE_STYLE_RESOURCE_PATH_REQUIRED')
    path=Path(reference['path'])
    require(not any(p.is_symlink() for p in (path,*path.parents)), 'STYLE_RESOURCE_SYMLINK_UNSUPPORTED')
    require(path.is_file(),'STYLE_RESOURCE_NOT_FILE')
    require(str(path.resolve())==reference['path'],'STYLE_RESOURCE_CANONICAL_PATH_REQUIRED')
    return source(reference)


def relink_style_resources(document, relocations):
    """Only path maintenance of existing same-byte style cards, without media validation."""
    from editing_runtime import exact_keys, require, fingerprint
    require(isinstance(relocations,list) and bool(relocations),'STYLE_RELOCATIONS_REQUIRED')
    require(isinstance(document.get('style_bindings'),dict),'STYLE_BINDINGS_REQUIRED')
    updated=copy.deepcopy(document);seen=set();records=[]
    for move in relocations:
        exact_keys(move,['style_key','from','to'],['style_key','from','to'])
        key=move['style_key']
        require(isinstance(key,str) and key in document['style_bindings'],'STYLE_RELOCATION_KEY_UNKNOWN')
        require(key not in seen,'STYLE_RELOCATION_KEY_DUPLICATE');seen.add(key)
        original=document['style_bindings'][key]['card']
        exact_keys(original,['path','sha256'],['path','sha256'])
        for name in ('from','to'):
            exact_keys(move[name],['path','sha256'],['path','sha256'])
            require(isinstance(move[name]['path'],str) and Path(move[name]['path']).is_absolute(),
                    'ABSOLUTE_STYLE_RESOURCE_PATH_REQUIRED')
            require(isinstance(move[name]['sha256'],str) and re.fullmatch('[0-9a-f]{64}',move[name]['sha256']),
                    'STYLE_RESOURCE_SHA256_REQUIRED')
        require(move['from']==original,'STYLE_RELOCATION_FROM_MISMATCH')
        require(move['to']['sha256']==original['sha256'],'STYLE_RELOCATION_SHA256_CHANGED')
        require(Path(move['from']['path']).resolve()!=Path(move['to']['path']).resolve(),
                'STYLE_RELOCATION_PATH_UNCHANGED')
        actual=_style_target(move['to'])
        updated['style_bindings'][key]['card']['path']=actual['path']
        records.append({'style_key':key,'from':copy.deepcopy(original),'to':copy.deepcopy(move['to']),
                        'target_identity':actual})
    restored=copy.deepcopy(updated)
    for move in records:
        restored['style_bindings'][move['style_key']]['card']['path']=move['from']['path']
    require(canonical(restored)==canonical(document),'STYLE_RELOCATION_NONPATH_CHANGE')
    require(fingerprint(updated)!=fingerprint(document),'NO_CHANGE_TO_COMMIT')
    return updated,records


def recheck_style_resources(records):
    """Repeat target byte and regular-file checks immediately before append."""
    from editing_runtime import require
    for move in records:
        actual=_style_target(move['to'])
        require(actual==move['target_identity'],'STYLE_RESOURCE_CHANGED_DURING_MAINTENANCE')


def work_version(request,directory,tools):
    from editing_runtime import exact_keys,require,fingerprint,write_json,source,ContractError
    action=request.get('action')
    fields={'init':['store','work_id','document','message','author'],
            'read':['store'],
            'commit':['store','expected_version','candidate','message','author'],
            'set-protection':['store','expected_version','protection','change_basis','message','author'],
            'restore':['store','expected_version','target_sequence','message','author'],
            'relink-style-resources':['store','expected_version','relocations','message','author']}
    require(action in fields,'WORK_ACTION_UNSUPPORTED')
    optional=(['style_resource_relocations'] if action=='restore' else
              ['drama_inheritance'] if action=='init' else [])
    exact_keys(request,['operation','action']+fields[action]+optional,['operation','action']+fields[action])
    p=Path(request['store']);require(p.is_absolute(),'ABSOLUTE_STORE_PATH_REQUIRED')
    from drama_binding import (validate_work_attachment, recheck as drama_recheck,
                               public_report, DramaBindingError)
    def check_drama(document, previous=None, expected_base=None):
        try:
            report=validate_work_attachment(document, previous=previous, expected_base=expected_base)
            if report is not None:
                drama_recheck(report)
            return public_report(report) if report is not None else None
        except (DramaBindingError, OSError) as exc:
            raise ContractError(str(exc)) from exc
    if action=='init':
        require(isinstance(request['message'],str) and request['message'].strip(),'REVISION_MESSAGE_REQUIRED')
        require(request['author'] in ['agent','human'],'AUTHOR_REQUIRED')
        validate_document(request['document'],tools)
        drama_report=None
        if 'drama_domain_ref' in request['document']['notes']:
            # A variant may inherit a checked domain from a real parent revision.
            inheritance=request.get('drama_inheritance')
            exact_keys(inheritance,['store','expected_version'],['store','expected_version'])
            parent_path=Path(inheritance['store'])
            require(parent_path.is_absolute() and parent_path.resolve()!=p.resolve(),
                    'DRAMA_PARENT_STORE_INVALID')
            parent_db=connect(parent_path)
            try:
                parent=load(parent_db)
                require(parent['version']==inheritance['expected_version'],'DRAMA_PARENT_VERSION_CONFLICT')
            finally:parent_db.close()
            drama_report=check_drama(request['document'],parent['document'],parent['version'])
        else:
            require('drama_inheritance' not in request,'DRAMA_INHERITANCE_WITHOUT_REF')
        require(isinstance(request['work_id'],str) and bool(re.fullmatch('[A-Za-z0-9][A-Za-z0-9_-]{0,79}',request['work_id'])),'WORK_ID_INVALID')
        require(p.parent.is_dir(),'STORE_PARENT_NOT_FOUND')
        fd=os.open(p,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
        db=sqlite3.connect(str(p),timeout=0);db.row_factory=sqlite3.Row
        try:
            with db:
                db.execute('PRAGMA user_version=1')
                db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
                db.execute('CREATE TABLE revisions(sequence INTEGER PRIMARY KEY,parent INTEGER NOT NULL,version TEXT NOT NULL,digest TEXT NOT NULL,document TEXT NOT NULL,action TEXT NOT NULL,message TEXT NOT NULL,author TEXT NOT NULL,extra TEXT NOT NULL,reserved TEXT)')
                db.executemany('INSERT INTO metadata VALUES(?,?)',[('work_id',request['work_id']),('head','0')])
                extra=({'drama_attachment_validation':drama_report,'drama_inheritance':request['drama_inheritance']}
                       if drama_report else {})
                state=append(db,{'sequence':0,'work_id':request['work_id']},request['document'],'init',request['message'],request['author'],extra)
        finally:db.close()
        result={**state,'action':'init'}
        if drama_report:result['drama_attachment_validation']=drama_report
    else:
        db=connect(p)
        try:
            db.execute('BEGIN' if action=='read' else 'BEGIN IMMEDIATE')
            current=load(db)
            if action=='read':
                history=[dict(row) for row in db.execute('SELECT sequence,parent,version,digest,action,message,author,extra FROM revisions ORDER BY sequence')]
                result={**current,'action':'read','history':history,'external_media_validation':'NOT_RUN'}
                try:
                    drama_report=check_drama(current['document'])
                    if drama_report:result['drama_attachment_validation']=drama_report
                except ContractError as exc:
                    # Keep the authoritative snapshot readable for repair; do not certify its attachment.
                    result['drama_attachment_validation']={'status':'FAIL','error':str(exc),
                        'semantic_review':'NOT_RUN','media_review':'NOT_RUN'}
            else:
                require(request['expected_version']==current['version'],'WORK_VERSION_CONFLICT')
                if action=='commit':
                    candidate_ref=source(request['candidate'])
                    candidate_bytes=Path(candidate_ref['path']).read_bytes()
                    require(hashlib.sha256(candidate_bytes).hexdigest()==candidate_ref['sha256'],
                            'SOURCE_HASH_MISMATCH: '+candidate_ref['path'])
                    bundle=json.loads(candidate_bytes.decode('utf-8'))
                    exact_keys(bundle,['schema','base_version','base_document_sha256','document','scope'],['schema','base_version','base_document_sha256','document','scope'])
                    require(bundle['schema']=='work-candidate/1','CANDIDATE_SCHEMA_UNSUPPORTED')
                    require(bundle['base_version']==current['version'] and bundle['base_document_sha256']==current['document_sha256'],'CANDIDATE_BASE_CONFLICT')
                    diff=revision_diff(current['document'],bundle['document'],bundle['scope'],tools)
                    require(diff['document_sha256']!=current['document_sha256'],'NO_CHANGE_TO_COMMIT')
                    drama_report=check_drama(bundle['document'],current['document'],current['version'])
                    require(source(request['candidate'])==candidate_ref,'CANDIDATE_CHANGED_DURING_VALIDATION')
                    state=append(db,current,bundle['document'],'commit',request['message'],request['author'],
                        {'diff':diff,'candidate':candidate_ref,**({'drama_attachment_validation':drama_report} if drama_report else {})})
                    result={**state,'action':'commit','diff':diff}
                    if drama_report:
                        result['drama_attachment_validation']=drama_report
                elif action=='set-protection':
                    require(isinstance(request['change_basis'],str) and request['change_basis'].strip(),'PROTECTION_CHANGE_BASIS_REQUIRED')
                    document=copy.deepcopy(current['document'])
                    if request['protection'] is None:
                        document.pop('evidence_protection',None)
                    else:
                        document['evidence_protection']=copy.deepcopy(request['protection'])
                    validate_document(document,tools)
                    require(fingerprint(document)!=current['document_sha256'],'NO_CHANGE_TO_COMMIT')
                    old_protection=current['document'].get('evidence_protection')
                    new_protection=document.get('evidence_protection')
                    extra={'change_basis':request['change_basis'],
                        'previous_protection_sha256':fingerprint(old_protection) if old_protection is not None else None,
                        'protection_sha256':fingerprint(new_protection) if new_protection is not None else None,
                        'authorization':'Explicit operation declaration only; author field is not proof of human approval.'}
                    drama_report=check_drama(document)
                    if drama_report:extra['drama_attachment_validation']=drama_report
                    state=append(db,current,document,'set-protection',request['message'],request['author'],extra)
                    result={**state,'action':'set-protection',**extra,
                        'invalidated':['evidence-map','content-review','listening-review'],
                        'semantic_review':'NOT_RUN','audibility_legibility':'NOT_RUN'}
                elif action=='relink-style-resources':
                    document,records=relink_style_resources(current['document'],request['relocations'])
                    extra={'relocations':records,'previous_version':current['version'],
                        'previous_document_sha256':current['document_sha256'],
                        'document_sha256':fingerprint(document),'scope':'same-byte style-card paths only',
                        'resource_binding_validation':'HASH_MATCHED','media_validation':'NOT_RUN',
                        'semantic_review':'NOT_RUN','protection_validation':{
                            'mode':'NOT_RUN','validated_this_operation':False,'stored_mapping_unchanged':True,
                            'declared_coverage':'NOT_REVALIDATED'}}
                    recheck_style_resources(records)
                    drama_report=check_drama(document)
                    if drama_report:extra['drama_attachment_validation']=drama_report
                    state=append(db,current,document,action,request['message'],request['author'],extra)
                    result={**state,'action':action,**extra,'history_preserved':True,
                        'invalidated':['candidate','host-snapshot','render','technical-qc','content-review',
                                       'visual-review','listening-review','evidence-map','delivery-selection']}
                else:
                    require(type(request['target_sequence']) is int,'SEQUENCE_INTEGER_REQUIRED')
                    target=load(db,request['target_sequence'])
                    document=target['document'];records=[]
                    if 'style_resource_relocations' in request:
                        document,records=relink_style_resources(document,request['style_resource_relocations'])
                    expected_document=fingerprint(document)
                    validate_document(document,tools)
                    require(fingerprint(document)==expected_document,'RESTORE_DOCUMENT_CHANGED_DURING_VALIDATION')
                    recheck_style_resources(records)
                    extra={'restored_from':target['sequence'],'previous_version':current['version']}
                    if records:
                        extra.update(style_resource_relocations=records,
                            target_document_sha256=target['document_sha256'],document_sha256=expected_document,
                            scope='historical content plus same-byte style-card paths; full document validated')
                    drama_report=check_drama(document)
                    if drama_report:extra['drama_attachment_validation']=drama_report
                    state=append(db,current,document,'restore',request['message'],request['author'],extra)
                    result={**state,'action':'restore',**extra,'history_preserved':True,
                            'invalidated':['render','technical-qc','content-review','visual-review','listening-review','evidence-map']}
            db.commit()
        except sqlite3.OperationalError as exc:
            db.rollback();raise ContractError('WORK_BUSY' if 'locked' in str(exc) else 'WORK_STORE_ERROR: '+str(exc)) from exc
        except Exception:
            db.rollback();raise
        finally:db.close()
    if 'evidence_protection' in result['document'] and action!='relink-style-resources':
        result['protection_validation'] = {
            'mode': 'ordinary_protection',
            'declared_coverage': 'DECLARED_SOURCE_RANGES_PRESERVED',
            'source_audio_clock_precision': 'NOT_CERTIFIED_BY_WORK_RECEIPT',
            'video_unit_coverage': 'PLAYBACK_MAY_BRIDGE_QUANTIZATION',
            'validated_this_operation': action != 'read',
        }
    # SQLite is authoritative if writing the export fails after a successful commit.
    write_json(directory/'work-state.json',result)
    return result


def timeline_revise(request,directory,tools):
    from editing_runtime import exact_keys,require,fingerprint,write_json
    exact_keys(request,['operation','base_version','document','expected_document_sha256','candidate','scope'],
               ['operation','base_version','document','expected_document_sha256','candidate','scope'])
    require(isinstance(request['base_version'],str) and re.fullmatch('[0-9a-f]{64}',request['base_version']),'BASE_VERSION_REQUIRED')
    require(fingerprint(request['document'])==request['expected_document_sha256'],'DOCUMENT_REVISION_CONFLICT')
    diff=revision_diff(request['document'],request['candidate'],request['scope'],tools)
    bundle={'schema':'work-candidate/1','base_version':request['base_version'],'base_document_sha256':request['expected_document_sha256'],
            'document':request['candidate'],'scope':request['scope']}
    write_json(directory/'candidate.json',bundle);write_json(directory/'revision-diff.json',diff)
    return {**diff,'applied_to_work':False}


def render_document(document,directory,tools,*,work_version,audio_backend=None,source_consumption=None):
    from source_binding import consumption_session, document_references
    from editing_runtime import sha256
    with consumption_session(document_references(document),source_consumption,directory,tools) as (_,bound_tools):
        result=_render_document_bound(document,directory,bound_tools,work_version=work_version,
                                      audio_backend=audio_backend,source_consumption=source_consumption)
    binding=directory/'source-binding.json'
    evidence=json.loads(binding.read_text())
    result['source_consumption']={'schema':evidence['schema'],'selection':evidence['selection'],
        'status':evidence['status'],'adoptable':evidence['adoptable'],
        'binding':{'path':str(binding),'sha256':sha256(binding)},
        'child_receipts':result.pop('child_receipts')}
    return result


def _render_document_bound(document,directory,tools,*,work_version,audio_backend=None,source_consumption=None):
    """Render one immutable WorkDocument; never write to the Work store."""
    from editing_runtime import run,sha256,write_json,require,fingerprint,OperationCancelled
    doc=copy.deepcopy(document)
    norm,cues,tracks=validate_document(doc,tools)
    child_receipts=[]
    def invoke(req,name):
        receipt=run(req,directory/name,tools)
        if receipt.get('cancelled'):
            raise OperationCancelled('WORK_RENDER_CANCELLED: '+name+': '+receipt.get('error',''))
        require(receipt['status']=='SUCCEEDED','WORK_RENDER_FAILED: '+name+': '+receipt.get('error',''))
        child_receipts.append({'operation':req['operation'],'path':str(directory/name/'receipt.json'),
                               'sha256':sha256(directory/name/'receipt.json')})
    invoke({'operation':'timeline-render','plan':doc['plan'],
            **({'source_consumption':source_consumption} if source_consumption is not None else {}),
            **({'audio_backend':audio_backend} if audio_backend is not None else {})},'timeline')
    current=directory/'timeline/preview.mp4'
    if tracks:
        invoke({'operation':'audio-mix','source':{'path':str(current),'sha256':sha256(current)},'base_gain_db':0,'tracks':tracks},'audio')
        current=directory/'audio/mixed.mp4'
    from overlay_ops import work_layers
    visual=work_layers(doc,norm,tools)
    if visual:
        fields=['id','source','source_start_frame','start_frame','duration_frames','rect','opacity','z','allow_upscale','input_color']
        invoke({'operation':'visual-layer-render','source':{'path':str(current),'sha256':sha256(current)},
                'input_color':'bt709-sdr-limited','layers':[{k:v[k] for k in fields} for v in visual]},'visual')
        current=directory/'visual/composited.mp4'
    if cues:
        invoke({'operation':'caption-burn','source':{'path':str(current),'sha256':sha256(current)},**doc['caption_style'],
                'cues':[{k:v for k,v in c.items() if k!='id'} for c in cues]},'captions')
        current=directory/'captions/captioned.mp4'
    invoke({'operation':'media-qc','source':{'path':str(current),'sha256':sha256(current)},
            'expected':{'duration':norm['duration'],'duration_tolerance':0.1,'width':norm['width'],'height':norm['height'],'audio_required':True}},'qc')
    write_json(directory/'rendered-document.json',doc)
    write_json(directory/'output-captions.json',{'cues':cues,'work_version':work_version})
    if visual:write_json(directory/'output-visual-layers.json',{'layers':visual,'work_version':work_version,'order':'after audio, before captions'})
    return {'video':{'path':str(current),'sha256':sha256(current)},'document_sha256':fingerprint(doc),
            'child_receipts':child_receipts,
            'layer_counts':{'audio_tracks':len(tracks),'visual_layers':len(visual),'captions':len(cues)}}


def work_render(request,directory,tools):
    from editing_runtime import exact_keys,require,source,write_json,fingerprint
    preview='preview_candidate' in request
    fields=['operation','store','expected_version']+(['preview_candidate'] if preview else [])
    exact_keys(request,fields+['audio_backend','source_consumption'],fields)
    db=connect(request['store'])
    try:
        db.execute('BEGIN');state=load(db);db.commit()
    finally:db.close()
    require(request['expected_version']==state['version'],'WORK_VERSION_CONFLICT')
    candidate_ref=None;diff=None
    if preview:
        candidate_ref=source(request['preview_candidate'])
        with open(candidate_ref['path'],encoding='utf-8') as stream:bundle=json.load(stream)
        exact_keys(bundle,['schema','base_version','base_document_sha256','document','scope'],
                   ['schema','base_version','base_document_sha256','document','scope'])
        require(bundle['schema']=='work-candidate/1','CANDIDATE_SCHEMA_UNSUPPORTED')
        require(bundle['base_version']==state['version'] and bundle['base_document_sha256']==state['document_sha256'],
                'CANDIDATE_BASE_CONFLICT')
        diff=revision_diff(state['document'],bundle['document'],bundle['scope'],tools)
        require(diff['document_sha256']!=state['document_sha256'],'NO_CHANGE_TO_PREVIEW')
        source(request['preview_candidate'])
        document=bundle['document']
    else:
        document=state['document']
    rendered=render_document(document,directory,tools,work_version=state['version'],audio_backend=request.get('audio_backend'),
                             source_consumption=request.get('source_consumption'))
    if preview:source(request['preview_candidate'])
    db=connect(request['store'])
    try:latest=load(db)
    finally:db.close()
    result={'work_id':state['work_id'],'version':state['version'],
            'document_sha256':rendered['document_sha256'],
            'audio_backend_request':copy.deepcopy(request.get('audio_backend')),
            'audio_backend_request_sha256':fingerprint(request.get('audio_backend')),
            'source_consumption_request':copy.deepcopy(request.get('source_consumption')),
            'source_consumption_request_sha256':fingerprint(request.get('source_consumption')),
            'source_consumption':rendered['source_consumption'],
            'video':rendered['video'],'current_at_finish':latest['version']==state['version'],
            'current_version_at_finish':latest['version'],'technical_status':'PASSED','delivery_status':'DEGRADED',
            'source_audio_evidence':'NOT_GRANTED_BY_RENDER',
            'style_application':'explicit document operations only; bindings are not automatic effects',
            'content_review':'NOT_RUN','listening_review':'NOT_RUN','native_editor_acceptance':'NOT_RUN'}
    if preview:
        result.update(preview_status='CANDIDATE_PREVIEW_NOT_COMMITTED',
                      preview_candidate=candidate_ref,
                      candidate_document_sha256=rendered['document_sha256'],
                      base_document_sha256=state['document_sha256'],
                      changed_fields=diff,
                      adoption_requires_fresh_head=True,
                      adoption_authorized_by_preview=False,
                      preview_current_at_finish=latest['version']==state['version'])
    write_json(directory/'render-binding.json',result)
    return result


def execute(request,directory,tools):
    from editing_runtime import ContractError
    try:
        return {'work-version':work_version,'timeline-revise':timeline_revise,'work-render':work_render}[request['operation']](request,directory,tools)
    except sqlite3.Error as exc:raise ContractError('WORK_STORE_ERROR: '+str(exc)) from exc
