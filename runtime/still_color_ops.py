"""Convert a still's declared color encoding to an untagged sRGB PNG; no look, no enhancement.

The embedded ICC profile (or an explicit caller policy for untagged images) is
the only color evidence used. LittleCMS, through Pillow ImageCms, performs the
transform. EXIF orientation is applied only when the caller asks for it.
"""
import hashlib
import io

MAX_STILL_BYTES = 512 * 1024 * 1024
MAX_PIXELS = 100_000_000
# Pillow mode -> ICC data color space the embedded profile must declare.
MODES = {'RGB': 'RGB ', 'RGBA': 'RGB ', 'P': 'RGB ', 'L': 'GRAY', 'LA': 'GRAY', 'CMYK': 'CMYK'}
DEVICE_CLASSES = ('mntr', 'scnr', 'prtr', 'spac')
INTENTS = ('relative-colorimetric', 'perceptual')


def _icc_facts(profile, raw):
    from PIL import ImageCms
    core = profile.profile
    return {'description': (ImageCms.getProfileDescription(profile) or '').strip(),
            'color_space': core.xcolor_space.strip(), 'device_class': core.device_class.strip(),
            'version': round(float(core.version), 2), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}


def normalize_still(request, directory, tools):
    from editing_runtime import exact_keys, source, require, sha256, write_json, ContractError
    try:
        import numpy as np
        from PIL import Image, ImageCms, ImageOps, __version__ as pillow_version
    except ImportError as exc:
        raise ContractError('DEPENDENCY_UNAVAILABLE: Pillow with ImageCms (LittleCMS) and numpy') from exc
    keys = ['operation', 'source', 'target', 'rendering_intent', 'black_point_compensation', 'untagged', 'orientation']
    exact_keys(request, keys, keys)
    require(request['target'] == 'srgb', 'STILL_NORMALIZE_TARGET_UNSUPPORTED')
    require(request['rendering_intent'] in INTENTS, 'STILL_NORMALIZE_INTENT_UNSUPPORTED')
    require(type(request['black_point_compensation']) is bool, 'STILL_NORMALIZE_BPC_FLAG_REQUIRED')
    require(request['untagged'] in ('assume-srgb', 'reject'), 'STILL_NORMALIZE_UNTAGGED_POLICY_REQUIRED')
    require(request['orientation'] in ('apply', 'require-upright'), 'STILL_NORMALIZE_ORIENTATION_POLICY_REQUIRED')
    asset = source(request['source'])
    # Decode the same bounded buffer that was hashed, not a second path read.
    with open(asset['path'], 'rb') as stream:
        payload = stream.read(MAX_STILL_BYTES + 1)
    require(len(payload) <= MAX_STILL_BYTES, 'STILL_FILE_TOO_LARGE')
    require(hashlib.sha256(payload).hexdigest() == asset['sha256'], 'SOURCE_HASH_MISMATCH: ' + asset['path'])
    if payload[:8] == b'\x89PNG\r\n\x1a\n' and payload[12:16] == b'IHDR':
        # Pillow decodes 16-bit RGB(A) PNGs as 8-bit modes, so the encoded depth is read from IHDR.
        require(payload[24] <= 8, 'STILL_NORMALIZE_BIT_DEPTH_UNSUPPORTED: %d-bit PNG' % payload[24])
    with Image.open(io.BytesIO(payload)) as opened:
        require(opened.format in ['PNG', 'JPEG', 'WEBP'], 'STILL_FORMAT_UNSUPPORTED')
        require(getattr(opened, 'n_frames', 1) == 1, 'ANIMATED_IMAGE_UNSUPPORTED')
        require(opened.width * opened.height <= MAX_PIXELS, 'STILL_PIXEL_BUDGET_EXCEEDED')
        require(opened.mode in MODES, 'STILL_PIXEL_MODE_UNSUPPORTED: %s' % opened.mode)
        opened.load()
        source_image = {'format': opened.format, 'mode': opened.mode, 'size': list(opened.size)}
        icc = opened.info.get('icc_profile') or None
        chunks = sorted(k for k in ('gamma', 'chromaticity', 'srgb') if k in opened.info)
        orientation = opened.getexif().get(274, 1)
        require(orientation in range(1, 9), 'STILL_ORIENTATION_INVALID')
        if orientation != 1:
            require(request['orientation'] == 'apply', 'STILL_ORIENTATION_REQUIRES_NORMALIZATION')
            image = ImageOps.exif_transpose(opened)
        else:
            image = opened.copy()
    if image.mode == 'P':
        image = image.convert('RGBA' if 'transparency' in image.info else 'RGB')
    elif image.mode in ('RGB', 'L') and 'transparency' in image.info:  # PNG tRNS color key -> real alpha
        image = image.convert({'RGB': 'RGBA', 'L': 'LA'}[image.mode])
    alpha = image.getchannel('A') if image.mode in ('RGBA', 'LA') else None
    base = image.convert({'RGBA': 'RGB', 'LA': 'L'}.get(image.mode, image.mode))
    intent = request['rendering_intent']
    if icc:
        try:
            profile = ImageCms.ImageCmsProfile(io.BytesIO(icc))
        except (OSError, ImageCms.PyCMSError) as exc:
            raise ContractError('STILL_NORMALIZE_ICC_INVALID') from exc
        facts = _icc_facts(profile, icc)
        require(facts['color_space'] == MODES[base.mode].strip(), 'STILL_NORMALIZE_PROFILE_MODE_MISMATCH: %s profile on %s pixels'
                % (facts['color_space'], base.mode))
        require(facts['device_class'] in DEVICE_CLASSES, 'STILL_NORMALIZE_PROFILE_CLASS_UNSUPPORTED: ' + facts['device_class'])
        flags = ImageCms.Flags.BLACKPOINTCOMPENSATION if request['black_point_compensation'] else ImageCms.Flags.NONE
        transform = ImageCms.buildTransform(
            profile, ImageCms.createProfile('sRGB'), base.mode, 'RGB',
            renderingIntent=(ImageCms.Intent.RELATIVE_COLORIMETRIC if intent == 'relative-colorimetric'
                             else ImageCms.Intent.PERCEPTUAL), flags=flags)
        converted = ImageCms.applyTransform(base, transform)
        basis = {'kind': 'embedded-icc', 'icc': facts, 'png_color_chunks': chunks}
        engine = {'name': 'LittleCMS via Pillow ImageCms', 'littlecms': ImageCms.core.littlecms_version,
                  'pillow': pillow_version, 'rendering_intent': intent,
                  'black_point_compensation': request['black_point_compensation'],
                  'destination': 'LittleCMS built-in sRGB (IEC 61966-2-1)'}
    else:
        require(base.mode != 'CMYK', 'STILL_NORMALIZE_CMYK_PROFILE_REQUIRED')
        require('srgb' in chunks or not {'gamma', 'chromaticity'} & set(chunks),
                'STILL_NORMALIZE_PNG_COLOR_CHUNKS_UNSUPPORTED: gAMA/cHRM without an ICC profile are not interpreted')
        if 'srgb' in chunks:
            kind = 'png-srgb-chunk'
        else:
            require(request['untagged'] == 'assume-srgb', 'STILL_NORMALIZE_UNTAGGED_REJECTED')
            kind = 'caller-declared-srgb'
        converted = base.convert('RGB')
        basis = {'kind': kind, 'icc': None, 'png_color_chunks': chunks}
        engine = {'name': 'none; code values copied', 'pillow': pillow_version}
    change = None
    if base.mode in ('RGB', 'L'):
        before = np.asarray(base.convert('RGB'), dtype=np.int16)
        delta = np.abs(np.asarray(converted, dtype=np.int16) - before)
        change = {'max': int(delta.max()), 'mean': round(float(delta.mean()), 4),
                  'basis': '8-bit code values before and after, per channel'}
    if alpha is not None:
        converted.putalpha(alpha)
    converted.info = {}
    output = directory / 'normalized.png'
    converted.save(output, format='PNG', icc_profile=None)
    with Image.open(output) as check:
        require(check.format == 'PNG' and check.mode in ('RGB', 'RGBA') and not check.info.get('icc_profile')
                and not check.getexif(), 'STILL_NORMALIZE_OUTPUT_CHECK_FAILED')
        written = {'mode': check.mode, 'size': list(check.size)}
    require(sha256(asset['path']) == asset['sha256'], 'STILL_SOURCE_CHANGED_DURING_NORMALIZE')
    result = {'schema': 'still-color-normalize/1', 'source': asset, 'source_image': source_image,
              'source_color': basis, 'transform': engine,
              'orientation': {'exif': orientation, 'applied': orientation != 1},
              'alpha': 'copied unchanged' if alpha is not None else 'none',
              'code_value_change': change,
              'output': {'path': str(output), 'sha256': sha256(output), 'format': 'PNG', **written,
                         'icc_profile': None, 'color': 'sRGB (IEC 61966-2-1) code values, untagged'},
              'next_step': 'still-image-render with input_color=srgb, then color atomics with space srgb-sdr',
              'effect_review': 'NOT_RUN',
              'limits': ['8-bit output; 16-bit and float stills are refused rather than truncated.',
                         'Out-of-gamut colors follow the chosen rendering intent; nothing is enhanced or graded.',
                         'Untagged images are sRGB only by caller declaration; that is not verified color evidence.',
                         'Gray and CMYK profiles are converted by LittleCMS; this library tests RGB matrix/TRC profiles.']}
    write_json(directory / 'still-color-normalize.json', result)
    return result
