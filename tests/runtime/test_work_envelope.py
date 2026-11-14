"""Explicit sample envelopes; no listening/semantic claims."""
import copy
from fractions import Fraction
import pytest
from test_local_undo import case, commit, state, request, run, audio_case
from audio_ops import validate_work_envelope, work_envelope_filters
import work_ops
import shared_timeline

ENV={'sample_rate':48000,'fade_in_samples':24000,'fade_out_samples':24000,'curve':'tri'}

@pytest.mark.parametrize('key,value', [('sample_rate',True),('sample_rate',44100),('fade_in_samples',True),('fade_out_samples',-1),('fade_in_samples',float('nan')),('curve','log'),('fade_in_samples',96001)])
def test_invalid(key,value):
    e={**ENV,key:value}
    with pytest.raises((ValueError,TypeError)):validate_work_envelope(e,2)


def test_clock_and_filter():
    assert validate_work_envelope(ENV,Fraction(2))==96000
    assert work_envelope_filters(ENV,96000)==',afade=t=in:ss=0:ns=24000:curve=tri,afade=t=out:ss=72000:ns=24000:curve=tri'
    with pytest.raises(ValueError):validate_work_envelope(ENV,Fraction(1,7))


def test_work_and_undo_preserve_gain(case):
    audio_case(case)
    commit(case,lambda d:d['audio_tracks']['music'].update(envelope=ENV))
    commit(case,lambda d:(d['audio_tracks']['music'].update(gain_db=-9),d['notes'].update(manual='keep')))
    q,out,tools,_=case;before=state(q)
    req=request(case,sequence=3);req['fields']=[{'kind':'audio_track','id':'music','field':'envelope'}]
    assert run(case,req)['status']=='CANDIDATE_PREPARED'
    import json
    doc=json.loads((out/'candidate.json').read_text())['document']
    assert 'envelope' not in doc['audio_tracks']['music']
    assert doc['audio_tracks']['music']['gain_db']==-9 and doc['notes']['manual']=='keep'
    assert state(q)==before


def test_shared_only_post_mix(case):
    audio_case(case)
    q,_,tools,_=case;a=state(q)['document'];b=copy.deepcopy(a)
    b['audio_tracks']['music']['envelope']=ENV
    work_ops.validate_document(b,tools)
    assert shared_timeline.compatible(a,b)
    b['audio_tracks']['music']['envelope']={**ENV,'fade_in_samples':True}
    assert not shared_timeline.compatible(a,b)

@pytest.mark.parametrize('field,value',[('start',1/96000),('offset',1/96000)])
def test_unaligned_work_rejects(case,field,value):
    audio_case(case);q,_,tools,_=case;doc=copy.deepcopy(state(q)['document'])
    doc['audio_tracks']['music']['envelope']={**ENV,'fade_out_samples':0}
    doc['audio_tracks']['music'][field]=value
    if field=='offset':doc['audio_tracks']['music']['end']=.5
    with pytest.raises(ValueError,match='ENVELOPE_'):work_ops.validate_document(doc,tools)


def test_missing_scope_rejected(case):
    audio_case(case);q,out,tools,_=case;old=state(q);doc=copy.deepcopy(old['document'])
    doc['audio_tracks']['music']['envelope']=ENV
    from test_local_undo import scope
    sc=scope();sc['audio_ids']=[]
    with pytest.raises(ValueError):
        work_ops.timeline_revise({'operation':'timeline-revise','base_version':old['version'],
            'document':old['document'],'expected_document_sha256':old['document_sha256'],
            'candidate':doc,'scope':sc},out,tools)
    assert state(q)==old


def test_sample_numeric_representation():
    from audio_ops import envelope_sample_count
    assert envelope_sample_count(.2+.1)==14400
    assert envelope_sample_count(1/3)==16000
    for bad in (.300000001,1/96000,Fraction(10**15)+Fraction(1,96000)):
        with pytest.raises(ValueError,match='SAMPLE_ALIGNED'):
            envelope_sample_count(bad)


def test_anchor_offset_uses_frame_clock(case):
    audio_case(case);doc=copy.deepcopy(state(case[0])['document']);clip=doc['plan']['clips'][0]
    doc['plan']['clips']=[{**clip,'id':'prefix','end':.2},{**clip,'start':.2}]
    track=doc['audio_tracks']['music']
    track.update(start=0,end=.5,offset=.1,envelope={**ENV,'fade_in_samples':2400,'fade_out_samples':2400})
    _,_,tracks=work_ops.validate_document(doc,case[2])
    assert tracks[0]['output_start']==.3


def test_large_endpoint_sample_difference():
    from audio_ops import envelope_sample_count
    a=4800001/48000;b=4814401/48000
    count=envelope_sample_count(b)-envelope_sample_count(a)
    assert count==14400
    env={**ENV,'fade_in_samples':2400,'fade_out_samples':2400}
    assert validate_work_envelope(env,Fraction(count,48000))==14400
    doc={'audio_tracks':{'track':{'start':a,'end':b,'envelope':env}}}
    other=copy.deepcopy(doc);other['audio_tracks']['track']['envelope']['curve']='qsin'
    assert shared_timeline.compatible(doc,other)
