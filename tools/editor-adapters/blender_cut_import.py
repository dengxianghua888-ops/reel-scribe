"""Experimental Blender 4.3.2 importer for verified Reel integer-CFR cut packages.
Run: blender -b --factory-startup --python-exit-code 1 --python THIS -- PACKAGE OUT.blend
No captions, effects, automatic edits, rendering, reverse import or publication.
"""
import hashlib
import json
import math
from fractions import Fraction
from pathlib import Path
import subprocess
import sys

SUPPORTED_VERSION = (4, 3, 2)


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def unique(pairs):
    out = {}
    for key, value in pairs:
        require(key not in out, 'DUPLICATE_JSON_KEY')
        out[key] = value
    return out


def read(path):
    return json.loads(path.read_text(), object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def number(value):
    require(not isinstance(value, bool), 'INVALID_NUMBER')
    if isinstance(value, dict):
        require(set(value) == {'numerator', 'denominator'}, 'INVALID_RATIONAL')
        require(all(type(v) is int for v in value.values()), 'INVALID_RATIONAL')
        return Fraction(value['numerator'], value['denominator'])
    require(isinstance(value, (int, float)) and math.isfinite(value), 'INVALID_NUMBER')
    return Fraction(str(value))


def schema(obj, name, fields):
    require(isinstance(obj, dict) and obj.get('OTIO_SCHEMA') == name, 'UNSUPPORTED_SCHEMA')
    require(set(obj) <= set(fields.split()) | {'OTIO_SCHEMA'}, 'UNSUPPORTED_FIELD')


def metadata(obj, allowed):
    """Allow exporter identity/clock metadata, never silently drop processing."""
    value = obj.get('metadata', {})
    require(isinstance(value, dict) and set(value) <= {'recap'}, 'UNSUPPORTED_METADATA')
    recap = value.get('recap', {})
    require(isinstance(recap, dict) and set(recap) <= set(allowed.split()), 'UNSUPPORTED_RECAP_METADATA')
    return recap


def seconds(rt):
    schema(rt, 'RationalTime.1', 'value rate')
    rate = number(rt['rate'])
    require(rate > 0, 'INVALID_RATE')
    return number(rt['value']) / rate


def frames(value, fps):
    result = value * fps
    require(result.denominator == 1, 'HOST_SUBFRAME_UNSUPPORTED')
    return int(result)


def safe_member(root, name):
    require(isinstance(name, str) and name and '\\' not in name, 'UNSAFE_PATH')
    rel = Path(name)
    require(not rel.is_absolute() and all(p not in ('.', '..') for p in name.split('/')), 'UNSAFE_PATH')
    require(':' not in name and (root / rel).resolve().is_relative_to(root), 'UNSAFE_PATH')
    return root / rel


def package(root):
    root = Path(root)
    require(not root.is_symlink(), 'SYMLINK_REJECTED')
    root = root.resolve(strict=True)
    require(not any(p.is_symlink() for p in root.rglob('*')), 'SYMLINK_REJECTED')
    manifest = read(root / 'checksums.json')
    require(manifest.get('schema') == 'film-otio-export/1' and manifest.get('completion_state') == 'COMPLETE', 'INCOMPLETE_PACKAGE')
    members = manifest['files']
    require({p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()} == set(members) | {'checksums.json'}, 'MEMBER_SET_CHANGED')
    for name, row in members.items():
        p = safe_member(root, name)
        require(p.stat().st_size == row['bytes'] and digest(p) == row['sha256'], 'MEMBER_CHANGED')
    return root, manifest


def probe(path):
    result = subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(path)],
                            capture_output=True, text=True, check=True, timeout=60)
    return json.loads(result.stdout)['streams']


def validate(root, media_probe=probe):
    """Trusted exporter-verified package preflight, not a new full-frame CFR proof."""
    root, manifest = package(root)
    require(not (root / 'captions.srt').read_text().strip(), 'CAPTIONS_UNSUPPORTED')
    require(read(root / 'caption-map.json').get('captions') == [], 'CAPTIONS_UNSUPPORTED')
    t = read(root / 'timeline.otio')
    schema(t, 'Timeline.1', 'name metadata global_start_time tracks')
    require(seconds(t['global_start_time']) == 0, 'GLOBAL_START_UNSUPPORTED')
    metadata(t, 'export_id producer profile authority identity_warning')
    profile = t['metadata']['recap']['profile']
    require(set(profile) == {'fps', 'width', 'height'}, 'UNSUPPORTED_PROFILE')
    fps = number(profile['fps'])
    require(fps.denominator == 1 and 1 <= fps <= 120, 'HOST_FPS_UNSUPPORTED')
    require(all(type(profile[k]) is int and 1 <= profile[k] <= 8192 for k in ('width', 'height')), 'INVALID_GEOMETRY')
    stack = t['tracks']
    schema(stack, 'Stack.1', 'name metadata children source_range effects markers enabled')
    require(not stack.get('effects') and not stack.get('markers') and stack.get('source_range') is None, 'STACK_EFFECT_UNSUPPORTED')
    require(stack.get('enabled', True) is True, 'DISABLED_STACK')
    metadata(stack, '')
    resources = read(root / 'media-manifest.json')['resources']
    cached = {}
    plan, names = [], set()
    require(1 <= len(stack['children']) <= 16, 'TRACK_LIMIT')
    for channel, track in enumerate(stack['children'], 1):
        schema(track, 'Track.1', 'name metadata children kind effects markers source_range enabled')
        metadata(track, 'track_id role')
        require(track['kind'] in ('Video', 'Audio'), 'TRACK_KIND')
        require(track.get('enabled') is True and not track.get('effects') and not track.get('markers') and track.get('source_range') is None, 'TRACK_EFFECT_UNSUPPORTED')
        cursor = Fraction(0)
        for clip in track['children']:
            kind = clip.get('OTIO_SCHEMA')
            require(kind in ('Clip.1', 'Gap.1'), 'CLIP_SCHEMA')
            schema(clip, kind, 'name metadata source_range effects markers enabled' + (' media_reference' if kind == 'Clip.1' else ''))
            require(clip.get('enabled') is True and not clip.get('effects') and not clip.get('markers'), 'CLIP_EFFECT_UNSUPPORTED')
            r = clip['source_range']; schema(r, 'TimeRange.1', 'start_time duration')
            start, duration = seconds(r['start_time']), seconds(r['duration'])
            require(start >= 0 and duration > 0, 'INVALID_WINDOW')
            target, offset, length = frames(cursor, fps) + 1, frames(start, fps), frames(duration, fps)
            if kind == 'Gap.1':
                metadata(clip, '')
                require(start == 0, 'GAP_OFFSET'); cursor += duration; continue
            metadata(clip, 'export_id instance_id segment_id visual_index resource_id source_start duration target_start lineage speed linked_video_instance resource_sha256')
            require(isinstance(clip['name'], str) and clip['name'] and clip['name'] not in names, 'DUPLICATE_CLIP_ID')
            names.add(clip['name'])
            ref = clip['media_reference']
            schema(ref, 'ExternalReference.1', 'name metadata target_url available_range available_image_bounds')
            require(ref.get('available_range') is None and ref.get('available_image_bounds') is None, 'REF_RANGE_UNSUPPORTED')
            url = ref['target_url']; path = safe_member(root, url)
            require(url in manifest['files'], 'MEDIA_NOT_BOUND')
            meta = metadata(ref, 'resource_id sha256'); resource = resources[meta['resource_id']]
            require(resource['package_path'] == url and resource['sha256'] == meta['sha256'] == manifest['files'][url]['sha256'], 'MEDIA_IDENTITY')
            facts = resource['facts']
            require(facts['start_time'] == 0 and facts['cfr'] is True and number(facts['fps']) == fps, 'MEDIA_CLOCK_UNSUPPORTED')
            require(facts['width'] == profile['width'] and facts['height'] == profile['height'], 'MEDIA_GEOMETRY')
            require(offset + length <= facts['frame_count'], 'SOURCE_OVERRUN')
            if url not in cached: cached[url] = media_probe(path)
            streams = cached[url]
            videos = [s for s in streams if s['codec_type'] == 'video']
            audios = [s for s in streams if s['codec_type'] == 'audio']
            require(len(videos) == 1 and len(audios) <= 1, 'STREAM_SELECTION_UNSUPPORTED')
            video = videos[0]
            require(Fraction(video['avg_frame_rate']) == fps and Fraction(video['r_frame_rate']) == fps and Fraction(video.get('start_time', '0')) == 0, 'PROBED_VIDEO_CLOCK')
            require((video['width'], video['height']) == (profile['width'], profile['height']), 'PROBED_GEOMETRY')
            if track['kind'] == 'Audio':
                require(len(audios) == 1 and Fraction(audios[0].get('start_time', '0')) == 0, 'PROBED_AUDIO_CLOCK')
                require((start + duration) * facts['sample_rate'] <= facts['duration_samples'], 'AUDIO_OVERRUN')
            recap = clip['metadata']['recap']
            require(number(recap['speed']) == 1 and number(recap['source_start']) == start and number(recap['duration']) == duration and number(recap['target_start']) == cursor, 'METADATA_WINDOW_MISMATCH')
            plan.append(dict(name=clip['name'], kind=track['kind'], path=str(path), channel=channel, target=target, offset=offset, length=length))
            cursor += duration
    require(plan and any(r['kind'] == 'Video' for r in plan) and len(plan) <= 10000, 'CLIP_LIMIT')
    return {'profile': profile, 'fps': int(fps), 'clips': plan, 'package_sha256': digest(root / 'checksums.json')}


def import_to_host(root, output, bpy):
    require(tuple(bpy.app.version) == SUPPORTED_VERSION, 'HOST_VERSION_UNSUPPORTED')
    output = Path(output).absolute()
    require(output.suffix == '.blend' and output.parent.is_dir() and not output.exists() and not output.is_symlink(), 'OUTPUT_UNSAFE_OR_EXISTS')
    plan = validate(root)  # all validation and media probing before first host mutation
    previous = bpy.context.window.scene
    scene = bpy.data.scenes.new('Reel limited cuts')
    try:
        bpy.context.window.scene = scene
        scene.render.fps = plan['fps']; scene.render.fps_base = 1
        scene.render.resolution_x = plan['profile']['width']; scene.render.resolution_y = plan['profile']['height']; scene.render.resolution_percentage = 100
        scene.view_settings.view_transform = 'Standard'; scene.sequencer_colorspace_settings.name = 'sRGB'
        seq = scene.sequence_editor_create()
        for row in plan['clips']:
            factory = seq.sequences.new_movie if row['kind'] == 'Video' else seq.sequences.new_sound
            strip = factory(row['name'], row['path'], row['channel'], row['target'] - row['offset'])
            strip.frame_final_start = row['target']; strip.frame_final_end = row['target'] + row['length']
            require(strip.frame_final_duration == row['length'] and strip.frame_final_start - strip.frame_start == row['offset'], 'HOST_WINDOW_MISMATCH')
            strip['reel_instance_id'] = row['name']
        scene.frame_start = 1; scene.frame_end = max(r['target'] + r['length'] - 1 for r in plan['clips'])
        scene['reel_package_sha256'] = plan['package_sha256']; scene['reel_adapter'] = 'experimental-blender-cut/1'
        scene['reel_limits'] = 'No captions, effects, fractional fps, reverse readback or GUI acceptance'
        require(not output.exists(), 'OUTPUT_EXISTS')
        bpy.ops.wm.save_as_mainfile(filepath=str(output), check_existing=True)
    except Exception:
        bpy.context.window.scene = previous
        bpy.data.scenes.remove(scene)
        raise
    return plan


if __name__ == '__main__':
    import bpy
    args = sys.argv[sys.argv.index('--') + 1:]
    require(len(args) == 2, 'EXPECTED_PACKAGE_AND_OUTPUT')
    import_to_host(args[0], args[1], bpy)
