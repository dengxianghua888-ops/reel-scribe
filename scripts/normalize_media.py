#!/usr/bin/env python3
"""Explicit, bounded, lossy local import. Never a rendering fallback."""
from __future__ import annotations
import argparse
from fractions import Fraction
import json
import math
import os
from pathlib import Path
import re
import stat
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
import editing_runtime as rt


def local_file(value):
    raw = str(value)
    rt.require('://' not in raw and not raw.startswith(('pipe:', 'file:', '-')), 'LOCAL_FILE_REQUIRED')
    path = Path(raw).absolute()
    rt.require(not any(p.is_symlink() for p in [path, *path.parents]), 'SYMLINK_FORBIDDEN')
    rt.require(path.exists() and stat.S_ISREG(path.stat().st_mode), 'REGULAR_FILE_REQUIRED')
    return path


def reject_external_references(path, magic):
    """Reject ISO-BMFF external data/reference movies before any ffprobe.

    WebM is accepted as a trusted local self-contained recording, not a generic
    untrusted-media security boundary. No playlist demuxer is selected.
    """
    if magic[:4] == b'\x1aE\xdf\xa3':
        return
    size = path.stat().st_size
    containers = {b'moov', b'trak', b'mdia', b'minf', b'dinf'}
    count = 0
    with path.open('rb') as stream:
        def walk(start, end, depth=0):
            nonlocal count
            rt.require(depth <= 8, 'INVALID_ISOBMFF_STRUCTURE')
            position = start
            while position < end:
                count += 1
                rt.require(count <= 100000 and end-position >= 8, 'INVALID_ISOBMFF_STRUCTURE')
                stream.seek(position); header = stream.read(8)
                length, kind = int.from_bytes(header[:4], 'big'), header[4:]
                header_size = 8
                if length == 1:
                    length = int.from_bytes(stream.read(8), 'big'); header_size = 16
                elif length == 0:
                    length = end-position
                rt.require(length >= header_size and position+length <= end, 'INVALID_ISOBMFF_STRUCTURE')
                body, stop = position+header_size, position+length
                rt.require(kind not in {b'rmra', b'rmda', b'rdrf'}, 'EXTERNAL_MEDIA_REFERENCE_FORBIDDEN')
                if kind in containers:
                    walk(body, stop, depth+1)
                elif kind == b'dref':
                    stream.seek(body); full = stream.read(8)
                    rt.require(len(full)==8 and full[:4]==b'\0'*4, 'INVALID_DREF')
                    entries = int.from_bytes(full[4:], 'big'); cursor=body+8
                    rt.require(entries==1, 'EXTERNAL_MEDIA_REFERENCE_FORBIDDEN')
                    stream.seek(cursor); entry=stream.read(12)
                    rt.require(len(entry)==12 and int.from_bytes(entry[:4],'big')==12
                        and entry[4:8]==b'url ' and entry[8:]==b'\0\0\0\1'
                        and cursor+12==stop, 'EXTERNAL_MEDIA_REFERENCE_FORBIDDEN')
                position = stop
        walk(0, size)


def gaps(clock, start, end):
    """Uncovered evidence, not proof of perceptible gaps."""
    cursor = Fraction(str(start)); stop = Fraction(str(end)); missing = []
    for a, b in clock['observed_intervals']:
        a, b = Fraction(a), Fraction(b)
        if b <= cursor or a >= stop:
            continue
        if a > cursor:
            missing.append([float(cursor), float(min(a, stop))])
        cursor = max(cursor, min(b, stop))
    if cursor < stop:
        missing.append([float(cursor), float(stop)])
    return missing


def _publish_receipt(directory, receipt, staging_name):
    """Fully write/fsync before exclusive commit-marker publication.

    Staging links are intentionally retained: cleanup is not part of commit.
    """
    staging = directory / staging_name
    with staging.open('x') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(staging, directory / 'receipt.json')
    # No fallible cleanup after this commit point.


def completed_import(directory):
    """Only this receipt+hash protocol identifies consumable derived media."""
    directory = Path(directory)
    marker = local_file(directory / 'receipt.json')
    receipt = json.loads(marker.read_text())
    rt.require(receipt.get('schema') == 'normalized-import/1' and
               receipt.get('status') == 'SUCCEEDED_TECHNICAL_NEEDS_REVIEW',
               'IMPORT_NOT_COMMITTED')
    derived = receipt.get('derived', {})
    media = local_file(directory / 'normalized.mov')
    rt.require(str(media) == derived.get('path') and media.stat().st_size == derived.get('bytes')
               and rt.sha256(media) == derived.get('sha256'), 'COMMITTED_MEDIA_MISMATCH')
    return receipt


def normalize(source, expected_sha256, output, *, start, end, fps='30',
              max_video_gap=0.05, max_audio_gap=0.02, accept_lossy=False,
              attribution='', license_url='', tools=None):
    rt.require(accept_lossy is True, 'EXPLICIT_LOSSY_ACCEPTANCE_REQUIRED')
    src = local_file(source)
    with src.open('rb') as stream:
        magic = stream.read(12)
    rt.require(magic[:4] == b'\x1aE\xdf\xa3' or magic[4:8] == b'ftyp',
               'ONLY_SELF_CONTAINED_WEBM_OR_ISOBMFF_INPUT')
    reject_external_references(src, magic)
    rt.require(re.fullmatch('[0-9a-f]{64}', expected_sha256 or '') is not None, 'SHA256_REQUIRED')
    rt.require(rt.sha256(src) == expected_sha256, 'SOURCE_HASH_MISMATCH')
    for value in [start, end, max_video_gap, max_audio_gap]:
        rt.require(type(value) in (int, float) and math.isfinite(value), 'FINITE_NUMBER_REQUIRED')
    rt.require(0 <= start < end and end-start <= 600, 'WINDOW_INVALID_OR_OVER_600_SECONDS')
    rt.require(0 <= max_video_gap <= 0.25 and 0 <= max_audio_gap <= 0.25, 'GAP_LIMIT_INVALID')
    rate = Fraction(str(fps))
    rt.require(1 <= rate <= 120, 'FPS_INVALID')
    # Require whole output frames; do not silently move the requested endpoint.
    rt.require((Fraction(str(end))-Fraction(str(start)))*rate % 1 == 0, 'WINDOW_NOT_FRAME_ALIGNED')
    dest = Path(output).absolute()
    rt.require('://' not in str(output), 'LOCAL_OUTPUT_REQUIRED')
    rt.require(not any(p.is_symlink() for p in [dest, *dest.parents]), 'SYMLINK_FORBIDDEN')
    rt.require(dest.parent.is_dir() and not dest.exists(), 'OUTPUT_MUST_BE_NEW_DIRECTORY')
    tools = tools or rt.Tools()
    identity = tools.doctor()
    rt.require(all('error' not in x for x in identity.values()), 'TOOL_IDENTITY_UNAVAILABLE')
    before = tools.probe(src)
    video = [s for s in before['streams'] if s.get('codec_type') == 'video']
    audio = [s for s in before['streams'] if s.get('codec_type') == 'audio']
    rt.require(len(video) == len(audio) == 1, 'EXACTLY_ONE_VIDEO_AND_AUDIO_REQUIRED')
    rt.require(not video[0].get('tags', {}).get('rotate') and not any(
        x.get('rotation', 0) for x in video[0].get('side_data_list', [])), 'ROTATED_INPUT_UNSUPPORTED')
    vc = tools.selected_video_clock(src, before, start, end)
    ac = tools.selected_audio_clock(src, before, start, end)
    vg, ag = gaps(vc, start, end), gaps(ac, start, end)
    rt.require(all(b-a <= max_video_gap + 1e-9 for a,b in vg), 'VIDEO_GAP_EXCEEDS_EXPLICIT_LIMIT')
    rt.require(all(b-a <= max_audio_gap + 1e-9 for a,b in ag), 'AUDIO_GAP_EXCEEDS_EXPLICIT_LIMIT')
    # A delayed first real picture must not be invisibly moved earlier. Allow
    # only a sub-frame boundary hold, disclosed below, never a large intro gap.
    first = [Fraction(a) for a,b in vc['observed_intervals'] if Fraction(b)>Fraction(str(start))]
    rt.require(first and float(first[0])-start <= min(max_video_gap, 1/float(rate))+1e-9,
               'LEADING_VIDEO_OFFSET_UNSUPPORTED')
    os.mkdir(dest)  # exclusive reservation; no overwritten output
    receipt = {'schema':'normalized-import/1', 'status':'FAILED',
        'source':{'path':str(src),'sha256':expected_sha256,'bytes':src.stat().st_size}, 'source_window':[start,end],
        'tool_identity':identity, 'before_probe':before, 'source_video_clock':vc,
        'source_audio_clock':ac, 'observed_uncovered_ranges':{'video':vg,'audio':ag},
        'policy':{'fps':str(rate),'sample_rate':48000,'max_video_gap':max_video_gap,
                  'max_audio_gap':max_audio_gap,'lossy':True},
        'attribution':attribution,'license_url':license_url,
        'commit_protocol':'Only a complete receipt.json with SUCCEEDED_TECHNICAL_NEEDS_REVIEW and matching derived hash commits the import; media/staging files alone are never consumable.',
        'timing_mapping':'derived t = original presentation timestamp - source_window.start; not per-stream STARTPTS',
        'changes':['H264 CRF18 lossy video encoding','CFR may drop/duplicate frames and hold sub-frame leading picture',
                   'audio resampling, async compensation and bounded silence padding; PCM s16 conversion'],
        'exact_changed_frame_and_sample_counts':'UNKNOWN',
        'listening_review':'NOT_RUN','creative_acceptance':'NOT_RUN'}
    duration = end-start
    graph = (f'[0:v:0]trim=start={start}:end={end},setpts=PTS-{start}/TB,'
             f'fps=fps={rate}:start_time=0,tpad=stop_mode=clone:stop_duration={max_video_gap},trim=duration={duration}[v];'
             f'[0:a:0]atrim=start={start}:end={end},asetpts=PTS-{start}/TB,'
             f'aresample=48000:async=1:first_pts=0,apad=whole_dur={duration},atrim=duration={duration}[a]')
    temp = dest/'pending.mov'
    args = [tools.binary('ffmpeg'),'-nostdin','-hide_banner','-v','error','-n',
            '-protocol_whitelist','file','-copyts','-noautorotate','-i',str(src),
            '-filter_complex',graph,'-map','[v]','-map','[a]','-t',str(duration),
            '-map_metadata','-1','-c:v','libx264','-preset','fast','-crf','18','-pix_fmt','yuv420p',
            '-video_track_timescale','90000','-c:a','pcm_s16le',str(temp)]
    receipt['argv'] = args
    published_identity = None
    final = dest/'normalized.mov'
    try:
        rt.exec_tool(args, timeout=600)
        tools.binary('ffmpeg')
        rt.require(rt.sha256(src)==expected_sha256, 'SOURCE_CHANGED_DURING_IMPORT')
        after = tools.probe(temp)
        dvc = tools.selected_video_clock(temp, after, 0, duration)
        dac = tools.selected_audio_clock(temp, after, 0, duration)
        rt.require_video_coverage(dvc, 0, duration)
        rt.audio_intersection(dac, 0, duration, require_full=True, require_precise=True)
        rt.exec_tool([tools.binary('ffmpeg'),'-nostdin','-v','error','-protocol_whitelist','file',
                      '-i',str(temp),'-f','null','-'], timeout=600)
        tools.binary('ffmpeg'); tools.binary('ffprobe')
        rt.require(rt.sha256(src)==expected_sha256,'SOURCE_CHANGED_DURING_IMPORT')
        # Hard-link publication is exclusive, never replacing a concurrent file.
        info = temp.stat()
        os.link(temp, final)
        published_identity = (info.st_dev, info.st_ino)
        receipt.update(status='SUCCEEDED_TECHNICAL_NEEDS_REVIEW', derived={
            'path':str(final),'sha256':rt.sha256(final),'bytes':final.stat().st_size},
            after_probe=after,derived_video_clock=dvc,derived_audio_clock=dac,
            full_decode='PASS',source_unchanged=True)
        _publish_receipt(dest, receipt, '.success-receipt.pending.json')
    except Exception as exc:
        receipt['status'] = 'FAILED'
        receipt['error'] = str(exc)
        receipt.pop('derived', None)
        receipt['uncommitted_media'] = str(final)
        receipt['rollback'] = 'NO_PUBLISHED_MEDIA'
        if published_identity is not None:
            try:
                actual = final.lstat()
                if (actual.st_dev, actual.st_ino) == published_identity:
                    final.unlink()
                    receipt['rollback'] = 'REMOVED_SAME_INODE_MEDIA_LINK'
                else:
                    receipt['rollback'] = 'NOT_REMOVED_IDENTITY_CHANGED'
            except OSError as cleanup_error:
                receipt['rollback'] = 'UNCOMMITTED_MEDIA_MAY_REMAIN: ' + str(cleanup_error)
        try:
            _publish_receipt(dest, receipt, '.failure-receipt.pending.json')
        except Exception as diagnostic_error:
            # Storage/permissions can prevent even diagnostics. No successful
            # marker was published; never promise full filesystem rollback.
            raise RuntimeError('IMPORT_UNCOMMITTED; do not consume media; ' + str(exc)
                               + '; diagnostic publication failed: ' + str(diagnostic_error)) from exc
        raise
    return receipt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source');parser.add_argument('--expected-sha256',required=True)
    parser.add_argument('--output',required=True);parser.add_argument('--start',type=float,required=True)
    parser.add_argument('--end',type=float,required=True);parser.add_argument('--fps',default='30')
    parser.add_argument('--max-video-gap',type=float,default=0.05)
    parser.add_argument('--max-audio-gap',type=float,default=0.02)
    parser.add_argument('--accept-lossy',action='store_true')
    parser.add_argument('--attribution',default='');parser.add_argument('--license-url',default='')
    args=vars(parser.parse_args())
    try:
        result=normalize(**args);print(json.dumps({'status':result['status'],'derived':result['derived']}))
    except Exception as exc:
        print(str(exc),file=sys.stderr);return 1
    return 0

if __name__=='__main__':sys.exit(main())
