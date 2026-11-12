"""Explicit source audio trim, gain and fade envelopes; no sound selection."""
import wave

def envelope(request,directory,tools):
    from editing_runtime import exact_keys,source,span,number,require,sha256,write_json,audio_intersection,windowed_mix_clock
    keys=['operation','source','start','end','sample_rate','channels','gain_db','fade_in','fade_out','curve']
    exact_keys(request,keys,keys);asset=source(request['source']);media=tools.probe(asset['path'])
    require(any(s['codec_type']=='audio' for s in media['streams']),'NO_AUDIO')
    a,b=span(request['start'],request['end'],media['duration'])
    audio_clock=windowed_mix_clock(tools,asset['path'],media,b,kind='audio',start=a,playback=True)
    audio_intersection(audio_clock,a,b,require_full=True,playback=True)
    rate=request['sample_rate'];channels=request['channels']
    require(type(rate) is int and rate in [16000,24000,44100,48000],'SAMPLE_RATE_INVALID')
    require(type(channels) is int and channels in [1,2],'CHANNELS_INVALID')
    gain=number(request['gain_db'],'gain_db');require(-120<=gain<=24,'GAIN_OUT_OF_RANGE')
    fi=number(request['fade_in'],'fade_in',0);fo=number(request['fade_out'],'fade_out',0)
    require(fi+fo<=b-a+1e-9,'FADES_EXCEED_INTERVAL')
    curve=request['curve'];require(curve in ['tri','qsin'],'FADE_CURVE_UNSUPPORTED')
    # Work at explicit output sample boundaries and report rounding. Never pad missing source audio.
    count=round((b-a)*rate);ni=round(fi*rate);no=round(fo*rate)
    require(count>0 and ni+no<=count,'SAMPLE_QUANTIZATION_INVALID')
    require(fi==0 or ni>0,'SUBSAMPLE_FADE');require(fo==0 or no>0,'SUBSAMPLE_FADE')
    filters=[f'atrim=start={a}:end={b}',f'asetpts=PTS-{a}/TB',f'aresample={rate}:async=1:first_pts=0',
             f'aformat=channel_layouts={"mono" if channels==1 else "stereo"}',f'atrim=end_sample={count}',f'volume={gain}dB']
    if ni:filters.append(f'afade=t=in:ss=0:ns={ni}:curve={curve}')
    if no:filters.append(f'afade=t=out:ss={count-no}:ns={no}:curve={curve}')
    output=directory/'enveloped.wav'
    tools.ff(['-copyts','-i',asset['path'],'-map','0:a:0','-af',','.join(filters),'-ar',str(rate),'-ac',str(channels),'-c:a','pcm_s16le',str(output)])
    with wave.open(str(output),'rb') as wav:
        frames=wav.getnframes();actual_rate=wav.getframerate();actual_channels=wav.getnchannels()
    require(frames==count,'AUDIO_COVERAGE_INCOMPLETE: expected explicit sample count; no padding applied')
    require(actual_rate==rate and actual_channels==channels,'AUDIO_FORMAT_MISMATCH')
    result={'schema':'audio-envelope/1','source':asset,'source_interval':[a,b],'audio':{'path':str(output),'sha256':sha256(output)},
        'sample_rate':rate,'channels':channels,'samples':frames,'duration':frames/rate,'gain_db':gain,'selected_audio_clock':audio_clock,
        'fade_in_samples':ni,'fade_out_samples':no,'curve':curve,'duration_quantization_seconds':frames/rate-(b-a),
        'scope':'Explicit gain/fades and trim only. No denoise, loudness normalization, dialogue protection, sound-role inference or listening acceptance.',
        'provenance':'derived audio; retain this receipt to map output sample zero to declared source start; resampling/decoder timing may need independent calibration',
        'source_audio_evidence':'NOT_GRANTED_BY_ENVELOPE'}
    write_json(directory/'audio-envelope.json',result);return result


def envelope_sample_count(seconds, error='ENVELOPE_PLACEMENT_NOT_SAMPLE_ALIGNED'):
    """Accept only integral samples, allowing at most two float representation ULPs."""
    import math
    from fractions import Fraction
    from editing_runtime import require
    value=Fraction(str(seconds))*48000
    if value.denominator==1:
        return int(value)
    number=float(value)
    require(math.isfinite(number),error)
    nearest=round(number)
    # This is numerical representation tolerance, not an audible time rounding policy.
    require(abs(value-nearest)<=min(Fraction(1,1000000),Fraction.from_float(2*math.ulp(number))),error)
    return nearest


def validate_work_envelope(value, duration):
    from editing_runtime import exact_keys, require
    keys=['sample_rate','fade_in_samples','fade_out_samples','curve']
    exact_keys(value,keys,keys)
    require(type(value['sample_rate']) is int and value['sample_rate']==48000,'ENVELOPE_SAMPLE_RATE_INVALID')
    for key in keys[1:3]:
        require(type(value[key]) is int and value[key]>=0,'ENVELOPE_SAMPLES_INVALID')
    count=envelope_sample_count(duration,'ENVELOPE_SOURCE_WINDOW_NOT_SAMPLE_ALIGNED')
    require(count>0,'ENVELOPE_SOURCE_WINDOW_NOT_SAMPLE_ALIGNED')
    require(value['fade_in_samples']+value['fade_out_samples']<=count,'FADES_EXCEED_INTERVAL')
    require(value['curve'] in ('tri','qsin'),'FADE_CURVE_UNSUPPORTED')
    return int(count)


def work_envelope_filters(value, count):
    fi=value['fade_in_samples'];fo=value['fade_out_samples'];curve=value['curve']
    return ((f',afade=t=in:ss=0:ns={fi}:curve={curve}' if fi else '')+
            (f',afade=t=out:ss={count-fo}:ns={fo}:curve={curve}' if fo else ''))
