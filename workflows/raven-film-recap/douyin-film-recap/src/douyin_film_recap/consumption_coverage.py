"""Coverage of declared windows by bound render records, never semantic evidence."""
from copy import deepcopy

from .render_contracts import rational, ratio
from .render_timeline import realized_duration
from .workspace import WorkspaceError


def _keys(value, fields):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise WorkspaceError('SUPPORT_WINDOW_FIELDS_INVALID')


def _span(start, end):
    # JSON clocks only; disallow strings, bools and arbitrary rational objects.
    if any(type(v) not in (int, float) for v in (start, end)):
        raise WorkspaceError('SUPPORT_WINDOW_CLOCK_INVALID')
    a, b = rational(start), rational(end)
    if a < 0 or b <= a:
        raise WorkspaceError('SUPPORT_WINDOW_RANGE_INVALID')
    return a, b


def validate(spec, board, base):
    _keys(spec, ['schema', 'beats'])
    if spec['schema'] != 'film-support-windows/1' or not isinstance(spec['beats'], list) or not spec['beats']:
        raise WorkspaceError('SUPPORT_WINDOWS_SCHEMA_INVALID')
    beats = {s.beat_id for s in board.segments}
    sources = {s['source_id']: s['sha256'] for s in base['sources']}
    seen = set()
    for beat in spec['beats']:
        _keys(beat, ['beat_id', 'alternatives'])
        bid = beat['beat_id']
        if not isinstance(bid, str) or bid not in beats or bid in seen:
            raise WorkspaceError('SUPPORT_BEAT_UNKNOWN_OR_DUPLICATE')
        seen.add(bid)
        groups = beat['alternatives']
        if not isinstance(groups, list) or not groups:
            raise WorkspaceError('SUPPORT_ALTERNATIVES_REQUIRED')
        for group in groups:
            if not isinstance(group, list) or not group:
                raise WorkspaceError('SUPPORT_CONJUNCTION_REQUIRED')
            ids = set()
            for window in group:
                _keys(window, ['id', 'source_id', 'source_sha256', 'start', 'end', 'basis'])
                if any(not isinstance(window[k], str) or not window[k].strip() for k in ('id', 'source_id', 'basis')):
                    raise WorkspaceError('SUPPORT_WINDOW_ID_AND_BASIS_REQUIRED')
                if window['id'] in ids:
                    raise WorkspaceError('SUPPORT_WINDOW_ID_DUPLICATE')
                ids.add(window['id'])
                if sources.get(window['source_id']) != window['source_sha256'] or window['source_id'] not in sources:
                    raise WorkspaceError('SUPPORT_SOURCE_IDENTITY_MISMATCH')
                _span(window['start'], window['end'])


def _eligible(segment, row, plan, base):
    """Return an exact record-level source interval or a conservative reason."""
    if segment.mode != 'original' or len(segment.visuals) != 1:
        return None, 'unsupported_nonoriginal_or_multivisual'
    try:
        nodes = [n for n in plan['nodes'] if n['kind'] == 'segment_av' and n.get('segment_id') == segment.segment_id]
        assemblies = [n for n in plan['nodes'] if n['kind'] == 'assembly']
        if len(nodes) != 1 or len(assemblies) != 1:
            return None, 'segment_contract_missing'
        node = nodes[0]; params = node['params']
        deps = [d for d in assemblies[0]['inputs'] if d['role'] == 'segment_av:' + segment.segment_id]
        if len(deps) != 1 or node['key_state'] != 'complete' or not node['semantic_key'] or deps[0]['key'] != node['semantic_key']:
            return None, 'segment_contract_key_mismatch'
        v = segment.visuals[0]; start, end = rational(v.start), rational(v.end); duration = end-start
        if (start*1000).denominator != 1 or (duration*1000).denominator != 1:
            return None, 'millisecond_seek_rounding_unresolved'
        source = next(s for s in base['sources'] if s['source_id'] == v.source_id)
        bound = params['sources']
        if len(bound) != 1 or bound[0]['sha256'] != source['sha256'] or bound[0]['size'] != source['bytes']:
            return None, 'segment_source_binding_mismatch'
        if params['mode'] != 'original' or rational(params['duration']) != duration or rational(bound[0]['source_start']) != start or rational(bound[0]['source_end']) != end:
            return None, 'segment_source_window_mismatch'
        fps = rational(params['fps'])
        actual = realized_duration(segment, deps[0]['media_contract'], fps, duration)
        entries = [e for e in plan['timeline']['realized'] if e['segment_id'] == segment.segment_id]
        if len(entries) != 1:
            return None, 'realized_segment_missing'
        clock = entries[0]
        if actual != duration or rational(clock['duration']) != duration or (clock['end_frame']-clock['start_frame'])/fps != duration:
            return None, 'measured_duration_not_exact_source_window'
        if rational(row['output_end'])-rational(row['output_start']) != duration:
            return None, 'edl_duration_not_exact_source_window'
        return (v.source_id, start, end), None
    except (ValueError, KeyError, TypeError, StopIteration, ZeroDivisionError):
        return None, 'segment_contract_unusable'


def _coverage(window, intervals):
    start, end = _span(window['start'], window['end']); merged = []
    for a, b in sorted((max(start,a), min(end,b)) for a,b in intervals if a < end and b > start):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(b, merged[-1][1])
        else:
            merged.append([a,b])
    gaps = [];cursor = start
    for a,b in merged:
        if a > cursor:gaps.append([cursor,a])
        cursor = b
    if cursor < end:gaps.append([cursor,end])
    return merged, gaps


def diagnose(spec, board, base, consumption, plan):
    validate(spec, board, base)
    results = []
    for declaration in spec['beats']:
        bid = declaration['beat_id']; intervals = {}; unknown = []; reasons = []
        if consumption['status'] == 'recorded':
            for segment in board.segments:
                if segment.beat_id != bid:continue
                rows = [r for r in consumption['segments'] if r['segment_id'] == segment.segment_id and r['beat_id'] == bid]
                eligible, reason = _eligible(segment, rows[0], plan, base) if len(rows)==1 else (None,'edl_segment_missing')
                if eligible:
                    sid,a,b = eligible;intervals.setdefault(sid,[]).append((a,b))
                else:
                    unknown.extend((v.source_id,rational(v.start),rational(v.end)) for v in segment.visuals)
                    reasons.append({'segment_id':segment.segment_id,'reason':reason})
        alternatives = []
        for group in declaration['alternatives']:
            windows = []
            for window in group:
                covered,gaps = _coverage(window,intervals.get(window['source_id'],[]))
                uncertain = consumption['status'] != 'recorded' or any(sid==window['source_id'] and a<y and b>x for sid,a,b in unknown for x,y in gaps)
                status = ('FULL' if not gaps else 'UNKNOWN' if uncertain else 'PARTIAL' if covered else 'MISSING')
                windows.append({'id':window['id'],'status':'RECORDED_WINDOW_'+status if status!='UNKNOWN' else 'UNKNOWN',
                    'covered':[[ratio(a),ratio(b)] for a,b in covered], 'gaps':[[ratio(a),ratio(b)] for a,b in gaps]})
            statuses = {w['status'] for w in windows}
            status = ('RECORDED_WINDOW_FULL' if statuses=={'RECORDED_WINDOW_FULL'} else 'UNKNOWN' if 'UNKNOWN' in statuses else
                      'RECORDED_WINDOW_MISSING' if statuses=={'RECORDED_WINDOW_MISSING'} else 'RECORDED_WINDOW_PARTIAL')
            alternatives.append({'status':status,'windows':windows})
        statuses = {g['status'] for g in alternatives}
        status = next((s for s in ['RECORDED_WINDOW_FULL','UNKNOWN','RECORDED_WINDOW_PARTIAL','RECORDED_WINDOW_MISSING'] if s in statuses))
        results.append({'beat_id':bid,'status':status,'alternatives':alternatives,'mapping_unknowns':reasons})
    return {'schema':'film-recorded-window-coverage/1','declaration':deepcopy(spec),'beats':results,'declaration_is_semantic_gold':False,
            'physical_frame_coverage':'NOT_VERIFIED','semantic_review':'NOT_RUN','media_reverified':False,
            'render_binding_status':consumption['status'],'render_binding_reason':consumption.get('reason')}
