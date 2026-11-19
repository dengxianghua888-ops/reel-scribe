"""still-color-normalize against independently computed color math.

The wide-gamut test profile is built here byte by byte (ICC v2 matrix/TRC,
Adobe RGB (1998) primaries, gamma 563/256); expected sRGB values come from the
primaries with plain matrix algebra, not from LittleCMS. Synthetic images only.
"""
import hashlib
import io
from pathlib import Path
import shutil
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
np = pytest.importorskip('numpy')
Image = pytest.importorskip('PIL.Image')
ImageCms = pytest.importorskip('PIL.ImageCms')
from PIL import PngImagePlugin  # noqa: E402
import editing_runtime as rt  # noqa: E402

D65 = (0.3127, 0.3290)
D50_PCS = (0.9642, 1.0, 0.8249)
ADOBE = ((0.64, 0.33), (0.21, 0.71), (0.15, 0.06))
SRGB = ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06))
ADOBE_GAMMA = 563 / 256
BRADFORD = np.array([[0.8951, 0.2664, -0.1614], [-0.7502, 1.7135, 0.0367], [0.0389, -0.0685, 1.0296]])


def rgb_to_xyz(primaries, white=D65):
    columns = np.array([[x / y, 1.0, (1 - x - y) / y] for x, y in primaries]).T
    w = np.array([white[0] / white[1], 1.0, (1 - white[0] - white[1]) / white[1]])
    return columns * np.linalg.solve(columns, w)


def to_d50(matrix):
    src = rgb_to_xyz(SRGB).sum(axis=1)  # D65 white, Y = 1
    scale = (BRADFORD @ np.array(D50_PCS)) / (BRADFORD @ src)
    return np.linalg.inv(BRADFORD) @ np.diag(scale) @ BRADFORD @ matrix


def _pad(data):
    return data + b'\0' * (-len(data) % 4)


def icc_profile(description='reel-scribe test wide-gamut RGB'):
    """Minimal ICC v2 display profile: desc, cprt, wtpt, rXYZ/gXYZ/bXYZ (D50), rTRC/gTRC/bTRC (gamma)."""
    def s15(v):
        return struct.pack('>i', round(v * 65536))

    def xyz(values):
        return b'XYZ ' + b'\0' * 4 + b''.join(s15(v) for v in values)

    text = description.encode('ascii') + b'\0'
    desc = b'desc' + b'\0' * 4 + struct.pack('>I', len(text)) + text + struct.pack('>II', 0, 0) + struct.pack('>HB', 0, 0) + b'\0' * 67
    curve = b'curv' + b'\0' * 4 + struct.pack('>IH', 1, round(ADOBE_GAMMA * 256))
    matrix = to_d50(rgb_to_xyz(ADOBE))
    tags = [(b'desc', desc), (b'cprt', b'text' + b'\0' * 4 + b'CC0 test profile\0'), (b'wtpt', xyz(D50_PCS)),
            (b'rXYZ', xyz(matrix[:, 0])), (b'gXYZ', xyz(matrix[:, 1])), (b'bXYZ', xyz(matrix[:, 2])),
            (b'rTRC', curve), (b'gTRC', curve), (b'bTRC', curve)]
    offset = 128 + 4 + 12 * len(tags)
    table, body = struct.pack('>I', len(tags)), b''
    for signature, data in tags:
        table += signature + struct.pack('>II', offset + len(body), len(data))
        body += _pad(data)
    size = offset + len(body)
    header = (struct.pack('>I', size) + b'\0' * 4 + struct.pack('>I', 0x02100000) + b'mntrRGB XYZ ' + b'\0' * 12
              + b'acsp' + b'\0' * 24 + struct.pack('>I', 0) + b''.join(s15(v) for v in D50_PCS) + b'\0' * 48)
    assert len(header) == 128
    return header + table + body


def srgb_encode(linear):
    linear = np.clip(linear, 0, 1)
    return np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)


def expected_srgb(adobe_codes):
    linear = (np.asarray(adobe_codes) / 255.0) ** ADOBE_GAMMA
    xyz = linear @ rgb_to_xyz(ADOBE).T
    return srgb_encode(xyz @ np.linalg.inv(rgb_to_xyz(SRGB)).T) * 255


def ref(path):
    path = Path(path)
    return {'path': str(path.resolve()), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def normalize(tmp_path, path, name='run', **changes):
    request = {'operation': 'still-color-normalize', 'source': ref(path), 'target': 'srgb',
               'rendering_intent': 'relative-colorimetric', 'black_point_compensation': False,
               'untagged': 'reject', 'orientation': 'require-upright', **changes}
    return rt.run(request, tmp_path / name, rt.Tools())


def chart_codes():
    levels = [40, 90, 140, 190, 230]
    codes = np.array([[r, g, b] for r in levels for g in levels for b in levels], dtype=np.uint8)
    target = expected_srgb(codes)
    return codes[((target > 3) & (target < 252)).all(axis=1)]  # keep colors that stay inside sRGB


def image_from(codes, mode='RGB'):
    img = Image.new(mode, (len(codes), 1))
    img.putdata([tuple(int(v) for v in row) for row in codes])
    return img


def test_crafted_profile_is_a_valid_icc_profile():
    profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile()))
    assert ImageCms.getProfileDescription(profile).strip() == 'reel-scribe test wide-gamut RGB'
    assert profile.profile.xcolor_space == 'RGB ' and profile.profile.device_class == 'mntr'


def test_wide_gamut_profile_converts_like_independent_matrix_math(tmp_path):
    codes = chart_codes()
    assert len(codes) > 40
    path = tmp_path / 'wide.png'
    image_from(codes).save(path, icc_profile=icc_profile())
    receipt = normalize(tmp_path, path)
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    result = receipt['result']
    assert result['source_color']['kind'] == 'embedded-icc'
    assert result['source_color']['icc']['description'] == 'reel-scribe test wide-gamut RGB'
    out = np.asarray(Image.open(result['output']['path']).convert('RGB'), dtype=float)[0]
    error = np.abs(out - expected_srgb(codes))
    assert error.max() <= 2.0 and error.mean() < 0.6
    assert result['code_value_change']['max'] >= 10  # a real conversion, not a relabel
    with Image.open(result['output']['path']) as written:
        assert written.format == 'PNG' and 'icc_profile' not in written.info and not written.getexif()


def test_srgb_profile_is_close_to_identity_on_jpeg(tmp_path):
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile('sRGB')).tobytes()
    path = tmp_path / 'srgb.jpg'
    Image.fromarray(np.random.default_rng(2).integers(0, 256, (32, 48, 3), dtype=np.uint8)).save(path, icc_profile=srgb, quality=95)
    receipt = normalize(tmp_path, path)
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    assert receipt['result']['code_value_change']['max'] <= 1
    decoded = np.asarray(Image.open(path).convert('RGB'), dtype=int)
    out = np.asarray(Image.open(receipt['result']['output']['path']), dtype=int)
    assert np.abs(out - decoded).max() <= 1


def test_untagged_images_follow_the_explicit_policy(tmp_path):
    codes = np.random.default_rng(3).integers(0, 256, (20, 3))
    plain = tmp_path / 'plain.png'
    image_from(codes).save(plain)
    refused = normalize(tmp_path, plain, 'reject')
    assert refused['status'] == 'FAILED' and 'STILL_NORMALIZE_UNTAGGED_REJECTED' in refused['error']
    declared = normalize(tmp_path, plain, 'declared', untagged='assume-srgb')
    assert declared['status'] == 'SUCCEEDED', declared.get('error')
    assert declared['result']['source_color']['kind'] == 'caller-declared-srgb'
    out = np.asarray(Image.open(declared['result']['output']['path']), dtype=int)[0]
    assert np.array_equal(out, codes)
    chunk = PngImagePlugin.PngInfo()
    chunk.add(b'sRGB', b'\x00')
    tagged = tmp_path / 'srgb-chunk.png'
    image_from(codes).save(tagged, pnginfo=chunk)
    ok = normalize(tmp_path, tagged, 'chunk')
    assert ok['status'] == 'SUCCEEDED' and ok['result']['source_color']['kind'] == 'png-srgb-chunk'
    gamma = PngImagePlugin.PngInfo()
    gamma.add(b'gAMA', struct.pack('>I', 55000))
    gamma_path = tmp_path / 'gamma.png'
    image_from(codes).save(gamma_path, pnginfo=gamma)
    bad = normalize(tmp_path, gamma_path, 'gamma', untagged='assume-srgb')
    assert bad['status'] == 'FAILED' and 'STILL_NORMALIZE_PNG_COLOR_CHUNKS_UNSUPPORTED' in bad['error']


def test_ambiguous_or_mismatched_color_is_refused(tmp_path):
    cmyk = tmp_path / 'cmyk.jpg'
    Image.new('CMYK', (8, 8), (10, 20, 30, 40)).save(cmyk)
    receipt = normalize(tmp_path, cmyk, 'cmyk', untagged='assume-srgb')
    assert receipt['status'] == 'FAILED' and 'STILL_NORMALIZE_CMYK_PROFILE_REQUIRED' in receipt['error']
    gray = tmp_path / 'gray.png'
    Image.new('L', (8, 8), 128).save(gray, icc_profile=icc_profile())
    receipt = normalize(tmp_path, gray, 'gray')
    assert receipt['status'] == 'FAILED' and 'STILL_NORMALIZE_PROFILE_MODE_MISMATCH' in receipt['error']
    broken = tmp_path / 'broken.png'
    Image.new('RGB', (8, 8)).save(broken, icc_profile=b'not an icc profile at all' * 8)
    receipt = normalize(tmp_path, broken, 'broken')
    assert receipt['status'] == 'FAILED' and 'STILL_NORMALIZE_ICC_INVALID' in receipt['error']


@pytest.mark.parametrize('changes,error', [
    ({'target': 'display-p3'}, 'STILL_NORMALIZE_TARGET_UNSUPPORTED'),
    ({'rendering_intent': 'saturation'}, 'STILL_NORMALIZE_INTENT_UNSUPPORTED'),
    ({'black_point_compensation': 'yes'}, 'STILL_NORMALIZE_BPC_FLAG_REQUIRED'),
    ({'untagged': 'guess'}, 'STILL_NORMALIZE_UNTAGGED_POLICY_REQUIRED'),
    ({'orientation': 'auto'}, 'STILL_NORMALIZE_ORIENTATION_POLICY_REQUIRED'),
    ({'extra': 1}, 'UNKNOWN_FIELDS'),
])
def test_request_validation(tmp_path, changes, error):
    path = tmp_path / 'x.png'
    Image.new('RGB', (4, 4)).save(path)
    receipt = normalize(tmp_path, path, **changes)
    assert receipt['status'] == 'FAILED' and error in receipt['error']
    assert not (tmp_path / 'run' / 'normalized.png').exists()


def test_exif_orientation_is_applied_only_on_request(tmp_path):
    stored = Image.new('RGB', (60, 40), (20, 20, 20))
    stored.paste((230, 30, 30), (0, 0, 20, 20))  # marker in the stored top-left corner
    exif = Image.Exif()
    exif[274] = 6  # display = stored rotated 90 degrees clockwise
    path = tmp_path / 'rotated.jpg'
    stored.save(path, exif=exif.tobytes(), quality=95)
    refused = normalize(tmp_path, path, 'upright', untagged='assume-srgb')
    assert refused['status'] == 'FAILED' and 'STILL_ORIENTATION_REQUIRES_NORMALIZATION' in refused['error']
    applied = normalize(tmp_path, path, 'apply', untagged='assume-srgb', orientation='apply')
    assert applied['status'] == 'SUCCEEDED', applied.get('error')
    assert applied['result']['orientation'] == {'exif': 6, 'applied': True}
    out = np.asarray(Image.open(applied['result']['output']['path']), dtype=int)
    assert out.shape[:2] == (60, 40)  # width and height swapped
    assert out[10, 30, 0] > 180 and out[10, 30, 1] < 80  # marker now in the displayed top-right corner


def _png16(path, width=8, height=2):
    """A real 16-bit RGB PNG (Pillow would decode it as an 8-bit RGB image)."""
    import zlib
    rows = b''.join(b'\0' + b''.join(struct.pack('>HHH', 65535 * x // (width - 1), 1234, 40000) for x in range(width))
                    for _ in range(height))

    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    Path(path).write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 16, 2, 0, 0, 0))
                           + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def test_sixteen_bit_png_is_refused_not_truncated(tmp_path):
    path = tmp_path / 'deep.png'
    _png16(path)
    assert Image.open(path).mode == 'RGB'  # the decoded mode alone would hide the 16-bit encoding
    receipt = normalize(tmp_path, path, untagged='assume-srgb')
    assert receipt['status'] == 'FAILED' and 'STILL_NORMALIZE_BIT_DEPTH_UNSUPPORTED: 16-bit PNG' in receipt['error']
    assert not (tmp_path / 'run' / 'normalized.png').exists()


@pytest.mark.parametrize('mode,key,pixel', [('RGB', (255, 0, 255), (40, 90, 140)), ('L', 7, 120)])
def test_png_color_key_transparency_becomes_alpha(tmp_path, mode, key, pixel):
    img = Image.new(mode, (4, 2), pixel)
    img.putpixel((0, 0), key)
    path = tmp_path / f'key-{mode}.png'
    img.save(path, transparency=key)
    receipt = normalize(tmp_path, path, mode, untagged='assume-srgb')
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    out = np.asarray(Image.open(receipt['result']['output']['path']))
    assert receipt['result']['output']['mode'] == 'RGBA' and receipt['result']['alpha'] == 'copied unchanged'
    assert out[0, 0, 3] == 0 and (out[..., 3].reshape(-1)[1:] == 255).all()
    expected = pixel if mode == 'RGB' else (pixel,) * 3
    assert tuple(out[1, 1, :3]) == expected


def test_alpha_is_copied_unchanged(tmp_path):
    codes = chart_codes()[:30]
    rgba = np.concatenate([codes, np.arange(0, 240, 8, dtype=np.uint8)[:len(codes), None]], axis=1)
    path = tmp_path / 'alpha.png'
    image_from(rgba, 'RGBA').save(path, icc_profile=icc_profile())
    receipt = normalize(tmp_path, path)
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    out = np.asarray(Image.open(receipt['result']['output']['path']))
    assert receipt['result']['output']['mode'] == 'RGBA' and np.array_equal(out[0, :, 3], rgba[:, 3])


@pytest.mark.skipif(not (shutil.which('ffmpeg') and shutil.which('ffprobe')), reason='FFmpeg required')
def test_normalized_still_runs_through_the_srgb_color_chain(tmp_path):
    path = tmp_path / 'wide.png'
    image_from(np.repeat(chart_codes()[:8], 8, axis=0)).resize((64, 32), Image.NEAREST).save(path, icc_profile=icc_profile())
    receipt = normalize(tmp_path, path)
    assert receipt['status'] == 'SUCCEEDED', receipt.get('error')
    still = {'operation': 'still-image-render', 'source': ref(receipt['result']['output']['path']), 'frames': 12,
             'fps': '24', 'width': 64, 'height': 32, 'interpolation': 'linear', 'background_rgb': [0, 0, 0],
             'crop_keyframes': [{'frame': 0, 'rect': [0, 0, 64, 32]}, {'frame': 11, 'rect': [0, 0, 64, 32]}],
             'allow_upscale': False, 'input_color': 'srgb'}
    rendered = rt.run(still, tmp_path / 'still', rt.Tools())
    assert rendered['status'] == 'SUCCEEDED', rendered.get('error')
    scan = {'operation': 'color-profile-scan', 'source': ref(rendered['result']['video']['path']), 'start': 0,
            'end': 0.5, 'samples': {'mode': 'times', 'times': [0.25]}, 'analysis_size': [32, 16],
            'input_color': {'space': 'srgb-sdr', 'range': 'limited', 'basis': 'verified-metadata'},
            'palette_colors': 2, 'max_samples': 1}
    measured = rt.run(scan, tmp_path / 'scan', rt.Tools())
    assert measured['status'] == 'SUCCEEDED', measured.get('error')
    assert measured['result']['stream']['observed_tags']['color_transfer'] == 'iec61966-2-1'
