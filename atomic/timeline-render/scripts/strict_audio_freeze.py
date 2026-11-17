"""Produce or verify a MOV with copied H.264 video and exact s16 PCM ranges.

Explicit strict-media helper for timeline-render; never commits a work version.
Request v2 additionally binds the delivery to the checked real work head.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "runtime"))
from tool_identity import inspect_tool


class Rejected(ValueError):
    pass


def require(ok, code):
    if not ok:
        raise Rejected(code)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fingerprint(value):
    return sha(json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode())


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def export_json(path, value):
    """Publish a complete JSON file last; preserve a failed temporary write."""
    path = Path(path)
    require(not path.exists(), "EXPORT_ALREADY_EXISTS")
    temporary = path.with_name(path.name + ".pending")
    with temporary.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def ref(path):
    path = Path(path).resolve()
    return {"path": str(path), "sha256": sha(path.read_bytes())}


def exact_keys(obj, keys, label):
    require(isinstance(obj, dict) and set(obj) == set(keys), label + "_FIELDS")


def bound_file(value, label):
    exact_keys(value, ["path", "sha256"], label)
    p = Path(value["path"])
    require(p.is_absolute() and p.is_file(), label + "_FILE_MISSING")
    require(isinstance(value["sha256"], str) and len(value["sha256"]) == 64, label + "_HASH_INVALID")
    require(ref(p)["sha256"] == value["sha256"], label + "_HASH_MISMATCH")
    return p


class Tools:
    def __init__(self, request):
        exact_keys(request, ["ffmpeg", "ffprobe"], "TOOLS")
        self.ff = bound_file(request["ffmpeg"], "FFMPEG")
        self.fp = bound_file(request["ffprobe"], "FFPROBE")
        self.tool_chains = {}
        for name, path in (("ffmpeg", self.ff), ("ffprobe", self.fp)):
            observed = inspect_tool(str(path), run_version=False)
            require(observed["status"] == "RESOLVED_EXECUTABLE_CHAIN",
                    "MEDIA_TOOL_IDENTITY_UNRESOLVED: " + name + ": " + observed.get("error", "unknown"))
            self.tool_chains[name] = observed
        self.commands = []

    def run(self, args):
        command = [str(x) for x in args]
        for name, path in (("ffmpeg", self.ff), ("ffprobe", self.fp)):
            if command[0] == str(path):
                current = inspect_tool(str(path), run_version=False)
                require(current["status"] == "RESOLVED_EXECUTABLE_CHAIN" and
                        current["identity_sha256"] == self.tool_chains[name]["identity_sha256"],
                        "MEDIA_TOOL_IDENTITY_CHANGED: " + name)
        try:
            process = subprocess.run(command, capture_output=True, timeout=300)
        except subprocess.TimeoutExpired as exc:
            self.commands.append({"argv": command, "returncode": None, "error": "timeout", "timeout_seconds": 300})
            raise Rejected("MEDIA_TOOL_TIMEOUT_PARTIAL_OUTPUT_RETAINED") from exc
        except OSError as exc:
            self.commands.append({"argv": command, "returncode": None, "error": str(exc)})
            raise Rejected("MEDIA_TOOL_IO_ERROR_PARTIAL_OUTPUT_RETAINED") from exc
        self.commands.append({"argv": command, "returncode": process.returncode,
                              "stdout_sha256": sha(process.stdout), "stderr_sha256": sha(process.stderr),
                              "stderr": process.stderr.decode("utf-8", errors="replace")})
        for name, path in (("ffmpeg", self.ff), ("ffprobe", self.fp)):
            if command[0] == str(path):
                current = inspect_tool(str(path), run_version=False)
                require(current["status"] == "RESOLVED_EXECUTABLE_CHAIN" and
                        current["identity_sha256"] == self.tool_chains[name]["identity_sha256"],
                        "MEDIA_TOOL_IDENTITY_CHANGED: " + name)
        require(process.returncode == 0, "MEDIA_TOOL_FAILED")
        return process.stdout

    def probe(self, path):
        return json.loads(self.run([self.fp, "-v", "error", "-show_streams", "-show_format", "-of", "json", path]))

    def pcm(self, path):
        return self.run([self.ff, "-nostdin", "-v", "error", "-i", path, "-map", "0:a:0", "-c:a", "pcm_s16le", "-f", "s16le", "-"])

    def frames(self, path):
        raw = self.run([self.ff, "-nostdin", "-v", "error", "-i", path, "-map", "0:v:0", "-an", "-vsync", "0", "-f", "framehash", "-hash", "sha256", "-"])
        return [[v.strip() for v in line.split(",")] for line in raw.decode().splitlines() if line and not line.startswith("#")]

    def packets(self, path):
        data = json.loads(self.run([self.fp, "-v", "error", "-select_streams", "v:0", "-show_packets", "-show_data_hash", "sha256", "-of", "json", path]))
        return [{k: p.get(k) for k in ["pts", "dts", "duration", "size", "flags", "data_hash"]} for p in data["packets"]]


def validate_request(request):
    require(isinstance(request, dict), "REQUEST_FIELDS")
    schema = request.get("schema")
    require(schema in ["strict-audio-freeze-request/1", "strict-audio-freeze-request/2"]
            and request.get("operation") == "strict-audio-freeze", "UNSUPPORTED_OPERATION")
    fields = ["schema", "operation", "baseline", "candidate", "pcm_format", "frozen_ranges", "output_profile", "tools"]
    if schema.endswith("/2"):
        fields += ["work", "duration_policy"]
        exact_keys(request.get("work"), ["store", "expected_version"], "WORK")
        require(isinstance(request.get("candidate"), dict), "CANDIDATE_FIELDS")
        require(request["work"]["expected_version"] == request["candidate"].get("version"), "WORK_EXPECTED_VERSION_MISMATCH")
        policy = request.get("duration_policy")
        require(isinstance(policy, dict), "DURATION_POLICY_REQUIRED")
        if policy.get("mode") == "preserve-decoded-padding":
            exact_keys(policy, ["mode"], "DURATION_POLICY")
        else:
            exact_keys(policy, ["mode", "video_seconds", "audio_frames"], "DURATION_POLICY")
            require(policy["mode"] == "exact" and isinstance(policy["video_seconds"], str)
                    and Fraction(policy["video_seconds"]) > 0 and type(policy["audio_frames"]) is int
                    and policy["audio_frames"] > 0, "INVALID_EXACT_DURATION_POLICY")
    exact_keys(request, fields, "REQUEST")


def work_snapshot(request, write_lock=False):
    """Return a held transaction; callers close it without changing work history."""
    p = Path(request["work"]["store"])
    require(p.is_absolute() and p.is_file(), "WORK_STORE_NOT_FOUND")
    db = sqlite3.connect(p.resolve().as_uri() + ("?mode=rw" if write_lock else "?mode=ro"),
                         uri=True, timeout=0)
    db.row_factory = sqlite3.Row
    try:
        db.execute("BEGIN IMMEDIATE" if write_lock else "BEGIN")
        require(db.execute("PRAGMA user_version").fetchone()[0] == 1, "WORK_STORE_SCHEMA_UNSUPPORTED")
        meta = dict(db.execute("SELECT key,value FROM metadata"))
        current = db.execute("SELECT * FROM revisions WHERE sequence=?", (int(meta["head"]),)).fetchone()
        require(current is not None and current["version"] == request["work"]["expected_version"], "WORK_VERSION_CONFLICT")
        require(meta["work_id"] == request["candidate"]["work_id"] == request["baseline"]["work_id"], "WORK_ID_MISMATCH")
        states = {}
        for role in ["baseline", "candidate"]:
            rows = db.execute("SELECT * FROM revisions WHERE version=?", (request[role]["version"],)).fetchall()
            require(len(rows) == 1, "WORK_REVISION_NOT_FOUND")
            row = rows[0]
            require(fingerprint(json.loads(row["document"])) == row["digest"], "WORK_DOCUMENT_HASH_MISMATCH")
            require(fingerprint({"work_id": meta["work_id"], "sequence": row["sequence"],
                                 "document_sha256": row["digest"]}) == row["version"], "WORK_VERSION_HASH_MISMATCH")
            binding = read(bound_file(request[role]["render_binding"], role.upper() + "_BINDING"))
            require(binding.get("work_id") == meta["work_id"] and binding.get("version") == row["version"]
                    and binding.get("document_sha256") == row["digest"]
                    and binding.get("video") == request[role]["media"], "WORK_RENDER_DOCUMENT_MISMATCH")
            states[role] = {"sequence": row["sequence"], "version": row["version"], "document_sha256": row["digest"]}
        seq = current["sequence"]
        visited = set()
        while seq != states["baseline"]["sequence"]:
            require(seq > 0 and seq not in visited, "BASELINE_NOT_WORK_ANCESTOR")
            visited.add(seq)
            row = db.execute("SELECT parent FROM revisions WHERE sequence=?", (seq,)).fetchone()
            require(row is not None and 0 <= row["parent"] < seq, "WORK_HISTORY_INVALID")
            seq = row["parent"]
        return db, {"store": str(p.resolve()), "work_id": meta["work_id"],
                    "sequence": current["sequence"], "version": current["version"],
                    "document_sha256": current["digest"], "baseline": states["baseline"]}
    except Exception:
        db.close()
        raise


def check_duration_policy(request, sources):
    policy = request["duration_policy"]
    video = sources["candidate"]["video"]
    video_seconds = Fraction(video["time_base"]) * int(video["duration_ts"])
    audio_frames = len(sources["candidate"]["pcm"]) // 4
    if policy["mode"] == "exact":
        require(video_seconds == Fraction(policy["video_seconds"]), "EXACT_VIDEO_DURATION_CONFLICT")
        require(audio_frames == policy["audio_frames"], "EXACT_AUDIO_DURATION_CONFLICT")
    return {"policy": policy, "video_seconds_fraction": str(video_seconds),
            "audio_frames": audio_frames, "audio_seconds_fraction": str(Fraction(audio_frames, 48000)),
            "streams_equal_duration": video_seconds == Fraction(audio_frames, 48000),
            "audio_trimmed": False}


def validate(request, tools):
    validate_request(request)
    require(request["pcm_format"] == {"sample_rate": 48000, "channels": 2, "channel_layout": "stereo", "sample_format": "s16le", "time_origin": "decoded_frame_zero"}, "UNSUPPORTED_PCM_FORMAT")
    require(request["output_profile"] == {"container": "mov", "video": "copy", "audio": "pcm_s16le"}, "UNSUPPORTED_OUTPUT_PROFILE")
    sources = {}
    for name in ["baseline", "candidate"]:
        item = request[name]
        exact_keys(item, ["work_id", "version", "media", "render_binding"], name.upper())
        require(isinstance(item["work_id"], str) and bool(item["work_id"]) and isinstance(item["version"], str) and len(item["version"]) == 64, "INVALID_WORK_IDENTITY")
        media = bound_file(item["media"], name.upper())
        binding = read(bound_file(item["render_binding"], name.upper() + "_BINDING"))
        require(binding["work_id"] == item["work_id"] and binding["version"] == item["version"] and binding["video"] == item["media"], name.upper() + "_IDENTITY_MISMATCH")
        probe = tools.probe(media)
        audio = [s for s in probe["streams"] if s["codec_type"] == "audio"]
        video = [s for s in probe["streams"] if s["codec_type"] == "video"]
        require(len(audio) == 1 and len(video) == 1 and len(probe["streams"]) == 2, "UNSUPPORTED_STREAM_LAYOUT")
        require(audio[0]["sample_rate"] == "48000" and audio[0]["channels"] == 2 and audio[0].get("channel_layout") == "stereo", "PCM_SOURCE_FORMAT_MISMATCH")
        require(Fraction(audio[0]["start_time"]) == 0 and Fraction(video[0]["start_time"]) == 0, "NONZERO_STREAM_ORIGIN_UNSUPPORTED")
        require(video[0]["codec_name"] == "h264", "VIDEO_CODEC_UNSUPPORTED")
        decoded = tools.pcm(media)
        require(len(decoded) % 4 == 0, "PCM_ALIGNMENT")
        sources[name] = {"path": media, "probe": probe, "audio": audio[0], "video": video[0], "pcm": decoded}
    require(request["baseline"]["work_id"] == request["candidate"]["work_id"], "WORK_ID_MISMATCH")
    ranges = request["frozen_ranges"]
    require(isinstance(ranges, list) and bool(ranges), "EMPTY_FREEZE_RANGES")
    cursor = 0
    for interval in ranges:
        require(isinstance(interval, list) and len(interval) == 2 and all(type(n) is int for n in interval), "INVALID_SAMPLE_INTERVAL")
        a, b = interval
        require(0 <= a < b and a >= cursor, "INVALID_SAMPLE_INTERVAL")
        require(b <= min(len(sources["baseline"]["pcm"]), len(sources["candidate"]["pcm"])) // 4, "FREEZE_RANGE_OUT_OF_BOUNDS")
        cursor = b
    return sources


def expected_pcm(request, sources):
    result = bytearray(sources["candidate"]["pcm"])
    for a, b in request["frozen_ranges"]:
        result[a * 4:b * 4] = sources["baseline"]["pcm"][a * 4:b * 4]
    return bytes(result)


def verify(request, sources, path, tools):
    probe = tools.probe(path)
    audio = [s for s in probe["streams"] if s["codec_type"] == "audio"]
    video = [s for s in probe["streams"] if s["codec_type"] == "video"]
    require(len(probe["streams"]) == 2 and len(audio) == 1 and len(video) == 1, "DELIVERY_STREAM_LAYOUT")
    require(audio[0]["codec_name"] == "pcm_s16le" and audio[0]["sample_rate"] == "48000" and audio[0]["channels"] == 2 and audio[0].get("channel_layout") == "stereo", "DELIVERY_NOT_DECLARED_LOSSLESS_PCM")
    require(Fraction(audio[0]["start_time"]) == 0 and Fraction(video[0]["start_time"]) == 0, "DELIVERY_ORIGIN_CHANGED")
    actual = tools.pcm(path)
    candidate, baseline = sources["candidate"]["pcm"], sources["baseline"]["pcm"]
    require(len(actual) == len(candidate), "DELIVERY_SAMPLE_COUNT_CHANGED")
    ranges, complement = [], []
    cursor = 0
    for a, b in request["frozen_ranges"]:
        observed, locked = actual[a * 4:b * 4], baseline[a * 4:b * 4]
        require(observed == locked, "FROZEN_PCM_MISMATCH")
        ranges.append({"sample_interval": [a, b], "exact": True, "sha256": sha(observed)})
        if cursor < a:
            complement.append([cursor, a])
        cursor = b
    if cursor < len(candidate) // 4:
        complement.append([cursor, len(candidate) // 4])
    for a, b in complement:
        require(actual[a * 4:b * 4] == candidate[a * 4:b * 4], "NONFROZEN_PCM_NOT_CANDIDATE")
    require(actual == expected_pcm(request, sources), "FULL_PCM_MISMATCH")
    clockfields = ["codec_name", "width", "height", "pix_fmt", "time_base", "start_pts", "duration_ts", "nb_frames", "avg_frame_rate"]
    require(all(video[0].get(k) == sources["candidate"]["video"].get(k) for k in clockfields), "VIDEO_STREAM_FIELDS_CHANGED")
    candidate_packets, delivered_packets = tools.packets(sources["candidate"]["path"]), tools.packets(path)
    require(candidate_packets == delivered_packets, "VIDEO_PACKET_CONTENT_OR_TIMING_CHANGED")
    candidate_frames, delivered_frames = tools.frames(sources["candidate"]["path"]), tools.frames(path)
    require(candidate_frames == delivered_frames, "VIDEO_DECODED_FRAMES_CHANGED")
    return {"status": "PASSED_EXACT_DECLARED_MEDIA_CONSTRAINTS", "decoded_frames": len(delivered_frames),
            "video_packet_count": len(delivered_packets), "video_packets_and_decoded_frames_exact": True,
            "video_packet_table_sha256": sha(json.dumps(delivered_packets, sort_keys=True).encode()),
            "video_frame_table_sha256": sha(json.dumps(delivered_frames).encode()),
            "audio_frame_count": len(actual) // 4, "audio_pcm_sha256": sha(actual), "frozen_ranges": ranges,
            "nonfrozen_ranges": [{"sample_interval": [a, b], "candidate_exact": True, "sha256": sha(actual[a * 4:b * 4])} for a, b in complement],
            "output_probe": probe, "full_listening": "NOT_RUN", "human_edit_protection": "NOT_RUN", "host_acceptance": "NOT_RUN"}


def execute(request, directory, media_to_verify=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    receipt = {"schema": "strict-audio-freeze-receipt/1", "request_sha256": sha(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()),
               "operation": "verify" if media_to_verify else "create", "status": "RUNNING", "script": ref(__file__)}
    tools = None
    work_db = None
    binding = None
    try:
        validate_request(request)
        guarded = request["schema"].endswith("/2")
        if guarded:
            initial_db, initial_work = work_snapshot(request)
            initial_db.close()
            receipt["work_at_start"] = initial_work
        tools = Tools(request["tools"])
        receipt["tool_chains"] = tools.tool_chains
        sources = validate(request, tools)
        if guarded:
            receipt["duration_check"] = check_duration_policy(request, sources)
        if media_to_verify:
            output = Path(media_to_verify).resolve()
        else:
            raw = directory / "assembled.s16le"
            raw.write_bytes(expected_pcm(request, sources))
            output = directory / "master.mov"
            vclock = Fraction(sources["candidate"]["video"]["time_base"])
            require(vclock.numerator == 1, "VIDEO_TIMEBASE_UNSUPPORTED")
            tools.run([tools.ff, "-nostdin", "-v", "error", "-n", "-i", sources["candidate"]["path"],
                       "-f", "s16le", "-ar", "48000", "-ac", "2", "-i", raw,
                       "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "pcm_s16le",
                       "-video_track_timescale", str(vclock.denominator), "-movflags", "+faststart", output])
        output_before = ref(output)
        receipt["verification"] = verify(request, sources, output, tools)
        require(ref(output) == output_before, "DELIVERY_CHANGED_DURING_VERIFICATION")
        for name in ["baseline", "candidate"]:
            bound_file(request[name]["media"], name.upper())
            bound_file(request[name]["render_binding"], name.upper() + "_BINDING")
        for name, path in (("ffmpeg", tools.ff), ("ffprobe", tools.fp)):
            current = inspect_tool(str(path), run_version=False)
            require(current["status"] == "RESOLVED_EXECUTABLE_CHAIN" and
                    current["identity_sha256"] == tools.tool_chains[name]["identity_sha256"],
                    "MEDIA_TOOL_IDENTITY_CHANGED: " + name)
        receipt.update(status="SUCCEEDED", media=output_before, baseline=request["baseline"], candidate=request["candidate"],
                       artifact_role="strict_media_candidate_not_committed_work_version")
        if guarded:
            # Short final writer reservation prevents concurrent work commits while
            # exporting the checked binding. No metadata or revision row is changed.
            work_db, final_work = work_snapshot(request, write_lock=True)
            require(final_work == initial_work, "WORK_CHANGED_DURING_VERIFICATION")
            binding = {"schema": "strict-work-delivery-binding/1", **final_work,
                       "media": receipt["media"], "current_at_finish": True,
                       "request_sha256": receipt["request_sha256"], "script": receipt["script"],
                       "tool_chains": receipt["tool_chains"],
                       "mastering": {"baseline": request["baseline"], "candidate": request["candidate"],
                                     "frozen_ranges": request["frozen_ranges"], "pcm_format": request["pcm_format"],
                                     "output_profile": request["output_profile"], "duration_check": receipt["duration_check"]},
                       "verification": receipt["verification"], "work_history_changed": False,
                       "delivery_status": "TECHNICALLY_BOUND_NOT_FULLY_REVIEWED",
                       "validity": "Requires matching SUCCEEDED receipt and current media hash; a binding alone is not completed delivery",
                       "limits": ["Point-in-time export binding, not current-delivery selection or work revision adoption",
                                  "Recheck work version before later use; listening and target compatibility remain unverified"]}
            receipt.update(work_at_finish=final_work,
                           artifact_role="strict_media_delivery_bound_to_checked_work_version_not_adopted")
    except sqlite3.Error as exc:
        receipt.update(status="REJECTED", error="WORK_BUSY" if "locked" in str(exc) else "WORK_STORE_ERROR: " + str(exc))
    except (Rejected, OSError, KeyError, TypeError, ValueError, ZeroDivisionError) as exc:
        receipt.update(status="REJECTED", error=str(exc))
    finally:
        try:
            # Success is published only after request, command log and optional
            # binding are complete. Never replace the verified media fingerprint
            # with a hash of bytes that changed after verification.
            export_json(directory / "request.json", request)
            export_json(directory / "commands.json", tools.commands if tools else [])
            if receipt["status"] == "SUCCEEDED":
                require(ref(output) == output_before, "DELIVERY_CHANGED_BEFORE_EXPORT")
                if binding is not None:
                    export_json(directory / "work-delivery-binding.json", binding)
                    receipt["work_delivery_binding"] = ref(directory / "work-delivery-binding.json")
            export_json(directory / "receipt.json", receipt)
        except (OSError, Rejected, TypeError, ValueError) as exc:
            receipt.update(status="REJECTED", error="EVIDENCE_EXPORT_FAILED: " + str(exc))
            receipt.pop("work_delivery_binding", None)
            # Best effort failure marker; if storage also rejects this, propagate
            # the error. A leftover binding or .pending is not a success receipt.
            if not (directory / "receipt.json").exists():
                with (directory / "receipt.json").open("x", encoding="utf-8") as stream:
                    json.dump(receipt, stream, ensure_ascii=False, indent=2)
                    stream.write("\n")
            else:
                raise
        finally:
            if work_db is not None:
                work_db.close()
    return receipt


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--request", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--verify-media")
    args = p.parse_args()
    receipt = execute(read(args.request), args.out, args.verify_media)
    print(json.dumps({k: receipt[k] for k in ["status", "error"] if k in receipt}))
    raise SystemExit(0 if receipt["status"] == "SUCCEEDED" else 1)


if __name__ == "__main__":
    main()
