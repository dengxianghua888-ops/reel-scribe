"""Actual Pillow font bytes; atomic replacement never modifies an open inode."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools/editor-adapters' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=['plan_caption_readability', 'review_caption_translation'])
def tool(request):
    return load(request.param)


@pytest.fixture
def fonts():
    pairs = [('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
              '/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf'),
             ('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
              '/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc')]
    for first, second in pairs:
        if Path(first).is_file() and Path(second).is_file():
            return Path(first).read_bytes(), Path(second).read_bytes()
    pytest.fail('Real-font regressions require the existing DejaVu or CI Noto CJK font pair')


def arguments(tool, tmp_path, fonts):
    font = tmp_path / 'font.ttf'
    font.write_bytes(fonts[0])
    row = {'id': 'one', 'text': 'iiiiiiiiiiiiiiiiiiiiiiii', 'start_frame': 0,
           'end_frame': 72, 'declared_start_sec': 0, 'declared_end_sec': 3,
           'start_delta_sec': 0, 'end_delta_sec': 0}
    source = tmp_path / 'map.json'
    source.write_text(json.dumps({'rows': [row]}))
    common = dict(font=font, font_sha256=tool.contract.digest(font), fps=24,
                  frame_end=72, minimum_size=32, maximum_size=40, output=tmp_path / 'out.json')
    if hasattr(tool, 'fit'):
        draft = tmp_path / 'draft.json'
        draft.write_text(json.dumps({'schema': 'caption-translation-draft/1', 'entries': [
            {'id': 'one', 'source_text': row['text'], 'target_text': row['text'],
             'target_language': 'zh-CN', 'context_ids': [], 'fidelity_notes': [],
             'omitted_information': []}]}))
        return SimpleNamespace(**common, source_map=source, source_sha256=tool.contract.digest(source),
                               draft=draft, draft_sha256=tool.contract.digest(draft))
    return SimpleNamespace(**common, caption_map=source, map_sha256=tool.contract.digest(source),
                           acknowledge_reflow=True)


def replace_bytes(path, payload):
    replacement = path.with_name('replacement.ttf')
    replacement.write_bytes(payload)
    os.replace(replacement, path)


def test_atomic_path_replacement_cannot_change_pinned_measurements(tool, tmp_path, fonts, monkeypatch):
    args = arguments(tool, tmp_path, fonts)
    tool.build(args)
    expected = json.loads(args.output.read_text())
    args.output = tmp_path / 'after.json'
    real_load = tool.ImageFont.truetype

    def load_with_replacement(source, *pos, **kw):
        if isinstance(source, (str, Path)) and str(source) == str(args.font):
            replace_bytes(args.font, fonts[1])
            try:
                return real_load(source, *pos, **kw)
            finally:
                replace_bytes(args.font, fonts[0])
        return real_load(source, *pos, **kw)

    monkeypatch.setattr(tool.ImageFont, 'truetype', load_with_replacement)
    tool.build(args)
    actual = json.loads(args.output.read_text())
    assert actual == expected
    assert actual['font']['sha256'] == tool.contract.digest(args.font)
    assert actual['adopted'] is False


def test_pillow_consumes_pinned_bytes_not_a_reopened_path(tool, tmp_path, fonts, monkeypatch):
    args = arguments(tool, tmp_path, fonts)
    real_load = tool.ImageFont.truetype
    captured = []

    def observing_load(source, *pos, **kw):
        assert hasattr(source, 'read'), 'Pillow must consume captured font bytes'
        position = source.tell()
        captured.append(hashlib.sha256(source.read()).hexdigest())
        source.seek(position)
        return real_load(source, *pos, **kw)

    monkeypatch.setattr(tool.ImageFont, 'truetype', observing_load)
    tool.build(args)
    assert captured and set(captured) == {args.font_sha256}


def test_persistent_font_drift_rejected(tool, tmp_path, fonts, monkeypatch):
    args = arguments(tool, tmp_path, fonts)
    real_load = tool.ImageFont.truetype

    def changing_load(source, *pos, **kw):
        font = real_load(source, *pos, **kw)
        replace_bytes(args.font, fonts[1])
        return font

    monkeypatch.setattr(tool.ImageFont, 'truetype', changing_load)
    with pytest.raises(ValueError, match='INPUT_CHANGED_DURING_READ'):
        tool.build(args)
    assert not args.output.exists()


def test_stale_font_rejected_before_pillow(tool, tmp_path, fonts, monkeypatch):
    args = arguments(tool, tmp_path, fonts)
    args.font_sha256 = '0' * 64
    monkeypatch.setattr(tool.ImageFont, 'truetype', lambda *a, **k: pytest.fail('unverified font loaded'))
    with pytest.raises(ValueError, match='STALE_INPUT'):
        tool.build(args)
    assert not args.output.exists()


def test_pinned_font_keeps_input_and_exclusive_report(tool, tmp_path, fonts):
    args = arguments(tool, tmp_path, fonts)
    tool.build(args)
    original = args.output.read_bytes()
    with pytest.raises(FileExistsError):
        tool.build(args)
    assert args.output.read_bytes() == original
    assert args.font.read_bytes() == fonts[0]


def test_substituted_font_descriptor_rejected(tool, tmp_path, fonts, monkeypatch):
    args = arguments(tool, tmp_path, fonts)
    real_open = Path.open

    def open_other(path, *pos, **kw):
        if path == args.font and (pos[0] if pos else kw.get('mode')) == 'rb':
            # The pathname keeps A while its read descriptor supplies B.
            return io.BytesIO(fonts[1])
        return real_open(path, *pos, **kw)

    monkeypatch.setattr(Path, 'open', open_other)
    with pytest.raises(ValueError, match='STALE_INPUT'):
        tool.build(args)
    with real_open(args.font, 'rb') as stream:
        assert stream.read() == fonts[0]
    assert not args.output.exists()


@pytest.mark.parametrize('payload', [b'', b'not a TrueType font'], ids=['empty', 'malformed'])
def test_pinned_invalid_font_never_publishes(tool, tmp_path, fonts, payload):
    args = arguments(tool, tmp_path, fonts)
    replace_bytes(args.font, payload)
    args.font_sha256 = tool.contract.digest(args.font)
    with pytest.raises(OSError):
        tool.build(args)
    assert not args.output.exists()


def test_font_capture_limit_is_bounded_and_exact(tmp_path, monkeypatch):
    module = load('plan_caption_readability')
    # Exercise the boundary without allocating 64 MiB for each regression.
    monkeypatch.setattr(module, 'MAX_FONT_BYTES', 32)
    requests = []

    class Read(io.BytesIO):
        def read(self, n=-1):
            requests.append(n)
            return super().read(n)

    monkeypatch.setattr(Path, 'open', lambda *a, **k: Read(b'a' * 32))
    assert module.capture_pinned_font(tmp_path / 'font', hashlib.sha256(b'a' * 32).hexdigest()) == b'a' * 32
    monkeypatch.setattr(Path, 'open', lambda *a, **k: Read(b'a' * 33))
    with pytest.raises(ValueError, match='FONT_SIZE_LIMIT'):
        module.capture_pinned_font(tmp_path / 'font', hashlib.sha256(b'a' * 33).hexdigest())
    assert requests == [33, 33]


def test_existing_direct_path_api_matches_snapshot(fonts, tmp_path):
    module = load('plan_caption_readability')
    path = tmp_path / 'font.ttf'
    path.write_bytes(fonts[0])
    assert module.load_font(path, 40).getlength('Width') == module.load_font(fonts[0], 40).getlength('Width')


def test_cjk_font_build(tool, tmp_path, fonts):
    path = Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')
    assert path.is_file(), 'Runtime/CI setup includes fonts-noto-cjk'
    args = arguments(tool, tmp_path, fonts)
    replace_bytes(args.font, path.read_bytes())
    args.font_sha256 = tool.contract.digest(args.font)
    source_path = getattr(args, 'source_map', getattr(args, 'caption_map', None))
    source = json.loads(source_path.read_text())
    source['rows'][0]['text'] = '不要删除否定词。'
    source_path.write_text(json.dumps(source))
    if hasattr(tool, 'fit'):
        args.source_sha256 = tool.contract.digest(source_path)
        draft = json.loads(args.draft.read_text())
        draft['entries'][0].update(source_text='不要删除否定词。', target_text='不要删除否定词。')
        args.draft.write_text(json.dumps(draft))
        args.draft_sha256 = tool.contract.digest(args.draft)
    else:
        args.map_sha256 = tool.contract.digest(source_path)
    tool.build(args)
    result = json.loads(args.output.read_text())
    assert result['font']['sha256'] == args.font_sha256
    assert result['font']['face_index'] == 0
    assert result['adopted'] is False


def test_font_limit_rejected_before_loading(tool, tmp_path, fonts, monkeypatch):
    args = arguments(tool, tmp_path, fonts)
    module = tool.layout if hasattr(tool, 'fit') else tool
    monkeypatch.setattr(module, 'MAX_FONT_BYTES', 8)
    monkeypatch.setattr(tool.ImageFont, 'truetype', lambda *a, **k: pytest.fail('oversized font loaded'))
    with pytest.raises(ValueError, match='FONT_SIZE_LIMIT'):
        tool.build(args)
    assert not args.output.exists()


def test_truncated_real_font_never_publishes(tool, tmp_path, fonts):
    args = arguments(tool, tmp_path, fonts)
    replace_bytes(args.font, fonts[0][:64])
    args.font_sha256 = tool.contract.digest(args.font)
    with pytest.raises(OSError):
        tool.build(args)
    assert not args.output.exists()


def test_inode_changes_after_open_do_not_change_captured_font(tool, tmp_path, fonts, monkeypatch):
    args = arguments(tool, tmp_path, fonts)
    tool.build(args)
    expected = json.loads(args.output.read_text())
    args.output = tmp_path / 'changed-inode.json'
    real_open = Path.open

    class Captured:
        def __enter__(self):
            self.stream = real_open(args.font, 'rb')
            replace_bytes(args.font, fonts[1])
            return self

        def read(self, n=-1):
            try:
                return self.stream.read(n)
            finally:
                replace_bytes(args.font, fonts[0])

        def __exit__(self, *exc):
            self.stream.close()

    def capturing_open(path, *pos, **kw):
        if path == args.font and (pos[0] if pos else kw.get('mode')) == 'rb':
            return Captured()
        return real_open(path, *pos, **kw)

    monkeypatch.setattr(Path, 'open', capturing_open)
    tool.build(args)
    assert json.loads(args.output.read_text()) == expected
