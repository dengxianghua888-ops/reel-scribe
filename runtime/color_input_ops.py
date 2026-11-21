"""Explicit HDR (HLG or PQ, BT.2020) to BT.709 SDR input transform.

The caller declares what the source is and chooses the tone-mapping operator and
its peak; nothing here guesses the source type or picks an operator. The chain is
zscale linearize (nominal peak luminance npl) -> BT.709 primaries in float ->
FFmpeg tonemap -> BT.709 transfer and matrix, limited range. The report measures
the source on sampled frames (linear peak, share above SDR reference white, share
outside the BT.709 gamut) so the caller can judge the chosen peak; it does not
judge the look. Dolby Vision enhancement data is ignored: only the base layer is read.
"""
SCHEMA = 'color-input-transform/1'
TRANSFERS = {'hlg': 'arib-std-b67', 'pq': 'smpte2084'}
OPERATORS = ('clip', 'mobius', 'hable', 'reinhard', 'linear', 'gamma')
OUTPUT_FORMATS = ('yuv420p', 'yuv420p10le')
HDR_PIXEL_FORMATS = {'yuv420p', 'yuv422p', 'yuv444p', 'yuv420p10le', 'yuv422p10le', 'yuv444p10le'}
UNKNOWN = (None, 'unknown', 'unspecified')
MAX_FRAMES = 16
ANALYSIS_WIDTH = 256
PEAK_WARNING_RATIO = 2.0
ABOVE_WHITE = 1.01  # 1% over SDR reference white: beyond 10-bit quantization of white itself
BELOW_GAMUT = -0.01  # a channel 1% of white below zero: beyond quantization and chroma noise


def _r(value, digits=4):
    return round(float(value), digits)


def _validate_stream(video, declared):
    from editing_runtime import exact_keys, require
    exact_keys(declared, ['transfer', 'range', 'basis'], ['transfer', 'range', 'basis'])
    require(declared['transfer'] in TRANSFERS, 'COLOR_INPUT_TRANSFER_UNSUPPORTED')
    require(declared['range'] in ('limited', 'full'), 'COLOR_INPUT_RANGE_REQUIRED')
    require(declared['basis'] in ('verified-metadata', 'caller-declared'), 'COLOR_INPUT_BASIS_REQUIRED')
    require(video.get('pix_fmt') in HDR_PIXEL_FORMATS, 'COLOR_INPUT_PIXEL_FORMAT_UNSUPPORTED: %s' % video.get('pix_fmt'))
    expected = {'color_transfer': TRANSFERS[declared['transfer']], 'color_primaries': 'bt2020',
                'color_space': 'bt2020nc', 'color_range': 'tv' if declared['range'] == 'limited' else 'pc'}
    observed = {key: video.get(key) for key in expected}
    for key, value in expected.items():
        require(observed[key] in UNKNOWN or observed[key] == value, 'COLOR_INPUT_METADATA_CONFLICT: %s=%s' % (key, observed[key]))
        if declared['basis'] == 'verified-metadata':
            require(observed[key] == value, 'COLOR_INPUT_METADATA_REQUIRED: ' + key)
    return {'pix_fmt': video.get('pix_fmt'), 'observed_tags': observed,
            'unobserved_tags': sorted(k for k, v in observed.items() if v in UNKNOWN)}


def _tonemap(value):
    from editing_runtime import exact_keys, require, number
    exact_keys(value, ['operator', 'peak_nits', 'desat', 'param'], ['operator', 'desat'])
    require(value['operator'] in OPERATORS, 'COLOR_INPUT_OPERATOR_UNSUPPORTED')
    desat = number(value['desat'], 'desat', 0)
    require(desat <= 10, 'COLOR_INPUT_DESAT_OUT_OF_RANGE')
    result = {'operator': value['operator'], 'desat': desat}
    if value['operator'] == 'clip':
        require('peak_nits' not in value and 'param' not in value, 'COLOR_INPUT_CLIP_TAKES_NO_PEAK_OR_PARAM')
    else:
        # The peak decides where highlights land; FFmpeg's default comes from metadata or a nominal value.
        require('peak_nits' in value, 'COLOR_INPUT_PEAK_REQUIRED: %s' % value['operator'])
        peak = number(value['peak_nits'], 'peak_nits', 0)
        require(50 <= peak <= 10000, 'COLOR_INPUT_PEAK_OUT_OF_RANGE')
        result['peak_nits'] = peak
    if 'param' in value:
        require(value['operator'] in ('mobius', 'reinhard', 'linear', 'gamma'), 'COLOR_INPUT_PARAM_UNSUPPORTED')
        result['param'] = number(value['param'], 'param')
    return result


def _filter(declared, tonemap, npl, out_fmt):
    rin = 'tv' if declared['range'] == 'limited' else 'full'
    options = 'tonemap=%s:desat=%g' % (tonemap['operator'], tonemap['desat'])
    if 'peak_nits' in tonemap:
        options += ':peak=%g' % (tonemap['peak_nits'] / npl)
    if 'param' in tonemap:
        options += ':param=%g' % tonemap['param']
    return (f"zscale=tin={TRANSFERS[declared['transfer']]}:pin=2020:min=2020_ncl:rin={rin}:t=linear:npl={npl:g},"
            f"format=gbrpf32le,zscale=p=709,{options},zscale=t=709:m=709:r=tv,format={out_fmt},"
            f"setparams=colorspace=bt709:color_primaries=bt709:color_trc=bt709:range=tv")


def _linear_frames(path, frames, declared, npl, width, height, tools):
    """Sampled frames as linear BT.709-primaries float RGB (1.0 = npl nits), before tone mapping."""
    import subprocess
    from editing_runtime import require
    from color_numerics import numpy
    np = numpy()
    rin = 'tv' if declared['range'] == 'limited' else 'full'
    picks = '+'.join('eq(n,%d)' % f for f in frames)
    vf = (f"select='{picks}',zscale=w={width}:h={height}:f=point:tin={TRANSFERS[declared['transfer']]}:pin=2020:"
          f"min=2020_ncl:rin={rin}:t=linear:npl={npl:g},format=gbrpf32le,zscale=p=709,format=gbrpf32le")
    raw = subprocess.run([tools.binary('ffmpeg'), '-v', 'error', '-i', str(path), '-vf', vf, '-fps_mode', 'passthrough',
                          '-f', 'rawvideo', '-pix_fmt', 'gbrpf32le', '-'], capture_output=True, check=True, timeout=600).stdout
    size = width * height
    require(len(raw) == size * 3 * 4 * len(frames), 'COLOR_INPUT_DECODE_INCOMPLETE')
    planes = np.frombuffer(raw, dtype='<f4').reshape(len(frames), 3, size)  # planar G, B, R
    return np.stack([planes[:, 2], planes[:, 0], planes[:, 1]], axis=-1).reshape(-1, 3).astype(np.float64)


def transform(request, directory, tools):
    from editing_runtime import exact_keys, require, source, write_json, sha256, number
    from color_ops import frame_clock
    from color_numerics import numpy
    fields = ['operation', 'source', 'input', 'nominal_peak_nits', 'tonemap', 'output_pix_fmt', 'sample_frames']
    exact_keys(request, fields, fields)
    np = numpy()
    asset = source(request['source'])
    media = tools.probe(asset['path'])
    videos = [s for s in media['streams'] if s.get('codec_type') == 'video']
    require(videos, 'VIDEO_STREAM_REQUIRED')
    stream = _validate_stream(videos[0], request['input'])
    npl = number(request['nominal_peak_nits'], 'nominal_peak_nits', 0)
    require(50 <= npl <= 10000, 'COLOR_INPUT_NOMINAL_PEAK_OUT_OF_RANGE')
    tonemap = _tonemap(request['tonemap'])
    out_fmt = request['output_pix_fmt']
    require(out_fmt in OUTPUT_FORMATS, 'COLOR_INPUT_OUTPUT_FORMAT_UNSUPPORTED')
    clock = frame_clock(asset['path'], tools)
    frames = request['sample_frames']
    require(isinstance(frames, list) and 1 <= len(frames) <= MAX_FRAMES and all(type(f) is int for f in frames)
            and len(set(frames)) == len(frames) and all(0 <= f < len(clock) for f in frames), 'COLOR_INPUT_SAMPLE_FRAMES_INVALID')
    frames = sorted(frames)
    width = min(ANALYSIS_WIDTH, int(videos[0]['width']))
    height = max(2, round(width * int(videos[0]['height']) / int(videos[0]['width']) / 2) * 2)
    linear = _linear_frames(asset['path'], frames, request['input'], npl, width, height, tools)
    luminance = np.clip(linear, 0.0, None) @ np.array([0.2126, 0.7152, 0.0722]) * npl
    measured = {'peak_nits_max': _r(luminance.max(), 2), 'peak_nits_p999': _r(np.percentile(luminance, 99.9), 2),
                'peak_nits_p99': _r(np.percentile(luminance, 99), 2),
                'above_sdr_white_fraction': _r(np.mean(linear.max(axis=1) > ABOVE_WHITE), 6),
                'outside_bt709_gamut_fraction': _r(np.mean(linear.min(axis=1) < BELOW_GAMUT), 6),
                'basis': 'sampled frames, point-sampled at %dx%d, linear BT.709 primaries after zscale (1.0 = %g nits)'
                         % (width, height, npl)}
    warnings = []
    if 'peak_nits' in tonemap and measured['peak_nits_max'] > 0:
        ratio = tonemap['peak_nits'] / measured['peak_nits_max']
        if ratio > PEAK_WARNING_RATIO:
            warnings.append('peak_nits is %.1fx the measured sample peak: midtones will be darker than needed' % ratio)
        elif ratio < 1 / PEAK_WARNING_RATIO:
            warnings.append('peak_nits is %.2fx the measured sample peak: brighter highlights will clip' % ratio)
    if tonemap['operator'] == 'clip' and measured['above_sdr_white_fraction'] > 0:
        warnings.append('clip operator: %.2f%% of sampled pixels are above SDR white and will clip'
                        % (100 * measured['above_sdr_white_fraction']))
    vf = _filter(request['input'], tonemap, npl, out_fmt)
    tools.ff(['-i', asset['path'], '-vf', vf, '-map', '0:v:0', '-map', '0:a?', '-fps_mode', 'passthrough',
              '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-c:a', 'copy', '-colorspace', 'bt709',
              '-color_trc', 'bt709', '-color_primaries', 'bt709', '-color_range', 'tv', '-movflags', '+faststart',
              'sdr.mp4'], cwd=directory)
    output = directory / 'sdr.mp4'
    out_video = next(s for s in tools.probe(str(output))['streams'] if s.get('codec_type') == 'video')
    tags = {k: out_video.get(k) for k in ('color_transfer', 'color_primaries', 'color_space', 'color_range')}
    require(tags == {'color_transfer': 'bt709', 'color_primaries': 'bt709', 'color_space': 'bt709', 'color_range': 'tv'},
            'COLOR_INPUT_OUTPUT_TAGS_UNEXPECTED: %s' % tags)
    out_frames = len(frame_clock(str(output), tools))
    require(out_frames == len(clock), 'COLOR_INPUT_FRAME_COUNT_CHANGED: %d -> %d' % (len(clock), out_frames))
    source(request['source'])  # bytes must still match after decoding
    result = {'schema': SCHEMA, 'source': asset, 'stream': stream, 'input': request['input'],
              'nominal_peak_nits': npl, 'tonemap': tonemap, 'filter': vf,
              'video': {'path': str(output), 'sha256': sha256(output), 'pix_fmt': out_video.get('pix_fmt'),
                        'frames': out_frames, 'tags': tags},
              'measured_source': measured, 'warnings': warnings,
              'output_interpretation': {'space': 'bt709-sdr', 'range': 'limited', 'basis': 'verified-metadata'},
              'aesthetic_judgement': 'NOT_PROVIDED',
              'limits': ['The operator and peak are the caller\'s choice; a different operator gives a different picture.',
                         'Measurements cover the sampled frames only.',
                         'Dolby Vision RPU and HDR10+ dynamic metadata are not read; only the base layer is converted.',
                         'Colors outside BT.709 are clipped after conversion; outside_bt709_gamut_fraction reports how many.']}
    write_json(directory / 'color-input-transform.json', result)
    return result
