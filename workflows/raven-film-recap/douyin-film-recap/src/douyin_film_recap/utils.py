from __future__ import annotations

import hashlib
import json
import re
import subprocess
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence


VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi", ".ts"}


def natural_key(value: str) -> list[Any]:
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def discover_videos(path: str | Path) -> list[Path]:
    target = Path(path).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(target)
    if target.is_file():
        if target.suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError(f"Unsupported video extension: {target.suffix}")
        return [target]
    files = [p for p in target.rglob("*") if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
    files.sort(key=lambda p: natural_key(str(p.relative_to(target))))
    if not files:
        raise ValueError(f"No supported video files found in {target}")
    return files


CONTENT_IDENTITY_SCHEMA = "sha256-full/2"


class SourceChangedDuringRead(RuntimeError):
    """The file did not remain stable while its bytes were being identified."""


def _file_observation(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def content_identity(path: str | Path, chunk_size: int = 1024 * 1024) -> dict[str, Any]:
    """Stream every byte and reject observable changes, with bounded memory.

    Metadata detects ordinary mutations during this read; it is never a cached
    content identity. This does not provide isolation against a hostile writer.
    """
    if chunk_size <= 0:
        raise ValueError("Hash chunk size must be positive")
    target = Path(path)
    digest = hashlib.sha256()
    size = 0
    with target.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Content identity requires a regular file")
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
            size += len(chunk)
        after = os.fstat(handle.fileno())
        try:
            current = target.stat()
        except OSError as exc:
            raise SourceChangedDuringRead("Source disappeared during content hashing") from exc
    if (size != before.st_size or _file_observation(before) != _file_observation(after)
            or _file_observation(before) != _file_observation(current)):
        raise SourceChangedDuringRead("Source changed during content hashing")
    return {"schema": CONTENT_IDENTITY_SCHEMA, "sha256": digest.hexdigest(), "bytes": size}


def file_fingerprint(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Authoritative full-content SHA. Legacy sampled values require migration."""
    return content_identity(path, chunk_size)["sha256"]


def sampled_fingerprint_hint(path: str | Path, chunk_size: int = 1024 * 1024) -> str:
    """Legacy head/tail hint only. Never use to authorize cache reuse or resume."""
    target = Path(path)
    stat = target.stat()
    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode())
    digest.update(str(stat.st_mtime_ns).encode())
    with target.open("rb") as handle:
        head = handle.read(chunk_size)
        digest.update(head)
        if stat.st_size > chunk_size:
            handle.seek(max(0, stat.st_size - chunk_size))
            digest.update(handle.read(chunk_size))
    return digest.hexdigest()


def content_fingerprint(path: str | Path) -> str:
    """Hash the entire artifact, independent of mutable filesystem timestamps."""
    return content_identity(path)["sha256"]


def fingerprint_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    # Keep the last valid state/artifact if a process is interrupted mid-write.
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=f".{target.name}.", delete=False) as handle:
            temporary = handle.name
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def run_command(
    args: Sequence[str | Path],
    *,
    cwd: str | Path | None = None,
    timeout: float | None = None,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = [str(item) for item in args]
    try:
        return subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            check=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "")[-5000:]
        stdout = (exc.stdout or "")[-2000:]
        raise RuntimeError(
            f"Command failed ({exc.returncode}): {' '.join(command)}\n"
            f"stdout: {stdout}\nstderr: {stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Command timed out: {' '.join(command)}") from exc


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def overlap_seconds(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def chunks(items: Sequence[Any], size: int) -> Iterable[Sequence[Any]]:
    for index in range(0, len(items), size):
        yield items[index : index + size]


def safe_slug(value: str) -> str:
    slug = re.sub(r"[^\w\-.]+", "-", value, flags=re.UNICODE).strip("-_.")
    return slug or "project"


def extract_json_object(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start_positions = [pos for pos in (cleaned.find("{"), cleaned.find("[")) if pos >= 0]
    if not start_positions:
        raise ValueError("No JSON object found in model response")
    start = min(start_positions)
    opener = cleaned[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(cleaned)):
        char = cleaned[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return json.loads(cleaned[start : index + 1])
    raise ValueError("Unclosed JSON object in model response")


def redact_secret(value: str) -> str:
    if len(value) <= 8:
        return "***"
    return value[:3] + "***" + value[-3:]
