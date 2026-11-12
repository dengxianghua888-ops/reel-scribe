"""Real libass pixels on synthetic background; not real content alignment QA."""
import shutil
import subprocess
from types import SimpleNamespace
import pytest
from PIL import Image
from pydantic import ValidationError
from douyin_film_recap.config import RenderConfig
from douyin_film_recap.render import _subtitle_style, _escape_subtitle_path
from douyin_film_recap.subtitles import _split_text


def white_box(ffmpeg, srt, width, height, style):
    result = subprocess.run([ffmpeg, '-nostdin', '-v', 'error', '-f', 'lavfi',
        '-i', f'color=c=black:s={width}x{height}:r=1:d=1', '-vf',
        f"subtitles='{_escape_subtitle_path(srt)}':force_style='{style}'",
        '-frames:v', '1', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
        check=True, stdout=subprocess.PIPE)
    frame = Image.frombytes('RGB', (width, height), result.stdout)
    return frame.convert('L').point(lambda x: 255 if x > 180 else 0).getbbox()


@pytest.mark.parametrize('width,height,size,margin', [(1080, 1920, 62, 250), (540, 960, 31, 125)])
def test_real_libass_uses_output_pixel_canvas(tmp_path, width, height, size, margin):
    ffmpeg = shutil.which('ffmpeg')
    assert ffmpeg, 'Real subtitle render requires FFmpeg; do not silently skip'
    srt = tmp_path / 'captions.srt'
    srt.write_text('1\n00:00:00,000 --> 00:00:01,000\n你不能这样开车。\n比分为 21 比 20，WiFi 门铃。\n', encoding='utf-8')
    cfg = SimpleNamespace(render=RenderConfig(width=width, height=height,
        subtitle_font_size=size, subtitle_margin_v=margin))
    style = _subtitle_style(cfg)
    assert f'PlayResX={width},PlayResY={height}' in style
    box = white_box(ffmpeg, srt, width, height, style)
    assert box is not None
    left, top, right, bottom = box
    assert 0 < left < right < width
    assert height * .65 < top < bottom < height
    assert height - margin - size < bottom <= height - margin + size * .3
    assert size < bottom - top < size * 3
    legacy = ','.join(style.split(',')[2:])
    old_box = white_box(ffmpeg, srt, width, height, legacy)
    assert old_box is None or old_box[1] < height * .5


@pytest.mark.parametrize('field,value', [('subtitle_font_size', 0), ('subtitle_font_size', -1),
    ('subtitle_margin_v', -1), ('subtitle_outline', -1)])
def test_negative_or_zero_pixel_parameters_are_rejected(field, value):
    with pytest.raises(ValidationError):
        RenderConfig(**{field: value})


@pytest.mark.parametrize('field,value', [('subtitle_margin_v', 1920), ('subtitle_font_size', 1921)])
def test_style_rejects_impossible_output_canvas_values(field, value):
    cfg = SimpleNamespace(render=RenderConfig(**{field: value}))
    with pytest.raises(ValueError, match='output canvas'):
        _subtitle_style(cfg)


@pytest.mark.parametrize('text,limit', [('你不能像在光洁的柏油路上一样开车。', 16),
    ('甲乙丙丁。继续', 4), ('甲乙丙丁！', 4), ('甲乙丙丁）后续', 4)])
def test_closing_punctuation_not_stranded_when_width_permits(text, limit):
    lines = _split_text(text, limit)
    assert ''.join(lines) == text
    assert all(len(line) <= limit for line in lines)
    assert all(line[0] not in '。！，）' for line in lines)
