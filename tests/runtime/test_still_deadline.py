"""No media/model service: a non-consuming encoder must not hang the caller."""
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'runtime'))
import still_ops
from editing_runtime import ContractError, sha256


def test_deadline_includes_blocked_stdin_and_reaps_encoder(tmp_path, monkeypatch):
    source = tmp_path / 'source.png'
    Image.new('RGB', (256, 256), 'red').save(source)
    fake = tmp_path / 'encoder'
    pid = tmp_path / 'pid'
    fake.write_text(f'#!{sys.executable}\nimport os,time\nfrom pathlib import Path\n'
                    f'Path({str(pid)!r}).write_text(str(os.getpid()))\ntime.sleep(60)\n')
    fake.chmod(0o700)
    monkeypatch.setattr(still_ops, 'ENCODER_TIMEOUT_SEC', 0.3)
    real_popen = still_ops.subprocess.Popen
    encoder_pids = []

    def record_encoder(*args, **kwargs):
        child = real_popen(*args, **kwargs)
        encoder_pids.append(child.pid)
        return child

    monkeypatch.setattr(still_ops.subprocess, 'Popen', record_encoder)
    request = dict(operation='still-image-render', source={'path': str(source), 'sha256': sha256(source)},
        frames=100, fps=30, width=256, height=256,
        crop_keyframes=[{'frame': 0, 'rect': [0, 0, 256, 256]},
                        {'frame': 99, 'rect': [0, 0, 256, 256]}],
        interpolation='linear', background_rgb=[0, 0, 0], allow_upscale=False, input_color='srgb')
    started = time.monotonic()
    with pytest.raises(ContractError, match='STILL_ENCODER_TIMEOUT'):
        still_ops.render_still(request, tmp_path, SimpleNamespace(binary=lambda name: str(fake)))
    assert time.monotonic() - started < 3
    # The watchdog may reap a child before its interpreter writes the PID file.
    # Popen identifies the actual child even during that startup race; the
    # non-consuming stdin pipe, deadline and elapsed-time assertions stay intact.
    assert len(encoder_pids) == 1
    with pytest.raises(ProcessLookupError):
        os.kill(encoder_pids[0], 0)
    assert (tmp_path / 'encode.log').exists()
