"""Synthetic color test media with known pixel values.

Charts are generated as exact 8-bit sRGB-coded PNGs and encoded as BT.709
limited-range video; HLG/PQ variants are real zscale encodings of those SDR
values. These fixtures prove arithmetic and gating behavior only. They are not
camera footage, display calibration, or evidence of any look's quality.

Color tags are set on the frames with setparams as well as on the encoder.
On the CI runner's FFmpeg the -color_primaries/-color_trc output options alone
left the stream without those tags (observed from CI failures), while frame
properties set by setparams are carried into the encoder on every version.
"""
import shutil
import subprocess
from pathlib import Path

GRAY_STEPS = [0, 26, 51, 77, 102, 128, 153, 179, 204, 230, 255]
PATCHES = [(f'gray-{v:03d}', (v, v, v)) for v in GRAY_STEPS] + [
    ('red', (200, 30, 30)), ('green', (30, 180, 40)), ('blue', (30, 40, 200)),
    ('cyan', (30, 190, 200)), ('magenta', (190, 40, 190)), ('yellow', (220, 200, 40)),
    ('skin-light', (224, 172, 140)), ('skin-deep', (141, 85, 54)),
]
SDR_TAGS = ['-colorspace', 'bt709', '-color_primaries', 'bt709', '-color_trc', 'bt709']
UNTAGGED = 'setparams=colorspace=unknown:color_primaries=unknown:color_trc=unknown:range=unknown'
_SETPARAMS_KEYS = {'colorspace': 'colorspace', 'color_primaries': 'color_primaries',
                   'color_trc': 'color_trc', 'color_range': 'range'}


def frame_tags(**tags):
    return 'setparams=' + ':'.join(f'{_SETPARAMS_KEYS[k]}={v}' for k, v in tags.items())


def available():
    return bool(shutil.which('ffmpeg') and shutil.which('ffprobe'))


def _run(args):
    subprocess.run(['ffmpeg', '-v', 'error', '-y', *map(str, args)], check=True, timeout=120)


def image(path, blocks, size=(96, 64)):
    """Write a PNG of vertical bands: blocks=[(rgb, share), ...] left to right."""
    from PIL import Image
    width, height = size
    img = Image.new('RGB', size)
    x = 0
    for index, (rgb, share) in enumerate(blocks):
        end = width if index == len(blocks) - 1 else x + round(width * share)
        for column in range(x, end):
            for row in range(height):
                img.putpixel((column, row), tuple(rgb))
        x = end
    img.save(path)
    return Path(path)


def chart(path, columns=6, patch=16):
    from PIL import Image
    rows = -(-len(PATCHES) // columns)
    img = Image.new('RGB', (columns * patch, rows * patch), (0, 0, 0))
    for index, (_, rgb) in enumerate(PATCHES):
        x0, y0 = (index % columns) * patch, (index // columns) * patch
        for x in range(x0, x0 + patch):
            for y in range(y0, y0 + patch):
                img.putpixel((x, y), rgb)
    img.save(path)
    return Path(path)


def encode_sdr(png, out, *, seconds=1, fps=25, pix_fmt='yuv444p', full_range=False, tags=True):
    """Near-lossless BT.709 encode of an exact RGB still (qp 0, 4:4:4 by default)."""
    rng = 'pc' if full_range else 'tv'
    tagging = (frame_tags(colorspace='bt709', color_primaries='bt709', color_trc='bt709', color_range=rng)
               if tags else UNTAGGED)
    _run(['-loop', '1', '-framerate', fps, '-t', seconds, '-i', png,
          '-vf', f'scale=out_color_matrix=bt709:out_range={rng},format={pix_fmt},{tagging}',
          '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast',
          *(SDR_TAGS + ['-color_range', rng] if tags else []), out])
    return Path(out)


def encode_hdr(sdr_video, out, transfer):
    """Real HLG (arib-std-b67) or PQ (smpte2084) BT.2020 10-bit encode of SDR content."""
    if transfer not in ('arib-std-b67', 'smpte2084'):
        raise ValueError(transfer)
    _run(['-i', sdr_video, '-vf',
          f'zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=2020:t={transfer}:m=2020_ncl:r=tv,format=yuv420p10le',
          '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast',
          '-color_primaries', 'bt2020', '-color_trc', transfer, '-colorspace', 'bt2020nc', '-color_range', 'tv', out])
    return Path(out)


def retag(video, out, **tags):
    """Losslessly re-encode (qp 0, same pixel format) with different VUI color tags."""
    args = ['-i', video, '-vf', frame_tags(**tags), '-c:v', 'libx264', '-qp', '0', '-preset', 'ultrafast']
    for key, value in tags.items():
        args += ['-' + key, value]
    _run(args + [out])
    return Path(out)
