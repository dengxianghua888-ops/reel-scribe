"""Strict Blender 4.3.2 cut snapshot bridge; never saves the open host or adopts edits.
Blender: -b --disable-autoexec PROJECT --python-exit-code 1 --python THIS -- PACKAGE NEW_OTIO EXPECTED_HOST_SHA256
The resulting saved OTIO feeds existing film otio_readback.capture_saved_snapshot.
"""
import importlib.util
import json
import hashlib
import os
import tempfile
import subprocess
from pathlib import Path
import sys
from fractions import Fraction

_spec = importlib.util.spec_from_file_location('cut_import', Path(__file__).with_name('blender_cut_import.py'))
imp = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(imp)
require = imp.require

# Restrict processing rather than silently discarding unsupported native properties.
COMMON = {'mute': False, 'blend_type': 'ALPHA_OVER', 'blend_alpha': 1.0,
          'effect_fader': 0.0, 'use_default_fade': False, 'use_linear_modifiers': False}
VIDEO = {'alpha_mode':'STRAIGHT', 'views_format':'INDIVIDUAL', 'stream_index': 0, 'use_multiview': False, 'use_deinterlace': False,
         'use_flip_x': False, 'use_flip_y': False, 'use_float': False,
         'use_reverse_frames': False, 'color_multiply': 1.0, 'multiply_alpha': False,
         'color_saturation': 1.0, 'strobe': 0.0, 'use_proxy': False,
         'animation_offset_start': 0, 'animation_offset_end': 0}
AUDIO = {'sound_offset': 0.0, 'volume': 1.0, 'pan': 0.0, 'animation_offset_start': 0, 'animation_offset_end': 0}


def integer(value):
    require(type(value) in (int, float) and Fraction(str(value)).denominator == 1, 'HOST_SUBFRAME_UNSUPPORTED')
    return int(value)


def observe(bpy):
    require(tuple(bpy.app.version) == imp.SUPPORTED_VERSION, 'HOST_VERSION_UNSUPPORTED')
    scene = bpy.context.scene
    require(scene.get('reel_adapter') == 'experimental-blender-cut/1', 'HOST_ADAPTER_BINDING')
    require(not bpy.data.libraries and not scene.animation_data and not scene.use_nodes, 'HOST_ANIMATION_OR_COMPOSITOR')
    require(scene.render.frame_map_old == 100 and scene.render.frame_map_new == 100, 'HOST_TIME_REMAP_UNSUPPORTED')
    require(scene.frame_step == 1 and scene.use_audio, 'HOST_AUDIO_OR_FRAME_STEP')
    require(scene.audio_volume == 1 and scene.render.use_sequencer and scene.render.pixel_aspect_x == 1 and scene.render.pixel_aspect_y == 1, 'HOST_OUTPUT_PROCESSING')
    require(scene.render.fps_base == 1 and scene.render.resolution_percentage == 100,
            'HOST_PROFILE_CHANGED')
    require(scene.view_settings.view_transform == 'Standard' and scene.view_settings.look == 'None' and
            scene.view_settings.exposure == 0 and scene.view_settings.gamma == 1 and
            not scene.view_settings.use_curve_mapping and scene.sequencer_colorspace_settings.name == 'sRGB',
            'HOST_COLOR_PROCESSING')
    seq = scene.sequence_editor
    require(seq is not None and not seq.meta_stack, 'HOST_SEQUENCE_REQUIRED')
    require(all(not c.mute for c in seq.channels), 'HOST_MUTED_CHANNEL')
    rows = []
    for strip in seq.sequences_all:
        require(strip.type in ('MOVIE', 'SOUND'), 'HOST_STRIP_TYPE_UNSUPPORTED')
        require(not strip.modifiers, 'HOST_MODIFIER_UNSUPPORTED')
        for key, expected in {**COMMON, **(VIDEO if strip.type == 'MOVIE' else AUDIO)}.items():
            require(hasattr(strip, key) and getattr(strip, key) == expected, 'HOST_PROCESSING_UNSUPPORTED: ' + key)
        if strip.type == 'MOVIE':
            require(strip.colorspace_settings.name == 'sRGB', 'HOST_SOURCE_COLOR_CHANGED')
            require(not strip.retiming_keys, 'HOST_RETIMING_UNSUPPORTED')
            require(all(getattr(strip.transform,k)==v for k,v in {'offset_x':0,'offset_y':0,'scale_x':1,'scale_y':1,'rotation':0}.items()), 'HOST_TRANSFORM_UNSUPPORTED')
            require(all(getattr(strip.crop,k)==0 for k in ('min_x','max_x','min_y','max_y')), 'HOST_CROP_UNSUPPORTED')
            path = bpy.path.abspath(strip.filepath)
        else:
            require(strip.sound and not strip.sound.packed_file and not strip.sound.use_mono and not getattr(strip.sound,'animation_data',None), 'HOST_PACKED_SOUND_UNSUPPORTED')
            path = bpy.path.abspath(strip.sound.filepath)
        rows.append({'id':strip.get('reel_instance_id'), 'name':strip.name,
                     'kind':'Video' if strip.type=='MOVIE' else 'Audio', 'path':str(Path(path).resolve()),
                     'channel':strip.channel,'target':integer(strip.frame_final_start),
                     'offset':integer(strip.frame_final_start-strip.frame_start),
                     'length':integer(strip.frame_final_end-strip.frame_final_start)})
    return {'package_sha256':scene.get('reel_package_sha256'), 'profile':{
        'fps':scene.render.fps,'width':scene.render.resolution_x,'height':scene.render.resolution_y},
        'frame_start':scene.frame_start,'frame_end':scene.frame_end,'clips':rows}


def project(root, observed, media_probe=imp.probe):
    """Validate all native observations before constructing a saved OTIO branch."""
    root = Path(root).resolve()
    _, seal = imp.package(root)
    seal_sha = imp.digest(root/'checksums.json')
    base = imp.validate(root,media_probe)
    require(base['package_sha256']==seal_sha,'PACKAGE_CHANGED_DURING_READBACK')
    require(observed['package_sha256']==base['package_sha256'], 'HOST_PACKAGE_MISMATCH')
    profile={'fps':base['fps'],'width':base['profile']['width'],'height':base['profile']['height']}
    require(observed['profile']==profile and observed['frame_start']==1, 'HOST_PROFILE_CHANGED')
    expected={r['name']:r for r in base['clips']}; actual={}
    for row in observed['clips']:
        require(row['id'] in expected and row['id'] not in actual and row['name']==row['id'], 'HOST_INSTANCE_SET_CHANGED')
        old=expected[row['id']]
        require(all(row[k]==old[k] for k in ('kind','path','channel')), 'HOST_RESOURCE_OR_TRACK_CHANGED')
        require(all(type(row[k]) is int for k in ('target','offset','length')) and row['target']>=1 and row['offset']>=0 and row['length']>0,'HOST_INVALID_WINDOW')
        # First release only trims within the exported window, never extends unseen evidence.
        require(old['offset']<=row['offset'] and row['offset']+row['length']<=old['offset']+old['length'], 'HOST_WINDOW_EXTENSION_UNSUPPORTED')
        actual[row['id']]=row
    require(set(actual)==set(expected), 'HOST_INSTANCE_SET_CHANGED')
    raw=(root/'timeline.otio').read_bytes()
    require(hashlib.sha256(raw).hexdigest()==seal['files']['timeline.otio']['sha256'],'PACKAGE_CHANGED_DURING_READBACK')
    timeline=json.loads(raw,object_pairs_hook=imp.unique)
    end=1
    for track in timeline['tracks']['children']:
        cursor=1
        for clip in track['children']:
            require(clip['OTIO_SCHEMA']=='Clip.1','HOST_GAP_UNSUPPORTED')
            row=actual[clip['name']]
            require(row['target']==cursor,'HOST_GAP_OVERLAP_OR_REORDER_UNSUPPORTED')
            meta=clip['metadata']['recap']
            if track['kind']=='Audio':
                require(meta.get('linked_video_instance') in actual,'HOST_AUDIO_PAIR_REQUIRED')
                picture=actual[meta['linked_video_instance']]
                require(picture['kind']=='Video' and all(row[k]==picture[k] for k in ('path','target','offset','length')), 'HOST_AUDIO_VIDEO_DESYNC')
            for field,value in [('source_start',row['offset']),('duration',row['length']),('target_start',row['target']-1)]:
                meta[field]={'numerator':value,'denominator':base['fps']}
            rate=imp.number(clip['source_range']['start_time']['rate'])
            duration_rate=imp.number(clip['source_range']['duration']['rate'])
            require(rate==duration_rate,'HOST_RATE_MISMATCH')
            start_units=Fraction(row['offset'],base['fps'])*rate
            duration_units=Fraction(row['length'],base['fps'])*rate
            require(start_units.denominator==duration_units.denominator==1,'HOST_AUDIO_SUBSAMPLE_UNSUPPORTED')
            clip['source_range']={'OTIO_SCHEMA':'TimeRange.1','start_time':{'OTIO_SCHEMA':'RationalTime.1','value':int(start_units),'rate':float(rate)},'duration':{'OTIO_SCHEMA':'RationalTime.1','value':int(duration_units),'rate':float(rate)}}
            cursor+=row['length']
        end=max(end,cursor)
    require(observed['frame_end']==end-1,'HOST_RENDER_RANGE_CHANGED')
    imp.package(root)
    require(imp.digest(root/'checksums.json')==seal_sha,'PACKAGE_CHANGED_DURING_READBACK')
    return timeline


def export_snapshot(root, output, bpy, expected_host_sha256):
    source=Path(bpy.data.filepath)
    require(source.is_file() and not source.is_symlink(),'SAVED_HOST_REQUIRED')
    before=imp.digest(source)
    require(before == expected_host_sha256, 'HOST_FILE_IDENTITY_CONFLICT')
    timeline=project(root,observe(bpy))
    require(imp.digest(source)==before,'HOST_FILE_CHANGED_DURING_READBACK')
    output=Path(output)
    require(output.parent.is_dir() and output.suffix=='.otio' and not output.is_symlink(), 'OUTPUT_UNSAFE')
    require(not output.resolve().is_relative_to(Path(root).resolve()), 'OUTPUT_CANNOT_MODIFY_PACKAGE')
    atomic_new(output, json.dumps(timeline,ensure_ascii=False,sort_keys=True,allow_nan=False).encode())
    return {'saved_otio':str(output),'saved_host_sha256':before, 'saved_host_path':str(source),
            'saved_otio_sha256':imp.digest(output), 'adoption_performed':False,'host_cas':False}


def atomic_new(output, raw):
    """Same-directory hard-link commit: no partial target and no overwrite."""
    output=Path(output)
    fd,name=tempfile.mkstemp(prefix='.readback-',suffix='.pending',dir=output.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        os.link(name,output)
    finally:
        try:os.unlink(name)
        except OSError:pass


def launch(saved_host, root, output, *, blender='blender'):
    """Only supported public entry: controlled saved-file load with pre/post identity."""
    saved_host=Path(saved_host).absolute();root=Path(root).absolute();output=Path(output).absolute()
    require(saved_host.is_file() and not saved_host.is_symlink(),'SAVED_HOST_REQUIRED')
    require(not output.exists() and not output.is_symlink() and output.parent.is_dir(),'OUTPUT_UNSAFE_OR_EXISTS')
    require(not output.resolve().is_relative_to(root.resolve()),'OUTPUT_CANNOT_MODIFY_PACKAGE')
    imp.package(root)
    package_sha=imp.digest(root/'checksums.json')
    expected=imp.digest(saved_host)
    with tempfile.TemporaryDirectory(prefix='reel-readback-') as tmp:
        staged=Path(tmp)/'saved.otio'
        result=subprocess.run([blender,'-b','--disable-autoexec',str(saved_host),'--python-exit-code','1',
            '--python',str(Path(__file__).resolve()),'--',str(root),str(staged),expected],
            capture_output=True,text=True,timeout=180)
        require(result.returncode==0,'HOST_READBACK_FAILED: '+result.stdout[-2500:]+result.stderr[-1000:])
        require(imp.digest(saved_host)==expected,'HOST_FILE_CHANGED_DURING_READBACK')
        imp.package(root)
        require(imp.digest(root/'checksums.json')==package_sha,'PACKAGE_CHANGED_DURING_READBACK')
        raw=staged.read_bytes();json.loads(raw)
        atomic_new(output,raw)
    return {'saved_otio':str(output),'saved_host_path':str(saved_host),'saved_host_sha256':expected,
            'saved_otio_sha256':imp.digest(output),'adoption_performed':False,'host_cas':False,
            'mode':'controlled-background-saved-file-readback'}


if __name__=='__main__':
    try:
        import bpy
    except ModuleNotFoundError:
        import argparse
        parser=argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--host',required=True);parser.add_argument('--package',required=True)
        parser.add_argument('--output',required=True);parser.add_argument('--blender',default='blender')
        args=parser.parse_args();print(json.dumps(launch(args.host,args.package,args.output,blender=args.blender)))
    else:
        args=sys.argv[sys.argv.index('--')+1:]
        require(len(args)==3,'EXPECTED_PACKAGE_NEW_OTIO_AND_HOST_SHA')
        print(json.dumps(export_snapshot(args[0],args[1],bpy,args[2])))
