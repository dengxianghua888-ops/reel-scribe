#!/usr/bin/env python3
"""Explicit media operations, immutable receipts and version-bound local edits.

No editorial ranking, inferred cuts, narration writing or style selection lives here.
Python standard library core; still-image rendering additionally uses Pillow.
Media operations need explicitly resolved FFmpeg/ffprobe.
"""
import argparse
import array
import copy
import hashlib
import json
import math
import os
import re
from pathlib import Path
import shutil
import subprocess
import signal
import sqlite3
import time
import importlib.util
import sys
import wave
from fractions import Fraction

VERSION = '0.17.0-dev'

# A local batch lock must outlive its controller if a render child is still alive.
# Context-local inheritance leaves ordinary operations unchanged.
from contextvars import ContextVar
SUBPROCESS_LOCK_FDS = ContextVar('editing_subprocess_lock_fds', default=())
RUN_CANCELLATION = ContextVar('editing_run_cancellation', default=None)
RUN_PROGRESS = ContextVar('editing_run_progress', default=None)
RUN_DIRECTORY = ContextVar('editing_run_directory', default=None)
TOOL_DIAGNOSTIC_SEQUENCE = ContextVar('editing_tool_diagnostic_sequence', default=0)


class ContractError(ValueError):
    pass


class OperationCancelled(ContractError):
    pass


def require(condition, message):
    if not condition:
        raise ContractError(message)


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def number(value, name, minimum=None):
    require(not isinstance(value, bool) and isinstance(value, (int, float)), 'NUMERIC_REQUIRED: ' + name)
    require(math.isfinite(value), 'NONFINITE: ' + name)
    require(minimum is None or value >= minimum, 'OUT_OF_RANGE: ' + name)
    return float(value)


def exact_keys(obj, allowed, required=()):
    require(isinstance(obj, dict), 'OBJECT_REQUIRED')
    require(not (set(obj) - set(allowed)), 'UNKNOWN_FIELDS: ' + ','.join(sorted(set(obj) - set(allowed))))
    require(set(required) <= set(obj), 'MISSING_FIELDS: ' + ','.join(sorted(set(required) - set(obj))))


def write_json(path, value):
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(payload)


def source(ref, hash_required=True):
    exact_keys(ref, ['path', 'sha256'], ['path', 'sha256'] if hash_required else ['path'])
    if hash_required or 'sha256' in ref:
        require(isinstance(ref.get('sha256'), str) and bool(re.fullmatch('[0-9a-f]{64}', ref['sha256'])), 'SHA256_REQUIRED')
    p = Path(ref['path']).expanduser()
    require(p.is_absolute(), 'ABSOLUTE_SOURCE_PATH_REQUIRED')
    p = p.resolve()
    require(p.is_file(), 'SOURCE_NOT_FOUND: ' + str(p))
    digest = sha256(p)
    require(not ref.get('sha256') or ref['sha256'] == digest, 'SOURCE_HASH_MISMATCH: ' + str(p))
    return {'path': str(p), 'sha256': digest, 'bytes': p.stat().st_size}


def owned_process(command, timeout=300, cwd=None):
    """Stop only this invocation's process group on catchable cancellation."""
    proc = subprocess.Popen(command, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, cwd=cwd,
                            pass_fds=SUBPROCESS_LOCK_FDS.get(), start_new_session=True)
    reason = None
    deadline = time.monotonic() + timeout
    try:
        while True:
            cancellation = RUN_CANCELLATION.get()
            if cancellation is not None and cancellation.is_set():
                reason = 'cancelled'
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                reason = 'timeout'
                break
            try:
                stdout, stderr = proc.communicate(timeout=min(0.1, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    except KeyboardInterrupt:
        reason = 'cancelled'
    if reason is not None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = proc.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = proc.communicate()
    result = subprocess.CompletedProcess(command, proc.returncode, stdout, stderr)
    result.pid = proc.pid
    result.termination_reason = reason
    return result


def exec_tool(command, timeout=300, cwd=None):
    from source_binding import ACTIVE_BINDING
    binding = ACTIVE_BINDING.get()
    touched = []
    if binding is not None:
        command, touched = binding.command(command)
        binding.observe('before-tool-consumption', touched)
    try:
        result = owned_process(command, timeout=timeout, cwd=cwd)
    finally:
        if binding is not None:
            binding.observe('after-tool-consumption', touched)
    directory = RUN_DIRECTORY.get()
    if directory is not None and (result.termination_reason is not None or result.returncode != 0):
        sequence = TOOL_DIAGNOSTIC_SEQUENCE.get() + 1
        TOOL_DIAGNOSTIC_SEQUENCE.set(sequence)
        write_json(directory / f'tool-termination-{sequence}.json',
                   {'argv': command, 'pid': result.pid, 'exit_code': result.returncode,
                    'termination_reason': result.termination_reason,
                    'stdout': result.stdout, 'stderr': result.stderr})
    if result.termination_reason == 'cancelled':
        raise OperationCancelled('TOOL_CANCELLED: partial outputs retained')
    require(result.termination_reason != 'timeout', 'TOOL_TIMEOUT: partial outputs retained')
    require(result.returncode == 0, 'TOOL_FAILED: ' + result.stderr[-4000:])
    return result


class Tools:
    def __init__(self, ffmpeg=None, ffprobe=None):
        self.ffmpeg = ffmpeg or os.environ.get('EDITING_FFMPEG') or shutil.which('ffmpeg')
        self.ffprobe = ffprobe or os.environ.get('EDITING_FFPROBE') or shutil.which('ffprobe')
        self._identity_lock = {}
        self._tool_blocked = {}

    def binary(self, name):
        path = getattr(self, name)
        require(path and Path(path).is_file(), 'DEPENDENCY_UNAVAILABLE: ' + name)
        require(name not in self._tool_blocked, 'TOOL_IDENTITY_UNAVAILABLE: ' + name + ': ' + self._tool_blocked.get(name, ''))
        resolved = str(Path(path).resolve())
        from tool_identity import inspect_tool
        identity = inspect_tool(resolved, run_version=False)
        require(identity['status'] == 'RESOLVED_EXECUTABLE_CHAIN',
                'TOOL_IDENTITY_UNRESOLVED: ' + name + ': ' + identity.get('error', 'unknown'))
        locked = self._identity_lock.get(name)
        require(locked is None or locked == identity['identity_sha256'], 'TOOL_IDENTITY_CHANGED: ' + name)
        if locked is None:
            self._identity_lock[name] = identity['identity_sha256']
        return resolved

    def doctor(self):
        result = {}
        for name in ['ffmpeg', 'ffprobe']:
            try:
                configured = getattr(self, name)
                require(configured and Path(configured).is_file(), 'DEPENDENCY_UNAVAILABLE: ' + name)
                path = str(Path(configured).resolve())
                from tool_identity import inspect_tool
                identity = inspect_tool(path)
                result[name] = {'path': path, 'version': identity['version'],
                                'sha256': sha256(path), 'identity': identity}
                if identity['status'] != 'RESOLVED_EXECUTABLE_CHAIN':
                    result[name]['error'] = identity.get('error', 'TOOL_IDENTITY_UNRESOLVED')
                elif identity['version_probe'] != 'SUCCEEDED':
                    result[name]['error'] = 'TOOL_VERSION_UNAVAILABLE'
                elif name in self._identity_lock and self._identity_lock[name] != identity['identity_sha256']:
                    result[name]['error'] = 'TOOL_IDENTITY_CHANGED'
                else:
                    self._identity_lock[name] = identity['identity_sha256']
                    self._tool_blocked.pop(name, None)
                if 'error' in result[name]:
                    self._tool_blocked[name] = result[name]['error']
            except (ContractError, OSError) as exc:
                result[name] = {'error': str(exc)}
                self._tool_blocked[name] = str(exc)
        return result

    def probe(self, path):
        binary = self.binary('ffprobe')
        result = exec_tool([binary, '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)])
        self.binary('ffprobe')
        data = json.loads(result.stdout)
        duration = float(data.get('format', {}).get('duration', 0))
        require(math.isfinite(duration) and duration > 0, 'MEDIA_DURATION_UNAVAILABLE')
        return {'duration': duration, 'streams': data.get('streams', []), 'format': data.get('format', {})}

    def selected_video_clock(self, path, media, requested_start, requested_end):
        """Observe the frames rendered by v:0, rather than using format.duration.

        This deliberately fails closed on missing frame durations or excessive
        observations. A seek near the request avoids scanning earlier hours.
        """
        videos = [s for s in media['streams'] if s.get('codec_type') == 'video']
        require(videos, 'VIDEO_STREAM_REQUIRED')
        index = videos[0]['index']  # FFmpeg [i:v:0] and ffprobe v:0.
        time_base = Fraction(videos[0]['time_base'])
        try:
            nominal_frame_duration = 1 / Fraction(videos[0]['avg_frame_rate'])
        except (KeyError, ValueError, ZeroDivisionError):
            nominal_frame_duration = None
        binary = self.binary('ffprobe')
        seek_start = max(0, float(requested_start) - 5)
        seek_end = float(requested_end) + 2
        result = exec_tool([binary, '-v', 'error', '-select_streams', 'v:0',
            '-read_intervals', str(seek_start) + '%' + str(seek_end), '-show_frames', '-show_entries',
            'frame=media_type,stream_index,best_effort_timestamp,pkt_duration,duration',
            '-of', 'json', str(path)], timeout=60)
        self.binary('ffprobe')
        frames = json.loads(result.stdout).get('frames', [])
        require(frames and len(frames) <= 50000, 'SOURCE_VIDEO_OBSERVATION_UNAVAILABLE')
        intervals = []
        playback_intervals = []
        previous_start = None
        max_frame_duration = Fraction(0)
        segment_anchor = None
        segment_grid_valid = True
        for frame in frames:
            require(frame.get('media_type') == 'video' and frame.get('stream_index') == index,
                    'SOURCE_VIDEO_SELECTOR_MISMATCH')
            stamp = frame.get('best_effort_timestamp')
            # FFmpeg 7 names decoded AVFrame duration `duration`; older
            # versions expose `pkt_duration`. Never infer missing evidence.
            duration = frame.get('duration', frame.get('pkt_duration'))
            if 'duration' in frame and 'pkt_duration' in frame:
                require(type(frame['pkt_duration']) is int and frame['pkt_duration'] == duration,
                        'SOURCE_VIDEO_FRAME_DURATION_CONFLICT')
            require(type(stamp) is int and type(duration) is int,
                    'SOURCE_VIDEO_FRAME_DURATION_UNVERIFIED')
            start, length = stamp*time_base, duration*time_base
            require(length > 0, 'SOURCE_VIDEO_FRAME_DURATION_UNVERIFIED')
            max_frame_duration = max(max_frame_duration, length)
            require(previous_start is None or start > previous_start, 'SOURCE_TIME_DISCONTINUOUS')
            previous_start = start
            end = start + length
            if intervals and start <= intervals[-1][1]:
                intervals[-1][1] = max(intervals[-1][1], end)
            else:
                intervals.append([start, end])
            # A held frame can span multiple nominal steps. Bridge rounding only
            # when every start and presentation length in this local prefix is
            # consistent with that grid, never merely the current endpoint.
            length_steps = round(length / nominal_frame_duration) if nominal_frame_duration is not None else 0
            length_on_grid = (nominal_frame_duration is not None and length_steps >= 1 and
                abs(length - length_steps * nominal_frame_duration) <= time_base)
            start_on_grid = (segment_anchor is not None and nominal_frame_duration is not None and
                abs(start - (segment_anchor + round((start-segment_anchor)/nominal_frame_duration)*nominal_frame_duration)) <= time_base)
            quantized_neighbor = (playback_intervals and segment_grid_valid and start_on_grid and length_on_grid and
                0 < start - playback_intervals[-1][1] <= time_base and
                start - playback_intervals[-1][1] < nominal_frame_duration / 2)
            if playback_intervals and (start <= playback_intervals[-1][1] or quantized_neighbor):
                require(start >= playback_intervals[-1][0], 'SOURCE_TIME_DISCONTINUOUS')
                playback_intervals[-1][1] = max(playback_intervals[-1][1], end)
                segment_grid_valid = segment_grid_valid and start_on_grid and length_on_grid
            else:
                playback_intervals.append([start, end])
                segment_anchor = start
                segment_grid_valid = length_on_grid
        return {'clock_policy_version': 'selected-video-frames/1',
                'stream_index': index, 'stream_selector': 'v:0',
                'time_base': str(time_base), 'observation_window': [str(seek_start), str(seek_end)],
                'quantization_continuity': 'playback only: at most one tick and less than half a nominal frame when integer PTS matches local CFR grid; explicit frame-duration gaps remain absent from source evidence',
                'observed_intervals': [[str(a), str(b)] for a, b in intervals],
                'playback_intervals': [[str(a), str(b)] for a, b in playback_intervals],
                'max_observed_frame_duration': str(max_frame_duration),
                'observation': 'selected decoded video frames and per-frame presentation duration',
                'not_semantic_evidence': True}

    def selected_audio_clock(self, path, media, requested_start, requested_end, *, allow_empty=False, playback=False):
        """Observe a:0; optionally add ordinary-only complete-block playback ranges."""
        from vorbis_group_clock import supported, read_block_headers, playback_clock
        streams = [s for s in media['streams'] if s.get('codec_type') == 'audio']
        require(streams, 'NO_AUDIO')
        selected = streams[0]
        index = selected['index']
        rate = selected.get('sample_rate')
        require(rate and int(rate) > 0, 'SOURCE_AUDIO_SAMPLE_RATE_UNVERIFIED')
        time_base = Fraction(selected['time_base'])
        binary = self.binary('ffprobe')
        seek_start = max(0, float(requested_start) - 5)
        seek_end = float(requested_end) + 2
        group_playback = playback and supported(media.get('format', {}).get('format_name'),
                                                selected.get('codec_name'), time_base)
        fields = 'frame=media_type,stream_index,best_effort_timestamp,nb_samples'
        modes = ['-show_frames']
        if group_playback:
            modes += ['-show_packets']
            fields += ',pkt_pos,pkt_size,pkt_dts,pkt_duration,sample_rate:' + \
                      'packet=codec_type,stream_index,pts,dts,duration,size,pos'
        result = exec_tool([binary, '-v', 'error', '-select_streams', 'a:0',
            '-read_intervals', str(seek_start) + '%' + str(seek_end)] + modes +
            ['-show_entries', fields, '-of', 'json', str(path)], timeout=60)
        self.binary('ffprobe')
        observation = json.loads(result.stdout)
        if group_playback:
            require(isinstance(observation, dict) and isinstance(observation.get('packets_and_frames'), list),
                    'SOURCE_AUDIO_OBSERVATION_UNAVAILABLE')
            rows = observation['packets_and_frames']
            require(len(rows) <= 100000 and all(isinstance(x, dict) and x.get('type') in ('packet', 'frame') for x in rows),
                    'SOURCE_AUDIO_OBSERVATION_UNAVAILABLE')
            frames = [x for x in rows if x['type'] == 'frame']
        else:
            require(isinstance(observation, dict) and isinstance(observation.get('frames'), list),
                    'SOURCE_AUDIO_OBSERVATION_UNAVAILABLE')
            frames = observation['frames']
        require(len(frames) <= 50000 and (frames or allow_empty), 'SOURCE_AUDIO_OBSERVATION_UNAVAILABLE')
        intervals = []
        previous_start = None
        segment_anchor = None
        segment_samples = 0
        for frame in frames:
            require(frame.get('media_type') == 'audio' and frame.get('stream_index') == index,
                    'SOURCE_AUDIO_SELECTOR_MISMATCH')
            stamp, samples = frame.get('best_effort_timestamp'), frame.get('nb_samples')
            require(type(stamp) is int and type(samples) is int and samples > 0,
                    'SOURCE_AUDIO_FRAME_CLOCK_UNVERIFIED')
            start = stamp*time_base
            require(start >= 0 and (previous_start is None or start > previous_start),
                    'SOURCE_TIME_ORIGIN_UNVERIFIED')
            previous_start = start
            end = start + Fraction(samples, int(rate))
            quantized_neighbor = (intervals and 0 < start - intervals[-1][1] <= time_base and
                stamp == round((segment_anchor + Fraction(segment_samples, int(rate)))/time_base))
            if intervals and (start <= intervals[-1][1] or quantized_neighbor):
                intervals[-1][1] = max(intervals[-1][1], end)
                segment_samples += samples
            else:
                intervals.append([start, end])
                segment_anchor = start
                segment_samples = samples
        precision = 'SAMPLE_RESOLVING' if time_base <= Fraction(1, int(rate)) else 'COARSE_UNPROVEN'
        clock = {'clock_policy_version': 'selected-audio-samples/1',
                'stream_index': index, 'stream_selector': 'a:0', 'sample_rate': int(rate),
                'time_base': str(time_base), 'source_time_precision': precision,
                'observation_window': [str(seek_start), str(seek_end)],
                'quantization_continuity': 'one tick only when integer PTS matches accumulated decoded sample count',
                'observed_intervals': [[str(a), str(b)] for a, b in intervals],
                'observation': 'selected decoded audio frame PTS and sample count; packet priming alone does not extend coverage'}
        clock['playback_intervals'] = [list(x) for x in clock['observed_intervals']]
        clock['playback_barriers'] = []
        clock['playback_basis'] = {'status': 'OBSERVED_ONLY', 'ordinary_only': True,
                                   'reason': 'group playback not requested or unsupported container/codec/time base'}
        if group_playback:
            positions = [x.get('pos') for x in observation['packets_and_frames'] if x['type'] == 'packet']
            blocks, header_errors = read_block_headers(path, positions)
            clock.update(playback_clock(clock['observed_intervals'], observation, blocks,
                stream_index=index, sample_rate=int(rate), time_base=time_base,
                codec_name=selected.get('codec_name'), format_name=media.get('format', {}).get('format_name')))
            clock['playback_basis']['header_read_errors'] = header_errors
        return clock

    def ff(self, args, cwd=None, timeout=300):
        binary = self.binary('ffmpeg')
        result = exec_tool([binary, '-nostdin', '-hide_banner', '-v', 'error', '-n'] + args, cwd=cwd, timeout=timeout)
        self.binary('ffmpeg')
        return result


def span(start, end, duration):
    a, b = number(start, 'start', 0), number(end, 'end', 0)
    require(a < b <= duration + 0.000001, 'SOURCE_RANGE_INVALID')
    return a, b


def require_video_coverage(clock, start, end, *, playback=False):
    a, b = Fraction(str(start)), Fraction(str(end))
    key = 'playback_intervals' if playback else 'observed_intervals'
    require(any(Fraction(str(x)) <= a and b <= Fraction(str(y))
                for x, y in clock[key]), 'SOURCE_VIDEO_RANGE_UNVERIFIED')


def audio_intersection(clock, start, end, *, require_full=False, require_precise=False, playback=False):
    a, b = Fraction(str(start)), Fraction(str(end))
    require(not (playback and require_precise), 'PRECISE_PLAYBACK_CLOCK_FORBIDDEN')
    if require_precise:
        require(clock['source_time_precision'] == 'SAMPLE_RESOLVING',
                'SOURCE_AUDIO_CLOCK_PRECISION_UNVERIFIED')
    if playback:
        for barrier in clock.get('playback_barriers', []):
            left, right = map(Fraction, barrier['interval'])
            require(not (a < right and b > left if left < right else a < left < b),
                    'SOURCE_AUDIO_DISCONTINUOUS')
    ranges = clock.get('playback_intervals', clock['observed_intervals']) if playback else clock['observed_intervals']
    hits = [(Fraction(x), Fraction(y)) for x, y in ranges
            if Fraction(x) < b and Fraction(y) > a]
    require(len(hits) <= 1, 'SOURCE_AUDIO_DISCONTINUOUS')
    if require_full:
        # FFprobe may round a sample-exact container duration to six decimals.
        # Only the right endpoint gets this sub-sample allowance; gaps stay gaps.
        endpoint_rounding = (Fraction(0) if require_precise else
                             min(Fraction(1, 2000000), Fraction(1, 2*clock['sample_rate'])))
        require(bool(hits) and hits[0][0] <= a and b <= hits[0][1] + endpoint_rounding,
                'SOURCE_AUDIO_RANGE_UNVERIFIED')
    return bool(hits)


def normalize_plan(plan, tools):
    exact_keys(plan, ['schema', 'fps', 'width', 'height', 'fit', 'sources', 'clips', 'allow_source_reuse'],
               ['schema', 'fps', 'width', 'height', 'fit', 'sources', 'clips'])
    require(plan['schema'] == 'execution-plan/1', 'SCHEMA_UNSUPPORTED')
    try:
        fps = Fraction(str(plan['fps']))
    except (ValueError, ZeroDivisionError) as exc:
        raise ContractError('FPS_INVALID') from exc
    require(1 <= fps <= 120, 'FPS_OUT_OF_RANGE')
    for k in ['width', 'height']:
        require(type(plan[k]) is int and 2 <= plan[k] <= 8192 and plan[k] % 2 == 0, 'EVEN_DIMENSION_REQUIRED: ' + k)
    require(plan['fit'] in ['contain', 'cover'], 'FIT_REQUIRED: contain or cover')
    require(isinstance(plan['sources'], dict) and plan['sources'], 'SOURCES_REQUIRED')
    require(isinstance(plan['clips'], list) and plan['clips'], 'CLIPS_REQUIRED')
    require(type(plan.get('allow_source_reuse', False)) is bool, 'REUSE_BOOLEAN_REQUIRED')
    sources = {}
    for sid, ref in plan['sources'].items():
        require(isinstance(sid, str) and sid, 'SOURCE_ID_REQUIRED')
        s = source(ref)
        s['media'] = tools.probe(s['path'])
        require(any(x['codec_type'] == 'video' for x in s['media']['streams']), 'VIDEO_STREAM_REQUIRED: ' + sid)
        sources[sid] = s
    clips, seen, ranges, cursor = [], set(), {}, 0
    for item in plan['clips']:
        exact_keys(item, ['id', 'source_id', 'start', 'end', 'gain_db', 'mute', 'speed'], ['id', 'source_id', 'start', 'end', 'gain_db'])
        require(type(item.get('mute',False)) is bool,'MUTE_BOOLEAN_REQUIRED')
        raw_speed=item.get('speed','1')
        require(not isinstance(raw_speed,bool) and isinstance(raw_speed,(int,float,str)),'SPEED_RATIONAL_REQUIRED')
        try:
            speed=Fraction(str(raw_speed))
        except (ValueError,ZeroDivisionError,OverflowError) as exc:
            raise ContractError('SPEED_RATIONAL_REQUIRED') from exc
        # One atempo stage preserves pitch in this bounded interval. Wider or
        # time-varying speed needs a separately specified audio policy.
        require(Fraction(1,2)<=speed<=2,'SPEED_OUT_OF_RANGE')
        cid = item['id']
        require(isinstance(cid, str) and cid and cid not in seen, 'CLIP_ID_DUPLICATE_OR_EMPTY')
        seen.add(cid)
        sid = item['source_id']
        require(sid in sources, 'UNKNOWN_SOURCE: ' + str(sid))
        a, b = span(item['start'], item['end'], sources[sid]['media']['duration'])
        clock = windowed_mix_clock(tools, sources[sid]['path'], sources[sid]['media'], b, kind='video', start=a)
        require_video_coverage(clock, a, b, playback=True)
        gain = number(item['gain_db'], 'gain_db')
        audio_clock = None
        if not item.get('mute', False) and gain > -120 and any(
                s['codec_type'] == 'audio' for s in sources[sid]['media']['streams']):
            audio_clock = windowed_mix_clock(tools, sources[sid]['path'], sources[sid]['media'], b,
                                             kind='audio', start=a, allow_no_audio=True, playback=True)
            audio_intersection(audio_clock, a, b, playback=True)
        require(-120 <= gain <= 24, 'GAIN_OUT_OF_RANGE')
        # Source IDs and paths are aliases, not permission to reuse identical media.
        identity = sources[sid]['sha256']
        if not plan.get('allow_source_reuse', False):
            require(not any(a < y and b > x for x, y in ranges.get(identity, [])), 'SOURCE_REUSE_NOT_AUTHORIZED')
        ranges.setdefault(identity, []).append((a, b))
        frames = round((Fraction(str(b)) - Fraction(str(a))) * fps / speed)
        require(frames > 0, 'SUBFRAME_CLIP')
        length = float(frames / fps)
        effective_end=min(b,float(Fraction(str(a))+frames/fps*speed))
        mapped_output_end=min(float((cursor+frames)/fps),float(cursor/fps)+(effective_end-a)/float(speed))
        clips.append({**item, 'selected_video_clock':clock,
                      **({'selected_audio_clock':audio_clock} if audio_clock is not None else {}),
                      'speed':str(speed), 'frames': frames, 'output_start_frame': cursor,
                      'output_end_frame': cursor + frames, 'output_start': float(cursor / fps),
                      'output_end': float((cursor + frames) / fps),
                      'effective_source_end':effective_end,
                      'source_to_output_map':{'source_start':a,'source_end':effective_end,
                                              'output_start':float(cursor/fps),'output_end':mapped_output_end,
                                              'source_seconds_per_output_second':str(speed)},
                      'quantization_delta_seconds': length - (b - a)/float(speed)})
        cursor += frames
    return {'schema': 'normalized-plan/1', 'request_plan_sha256': fingerprint(plan),
            'fps': str(fps), 'width': plan['width'], 'height': plan['height'], 'fit': plan['fit'],
            'sources': sources, 'clips': clips, 'total_frames': cursor,
            'duration': float(cursor / fps)}


RUBBERBAND_STREAM_SHA256 = '0e5a32ef52c02ad1372b3d91c9ce63cf7c359428c527c6b41c35017864ca8e96'

RUBBERBAND_V4_SHA256 = '44108917c2d7590f55e4cbed00528deb8da33339e3332edc48bdff5331079884'


def exec_rubberband(command, receipt_path, timeout=300):
    """Keep stdout and the terminal reason even on nonzero exit or cancellation."""
    proc = owned_process(command, timeout=timeout)
    write_json(receipt_path, {'argv': command, 'pid': proc.pid,
               'exit_code': proc.returncode, 'termination_reason': proc.termination_reason,
               'stdout': proc.stdout, 'stderr': proc.stderr})
    if proc.termination_reason == 'cancelled':
        raise OperationCancelled('RUBBERBAND_TOOL_CANCELLED: diagnostic saved at ' + str(receipt_path))
    require(proc.termination_reason != 'timeout',
            'RUBBERBAND_TOOL_TIMEOUT: diagnostic saved at ' + str(receipt_path))
    require(proc.returncode == 0, 'RUBBERBAND_TOOL_FAILED: diagnostic saved at ' + str(receipt_path))
    return proc


def selected_audio_backend(spec, directory, need_dsp=True):
    if spec is None:
        if not need_dsp:
            return {'kind': 'ffmpeg-atempo', 'dsp_required': False, 'policy': 'no retimed audible source; identity path, no helper'}
        spec = {'kind': 'rubberband-r3-stream-v5', 'helper': {'path': str(Path(__file__).parent / 'rubberband-offline-f32-stream-v5'), 'sha256': RUBBERBAND_STREAM_SHA256}}
    exact_keys(spec, ['kind', 'helper', 'stage_timeout_seconds'], ['kind'])
    budget = spec.get('stage_timeout_seconds', 300)
    require(type(budget) is int and 1 <= budget <= 7200, 'AUDIO_STAGE_TIMEOUT_INVALID')
    require(spec['kind'] in ('ffmpeg-atempo', 'rubberband-r3-v4', 'rubberband-r3-stream-v5'), 'AUDIO_BACKEND_UNSUPPORTED')
    if spec['kind'] == 'ffmpeg-atempo':
        require('helper' not in spec, 'AUDIO_BACKEND_HELPER_UNEXPECTED')
    else:
        if not need_dsp:
            return {'kind': spec['kind'], 'helper': None, 'dsp_required': False, 'stage_timeout_seconds': budget}
        require('helper' in spec, 'RUBBERBAND_HELPER_REQUIRED')
        helper = source(spec['helper'])
        require(helper['sha256'] == (RUBBERBAND_STREAM_SHA256 if spec['kind'] == 'rubberband-r3-stream-v5' else RUBBERBAND_V4_SHA256), 'RUBBERBAND_HELPER_IDENTITY_UNSUPPORTED')
        require(os.access(helper['path'], os.X_OK), 'RUBBERBAND_HELPER_NOT_EXECUTABLE')
        described = json.loads(exec_rubberband([helper['path'], '--describe'], directory / 'rubberband-describe-execution.json').stdout)
        require(sha256(helper['path']) == helper['sha256'], 'RUBBERBAND_HELPER_IDENTITY_CHANGED')
        require(described.get('library_source_release') == '4.0.0' and
                described.get('engine_requested') == 3 and described.get('dsp_executed') is False and
                described.get('input') == 'interleaved f32le',
                'RUBBERBAND_HELPER_DESCRIPTION_MISMATCH')
        require(spec['kind'] != 'rubberband-r3-stream-v5' or described.get('io_strategy') == 'two-pass-seekable-f32', 'RUBBERBAND_STREAM_DESCRIPTION_MISMATCH')
        return {'kind': spec['kind'], 'helper': helper, 'description': described, 'stage_timeout_seconds': budget}
    return {'kind': 'ffmpeg-atempo', 'stage_timeout_seconds': budget}


def analyze_target_pcm(target, frames, gain_db, report):
    """Bind the exact bytes used for peak statistics, then recheck the path."""
    require(target.stat().st_size == frames * 2 * 4, 'RUBBERBAND_TARGET_PCM_LENGTH_MISMATCH')
    digest = hashlib.sha256()
    peak, nonfinite, outside_unit, count = 0.0, 0, 0, 0
    with target.open('rb') as stream:
        while chunk := stream.read(65536 * 4):
            digest.update(chunk)
            values = array.array('f')
            values.frombytes(chunk)
            if sys.byteorder != 'little':
                values.byteswap()
            for value in values:
                count += 1
                if not math.isfinite(value):
                    nonfinite += 1
                else:
                    peak = max(peak, abs(value))
                    outside_unit += abs(value) > 1
    evidence = {'path': str(target), 'sha256': digest.hexdigest(),
                'path_sha256_after_scan': sha256(target),
                'frames': frames, 'channels': 2, 'gain_db_applied': gain_db,
                'sample_format': 'f32le', 'actual_peak': peak,
                'nonfinite_samples': nonfinite, 'outside_unit_samples': outside_unit,
                'samples': count, 'expected_samples': frames * 2, 'scope': 'actual preencode stereo matrix and declared gain; not AAC true-peak/listening QC'}
    write_json(report, evidence)
    require(count == frames * 2, 'RUBBERBAND_TARGET_PCM_LENGTH_MISMATCH')
    require(evidence['sha256'] == evidence['path_sha256_after_scan'],
            'RUBBERBAND_TARGET_PCM_IDENTITY_CHANGED')
    require(nonfinite == 0, 'RUBBERBAND_TARGET_PCM_NONFINITE')
    require(outside_unit == 0, 'RUBBERBAND_POST_GAIN_PEAK_RISK')
    return evidence


def prepare_rubberband_audio(clip, media, directory, tools, helper, index, fps, timeout=300, streaming=False):
    """Explicit rational f32 branch with separately reported natural DSP and video slot clocks."""
    speed = Fraction(clip['speed'])
    require(Fraction(1, 2) <= speed <= 2,
            'RUBBERBAND_V4_SPEED_UNSUPPORTED')
    clock = clip['selected_audio_clock']
    require(clock['source_time_precision'] == 'SAMPLE_RESOLVING' or (streaming and clock['source_time_precision'] == 'COARSE_UNPROVEN'),
            'RUBBERBAND_SOURCE_CLOCK_UNVERIFIED')
    if clock['source_time_precision'] != 'SAMPLE_RESOLVING':
        audio_intersection(clock, clip['start'], clip['effective_source_end'], playback=True)
    audio_stream = next(s for s in media['media']['streams'] if s['codec_type'] == 'audio')
    channels = audio_stream.get('channels')
    require(type(channels) is int and channels in (1, 2), 'RUBBERBAND_CHANNELS_UNSUPPORTED')
    a, requested_end = Fraction(str(clip['start'])), Fraction(str(clip['end']))
    # Keep the established nearest-video-frame policy and its reported effective
    # source endpoint; this branch grants no source-complete evidence.
    exact_end = min(requested_end, a + Fraction(clip['frames']) / Fraction(fps) * speed)
    b = exact_end
    input_frames = round((b - a) * 48000)
    require(input_frames > 0, 'RUBBERBAND_INPUT_EMPTY')
    require(input_frames < 2**51, 'RUBBERBAND_FRAME_NUMERIC_RANGE')
    require(streaming or input_frames * channels * 4 <= 256 * 1024 * 1024, 'RUBBERBAND_PCM_MEMORY_LIMIT')
    backend_time_ratio = float(1 / speed)
    natural_frames = math.floor(input_frames * backend_time_ratio + 0.5)
    require(input_frames * backend_time_ratio < 2**52, 'RUBBERBAND_TARGET_NUMERIC_RANGE')
    planned_frames = round(Fraction(clip['frames']) * 48000 / Fraction(fps))
    tail_adjustment = planned_frames - natural_frames
    # Any shortening here is only the <=2 sample difference between the two
    # rounding clocks; frame-level shortening already appears in normalized-plan.
    require(tail_adjustment >= -2 and
            tail_adjustment <= math.ceil(24000 / Fraction(fps)) + 2,
            'RUBBERBAND_QUANTIZATION_BOUND_EXCEEDED')
    output_frames = natural_frames
    required_disk = (input_frames * channels + output_frames * channels + planned_frames * 2) * 4 + 1024 * 1024
    require(shutil.disk_usage(directory).free >= required_disk, 'RUBBERBAND_STAGE_DISK_INSUFFICIENT')
    raw = directory / f'clip-{index}-source-clock.f32le'
    stretched = directory / f'clip-{index}-rubberband.f32le'
    # The observed selected-audio clock proves source coverage and absence;
    # apad fills only the missing head/tail of this fixed clip window.
    filt = (f'atrim=start={float(a)}:end={float(b)},'
            f'asetpts=PTS-{clip["start"]}/TB,aresample=48000:async=1:first_pts=0,'
            f'apad=whole_len={input_frames},atrim=end_sample={input_frames}')
    tools.ff(['-copyts', '-i', media['path'], '-map', '0:a:0', '-af', filt,
              '-ac', str(channels), '-ar', '48000', '-c:a', 'pcm_f32le',
              '-f', 'f32le', str(raw)], timeout=timeout)
    require(raw.stat().st_size == input_frames * channels * 4,
            'RUBBERBAND_SOURCE_PCM_LENGTH_MISMATCH')
    command = [helper['path'], str(raw), str(stretched), '48000', str(channels),
               repr(backend_time_ratio)]
    require(sha256(helper['path']) == helper['sha256'], 'RUBBERBAND_HELPER_IDENTITY_CHANGED')
    raw_sha256 = sha256(raw)
    proc = exec_rubberband(command, directory / f'clip-{index}-rubberband-execution.json', timeout=timeout)
    require(sha256(raw) == raw_sha256, 'RUBBERBAND_SOURCE_PCM_IDENTITY_CHANGED')
    require(sha256(helper['path']) == helper['sha256'], 'RUBBERBAND_HELPER_IDENTITY_CHANGED')
    receipt = json.loads(proc.stdout)
    require(receipt.get('engine') == 3 and receipt.get('terminal_available') == -1 and
            receipt.get('input_frames') == input_frames and
            receipt.get('actual_frames') == output_frames and
            receipt.get('expected_frames') == output_frames and
            receipt.get('time_ratio') == backend_time_ratio and
            receipt.get('channels') == channels and
            receipt.get('non_finite_samples') == 0 and
            receipt.get('helper_padding_applied') is False and
            receipt.get('helper_trimming_applied') is False,
            'RUBBERBAND_OUTPUT_RECEIPT_INVALID')
    peak = receipt.get('peak')
    require(type(peak) in (int, float) and math.isfinite(peak) and peak >= 0,
            'RUBBERBAND_OUTPUT_PEAK_INVALID')
    require(stretched.stat().st_size == output_frames * channels * 4,
            'RUBBERBAND_OUTPUT_PCM_LENGTH_MISMATCH')
    natural_sha256 = sha256(stretched)
    if streaming:
        require(receipt.get('io_strategy') == 'two-pass-seekable-f32' and receipt.get('study_frames') == receipt.get('process_frames') == input_frames and receipt.get('study_bytes') == receipt.get('process_bytes') == raw.stat().st_size and receipt.get('study_sha256') == receipt.get('process_sha256') == raw_sha256 and receipt.get('output_sha256') == natural_sha256 and receipt.get('input_device') == raw.stat().st_dev and receipt.get('input_inode') == raw.stat().st_ino and receipt.get('input_bytes') == raw.stat().st_size, 'RUBBERBAND_STREAM_CONSUMED_BYTES_INVALID')
    target = directory / f'clip-{index}-target-stereo-gain.f32le'
    target_filter = (f'apad=whole_len={planned_frames},atrim=end_sample={planned_frames},'
                     f'aformat=sample_fmts=fltp:channel_layouts=stereo,volume={clip["gain_db"]}dB')
    tools.ff(['-f', 'f32le', '-ar', '48000', '-ac', str(channels), '-i', str(stretched),
              '-af', target_filter, '-ac', '2', '-ar', '48000', '-c:a', 'pcm_f32le',
              '-f', 'f32le', str(target)], timeout=timeout)
    require(sha256(stretched) == natural_sha256, 'RUBBERBAND_OUTPUT_PCM_IDENTITY_CHANGED')
    require(target.stat().st_size == planned_frames * 2 * 4, 'RUBBERBAND_TARGET_PCM_LENGTH_MISMATCH')
    target_evidence = analyze_target_pcm(target, planned_frames, clip['gain_db'],
                                          directory / f'clip-{index}-target-pcm-analysis.json')
    evidence = {'helper': helper, 'target_pcm': target_evidence,
                'source_pcm': {'path': str(raw), 'sha256': raw_sha256,
                'frames': input_frames, 'channels': channels},
                'output_pcm': {'path': str(stretched), 'sha256': natural_sha256,
                'frames': output_frames, 'slot_frames': planned_frames}, 'backend_receipt': receipt,
                'quantization': {'ideal_duration_seconds': str((requested_end-a)/speed),
                    'effective_source_end': str(exact_end), 'source_endpoint_delta_seconds': str(exact_end-requested_end),
                    'input_sample_rounding_delta': str(Fraction(input_frames)-((b-a)*48000)),
                    'ideal_rational_output_samples': str(Fraction(input_frames, 1) / speed),
                    'backend_time_ratio_binary64': repr(backend_time_ratio),
                    'backend_target_delta_samples': str(Fraction(natural_frames)-Fraction(input_frames, 1)/speed),
                    'natural_output_samples': natural_frames, 'video_slot_samples': planned_frames,
                    'tail_adjustment_samples': tail_adjustment,
                    'tail_policy': 'reported effective-source trim; only post-selection tail silence padding or <=2 sample rounding trim'},
                'clock_policy': '48kHz source/video slot round-half-even; backend natural output std::round; bounded and reported slot tail adjustment',
                'source_audio_clock': clock, 'source_assurance': clock['source_time_precision'],
                'ordinary_coarse_playback_is_not_sample_precision': clock['source_time_precision'] != 'SAMPLE_RESOLVING',
                'stage_timeout_seconds': timeout, 'required_scratch_disk_bytes': required_disk}
    write_json(directory / f'clip-{index}-rubberband-receipt.json', evidence)
    return target, 2, evidence


def render(plan, directory, tools, audio_backend=None, source_consumption=None):
    from source_binding import consumption_session
    require(isinstance(plan, dict) and isinstance(plan.get('sources'), dict), 'SOURCES_REQUIRED')
    with consumption_session(list(plan['sources'].values()), source_consumption, directory, tools) as (_, bound_tools):
        result = _render_bound(plan, directory, bound_tools, audio_backend)
    binding_path = directory / 'source-binding.json'
    evidence = json.loads(binding_path.read_text())
    result['source_consumption'] = {'schema': evidence['schema'], 'selection': evidence['selection'],
                                    'status': evidence['status'], 'adoptable': evidence['adoptable'],
                                    'binding': {'path': str(binding_path), 'sha256': sha256(binding_path)}}
    return result


def _render_bound(plan, directory, tools, audio_backend=None):
    normalized = normalize_plan(plan, tools)
    need_dsp = any(Fraction(c['speed']) != 1 and 'selected_audio_clock' in c and
                   audio_intersection(c['selected_audio_clock'], c['start'], c['effective_source_end'], playback=True)
                   for c in normalized['clips'])
    backend = selected_audio_backend(audio_backend, directory, need_dsp=need_dsp)
    if not isinstance(audio_backend, dict) or 'stage_timeout_seconds' not in audio_backend:
        backend['stage_timeout_seconds'] = max(300, min(7200, math.ceil(normalized['duration'] * 2)))
    backend['stage_budget_policy'] = 'explicit per-stage upper limit' if isinstance(audio_backend, dict) and 'stage_timeout_seconds' in audio_backend else 'automatic per-stage max300 through7200 based on output duration'
    write_json(directory / 'normalized-plan.json', normalized)
    args, filters, labels, bridge_budgets, backend_receipts = ['-copyts'], [], [], [], []
    width, height, fps = normalized['width'], normalized['height'], normalized['fps']
    next_input_index = 0
    for i, clip in enumerate(normalized['clips']):
        media = normalized['sources'][clip['source_id']]
        source_input_index = next_input_index
        args += ['-i', media['path']]
        next_input_index += 1
        a, b, length = clip['start'], clip['end'], clip['frames'] / float(Fraction(fps))
        speed=float(Fraction(clip['speed']))
        observed_frame = Fraction(clip['selected_video_clock']['max_observed_frame_duration'])
        bridge_frames = math.ceil(observed_frame * Fraction(fps) / Fraction(clip['speed'])) + 1
        require(bridge_frames <= 120, 'SOURCE_FRAME_QUANTIZATION_UNSUPPORTED')
        bridge_budgets.append(bridge_frames)
        video_clock=f'(PTS-{a}/TB)/{speed}'
        audio_tempo='' if speed==1 else f'atempo={speed},'
        geometry = (f'scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2'
                    if normalized['fit'] == 'contain' else
                    f'scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}')
        # Bridge only the observed source-frame presentation duration after
        # speed mapping, plus one rounding frame. It never expands source or
        # evidence coverage; exact count is checked after decoding below.
        filters.append(f'[{source_input_index}:v:0]trim=start={a}:end={b},setpts={video_clock},{geometry},setsar=1,fps={fps},'
                       f'tpad=stop_mode=clone:stop={bridge_frames},trim=end_frame={clip["frames"]},'
                       f'setpts=N/({fps}*TB),format=yuv420p[v{i}]')
        if 'selected_audio_clock' in clip and audio_intersection(clip['selected_audio_clock'], a, clip['effective_source_end'], playback=True):
            if backend['kind'] in ('rubberband-r3-v4', 'rubberband-r3-stream-v5') and Fraction(clip['speed']) != 1:
                stretched, channels, evidence = prepare_rubberband_audio(
                    clip, media, directory, tools, backend['helper'], i, fps, timeout=backend['stage_timeout_seconds'], streaming=backend['kind'] == 'rubberband-r3-stream-v5')
                backend_receipts.append(evidence)
                raw_input_index = next_input_index
                args += ['-f', 'f32le', '-ar', '48000', '-ac', str(channels), '-i', str(stretched)]
                next_input_index += 1
                filters.append(f'[{raw_input_index}:a:0]atrim=end_sample={evidence["target_pcm"]["frames"]},'
                               f'asetpts=PTS-STARTPTS[a{i}]')
            else:
                filters.append(f'[{source_input_index}:a:0]atrim=start={a}:end={b},asetpts=(PTS-{a}/TB)/{speed},'
                               f'{audio_tempo}aresample=48000:async=1:first_pts=0,'
                               f'aformat=sample_fmts=fltp:channel_layouts=stereo,volume={"0" if clip.get("mute") else str(clip["gain_db"])+"dB"},'
                               f'apad,atrim=duration={length}[a{i}]')
        else:
            filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={length}[a{i}]')
        labels.append(f'[v{i}][a{i}]')
    filters.append(''.join(labels) + f'concat=n={len(labels)}:v=1:a=1[outv][outa]')
    output = directory / 'preview.mp4'
    for evidence in backend_receipts:
        require(sha256(evidence['target_pcm']['path']) == evidence['target_pcm']['sha256'], 'RUBBERBAND_TARGET_PCM_IDENTITY_CHANGED')
    tools.ff(args + ['-filter_complex', ';'.join(filters), '-map', '[outv]', '-map', '[outa]',
                     '-map_chapters', '-1', '-r', fps, '-fps_mode', 'cfr',
                     '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-c:a', 'aac', '-b:a', '192k',
                     '-movflags', '+faststart', str(output)], timeout=backend['stage_timeout_seconds'])
    for evidence in backend_receipts:
        require(sha256(evidence['source_pcm']['path']) == evidence['source_pcm']['sha256'], 'RUBBERBAND_SOURCE_PCM_IDENTITY_CHANGED')
        require(sha256(evidence['output_pcm']['path']) == evidence['output_pcm']['sha256'], 'RUBBERBAND_OUTPUT_PCM_IDENTITY_CHANGED')
        require(sha256(evidence['target_pcm']['path']) == evidence['target_pcm']['sha256'], 'RUBBERBAND_TARGET_PCM_IDENTITY_CHANGED')
        require(sha256(evidence['helper']['path']) == evidence['helper']['sha256'], 'RUBBERBAND_HELPER_IDENTITY_CHANGED')
    if backend['kind'] == 'rubberband-r3-v4' and backend['helper'] is not None:
        require(sha256(backend['helper']['path']) == backend['helper']['sha256'], 'RUBBERBAND_HELPER_IDENTITY_CHANGED')
    media = tools.probe(output)
    # concat exposes a microsecond time base. Without an explicit output clock,
    # MP4 can mark the last encoded packet discardable while audio still makes
    # the container duration look correct. Count decoded frames, not nb_frames.
    counted = json.loads(exec_tool([tools.binary('ffprobe'), '-v', 'error',
        '-select_streams', 'v:0', '-count_frames', '-show_entries',
        'stream=nb_read_frames,avg_frame_rate', '-of', 'json', str(output)], timeout=backend['stage_timeout_seconds']).stdout)
    stream = counted.get('streams', [{}])[0]
    require(str(stream.get('nb_read_frames')) == str(normalized['total_frames']), 'RENDER_FRAME_COUNT_MISMATCH')
    require(stream.get('avg_frame_rate') is not None and
            Fraction(stream['avg_frame_rate']) == Fraction(fps), 'RENDER_FRAME_RATE_MISMATCH')
    require(abs(media['duration'] - normalized['duration']) <= max(0.1, 2 / float(Fraction(fps))), 'RENDER_DURATION_MISMATCH')
    return {'media': media, 'normalized_plan': 'normalized-plan.json',
            'decoded_frames': int(stream['nb_read_frames']), 'verified_fps': stream['avg_frame_rate'],
            'quantization_bridge_frame_budgets': bridge_budgets,
            'verification_scope': 'technical render only; semantic/visual/listening review not performed',
            'source_audio_evidence': 'NOT_GRANTED_BY_RENDER',
            'creative_status': 'UNVERIFIED',
            'audio_speed_policy': ('Rubber Band R3 two-pass streaming f32; ordinary source assurance disclosed; listening not verified'
                if backend_receipts and backend['kind'] == 'rubberband-r3-stream-v5' else
                'Rubber Band R3 v4 f32; listening not verified' if backend_receipts else
                'FFmpeg atempo explicitly selected; listening not verified' if need_dsp and backend['kind'] == 'ffmpeg-atempo' else
                'identity or silence; no pitch/time DSP'),
            'audio_backend': backend, 'audio_backend_receipts': backend_receipts}


def map_captions(request, directory, tools):
    exact_keys(request, ['operation', 'plan', 'cues', 'boundary_policy'], ['operation', 'plan', 'cues', 'boundary_policy'])
    require(request['boundary_policy'] in ['reject-partial', 'clip'], 'BOUNDARY_POLICY_REQUIRED')
    normalized = normalize_plan(request['plan'], tools)
    require(isinstance(request['cues'], list), 'CUES_ARRAY_REQUIRED')
    ids, mapped = set(), []
    for cue in request['cues']:
        exact_keys(cue, ['id', 'source_id', 'start', 'end', 'text'], ['id', 'source_id', 'start', 'end', 'text'])
        require(isinstance(cue['id'], str) and cue['id'] and cue['id'] not in ids, 'CUE_ID_DUPLICATE_OR_EMPTY')
        ids.add(cue['id'])
        require(isinstance(cue['text'], str) and cue['text'].strip(), 'CUE_TEXT_REQUIRED')
        require(cue['source_id'] in normalized['sources'], 'CUE_SOURCE_UNKNOWN')
        a, b = span(cue['start'], cue['end'], normalized['sources'][cue['source_id']]['media']['duration'])
        for clip in normalized['clips']:
            if cue['source_id'] != clip['source_id']:
                continue
            left, right = max(a, clip['start']), min(b, clip['effective_source_end'])
            if left >= right:
                continue
            partial = left > a or right < b
            require(not partial or request['boundary_policy'] == 'clip', 'PARTIAL_CUE: ' + cue['id'])
            speed=float(Fraction(clip['speed']))
            start = clip['output_start'] + (left - clip['start']) / speed
            end = min(clip['output_end'], clip['output_start'] + (right - clip['start']) / speed)
            require(start < end, 'CUE_LOST_TO_FRAME_QUANTIZATION')
            mapped.append({'id': cue['id'], 'clip_id': clip['id'], 'start': start,
                           'end': end, 'text': cue['text'], 'partial': partial})
    mapped.sort(key=lambda c: (c['start'], c['end']))
    write_json(directory / 'captions.json', {'schema': 'output-captions/1', 'plan_sha256': fingerprint(request['plan']), 'cues': mapped})
    def timestamp(seconds):
        milliseconds = round(seconds * 1000)
        hours, milliseconds = divmod(milliseconds, 3600000)
        minutes, milliseconds = divmod(milliseconds, 60000)
        seconds, milliseconds = divmod(milliseconds, 1000)
        return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'
    with (directory / 'captions.srt').open('x', encoding='utf-8') as stream:
        for i, cue in enumerate(mapped, 1):
            require(round(cue['end'] * 1000) > round(cue['start'] * 1000), 'CUE_TOO_SHORT_FOR_SRT')
            stream.write(f'{i}\n{timestamp(cue["start"])} --> {timestamp(cue["end"])}\n{cue["text"]}\n\n')
    return {'mapped_cues': len(mapped), 'partial_cues': sum(x['partial'] for x in mapped),
            'text_modified': False, 'semantic_accuracy': 'UNVERIFIED'}


def patch_plan(request, directory, tools):
    exact_keys(request, ['operation', 'plan', 'expected_revision', 'allowed_clip_ids', 'changes'],
               ['operation', 'plan', 'expected_revision', 'allowed_clip_ids', 'changes'])
    plan = request['plan']
    require(fingerprint(plan) == request['expected_revision'], 'REVISION_CONFLICT')
    normalize_plan(plan, tools)
    require(isinstance(request['allowed_clip_ids'], list) and all(isinstance(x, str) for x in request['allowed_clip_ids']), 'ALLOWED_CLIPS_REQUIRED')
    require(isinstance(request['changes'], list) and request['changes'], 'CHANGES_REQUIRED')
    updated = copy.deepcopy(plan)
    clips = {x['id']: x for x in updated['clips']}
    require(set(request['allowed_clip_ids']) <= set(clips), 'ALLOWED_CLIP_UNKNOWN')
    for change in request['changes']:
        exact_keys(change, ['clip_id', 'set'], ['clip_id', 'set'])
        require(change['clip_id'] in request['allowed_clip_ids'], 'FROZEN_CLIP')
        exact_keys(change['set'], ['start', 'end', 'gain_db', 'speed'])
        require(bool(change['set']), 'EMPTY_CHANGE')
        clips[change['clip_id']].update(change['set'])
    normalize_plan(updated, tools)
    changed = [a['id'] for a, b in zip(plan['clips'], updated['clips']) if a != b]
    write_json(directory / 'execution-plan.json', updated)
    return {'previous_revision': fingerprint(plan), 'revision': fingerprint(updated),
            'changed_clip_ids': changed, 'unchanged_clips': [x['id'] for x in plan['clips'] if x['id'] not in changed],
            'timeline_positions_may_shift': any(set(x['set']) & {'start','end','speed'} for x in request['changes']),
            'invalidated': ['normalized-plan', 'captions', 'render', 'qc'] if changed else []}


def windowed_mix_clock(tools, path, media, end, *, kind, start=0, window_seconds=240,
                       allow_no_audio=False, playback=False):
    """Observe a complete mix input in bounded, overlapping presentation windows.

    Source selectors retain their per-call frame cap. The overlapping decoded
    intervals, rather than requested window endpoints, are stitched. Missing
    frames at a seam therefore remain a real gap and fail the caller's clock
    check instead of being invented as continuous media.
    """
    require(kind in ('video', 'audio'), 'CLOCK_KIND_UNSUPPORTED')
    require(kind == 'audio' or not allow_no_audio, 'CLOCK_KIND_UNSUPPORTED')
    require(kind == 'audio' or not playback, 'CLOCK_KIND_UNSUPPORTED')
    require(0 <= start < end and window_seconds > 0, 'CLOCK_WINDOW_INVALID')
    selector = tools.selected_video_clock if kind == 'video' else tools.selected_audio_clock
    windows = []
    cursor = float(start)
    while cursor < end:
        stop = min(end, cursor + window_seconds)
        if kind == 'audio':
            # Keep default observed calls compatible with existing selector implementations.
            kwargs = {'allow_empty': True, **({'playback': True} if playback else {})}
            windows.append(selector(path, media, cursor, stop, **kwargs))
        else:
            windows.append(selector(path, media, cursor, stop))
        cursor = stop
    first = windows[0]
    for clock in windows[1:]:
        require(all(clock[k] == first[k] for k in ('stream_index', 'stream_selector', 'time_base')),
                'SOURCE_CLOCK_WINDOW_SELECTOR_CHANGED')
        if kind == 'audio':
            require(clock['sample_rate'] == first['sample_rate'] and
                    clock['source_time_precision'] == first['source_time_precision'],
                    'SOURCE_CLOCK_WINDOW_SELECTOR_CHANGED')
    def merge_intervals(key):
        ranges = sorted((Fraction(a), Fraction(b)) for clock in windows for a, b in
                        (clock.get('playback_intervals', clock['observed_intervals']) if key == 'playback_intervals' else clock[key]))
        require(ranges or (kind == 'audio' and allow_no_audio),
                'BASE_PICTURE_CLOCK_UNVERIFIED' if kind == 'video' else 'SOURCE_AUDIO_DISCONTINUOUS')
        merged = []
        for a, b in ranges:
            if merged and a <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], b)
            else:
                merged.append([a, b])
        return [[str(a), str(b)] for a, b in merged]
    # Playback may bridge a verified one-tick CFR rounding gap. Strict source
    # evidence uses only observed intervals and must retain that gap.
    if kind == 'video':
        intervals = {'observed_intervals': merge_intervals('observed_intervals'),
                     'playback_intervals': merge_intervals('playback_intervals'),
                     'max_observed_frame_duration': str(max(Fraction(c['max_observed_frame_duration']) for c in windows))}
    else:
        observed = merge_intervals('observed_intervals')
        from vorbis_group_clock import merge_window_playback
        intervals = {'observed_intervals': observed,
                     **merge_window_playback(windows, observed)}
    return {**first, **intervals,
            'window_count': len(windows),
            'window_seconds': window_seconds,
            'window_observations': [clock['observation_window'] for clock in windows],
            'aggregation': 'overlapping decoded intervals only; playback bridges never enter strict observed evidence'}

def audio_mix(request, directory, tools):
    exact_keys(request, ['operation', 'source', 'base_gain_db', 'base_gain_windows', 'tracks'], ['operation', 'source', 'base_gain_db', 'tracks'])
    asset = source(request['source']); media = tools.probe(asset['path'])
    require(any(s['codec_type'] == 'video' for s in media['streams']), 'VIDEO_STREAM_REQUIRED')
    picture_clock = windowed_mix_clock(tools, asset['path'], media, media['duration'], kind='video')
    require(len(picture_clock['playback_intervals']) == 1 and
            Fraction(picture_clock['playback_intervals'][0][0]) == 0,
            'BASE_PICTURE_CLOCK_UNVERIFIED')
    picture_duration = float(Fraction(picture_clock['playback_intervals'][0][1]))
    gain = number(request['base_gain_db'], 'base_gain_db')
    require(-120 <= gain <= 24, 'GAIN_OUT_OF_RANGE')
    require(isinstance(request['tracks'], list) and request['tracks'], 'AUDIO_TRACKS_REQUIRED')
    args = ['-copyts', '-i', asset['path']]; filters, labels, used = [], [], []
    windows=request.get('base_gain_windows',[])
    require(isinstance(windows,list),'GAIN_WINDOWS_ARRAY_REQUIRED')
    gain_filter=f'volume={gain}dB'
    previous_end=0
    for window in windows:
        exact_keys(window,['start','end','gain_db'],['start','end','gain_db'])
        a,b=span(window['start'],window['end'],picture_duration)
        require(a >= previous_end,'OVERLAPPING_GAIN_WINDOWS');previous_end=b
        window_gain=number(window['gain_db'],'window_gain_db');require(-120 <= window_gain <= 24,'GAIN_OUT_OF_RANGE')
        # Absolute desired gain in each explicitly selected window, relative to the base setting.
        gain_filter+=f",volume={window_gain-gain}dB:enable='gte(t,{a})*lt(t,{b})'"
    base_clock = None
    if any(s['codec_type'] == 'audio' for s in media['streams']):
        base_clock = windowed_mix_clock(tools, asset['path'], media, picture_duration, kind='audio', playback=True)
        audio_intersection(base_clock, 0, picture_duration, playback=True)
        filters.append(f'[0:a:0]asetpts=PTS,aresample=48000:async=1:first_pts=0,'
                       f'aformat=sample_fmts=fltp:channel_layouts=stereo,{gain_filter},'
                       f'apad,atrim=duration={picture_duration}[base]')
    else:
        filters.append(f'anullsrc=r=48000:cl=stereo,atrim=duration={picture_duration}[base]')
    labels.append('[base]')
    for i, track in enumerate(request['tracks'], 1):
        exact_keys(track, ['source', 'start', 'end', 'output_start', 'gain_db'], ['source','start','end','output_start','gain_db'])
        ref=source(track['source']); info=tools.probe(ref['path'])
        require(any(s['codec_type']=='audio' for s in info['streams']), 'TRACK_AUDIO_REQUIRED')
        a,b=span(track['start'],track['end'],info['duration'])
        track_clock=windowed_mix_clock(tools,ref['path'],info,b,kind='audio',start=a,playback=True)
        audio_intersection(track_clock,a,b,require_full=True,playback=True)
        output_start=number(track['output_start'],'output_start',0)
        require(output_start+b-a <= picture_duration+0.000001, 'AUDIO_EXCEEDS_PICTURE')
        volume=number(track['gain_db'],'gain_db'); require(-120 <= volume <= 24,'GAIN_OUT_OF_RANGE')
        samples=round(output_start*48000)
        args += ['-i',ref['path']]
        filters.append(f'[{i}:a:0]atrim=start={a}:end={b},asetpts=PTS-{a}/TB,aresample=48000:async=1:first_pts=0,'
                       f'aformat=sample_fmts=fltp:channel_layouts=stereo,volume={volume}dB,adelay={samples}S:all=1[t{i}]')
        labels.append(f'[t{i}]'); used.append({'source':ref,'start':a,'end':b,'output_start_samples':samples,'gain_db':volume,'audio_clock_basis':track_clock.get('playback_basis', {'status':'OBSERVED_ONLY'})})
    filters.append(''.join(labels)+f'amix=inputs={len(labels)}:duration=first:dropout_transition=0:normalize=0[mix]')
    tools.ff(args+['-filter_complex',';'.join(filters),'-map','0:v:0','-map','[mix]','-c:v','copy','-c:a','aac','-b:a','192k',str(directory/'mixed.mp4')])
    return {'source':asset,'tracks':used,'base_gain_windows':windows,'picture_clock':picture_clock,
            'base_audio_clock_basis':base_clock.get('playback_basis') if base_clock is not None else None,
            'source_audio_evidence':'NOT_GRANTED_BY_MIX',
            'gain_window_precision':'FFmpeg audio frame boundaries',
            'automatic_ducking':False,'automatic_limiter':False,
            'audio_review':'NOT_RUN','note':'Gains and overlap are caller decisions; no automatic peak or loudness correction'}


def caption_burn(request, directory, tools):
    exact_keys(request,['operation','source','font','font_family','font_size','margin_v','color_rgb','cues'],
               ['operation','source','font','font_family','font_size','margin_v','color_rgb','cues'])
    asset=source(request['source']); font=source(request['font']); media=tools.probe(asset['path'])
    video=next((s for s in media['streams'] if s['codec_type']=='video'),None)
    require(video is not None,'VIDEO_STREAM_REQUIRED')
    family=request['font_family']
    require(isinstance(family,str) and bool(re.fullmatch(r'[\w \-]+',family)), 'FONT_FAMILY_INVALID')
    size=number(request['font_size'],'font_size',1); margin=number(request['margin_v'],'margin_v',0)
    require(size <= video['height'] and margin < video['height'], 'CAPTION_GEOMETRY_INVALID')
    rgb=request['color_rgb']; require(isinstance(rgb,str) and bool(re.fullmatch('[0-9A-Fa-f]{6}',rgb)),'COLOR_RGB_INVALID')
    require(isinstance(request['cues'],list) and request['cues'],'CUES_REQUIRED')
    (directory/'fonts').mkdir()
    suffix=Path(font['path']).suffix.lower(); require(suffix in ['.ttf','.otf','.ttc'],'FONT_FORMAT_UNSUPPORTED')
    from source_binding import execution_path
    shutil.copyfile(execution_path(font['path']),directory/'fonts'/('specified'+suffix))
    ass='[Script Info]\nScriptType: v4.00+\nPlayResX: '+str(video['width'])+'\nPlayResY: '+str(video['height'])+'\nWrapStyle: 0\n'
    ass+='[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n'
    ass+=f'Style: Default,{family},{size},&H00{rgb[4:6]}{rgb[2:4]}{rgb[0:2]},&H00000000,1,1,0,2,20,20,{margin},1\n'
    ass+='[Events]\nFormat: Layer, Start, End, Style, Text\n'
    previous_end=0
    def ts(value):
        centis=round(value*100); hours,centis=divmod(centis,360000); mins,centis=divmod(centis,6000); secs,centis=divmod(centis,100)
        return f'{hours}:{mins:02}:{secs:02}.{centis:02}'
    for cue in request['cues']:
        exact_keys(cue,['start','end','text'],['start','end','text'])
        a,b=span(cue['start'],cue['end'],media['duration'])
        require(a >= previous_end,'OVERLAPPING_CAPTIONS');previous_end=b
        require(round(b*100)>round(a*100),'CUE_TOO_SHORT_FOR_ASS')
        require(isinstance(cue['text'],str) and cue['text'].strip(),'CUE_TEXT_REQUIRED')
        # ASS override syntax must not be accepted through ordinary text.
        require(not any(x in cue['text'] for x in ['{','}','\\','\r']),'ASS_CONTROL_CHARACTERS_UNSUPPORTED')
        text=cue['text'].replace('\n',r'\N')
        ass+=f'Dialogue: 0,{ts(a)},{ts(b)},Default,{text}\n'
    (directory/'captions.ass').write_text(ass,encoding='utf-8')
    tools.ff(['-i',asset['path'],'-vf','ass=captions.ass:fontsdir=fonts','-map','0:v:0','-map','0:a?',
              '-c:v','libx264','-crf','18','-preset','medium','-c:a','copy','captioned.mp4'],cwd=directory)
    return {'source':asset,'font':font,'font_family':family,'cue_count':len(request['cues']),
            'visual_review':'NOT_RUN','font_fallback_verified':False,
            'note':'Burn performed; glyph/fallback and composition must be inspected on actual output'}


def tts_macos(request, directory, tools):
    exact_keys(request,['operation','text','voice','rate'],['operation','text','voice','rate'])
    text=request['text']; voice=request['voice'];rate=request['rate']
    require(isinstance(text,str) and bool(text.strip()),'TTS_TEXT_REQUIRED')
    require('[[' not in text and ']]' not in text,'EMBEDDED_SPEECH_COMMANDS_UNSUPPORTED')
    require(type(rate) is int and 80 <= rate <= 400,'TTS_RATE_OUT_OF_RANGE')
    binary=shutil.which('say');require(binary is not None,'DEPENDENCY_UNAVAILABLE: macOS say')
    inventory=exec_tool([binary,'-v','?']).stdout
    voices={m.group(1).strip() for line in inventory.splitlines() if (m:=re.match(r'^(.*?)\s{2,}\S+\s*#',line))}
    require(voice in voices,'VOICE_NOT_INSTALLED')
    (directory/'narration.txt').write_text(text,encoding='utf-8')
    exec_tool([binary,'-v',voice,'-r',str(rate),'-f',str(directory/'narration.txt'),'-o',str(directory/'speech.aiff')])
    tools.ff(['-i',str(directory/'speech.aiff'),'-ar','48000','-ac','1','-c:a','pcm_s16le',str(directory/'speech.wav')])
    info=tools.probe(directory/'speech.wav')
    return {'provider':'macos-say','provider_binary':binary,'provider_sha256':sha256(binary),
            'voice':voice,'rate':rate,'actual_duration':info['duration'],'word_alignment':'UNAVAILABLE',
            'listening_review':'NOT_RUN','text_sha256':sha256(directory/'narration.txt'),
            'note':'Explicit local system voice provider; no claim of cinematic voice quality or word timestamps'}


def execute(request, directory, tools):
    op = request.get('operation')
    if op == 'host-bridge':
        from host_bridge import execute as bridge_execute
        return bridge_execute(request, directory, tools)
    if op == 'generation-task':
        from generation_dispatch import execute as generation_execute
        return generation_execute(request, directory, tools)
    if op == 'model-text':
        from model_text_dispatch import execute as text_execute
        return text_execute(request, directory, tools)
    if op == 'model-text-deepseek':
        from deepseek_dispatch import execute as model_execute
        return model_execute(request, directory, tools)
    if op == 'work-delivery':
        from delivery_ops import execute as delivery_execute
        return delivery_execute(request, directory, tools)
    if op == 'visual-layer-render':
        from overlay_ops import composite
        return composite(request,directory,tools)
    if op == 'transcript-reference-compare':
        from text_compare_ops import execute as compare_execute
        return compare_execute(request, directory, tools)
    if op == 'speech-transcribe-local':
        from asr_ops import transcribe
        return transcribe(request,directory,tools)
    if op == 'video-reframe':
        from reframe_ops import reframe
        return reframe(request,directory,tools)
    if op in ['work-variant-create','work-batch-render']:
        from batch_ops import execute as batch_execute
        return batch_execute(request,directory,tools)
    if op == 'localization-plan-compile':
        from localization_ops import compile_localization
        return compile_localization(request,directory,tools)
    if op == 'still-image-render':
        from still_ops import render_still
        return render_still(request,directory,tools)
    if op == 'color-lut-apply':
        from color_ops import apply_lut
        return apply_lut(request,directory,tools)
    if op == 'cue-alignment-check':
        from cue_ops import alignment_check
        return alignment_check(request,directory,tools)
    if op == 'caption-coverage-check':
        from caption_ops import coverage_check
        return coverage_check(request,directory,tools)
    if op == 'audio-envelope':
        from audio_ops import envelope
        return envelope(request,directory,tools)
    if op in ['media-signal-scan','event-plan-compile']:
        from highlight_ops import execute as highlight_execute
        return highlight_execute(request,directory,tools)
    if op == 'evidence-plan-compile':
        from evidence_ops import compile_evidence
        return compile_evidence(request,directory,tools)
    if op in ['sync-offset-measure','multicam-plan-compile']:
        from multicam_ops import execute as multicam_execute
        return multicam_execute(request,directory,tools)
    if op in ['work-version','timeline-revise','work-render']:
        from work_ops import execute as work_execute
        return work_execute(request,directory,tools)
    if op in ['screen-focus','tutorial-plan-compile']:
        from tutorial_ops import execute as tutorial_execute
        return tutorial_execute(request,directory,tools)
    if op in ['transcript-import','speech-plan-compile']:
        from speech_ops import execute as speech_execute
        return speech_execute(request,directory,tools)
    if op == 'media-inspect':
        exact_keys(request, ['operation', 'source'], ['operation', 'source'])
        asset = source(request['source'], hash_required=False)
        return {'asset': asset, 'media': tools.probe(asset['path'])}
    if op == 'frame-extract':
        exact_keys(request, ['operation', 'source', 'times'], ['operation', 'source', 'times'])
        asset = source(request['source'])
        media = tools.probe(asset['path'])
        require(isinstance(request['times'], list) and request['times'], 'TIMES_REQUIRED')
        for i, t in enumerate(request['times']):
            t = number(t, 'time', 0)
            require(t < media['duration'], 'FRAME_TIME_OUT_OF_RANGE')
            output = directory / f'frame-{i:04}.png'
            tools.ff(['-ss', str(t), '-i', asset['path'], '-frames:v', '1', str(output)])
            require(output.is_file(), 'FRAME_NOT_PRODUCED')
        return {'source': asset, 'requested_times': request['times'], 'time_precision': 'decoder-selected frame at or after requested timestamp'}
    if op == 'audio-extract':
        exact_keys(request, ['operation', 'source', 'start', 'end', 'sample_rate', 'channels'],
                   ['operation', 'source', 'start', 'end', 'sample_rate', 'channels'])
        asset = source(request['source'])
        media = tools.probe(asset['path'])
        require(any(s['codec_type'] == 'audio' for s in media['streams']), 'NO_AUDIO')
        a, b = span(request['start'], request['end'], media['duration'])
        audio_clock = windowed_mix_clock(tools, asset['path'], media, b, kind='audio', start=a, playback=True)
        audio_intersection(audio_clock, a, b, require_full=True, playback=True)
        require(type(request['sample_rate']) is int and request['sample_rate'] in [16000, 24000, 44100, 48000], 'SAMPLE_RATE_UNSUPPORTED')
        require(type(request['channels']) is int and request['channels'] in [1, 2], 'CHANNELS_UNSUPPORTED')
        output = directory / 'audio.wav'
        filters = f'atrim=start={a}:end={b},asetpts=PTS-{a}/TB,aresample={request["sample_rate"]}:async=1:first_pts=0,atrim=duration={b-a}'
        tools.ff(['-copyts', '-i', asset['path'], '-map', '0:a:0', '-af', filters,
                  '-ac', str(request['channels']), '-c:a', 'pcm_s16le', str(output)])
        with wave.open(str(output), 'rb') as wav:
            samples = wav.getnframes()
        require(samples == round((b-a)*request['sample_rate']), 'AUDIO_COVERAGE_INCOMPLETE')
        return {'source': asset, 'source_start': a, 'source_end': b,
                'selected_audio_clock': audio_clock, 'samples': samples,
                'source_audio_evidence': 'NOT_GRANTED_BY_EXTRACTION'}
    if op == 'timeline-render':
        exact_keys(request, ['operation', 'plan', 'audio_backend', 'source_consumption'], ['operation', 'plan'])
        return render(request['plan'], directory, tools, request.get('audio_backend'), request.get('source_consumption'))
    if op == 'caption-map':
        return map_captions(request, directory, tools)
    if op == 'timeline-patch':
        return patch_plan(request, directory, tools)
    if op == 'audio-mix':
        return audio_mix(request, directory, tools)
    if op == 'caption-burn':
        return caption_burn(request, directory, tools)
    if op == 'tts-macos':
        return tts_macos(request, directory, tools)
    if op == 'media-qc':
        exact_keys(request, ['operation', 'source', 'expected'], ['operation', 'source', 'expected'])
        asset = source(request['source'])
        media = tools.probe(asset['path'])
        expected = request['expected']
        exact_keys(expected, ['duration', 'duration_tolerance', 'width', 'height', 'audio_required'],
                   ['duration', 'duration_tolerance', 'width', 'height', 'audio_required'])
        tolerance = number(expected['duration_tolerance'], 'duration_tolerance', 0)
        number(expected['duration'], 'duration', 0)
        require(type(expected['audio_required']) is bool, 'AUDIO_REQUIRED_BOOLEAN')
        video = next((s for s in media['streams'] if s['codec_type'] == 'video'), {})
        checks = {'duration': abs(media['duration']-expected['duration']) <= tolerance,
                  'width': video.get('width') == expected['width'], 'height': video.get('height') == expected['height'],
                  'audio': not expected['audio_required'] or any(s['codec_type'] == 'audio' for s in media['streams'])}
        tools.ff(['-i', asset['path'], '-f', 'null', '-'])
        checks['decode'] = True
        write_json(directory / 'technical-qc.json', {'source': asset, 'checks': checks,
                   'technical_status': 'PASSED' if all(checks.values()) else 'FAILED',
                   'content_review': 'NOT_RUN', 'visual_review': 'NOT_RUN', 'listening_review': 'NOT_RUN'})
        require(all(checks.values()), 'TECHNICAL_QC_FAILED: ' + ','.join(k for k,v in checks.items() if not v))
        return {'source': asset, 'checks': checks, 'delivery_status': 'DEGRADED',
                'reason': 'Technical checks only; no content, final picture or listening review'}
    raise ContractError('UNSUPPORTED_OPERATION: ' + str(op))


def runtime_module_sources():
    roots = {Path(__file__).resolve().parent}
    for name in ('tool_identity', 'overlay_ops'):
        spec = importlib.util.find_spec(name)
        if spec is not None and spec.origin:
            roots.add(Path(spec.origin).resolve().parent)
    return {str(p.resolve()): sha256(p) for root in roots for p in root.glob('*.py')}


def loaded_runtime_modules(snapshot):
    result = {}
    for name, module in tuple(sys.modules.items()):
        origin = getattr(module, '__file__', None)
        if origin:
            path = str(Path(origin).resolve())
            if path in snapshot:
                digest = sha256(path)
                require(digest == snapshot[path], 'RUNTIME_MODULE_SOURCE_CHANGED: ' + path)
                result[name] = {'path': path, 'sha256': digest}
    return result


def run(request, directory, tools):
    require(isinstance(request, dict), 'REQUEST_OBJECT_REQUIRED')
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    write_json(directory / 'request.json', request)
    receipt = {'schema': 'operation-receipt/1', 'runtime_version': VERSION,
               'runtime_sha256': sha256(__file__), 'request_sha256': fingerprint(request),
               'operation': request.get('operation')}
    directory_token = RUN_DIRECTORY.set(directory)
    sequence_token = TOOL_DIAGNOSTIC_SEQUENCE.set(0)
    try:
        snapshot = {}
        try:
            snapshot = runtime_module_sources()
            receipt['runtime_source_snapshot'] = snapshot
            receipt['runtime_files'] = {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
            cancellation = RUN_CANCELLATION.get()
            if cancellation is not None and cancellation.is_set():
                raise OperationCancelled('CANCELLED_BEFORE_EXECUTION')
            receipt['tools'] = tools.doctor()
            if cancellation is not None and cancellation.is_set():
                raise OperationCancelled('CANCELLED_BEFORE_EXECUTION')
            progress = RUN_PROGRESS.get()
            if progress is not None:
                progress('Executing operation')
            result = execute(request, directory, tools)
            for name in tuple(getattr(tools, '_identity_lock', {})):
                tools.binary(name)
            receipt['loaded_runtime_modules'] = loaded_runtime_modules(snapshot)
            receipt['result'] = result
            receipt['status'] = 'SUCCEEDED'
        except OperationCancelled as exc:
            receipt['status'] = 'FAILED'
            receipt['error'] = str(exc)
            receipt['cancelled'] = True
        except KeyboardInterrupt:
            receipt['status'] = 'FAILED'
            receipt['error'] = 'CANCELLED_BY_USER: partial outputs retained'
            receipt['cancelled'] = True
        except (ContractError, OSError, KeyError, TypeError, ValueError, sqlite3.Error) as exc:
            receipt['status'] = 'FAILED'
            receipt['error'] = str(exc)
            if str(exc).startswith(('TOOL_CANCELLED:', 'RUBBERBAND_TOOL_CANCELLED:')):
                receipt['cancelled'] = True
        receipt['artifacts'] = [{'path': str(p.relative_to(directory)), 'sha256': sha256(p), 'bytes': p.stat().st_size}
                                for p in sorted(directory.rglob('*')) if p.is_file()]
        write_json(directory / 'receipt.json', receipt)
        return receipt

    finally:
        TOOL_DIAGNOSTIC_SEQUENCE.reset(sequence_token)
        RUN_DIRECTORY.reset(directory_token)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['doctor', 'run'])
    parser.add_argument('--ffmpeg')
    parser.add_argument('--ffprobe')
    parser.add_argument('--request', type=Path)
    parser.add_argument('--work-dir', type=Path)
    args = parser.parse_args()
    tools = Tools(args.ffmpeg, args.ffprobe)
    if args.command == 'doctor':
        print(json.dumps(tools.doctor(), ensure_ascii=False, indent=2))
        return 0
    require(args.request and args.work_dir, 'REQUEST_AND_WORK_DIR_REQUIRED')
    receipt = run(json.loads(args.request.read_text()), args.work_dir, tools)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if receipt['status'] == 'SUCCEEDED' else 1


if __name__ == '__main__':
    sys.modules['editing_runtime'] = sys.modules[__name__]
    try:
        sys.exit(main())
    except (ContractError, OSError, ValueError) as exc:
        print(json.dumps({'status': 'FAILED', 'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)
