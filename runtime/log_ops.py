"""Explicit camera Log to SDR display transform through a pinned OpenColorIO built-in config.

The caller names the source's Log colorspace, how its Y'CbCr samples map to the
code values the Log curve is defined on (full or video range), the YUV matrix,
and the OCIO display and view. Nothing here guesses a camera, a range or a look.
The OCIO processor is evaluated on a cube grid over the Log code values and
applied by FFmpeg's lut3d in float. The receipt reports the bake error against
the exact processor, reads sampled frames back against the exact processor on
the decoded source, and measures how much of the source falls outside the code
value range or the display range, so the caller can check the declarations.
"""
import shutil
import tempfile
import threading
from pathlib import Path

SCHEMA = 'color-log-transform/1'
# Display -> (transfer for CIELAB comparison, output transfer tag, output interpretation space)
DISPLAYS = {'Rec.1886 Rec.709 - Display': ('bt1886', 'bt709', 'bt709-sdr'),
            'sRGB - Display': ('srgb', 'iec61966-2-1', 'srgb-sdr')}
MATRICES = {'bt2020nc': '2020_ncl', 'bt709': '709'}  # tag -> zscale matrixin
CODE_VALUES = {'full': 'full', 'video': 'limited'}  # -> zscale rangein
LOG_PIXEL_FORMATS = ('yuv420p10le', 'yuv422p10le', 'yuv444p10le', 'yuv422p12le', 'yuv444p12le')
HDR_TRANSFERS = ('arib-std-b67', 'smpte2084')
UNKNOWN = (None, 'unknown', 'unspecified')
LUT_SIZES = (33, 65)
OUTPUT_FORMATS = ('yuv420p', 'yuv420p10le')
MAX_SAMPLE_FRAMES = 8
ANALYSIS_WIDTH = 256
BAKE_POINTS = 4096
READBACK_MAX_MEDIAN_DE2000 = 2.0
WARN_FRACTION = 0.01
# Y'CbCr <-> float RGB goes through zscale (zimg): swscale clamps float RGB at 1.0, which would erase
# superwhite code values and hide a wrong code_values declaration from the measurements, and its
# float conversions changed between FFmpeg releases.


def _r(value, digits=4):
    return round(float(value), digits)


def _ocio():
    from editing_runtime import require
    try:
        import PyOpenColorIO as ocio
    except ImportError:
        ocio = None
    require(ocio is not None, 'COLOR_LOG_OCIO_REQUIRED: install the opencolorio package')
    return ocio


_OCIO_LOCK = threading.Lock()


def _config(ocio, ref, private):
    """A versioned built-in config, or a hash-bound .ocioz archive loaded from a private copy.

    Built-in configs are fixed by the OCIO release, unlike '-latest' aliases. An .ocioz archive holds
    the config and every LUT it uses in one file, so its hash binds them all; a plain .ocio file can
    reference LUTs outside itself and is refused. OCIO reads an archive's LUTs lazily, so the archive is
    copied into `private` and the copy's bytes are checked against the declared hash before loading.
    """
    from editing_runtime import require, source, sha256
    if isinstance(ref, str):
        require(ref.startswith('ocio://'), 'COLOR_LOG_CONFIG_UNSUPPORTED')
        require(ref[len('ocio://'):] in list(ocio.BuiltinConfigRegistry()), 'COLOR_LOG_CONFIG_UNSUPPORTED: %s' % ref)
        return ocio.Config.CreateFromFile(ref), {'kind': 'builtin', 'name': ref}
    require(isinstance(ref, dict), 'COLOR_LOG_CONFIG_UNSUPPORTED')
    asset = source(ref)
    require(asset['path'].endswith('.ocioz'),
            'COLOR_LOG_CONFIG_ARCHIVE_REQUIRED: a plain config can reference LUTs outside the hashed file; package it with ocioarchive')
    copy = private / 'config.ocioz'
    shutil.copyfile(asset['path'], copy)
    require(sha256(copy) == asset['sha256'], 'SOURCE_HASH_MISMATCH: %s changed while it was copied' % asset['path'])
    try:
        config = ocio.Config.CreateFromFile(str(copy))
    except Exception as exc:  # OCIO raises its own exception type for unreadable archives
        raise ValueError('COLOR_LOG_CONFIG_ARCHIVE_INVALID: %s' % exc) from exc
    return config, {'kind': 'archive', **asset}


def processor(request_ocio, colorspace, ocio=None):
    """Exact CPU processor from a Log colorspace to the requested display and view, and what built it.

    OCIO keeps one process-wide cache of LUT files keyed by their path inside the archive, so a second
    archive with another LUT under the same name would silently reuse the first one's data. The cache is
    cleared and the processor built under one lock; the CPU processor then holds its own copy of the data.
    """
    from editing_runtime import exact_keys, require
    ocio = ocio or _ocio()
    exact_keys(request_ocio, ['config', 'display', 'view'], ['config', 'display', 'view'])
    with _OCIO_LOCK, tempfile.TemporaryDirectory(prefix='reel-ocio-') as private:
        ocio.ClearAllCaches()
        config, origin = _config(ocio, request_ocio['config'], Path(private))
        space = config.getColorSpace(colorspace) if isinstance(colorspace, str) else None
        # Built-in configs mark camera spaces as the Input/ family; an archive only has to say the space is Log.
        require(space is not None and space.getEncoding() == 'log' and not space.isData()
                and (origin['kind'] == 'archive' or space.getFamily().startswith('Input/')),
                'COLOR_LOG_COLORSPACE_UNSUPPORTED: %s' % colorspace)
        display, view = request_ocio['display'], request_ocio['view']
        require(display in DISPLAYS and display in list(config.getDisplays()), 'COLOR_LOG_DISPLAY_UNSUPPORTED: %s' % display)
        require(view in list(config.getViews(display)), 'COLOR_LOG_VIEW_UNSUPPORTED: %s' % view)
        try:
            proc = config.getProcessor(colorspace, display, view, ocio.TRANSFORM_DIR_FORWARD)
            cpu = proc.getOptimizedCPUProcessor(ocio.OPTIMIZATION_LOSSLESS)
        except Exception as exc:  # e.g. a LUT missing from the archive
            raise ValueError('COLOR_LOG_PROCESSOR_UNAVAILABLE: %s' % exc) from exc
        built = {'config_origin': origin, 'version': ocio.__version__, 'config_name': config.getName(),
                 'config_cache_id': config.getCacheID(), 'processor_cache_id': proc.getCacheID()}
        ocio.ClearAllCaches()  # drop the archive's LUT data before the private copy goes
    return cpu, built


def apply_exact(cpu, rgb):
    """(N,3) code values -> display values from the exact processor (float32 internally, unclipped)."""
    from color_numerics import numpy
    np = numpy()
    values = np.ascontiguousarray(rgb, dtype=np.float32).copy()
    cpu.applyRGB(values)
    return values.astype(np.float64)


def _validate_stream(video, declared):
    from editing_runtime import exact_keys, require
    exact_keys(declared, ['colorspace', 'matrix', 'code_values'], ['colorspace', 'matrix', 'code_values'])
    require(declared['matrix'] in MATRICES, 'COLOR_LOG_MATRIX_UNSUPPORTED')
    require(declared['code_values'] in CODE_VALUES, 'COLOR_LOG_CODE_VALUES_REQUIRED')
    pix_fmt = video.get('pix_fmt')
    require(pix_fmt in LOG_PIXEL_FORMATS, 'COLOR_LOG_PIXEL_FORMAT_UNSUPPORTED: %s; Log input needs 10 or 12 bits' % pix_fmt)
    observed = {k: video.get(k) for k in ('color_space', 'color_primaries', 'color_transfer', 'color_range')}
    require(observed['color_transfer'] not in HDR_TRANSFERS,
            'COLOR_LOG_HDR_TRANSFER_CONFLICT: %s; convert HLG or PQ with color-input-transform' % observed['color_transfer'])
    require(observed['color_space'] in UNKNOWN or observed['color_space'] == declared['matrix'],
            'COLOR_LOG_MATRIX_CONFLICT: color_space=%s' % observed['color_space'])
    warnings = []
    # There is no standard tag for camera Log; files often carry bt709 or nothing. Record, do not trust.
    if observed['color_transfer'] not in UNKNOWN:
        warnings.append('source transfer tag is %s; decoded as the declared %s' % (observed['color_transfer'], declared['colorspace']))
    tagged_range = {'tv': 'video', 'pc': 'full'}.get(observed['color_range'])
    if tagged_range is not None and tagged_range != declared['code_values']:
        warnings.append('source range tag is %s; code values read as declared (%s)' % (observed['color_range'], declared['code_values']))
    return {'pix_fmt': pix_fmt, 'observed_tags': observed}, warnings


def _run_raw(command, expected, label):
    """Run an FFmpeg decode to stdout under the texture pipeline's watchdog (cancellation and progress)."""
    import subprocess
    import tempfile
    from editing_runtime import require
    from texture_ops import _spawn, _Watchdog, _size, _tail
    with tempfile.TemporaryFile() as log, tempfile.NamedTemporaryFile(suffix='.progress') as progress:
        command = command[:-1] + ['-progress', progress.name, command[-1]]
        process = _spawn(command, log, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        watchdog = _Watchdog([process], label, activity=lambda: _size(progress.name))
        try:
            raw = process.stdout.read()
            process.wait()
            watchdog.check()
        finally:
            watchdog.stop()
            process.stdout.close()
        require(process.returncode == 0, 'COLOR_LOG_DECODE_FAILED: ' + _tail(log))
    require(len(raw) == expected, 'COLOR_LOG_DECODE_INCOMPLETE: %s' % label)
    return raw


def _frames(path, frames, matrix, rng, width, height, tools, label):
    """Sampled frames as unclipped float RGB, converted at full resolution, then point-sampled."""
    from color_numerics import numpy
    np = numpy()
    picks = '+'.join('eq(n,%d)' % f for f in frames)
    vf = (f"select='{picks}',zscale=matrixin={matrix}:rangein={rng}:range=full,format=gbrpf32le,"
          f"zscale=w={width}:h={height}:filter=point,format=gbrpf32le")
    raw = _run_raw([tools.binary('ffmpeg'), '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-vf', vf,
                    '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'gbrpf32le', '-'],
                   width * height * 3 * 4 * len(frames), label)
    planes = np.frombuffer(raw, dtype='<f4').reshape(len(frames), 3, width * height)  # planar G, B, R
    return np.stack([planes[:, 2], planes[:, 0], planes[:, 1]], axis=-1).reshape(-1, 3).astype(np.float64)


def _bake(cpu, size, transfer):
    """Cube over the Log code values, clipped to the display range; bake error on a fixed point set."""
    from color_numerics import numpy, identity_table, interpolate, lab_from_rgb01, ciede2000
    np = numpy()
    grid = identity_table(size).reshape(-1, 3)
    values = apply_exact(cpu, grid)
    clipped = float(np.mean((values < -1e-6).any(axis=1) | (values > 1 + 1e-6).any(axis=1)))
    table = np.clip(values, 0.0, 1.0).reshape(size, size, size, 3)
    points = np.random.default_rng(20261121).random((BAKE_POINTS, 3))
    exact = np.clip(apply_exact(cpu, points), 0.0, 1.0)
    approx = interpolate(table, points, 'tetrahedral')
    delta = ciede2000(lab_from_rgb01(exact, transfer)[0], lab_from_rgb01(approx, transfer)[0])
    return table, {'grid_points_outside_display_range': _r(clipped, 6),
                   'bake_delta_e2000': {'median': _r(np.median(delta)), 'p95': _r(np.percentile(delta, 95)),
                                        'max': _r(delta.max()), 'points': BAKE_POINTS,
                                        'basis': 'exact OCIO processor vs tetrahedral cube interpolation, both clipped to '
                                                 '[0,1], at fixed pseudo-random Log code values'}}


def transform(request, directory, tools):
    from editing_runtime import exact_keys, require, source, write_json, sha256
    from color_ops import frame_clock
    from color_numerics import numpy, cube_text, lab_from_rgb01, ciede2000
    require(isinstance(request, dict) and (('ocio' in request) != ('lut' in request)), 'COLOR_LOG_OCIO_OR_LUT_REQUIRED')
    mode = 'ocio' if 'ocio' in request else 'lut'
    fields = ['operation', 'source', 'input', 'output_pix_fmt', 'sample_frames'] + (['ocio', 'lut_size'] if mode == 'ocio' else ['lut'])
    exact_keys(request, fields, fields)
    np = numpy()
    asset = source(request['source'])
    media = tools.probe(asset['path'])
    video = next((s for s in media['streams'] if s.get('codec_type') == 'video'), None)
    require(video is not None, 'VIDEO_STREAM_REQUIRED')
    declared = request['input']
    stream, warnings = _validate_stream(video, declared)
    if mode == 'ocio':
        ocio = _ocio()
        cpu, built = processor(request['ocio'], declared['colorspace'], ocio)
        display = request['ocio']['display']
        size = request['lut_size']
        require(type(size) is int and size in LUT_SIZES, 'COLOR_LOG_LUT_SIZE_UNSUPPORTED')
    else:
        # A vendor Log -> display cube: the vendor's documentation, not OCIO, defines what it does.
        from color_ops import verified_cube
        from color_numerics import table_from_rows
        exact_keys(request['lut'], ['cube', 'display'], ['cube', 'display'])
        require(isinstance(declared['colorspace'], str) and declared['colorspace'].strip(), 'COLOR_LOG_COLORSPACE_LABEL_REQUIRED')
        display = request['lut']['display']
        require(display in DISPLAYS, 'COLOR_LOG_DISPLAY_UNSUPPORTED: %s' % display)
        cube_ref, info, rows, payload = verified_cube(request['lut']['cube'])
        size = info['size']
        vendor_table = table_from_rows(rows, size)
    transfer, trc, space = DISPLAYS[display]
    out_fmt = request['output_pix_fmt']
    require(out_fmt in OUTPUT_FORMATS, 'COLOR_LOG_OUTPUT_FORMAT_UNSUPPORTED')
    clock = frame_clock(asset['path'], tools)
    frames = request['sample_frames']
    require(isinstance(frames, list) and 1 <= len(frames) <= MAX_SAMPLE_FRAMES and all(type(f) is int for f in frames)
            and len(set(frames)) == len(frames) and all(0 <= f < len(clock) for f in frames), 'COLOR_LOG_SAMPLE_FRAMES_INVALID')
    frames = sorted(frames)
    if mode == 'ocio':
        table, bake = _bake(cpu, size, transfer)
        (directory / 'log.cube').write_text(cube_text(table, 'color-log-transform'), encoding='utf-8')
    else:
        (directory / 'log.cube').write_bytes(payload)  # the verified bytes, under a fixed local name
    matrix, rng = MATRICES[declared['matrix']], CODE_VALUES[declared['code_values']]
    # Fixed local file name: the cube path is never interpreted as filter code.
    vf = (f"zscale=matrixin={matrix}:rangein={rng}:range=full,format=gbrpf32le,"
          f"lut3d=file=log.cube:interp=tetrahedral,"
          f"zscale=matrix=709:range=limited,format={out_fmt},"
          f"setparams=colorspace=bt709:color_primaries=bt709:color_trc={trc}:range=tv")
    tools.ff(['-i', asset['path'], '-vf', vf, '-map', '0:v:0', '-map', '0:a?', '-fps_mode', 'passthrough',
              '-c:v', 'libx264', '-crf', '18', '-preset', 'medium', '-c:a', 'copy', '-colorspace', 'bt709',
              '-color_trc', trc, '-color_primaries', 'bt709', '-color_range', 'tv', '-movflags', '+faststart',
              'sdr.mp4'], cwd=directory, timeout=3600)
    output = directory / 'sdr.mp4'
    out_video = next(s for s in tools.probe(str(output))['streams'] if s.get('codec_type') == 'video')
    tags = {k: out_video.get(k) for k in ('color_transfer', 'color_primaries', 'color_space', 'color_range')}
    require(tags == {'color_transfer': trc, 'color_primaries': 'bt709', 'color_space': 'bt709', 'color_range': 'tv'},
            'COLOR_LOG_OUTPUT_TAGS_UNEXPECTED: %s' % tags)
    out_frames = len(frame_clock(str(output), tools))
    require(out_frames == len(clock), 'COLOR_LOG_FRAME_COUNT_CHANGED: %d -> %d' % (len(clock), out_frames))
    width = min(ANALYSIS_WIDTH, int(video['width']))
    height = max(2, round(width * int(video['height']) / int(video['width']) / 2) * 2)
    codes = _frames(asset['path'], frames, matrix, rng, width, height, tools, 'source readback decode')
    decoded = _frames(str(output), frames, '709', 'limited', width, height, tools, 'output readback decode')
    # The cube's domain is [0,1]: the rendered picture saw clipped code values, so the prediction does too.
    if mode == 'ocio':
        exact = apply_exact(cpu, np.clip(codes, 0.0, 1.0))
    else:
        from color_numerics import interpolate
        exact = interpolate(vendor_table, np.clip(codes, 0.0, 1.0), 'tetrahedral')
    predicted = np.clip(exact, 0.0, 1.0)
    delta = ciede2000(lab_from_rgb01(predicted, transfer)[0], lab_from_rgb01(np.clip(decoded, 0.0, 1.0), transfer)[0])
    measured = {'code_values_outside_0_1_fraction': _r(np.mean((codes < -0.002).any(axis=1) | (codes > 1.002).any(axis=1)), 6),
                'code_value_p001': _r(np.percentile(codes, 0.1)), 'code_value_p999': _r(np.percentile(codes, 99.9)),
                'display_clipped_fraction': _r(np.mean((exact < -1e-4).any(axis=1) | (exact > 1 + 1e-4).any(axis=1)), 6),
                'basis': 'sampled frames, decoded with the declared matrix and code values, point-sampled at %dx%d' % (width, height)}
    if measured['code_values_outside_0_1_fraction'] > WARN_FRACTION:
        warnings.append('%.2f%% of sampled code values fall outside [0,1]: check code_values (full or video)'
                        % (100 * measured['code_values_outside_0_1_fraction']))
    if measured['display_clipped_fraction'] > WARN_FRACTION:
        warnings.append('%.2f%% of sampled pixels fall outside the display range for view %s and are clipped'
                        % (100 * measured['display_clipped_fraction'], request['ocio']['view']))  # never in lut mode
    readback = {'frames': frames, 'delta_e2000_median': _r(np.median(delta)), 'delta_e2000_p95': _r(np.percentile(delta, 95)),
                'max_median_delta_e2000': READBACK_MAX_MEDIAN_DE2000,
                'basis': ('exact OCIO processor' if mode == 'ocio' else 'tetrahedral interpolation of the vendor cube')
                         + ' on the decoded source frames vs the decoded output, clipped to [0,1]'}
    require(readback['delta_e2000_median'] <= READBACK_MAX_MEDIAN_DE2000, 'COLOR_LOG_READBACK_MISMATCH: %.3f' % readback['delta_e2000_median'])
    source(request['source'])  # bytes must still match after decoding
    cube = directory / 'log.cube'
    if mode == 'ocio':
        method = {'ocio': {**request['ocio'], **built},
                  'cube': {'path': str(cube), 'sha256': sha256(cube), 'size': size, **bake}}
    else:
        source(request['lut']['cube'])
        method = {'lut': {'cube': cube_ref, 'size': size, 'display': display, 'basis': 'caller-provided vendor LUT'},
                  'cube': {'path': str(cube), 'sha256': sha256(cube), 'size': size}}
    result = {'schema': SCHEMA, 'source': asset, 'stream': stream, 'input': declared, 'input_basis': 'caller-declared',
              'mode': mode, **method,
              'filter': vf,
              'video': {'path': str(output), 'sha256': sha256(output), 'pix_fmt': out_video.get('pix_fmt'),
                        'frames': out_frames, 'tags': tags},
              'measured_source': measured, 'readback': readback, 'warnings': warnings,
              'output_interpretation': {'space': space, 'range': 'limited', 'basis': 'verified-metadata'},
              'look_selection': 'CALLER_CHOSEN_VIEW' if mode == 'ocio' else 'CALLER_CHOSEN_VENDOR_LUT',
              'aesthetic_judgement': 'NOT_PROVIDED',
              'limits': ['The colorspace, code values and matrix are the caller\'s declarations; no tag identifies camera Log.',
                         'The view is the caller\'s choice; another view gives another picture.',
                         'Code values outside [0,1] are clipped at the cube; code_values_outside_0_1_fraction reports how many.',
                         'Values outside the display range are clipped; display_clipped_fraction reports how many sampled pixels.',
                         'In ocio mode the cube samples the processor (bake_delta_e2000); in lut mode the vendor cube is applied as given.',
                         'Readback covers the sampled frames only.']}
    write_json(directory / 'color-log-transform.json', result)
    return result
