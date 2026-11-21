"""Explicit film-texture effects: halation, vignette and grain, in that fixed order.

Each effect is a declared, parameterized operation that can be left out; grain is
seeded so the same request gives the same pixels. Effects run in numpy on full
resolution frames (halation and vignette in the declared display transfer's linear
light, grain on code values) and the frames are piped to FFmpeg. Readback recomputes
sampled frames from the decoded source and compares them with the decoded output.
Nothing here chooses a look or claims a texture resembles any film stock.
"""
SCHEMA = 'film-texture/1'
TRANSFERS = {'bt709-sdr': ('bt1886', 'bt709'), 'srgb-sdr': ('srgb', 'iec61966-2-1')}
EFFECTS = ('halation', 'vignette', 'grain')
MAX_READBACK_FRAMES = 4
READBACK_MAX_MEDIAN_DE2000 = 3.0
READBACK_SIGMA = 1.5
# Default swscale rounding darkened a pass-through RGB48 -> 4:2:0 round trip by ~0.006; these flags remove the bias.
SWS_FLAGS = 'accurate_rnd+full_chroma_int'
LUMA_709 = (0.2126, 0.7152, 0.0722)
# The pipe is supervised: cancellation or no completed frame for this long kills both FFmpeg processes.
STALL_TIMEOUT_SEC = 300


def _r(value, digits=4):
    return round(float(value), digits)


def _validate(effects):
    from editing_runtime import exact_keys, require, number
    require(isinstance(effects, dict) and effects and set(effects) <= set(EFFECTS), 'TEXTURE_EFFECTS_INVALID')
    result = {}
    if 'halation' in effects:
        h = effects['halation']
        exact_keys(h, ['threshold', 'radius_px', 'strength', 'tint'], ['threshold', 'radius_px', 'strength', 'tint'])
        threshold, radius, strength = number(h['threshold'], 'threshold'), number(h['radius_px'], 'radius_px'), number(h['strength'], 'strength')
        require(0.5 <= threshold <= 0.98 and 1 <= radius <= 64 and 0 < strength <= 1, 'TEXTURE_HALATION_OUT_OF_RANGE')
        tint = h['tint']
        require(isinstance(tint, list) and len(tint) == 3 and all(0 <= number(t, 'tint') <= 1 for t in tint) and max(tint) > 0,
                'TEXTURE_HALATION_TINT_INVALID')
        result['halation'] = {'threshold': threshold, 'radius_px': radius, 'strength': strength,
                              'tint': [float(t) for t in tint]}
    if 'vignette' in effects:
        v = effects['vignette']
        exact_keys(v, ['strength', 'start'], ['strength', 'start'])
        strength, start = number(v['strength'], 'strength'), number(v['start'], 'start')
        require(0 < strength <= 0.8 and 0 <= start < 1, 'TEXTURE_VIGNETTE_OUT_OF_RANGE')
        result['vignette'] = {'strength': strength, 'start': start}
    if 'grain' in effects:
        g = effects['grain']
        exact_keys(g, ['amount', 'size_px', 'mode', 'midtone_weighted', 'temporal', 'seed'],
                   ['amount', 'size_px', 'mode', 'midtone_weighted', 'temporal', 'seed'])
        amount, size = number(g['amount'], 'amount'), number(g['size_px'], 'size_px')
        require(0 < amount <= 0.08 and 0 <= size <= 4, 'TEXTURE_GRAIN_OUT_OF_RANGE')
        require(g['mode'] in ('luma', 'rgb') and g['temporal'] in ('per-frame', 'static'), 'TEXTURE_GRAIN_MODE_INVALID')
        require(type(g['midtone_weighted']) is bool, 'TEXTURE_GRAIN_MODE_INVALID')
        require(type(g['seed']) is int and 0 <= g['seed'] < 2 ** 32, 'TEXTURE_GRAIN_SEED_INVALID')
        result['grain'] = {'amount': amount, 'size_px': size, 'mode': g['mode'], 'midtone_weighted': g['midtone_weighted'],
                           'temporal': g['temporal'], 'seed': g['seed']}
    return result


def _box(values, radius, axis):
    """Box filter of width 2r+1 along an axis, edges reflected."""
    from color_numerics import numpy
    np = numpy()
    if radius <= 0:
        return values
    pad = [(0, 0)] * values.ndim
    pad[axis] = (radius + 1, radius)
    padded = np.pad(values, pad, mode='reflect')
    total = np.cumsum(padded, axis=axis)
    upper = np.take(total, range(2 * radius + 1, total.shape[axis]), axis=axis)
    lower = np.take(total, range(0, total.shape[axis] - 2 * radius - 1), axis=axis)
    return (upper - lower) / (2 * radius + 1)


def blur(values, sigma):
    """Approximate Gaussian blur: three separable box passes with r(r+1) ~ sigma^2."""
    if sigma <= 0:
        return values
    radius = max(1, round(((1 + 4 * sigma * sigma) ** 0.5 - 1) / 2))
    for axis in (0, 1):
        for _ in range(3):
            values = _box(values, radius, axis)
    return values


def apply(rgb, frame_index, effects, transfer):
    """(H,W,3) code values in [0,1] -> textured code values, deterministic for a given frame index."""
    from color_numerics import numpy, eotf, inverse_eotf
    np = numpy()
    height, width = rgb.shape[:2]
    out = rgb
    if 'halation' in effects or 'vignette' in effects:
        linear = eotf(rgb.reshape(-1, 3), transfer).reshape(rgb.shape)
        if 'halation' in effects:
            h = effects['halation']
            luma = rgb @ np.array(LUMA_709)
            ramp = np.clip((luma - h['threshold']) / max(1 - h['threshold'], 1e-6), 0, 1)
            highlights = linear * (ramp * ramp * (3 - 2 * ramp))[..., None]  # smoothstep above the threshold
            glow = blur(highlights.max(axis=2, keepdims=True), h['radius_px'] / 2)
            linear = linear + h['strength'] * glow * np.array(h['tint'])
        if 'vignette' in effects:
            v = effects['vignette']
            y, x = np.mgrid[0:height, 0:width]
            r = np.hypot((x + 0.5 - width / 2) / (width / 2), (y + 0.5 - height / 2) / (height / 2)) / np.sqrt(2)
            t = np.clip((r - v['start']) / (1 - v['start']), 0, 1)
            linear = linear * (1 - v['strength'] * t * t * (3 - 2 * t))[..., None]
        out = inverse_eotf(np.clip(linear, 0, 1).reshape(-1, 3), transfer).reshape(rgb.shape)
    if 'grain' in effects:
        g = effects['grain']
        seed = g['seed'] if g['temporal'] == 'static' else (g['seed'] + 7919 * frame_index) % 2 ** 32
        rng = np.random.default_rng(seed)
        channels = 1 if g['mode'] == 'luma' else 3
        noise = rng.standard_normal((height, width, channels))
        if g['size_px'] > 0:
            noise = blur(noise, g['size_px'] / 2)
            noise = noise / max(float(noise.std()), 1e-9)  # keep the declared amount after blurring
        noise = noise * g['amount']
        if g['midtone_weighted']:
            luma = out @ np.array(LUMA_709)
            noise = noise * (4 * luma * (1 - luma))[..., None]
        out = out + noise
    return np.clip(out, 0, 1)


def _spawn(command, log, **pipes):
    """FFmpeg in its own process group, so the watchdog can kill it and anything it started."""
    import subprocess
    from editing_runtime import SUBPROCESS_LOCK_FDS
    return subprocess.Popen(command, stderr=log, pass_fds=SUBPROCESS_LOCK_FDS.get(), start_new_session=True, **pipes)


def _kill(process):
    import os
    import signal
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


class _Watchdog:
    """Kills the processes on cancellation or when no progress is reported for STALL_TIMEOUT_SEC.

    Killing them is what unblocks a pipe read or write in the calling thread; check() then
    turns that into a cancellation or stall error instead of a decode or encode failure.
    """

    def __init__(self, processes, label):
        import threading
        import time
        from editing_runtime import RUN_CANCELLATION
        self.processes, self.label, self.timeout = processes, label, STALL_TIMEOUT_SEC
        self.cancellation = RUN_CANCELLATION.get()
        self.cancelled, self.stalled, self.finished = threading.Event(), threading.Event(), threading.Event()
        self.last = time.monotonic()
        self.thread = threading.Thread(target=self._watch, name='texture-pipe-watchdog', daemon=True)
        self.thread.start()

    def progress(self):
        import time
        self.last = time.monotonic()

    def _watch(self):
        import time
        while not self.finished.wait(0.05):
            if self.cancellation is not None and self.cancellation.is_set():
                self.cancelled.set()
            elif time.monotonic() - self.last > self.timeout:
                self.stalled.set()
            else:
                continue
            for process in self.processes:
                _kill(process)
            return

    def check(self):
        from editing_runtime import require, OperationCancelled
        # The event itself is read too: frames can finish faster than the watchdog polls.
        if self.cancelled.is_set() or (self.cancellation is not None and self.cancellation.is_set()):
            raise OperationCancelled('TEXTURE_CANCELLED: %s; partial outputs retained' % self.label)
        require(not self.stalled.is_set(), 'TEXTURE_STALLED: %s made no progress for %g s; partial outputs retained'
                % (self.label, self.timeout))

    def stop(self):
        self.finished.set()
        self.thread.join()
        for process in self.processes:
            _kill(process)
            process.wait()


def _tail(log):
    log.seek(0)
    return log.read().decode('utf-8', 'replace')[-2000:]


def _frames(path, indices, width, height, rng, tools, pix_fmt='rgb48le'):
    import subprocess
    import tempfile
    from editing_runtime import require
    from color_numerics import numpy
    np = numpy()
    picks = '+'.join('eq(n,%d)' % i for i in indices)
    vf = f"select='{picks}',scale=in_color_matrix=bt709:in_range={rng}:out_range=pc:flags={SWS_FLAGS},format={pix_fmt}"
    command = [tools.binary('ffmpeg'), '-nostdin', '-v', 'error', '-i', str(path), '-map', '0:v:0', '-vf', vf,
               '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', pix_fmt, '-']
    with tempfile.TemporaryFile() as log:
        process = _spawn(command, log, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        watchdog = _Watchdog([process], 'readback decode')
        try:
            raw = process.stdout.read()
            process.wait()
            watchdog.check()
        finally:
            watchdog.stop()
            process.stdout.close()
        require(process.returncode == 0, 'TEXTURE_READBACK_DECODE_FAILED: ' + _tail(log))
    size = width * height * 3
    require(len(raw) == size * 2 * len(indices), 'TEXTURE_READBACK_DECODE_INCOMPLETE')
    data = np.frombuffer(raw, dtype='<u2').reshape(len(indices), height, width, 3) / 65535.0
    return list(data)


def texture(request, directory, tools):
    import subprocess
    from fractions import Fraction
    from editing_runtime import exact_keys, require, source, write_json, sha256, frame_rate, ContractError
    from color_ops import frame_clock
    from color_profile_ops import _validate_stream
    from color_numerics import numpy, lab_from_rgb01, ciede2000
    np = numpy()
    fields = ['operation', 'source', 'input_color', 'effects', 'readback_frames']
    exact_keys(request, fields, fields)
    asset = source(request['source'])
    media = tools.probe(asset['path'])
    video = next((s for s in media['streams'] if s.get('codec_type') == 'video'), None)
    require(video is not None, 'VIDEO_STREAM_REQUIRED')
    stream = _validate_stream(video, request['input_color'])
    require(request['input_color']['range'] == 'limited', 'TEXTURE_LIMITED_RANGE_REQUIRED')
    effects = _validate(request['effects'])
    transfer, trc = TRANSFERS[request['input_color']['space']]
    # FFmpeg autorotates on decode, so raw frames of a rotated source would not have the coded dimensions.
    rotations = [video.get('tags', {}).get('rotate', 0)] + [s.get('rotation', 0) for s in video.get('side_data_list', [])]
    require(all(float(x) % 360 == 0 for x in rotations), 'ROTATED_TEXTURE_SOURCE_UNSUPPORTED')
    # Raw frames carry no timestamps and the encoder restamps them at one rate, so only zero-origin CFR survives.
    fps = frame_rate(video.get('avg_frame_rate'))
    require(0 < fps <= 120, 'TEXTURE_FRAME_RATE_UNSUPPORTED')
    require(frame_rate(video.get('r_frame_rate')) == fps, 'TEXTURE_CFR_REQUIRED')
    clock = frame_clock(asset['path'], tools)
    require(all(abs(t - float(Fraction(i, 1) / fps)) <= 1e-5 for i, t in enumerate(clock)), 'TEXTURE_ZERO_ORIGIN_CFR_REQUIRED')
    readback = request['readback_frames']
    require(isinstance(readback, list) and 1 <= len(readback) <= MAX_READBACK_FRAMES and all(type(f) is int for f in readback)
            and len(set(readback)) == len(readback) and all(0 <= f < len(clock) for f in readback), 'TEXTURE_READBACK_FRAMES_INVALID')
    width, height = int(video['width']), int(video['height'])
    require(width % 2 == 0 and height % 2 == 0, 'TEXTURE_EVEN_DIMENSIONS_REQUIRED')
    output = directory / 'textured.mp4'
    decode_command = [tools.binary('ffmpeg'), '-nostdin', '-v', 'error', '-i', asset['path'], '-map', '0:v:0', '-vf',
                      f'scale=in_color_matrix=bt709:in_range=tv:out_range=pc:flags={SWS_FLAGS},format=rgb48le',
                      '-fps_mode', 'passthrough', '-f', 'rawvideo', '-pix_fmt', 'rgb48le', '-']
    encode_command = [tools.binary('ffmpeg'), '-v', 'error', '-n', '-f', 'rawvideo', '-pix_fmt', 'rgb48le',
                      '-s', f'{width}x{height}', '-r', str(fps), '-i', '-', '-i', asset['path'],
                      '-map', '0:v', '-map', '1:a?', '-vf',
                      f'scale=out_color_matrix=bt709:in_range=pc:out_range=tv:flags={SWS_FLAGS},format=yuv420p,'
                      f'setparams=colorspace=bt709:color_primaries=bt709:color_trc={trc}:range=tv',
                      '-c:v', 'libx264', '-crf', '12', '-preset', 'medium', '-tune', 'grain', '-c:a', 'copy',
                      '-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', trc, '-color_range', 'tv',
                      '-movflags', '+faststart', str(output)]
    size = width * height * 3 * 2
    count = 0
    with (directory / 'decode.log').open('w+b') as decode_log, (directory / 'encode.log').open('w+b') as encode_log:
        decoder = _spawn(decode_command, decode_log, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE)
        try:
            encoder = _spawn(encode_command, encode_log, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        except BaseException:
            _kill(decoder)
            decoder.wait()
            raise
        watchdog = _Watchdog([decoder, encoder], 'texture pipeline')
        try:
            try:
                while True:
                    watchdog.check()
                    chunk = decoder.stdout.read(size)
                    watchdog.check()
                    if not chunk:
                        break
                    require(len(chunk) == size, 'TEXTURE_DECODE_INCOMPLETE')
                    frame = np.frombuffer(chunk, dtype='<u2').reshape(height, width, 3) / 65535.0
                    textured = apply(frame, count, effects, transfer)
                    watchdog.check()
                    encoder.stdin.write(np.round(textured * 65535).astype('<u2').tobytes())
                    count += 1
                    watchdog.progress()
                encoder.stdin.close()
                decoder.wait()
                encoder.wait()  # still supervised: the encoder flushes its lookahead here
                watchdog.check()
            except (BrokenPipeError, ContractError):
                watchdog.check()  # a kill by the watchdog explains the broken pipe or short read
                raise
        except BrokenPipeError as exc:
            encoder.wait()
            raise ContractError('TEXTURE_ENCODE_FAILED: ' + _tail(encode_log)) from exc
        finally:
            watchdog.stop()
            decoder.stdout.close()
            if not encoder.stdin.closed:
                try:
                    encoder.stdin.close()
                except BrokenPipeError:
                    pass
        require(decoder.returncode == 0, 'TEXTURE_DECODE_FAILED: ' + _tail(decode_log))
        require(encoder.returncode == 0, 'TEXTURE_ENCODE_FAILED: ' + _tail(encode_log))
    require(count == len(clock), 'TEXTURE_FRAME_COUNT_CHANGED: %d -> %d' % (len(clock), count))
    out_clock = frame_clock(str(output), tools)
    out_frames = len(out_clock)
    require(out_frames == count, 'TEXTURE_FRAME_COUNT_CHANGED: %d -> %d' % (count, out_frames))
    require(all(abs(t - s) <= 1e-5 for t, s in zip(out_clock, clock)), 'TEXTURE_OUTPUT_CLOCK_MISMATCH')
    indices = sorted(readback)
    sources = _frames(asset['path'], indices, width, height, 'tv', tools)
    outputs = _frames(str(output), indices, width, height, 'tv', tools)
    rows = []
    luma_weights = np.array(LUMA_709)
    for f, src, out in zip(indices, sources, outputs):
        full = apply(src, f, effects, transfer)
        # Grain cannot be compared pixel by pixel after 4:2:0 lossy coding, so the gate compares
        # lightly low-passed images; each effect's own contribution is measured separately below.
        a, b = blur(full, READBACK_SIGMA), blur(out, READBACK_SIGMA)
        delta = ciede2000(lab_from_rgb01(a.reshape(-1, 3), transfer)[0], lab_from_rgb01(b.reshape(-1, 3), transfer)[0])
        raw = ciede2000(lab_from_rgb01(full.reshape(-1, 3), transfer)[0], lab_from_rgb01(out.reshape(-1, 3), transfer)[0])
        row = {'frame': f, 'delta_e2000_median': _r(np.median(delta)), 'delta_e2000_p95': _r(np.percentile(delta, 95)),
               'unfiltered_delta_e2000_median': _r(np.median(raw))}
        for name in effects:
            without = apply(src, f, {k: v for k, v in effects.items() if k != name}, transfer)
            if name == 'grain':
                declared = (full - without) @ luma_weights
                measured = (out - without) @ luma_weights
                row['grain_luma_std'] = {'predicted': _r(declared.std(), 5), 'output': _r(measured.std(), 5),
                                         'output_minus_prediction_mean': _r(measured.mean() - declared.mean(), 5)}
            elif name == 'halation':
                row['halation_added_mean_rgb'] = {'predicted': [_r(v, 5) for v in (full - without).reshape(-1, 3).mean(axis=0)],
                                                  'output': [_r(v, 5) for v in (out - without).reshape(-1, 3).mean(axis=0)]}
            else:
                ch, cw = max(1, height // 10), max(1, width // 10)

                def ratio(img):
                    luma = img @ luma_weights
                    corners = np.mean([luma[:ch, :cw].mean(), luma[:ch, -cw:].mean(), luma[-ch:, :cw].mean(), luma[-ch:, -cw:].mean()])
                    middle = luma[height // 2 - ch // 2:height // 2 + ch // 2 + 1, width // 2 - cw // 2:width // 2 + cw // 2 + 1].mean()
                    return _r(corners / max(middle, 1e-6))
                row['corner_to_center_luma'] = {'without_vignette': ratio(without), 'predicted': ratio(full), 'output': ratio(out)}
        rows.append(row)
        require(row['delta_e2000_median'] <= READBACK_MAX_MEDIAN_DE2000, 'TEXTURE_READBACK_MISMATCH: frame %d' % f)
    source(request['source'])
    result = {'schema': SCHEMA, 'source': asset, 'stream': stream, 'input_color': request['input_color'],
              'effects': effects, 'order': [e for e in EFFECTS if e in effects],
              'video': {'path': str(output), 'sha256': sha256(output), 'frames': out_frames, 'pix_fmt': 'yuv420p',
                        'encoding': 'libx264 crf 12, tune grain, 4:2:0'},
              'readback': {'method': 'numpy recomputation of the effects on the decoded source frame vs the decoded output at full '
                                     'resolution; the gate compares both after a %.1f px Gaussian low-pass, and each effect is also '
                                     'measured as output minus the recomputation without it' % READBACK_SIGMA,
                           'max_median_delta_e2000': READBACK_MAX_MEDIAN_DE2000, 'frames': rows},
              'aesthetic_judgement': 'NOT_PROVIDED', 'film_stock_claim': 'NONE',
              'limits': ['Effects are parametric approximations, not measurements or emulations of any film stock.',
                         'Grain in rgb mode loses most chroma detail in 4:2:0 output; luma grain survives better.',
                         'Readback covers the listed frames only.']}
    write_json(directory / 'film-texture.json', result)
    return result
