"""Explicit source-audio cue to timeline-frame arithmetic. No beat or action inference."""
from fractions import Fraction


def alignment_check(request, directory, tools):
    from editing_runtime import exact_keys, require, fingerprint, source, number, write_json, verified_json
    from work_ops import validate_document
    fields = ['operation', 'document', 'expected_document_sha256', 'markers', 'checks']
    exact_keys(request, fields, fields)
    doc = request['document']
    require(fingerprint(doc) == request['expected_document_sha256'], 'DOCUMENT_REVISION_CONFLICT')
    norm, _, tracks = validate_document(doc, tools)
    marker_ref, markers = verified_json(request['markers'], 'MARKER')
    exact_keys(markers, ['schema', 'source', 'basis', 'points'], ['schema', 'source', 'basis', 'points'])
    require(markers['schema'] == 'audio-cue-markers/1', 'MARKER_SCHEMA_UNSUPPORTED')
    audio = source(markers['source']); media = tools.probe(audio['path'])
    require(any(s['codec_type'] == 'audio' for s in media['streams']), 'AUDIO_STREAM_REQUIRED')
    require(markers['basis'] in ['declared', 'model-candidate', 'human-reviewed'], 'MARKER_BASIS_REQUIRED')
    points = markers['points']; require(isinstance(points, list) and points, 'MARKERS_REQUIRED')
    by_id = {}
    for point in points:
        keys = ['id', 'time', 'label', 'uncertainty_seconds']
        exact_keys(point, keys, keys)
        pid = point['id']
        require(isinstance(pid, str) and pid.strip() and pid not in by_id, 'MARKER_ID_DUPLICATE_OR_EMPTY')
        t = number(point['time'], 'marker time', 0)
        require(t <= media['duration'], 'MARKER_OUTSIDE_SOURCE')
        require(isinstance(point['label'], str) and point['label'].strip(), 'MARKER_LABEL_REQUIRED')
        uncertainty = point['uncertainty_seconds']
        if uncertainty is not None: number(uncertainty, 'marker uncertainty', 0)
        by_id[pid] = point
    checks = request['checks']; require(isinstance(checks, list) and checks, 'CHECKS_REQUIRED')
    clips = {c['id']: c for c in norm['clips']}
    track_map = dict(zip(doc['audio_tracks'], tracks))
    ids, rows = set(), []
    fps = Fraction(norm['fps'])
    for check in checks:
        keys = ['id', 'audio_track_id', 'marker_id', 'clip_id', 'frame_offset', 'desired_delta_seconds', 'tolerance_seconds']
        exact_keys(check, keys, keys)
        cid = check['id']
        require(isinstance(cid, str) and cid.strip() and cid not in ids, 'CHECK_ID_DUPLICATE_OR_EMPTY'); ids.add(cid)
        require(check['audio_track_id'] in track_map, 'AUDIO_TRACK_UNKNOWN')
        require(check['marker_id'] in by_id, 'MARKER_UNKNOWN')
        require(check['clip_id'] in clips, 'CLIP_UNKNOWN')
        track = track_map[check['audio_track_id']]; point = by_id[check['marker_id']]; clip = clips[check['clip_id']]
        require(track['source']['sha256'] == audio['sha256'], 'MARKER_TRACK_SOURCE_MISMATCH')
        require(track['start'] <= point['time'] <= track['end'], 'MARKER_OUTSIDE_SELECTED_AUDIO')
        offset = check['frame_offset']
        require(type(offset) is int and 0 <= offset <= clip['frames'], 'FRAME_OFFSET_INVALID')
        desired = number(check['desired_delta_seconds'], 'desired delta')
        tolerance = number(check['tolerance_seconds'], 'tolerance', 0)
        frame = clip['output_start_frame']+offset
        visual_time = float(Fraction(frame, 1)/fps)
        audio_time = track['output_start']+point['time']-track['start']
        delta = visual_time-audio_time
        error = delta-desired
        rows.append({'id': cid, 'audio_track_id': check['audio_track_id'], 'marker_id': check['marker_id'],
                     'marker_label': point['label'], 'basis': markers['basis'], 'uncertainty_seconds': point['uncertainty_seconds'],
                     'clip_id': clip['id'], 'output_frame': frame, 'visual_time': visual_time, 'audio_time': audio_time,
                     'actual_delta_seconds': delta, 'desired_delta_seconds': desired, 'error_seconds': error,
                     'tolerance_seconds': tolerance, 'aligned': abs(error) <= tolerance+1e-9,
                     'audio_gain_db': track['gain_db'], 'boundary': offset == clip['frames']})
    aligned = all(r['aligned'] for r in rows)
    result = {'schema': 'cue-alignment/1', 'document_sha256': fingerprint(doc), 'markers': marker_ref,
              'status': 'ALIGNED' if aligned else 'MISALIGNED', 'all_aligned': aligned, 'checks': rows,
              'fps': norm['fps'], 'perceptual_sync': 'NOT_RUN', 'marker_semantics': 'NOT_VERIFIED',
              'scope': 'Numeric mapping of declared audio-source cues to explicit current output frame boundaries. '
                       'A cue at track end is a boundary, not proof of audible onset. Uncertainty is reported, not folded into tolerance. '
                       'No beat/downbeat/phrase/action detection, audibility, musicality, rendered-frame identity or lip-sync guarantee; no mutation.'}
    write_json(directory/'cue-alignment.json', result)
    return result
