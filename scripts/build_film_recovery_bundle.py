#!/usr/bin/env python3
"""Build a fixed stdlib-only maintenance candidate (B); no production runner."""
from pathlib import Path
import argparse
import json
import shutil
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "workflows/raven-film-recap/douyin-film-recap/src"))
from douyin_film_recap.workspace import RECOVERY_LAUNCHER, atomic, sha, verify_recovery_bundle


def build(out):
    out = Path(out).absolute()
    if out.exists() or any(p.is_symlink() for p in (out, *out.parents)):
        raise ValueError("Recovery build requires a new non-symlink output directory")
    out.mkdir(parents=True, exist_ok=False)
    source = REPO / "workflows/raven-film-recap/douyin-film-recap/src/douyin_film_recap/workspace.py"
    package = out / "src/douyin_film_recap"
    package.mkdir(parents=True)
    (out / "recover.py").write_text(RECOVERY_LAUNCHER, encoding="utf-8")
    (package / "__init__.py").write_text("# Read-only recovery package.\n", encoding="utf-8")
    expected = sha(source)
    shutil.copyfile(source, package / "workspace.py")
    if sha(source) != expected or sha(package / "workspace.py") != expected:
        raise ValueError("Recovery source changed while copying")
    files = [{"path": str(p.relative_to(out)), "sha256": sha(p)} for p in sorted(out.rglob("*")) if p.is_file()]
    atomic(out / "recovery-package.json", {"schema": "film-recovery-package/1",
        "mode": "READ_ONLY_RECOVERY", "supported_state_schemas": [1, 2],
        "files": files, "source_sha256": expected})
    package_sha = sha(out / "recovery-package.json")
    verify_recovery_bundle(out, package_sha)
    return {"status": "BUILT_BYTES_VERIFIED", "path": str(out), "package_sha256": package_sha,
            "source_sha256": expected, "qualification": "requires independent execution tests"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    print(json.dumps(build(parser.parse_args().out), ensure_ascii=False))
