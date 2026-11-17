"""Bounded tool executable-chain observation, never a general shell parser.

Only native binaries or exact two-line /bin/sh exec wrappers are recognized.
Identity does not certify shared libraries, plugins, model files or provenance.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def native_kind(header):
    if header[:4] == b"\x7fELF":
        return "elf"
    if header[:4] in [bytes.fromhex(x) for x in ["feedface", "feedfacf", "cefaedfe", "cffaedfe", "cafebabe", "bebafeca", "cafebabf", "bfbafeca"]]:
        return "mach-o"
    return None


def inspect_tool(path, max_wrappers=8, run_version=True):
    """Return explicit observations; unsupported chains never get executed.

    Version is invoked on the resolved binary only, with argv=[binary,-version].
    Normal caller execution routing remains the originally configured path.
    """
    report = {"schema": "tool-executable-chain/1", "requested_path": str(path),
              "status": "UNRESOLVED", "chain": [], "version": None,
              "version_probe": "NOT_RUN", "scope": "executable chain only; not dynamic dependencies or authenticity"}
    try:
        if type(max_wrappers) is not int or not 0 <= max_wrappers <= 32:
            raise ValueError("INVALID_WRAPPER_LIMIT")
        current, seen, wrappers = Path(path), set(), 0
        if not current.is_absolute():
            raise ValueError("ABSOLUTE_TOOL_PATH_REQUIRED")
        while True:
            resolved = current.resolve(strict=True)
            if resolved in seen:
                raise ValueError("TOOL_WRAPPER_CYCLE")
            seen.add(resolved)
            if not resolved.is_file():
                raise ValueError("TOOL_NOT_FILE")
            row = {"requested_path": str(current), "path": str(resolved), "sha256": digest(resolved)}
            report["chain"].append(row)
            with resolved.open("rb") as stream:
                header = stream.read(65537)
            kind = native_kind(header)
            if kind:
                row["kind"] = kind
                if not os.access(resolved, os.X_OK):
                    raise ValueError("TOOL_NOT_EXECUTABLE")
                report["resolved_binary"] = {"path": str(resolved), "sha256": row["sha256"], "kind": kind}
                break
            row["kind"] = "script-or-unrecognized-file"
            if len(header) > 65536:
                raise ValueError("TOOL_SCRIPT_TOO_LARGE")
            try:
                script = header.decode("utf-8")
            except UnicodeDecodeError:
                raise ValueError("UNSUPPORTED_TOOL_FILE")
            # No $, backticks or backslashes in target: quoted shell expansion
            # cannot be mistaken for a literal filesystem target.
            match = re.fullmatch(r'#!/bin/sh\nexec "(/[^"\n\r$`\\]*)" "\$@"\n?', script)
            if not match:
                raise ValueError("UNRESOLVED_COMPLEX_WRAPPER")
            if wrappers >= max_wrappers:
                raise ValueError("TOOL_WRAPPER_DEPTH_EXCEEDED")
            if not os.access(resolved, os.X_OK):
                raise ValueError("TOOL_NOT_EXECUTABLE")
            interpreter = Path("/bin/sh").resolve(strict=True)
            row.update(kind="literal-exec-wrapper", target=match.group(1),
                       interpreter={"path": str(interpreter), "sha256": digest(interpreter)})
            current = Path(match.group(1))
            wrappers += 1
        if run_version:
            completed = subprocess.run([report["resolved_binary"]["path"], "-version"],
                                       capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=15)
            report["version_probe"] = "SUCCEEDED" if completed.returncode == 0 and completed.stdout.splitlines() else "FAILED"
            report["version_returncode"] = completed.returncode
            if report["version_probe"] == "SUCCEEDED":
                report["version"] = completed.stdout.splitlines()[0]
        for row in report["chain"]:
            if str(Path(row["requested_path"]).resolve(strict=True)) != row["path"] or digest(row["path"]) != row["sha256"]:
                raise ValueError("TOOL_CHAIN_CHANGED_DURING_OBSERVATION")
            if "interpreter" in row and digest(row["interpreter"]["path"]) != row["interpreter"]["sha256"]:
                raise ValueError("TOOL_INTERPRETER_CHANGED_DURING_OBSERVATION")
        report["status"] = "RESOLVED_EXECUTABLE_CHAIN"
        report["identity_sha256"] = hashlib.sha256(json.dumps(report["chain"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        report["status"] = "UNRESOLVED"
        report["error"] = str(exc)
        report.pop("identity_sha256", None)
    return report
