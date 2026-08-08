#!/usr/bin/env python3
"""Audiomass plain stdlib server (no FastAPI / no uvicorn).

Serves the static frontend from src/ the old way AND exposes the /api/...
endpoints the stems UI needs, by delegating to the existing FastAPI-free
service layer in ../backend (job_service, PipelineService, event_bus).

Run:  .venv/bin/python audiomass-server.py
Env:  AUDIOMASS_PORT (default 5055)
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from email.parser import BytesParser
from email.policy import default as default_policy
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

# --- Resolve paths ----------------------------------------------------------
SRC_DIR = Path(__file__).resolve().parent          # .../audiomass/src
ROOT_DIR = SRC_DIR.parent                            # .../audiomass
BACKEND_DIR = ROOT_DIR / "backend"                   # service layer lives here

# Make `import services.job_service` etc. work (backend has no __init__.py;
# its subpackages do, so adding backend/ to sys.path is enough).
sys.path.insert(0, str(BACKEND_DIR))

from domain.enums import SourceType                  # noqa: E402
from domain.models import CreateJobRequest           # noqa: E402
from services.event_bus import event_bus             # noqa: E402
from services.job_service import (                   # noqa: E402
    ActiveJobConflictError,
    job_service,
)
from services import project_service                # noqa: E402
from utils.paths import JOBS_DIR                     # noqa: E402
from utils.validation import (                       # noqa: E402
    ValidationError,
    validate_upload_filename,
)


PORT = int(os.environ.get("AUDIOMASS_PORT", "5055"))
HOST = "0.0.0.0"

# Pitch class names (used by /api/transcribe for human-readable note names).
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Extension -> MIME for static serving (SimpleHTTPRequestHandler covers most,
# but we pin .wasm so the wasm modules load correctly).
EXTRA_MIME = {
    ".wasm": "application/wasm",
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
}


# --- Multipart/form-data parser (stdlib only) -------------------------------
def parse_multipart(body: bytes, content_type: str) -> dict[str, dict]:
    """Parse multipart/form-data without cgi/python-multipart.

    Returns {field_name: {"headers": {...}, "data": bytes,
                          "filename": str|None, "name": str}}.

    When a field name repeats (e.g. multiple 'clips' files), the value is a
    list of such dicts. Callers that expect a single value should use
    ``parse_multipart_all`` or check the type.
    """
    return _parse_multipart_impl(body, content_type, accumulate=False)


def parse_multipart_all(body: bytes, content_type: str) -> dict[str, list[dict]]:
    """Like parse_multipart, but every field name maps to a LIST of part dicts
    (even when only one is present). Use for forms with repeated fields."""
    return _parse_multipart_impl(body, content_type, accumulate=True)


def _parse_multipart_impl(body: bytes, content_type: str, *, accumulate: bool):
    header_bytes = b"Content-Type: " + content_type.encode("utf-8", "replace") + b"\r\n\r\n"
    msg = BytesParser(policy=default_policy).parsebytes(header_bytes + body)
    fields: dict = {}
    if not msg.is_multipart():
        return fields
    for part in msg.get_payload():
        cd = part.get("Content-Disposition", "")
        name = None
        filename = None
        for chunk in cd.split(";"):
            chunk = chunk.strip()
            if chunk.startswith("name="):
                name = chunk[5:].strip().strip('"')
            elif chunk.startswith("filename="):
                filename = chunk[9:].strip().strip('"')
        if name is None:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            payload = b""
        entry = {"name": name, "filename": filename, "data": payload}
        if accumulate:
            fields.setdefault(name, []).append(entry)
        else:
            fields[name] = entry
    return fields


# --- Helpers ----------------------------------------------------------------
def _json_snapshot(obj) -> str:
    """Serialize a pydantic model (JobSnapshot / ManifestResponse) to JSON."""
    return obj.model_dump_json()


def _split_first(s: str, sep: str) -> tuple[str, str]:
    i = s.find(sep)
    if i < 0:
        return s, ""
    return s[:i], s[i + len(sep):]


# --- Request handler --------------------------------------------------------
class AudioMassHandler(BaseHTTPRequestHandler):
    server_version = "AudioMass/1.0 (stdlib)"
    protocol_version = "HTTP/1.1"

    # Keep the log line concise.
    def log_message(self, fmt, *args):
        sys.stdout.write("[audiomass] %s - %s\n" % (self.address_string(), fmt % args))

    # ----- response helpers -----
    def _send_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Max-Age", "86400")

    def _send_json(self, status: int, obj, extra_headers: dict | None = None):
        body = obj if isinstance(obj, (bytes, bytearray)) else (
            json.dumps(obj).encode("utf-8"))
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._send_cors()
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_error_json(self, status: int, detail: str):
        self._send_json(status, {"detail": detail})

    def _send_no_content(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    # ----- entry points -----
    def do_OPTIONS(self):
        self.send_response(HTTPStatus.NO_CONTENT)
        self._send_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        try:
            if self.path.startswith("/api/"):
                self.route_api_get()
            else:
                self.serve_static()
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[audiomass] GET {self.path} error: {exc}\n")
            try:
                self._send_error_json(500, f"Internal error: {exc}")
            except Exception:
                pass

    def do_POST(self):
        try:
            if self.path.startswith("/api/"):
                self.route_api_post()
            else:
                self._send_error_json(404, "Not Found")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            sys.stderr.write(f"[audiomass] POST {self.path} error: {exc}\n")
            try:
                self._send_error_json(500, f"Internal error: {exc}")
            except Exception:
                pass

    def do_DELETE(self):
        try:
            if self.path.startswith("/api/"):
                self.route_api_delete()
            else:
                self._send_error_json(404, "Not Found")
        except BrokenPipeError:
            pass
        except Exception as exc:  # noqa: BLE001
            try:
                self._send_error_json(500, f"Internal error: {exc}")
            except Exception:
                pass

    # ----- static serving (the old way) -----
    def serve_static(self):
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "" or path == "/":
            path = "/index.html"

        # Prevent path traversal.
        rel = path.lstrip("/")
        fs_path = (SRC_DIR / rel).resolve()
        try:
            fs_path.relative_to(SRC_DIR)
        except ValueError:
            self._send_error_json(403, "Forbidden")
            return

        if not fs_path.exists() or not fs_path.is_file():
            self._send_error_json(404, "Not Found")
            return

        ext = fs_path.suffix.lower()
        mime = EXTRA_MIME.get(ext)
        if mime is None:
            # Fall back to the stdlib guess table.
            import mimetypes
            mime = mimetypes.guess_type(str(fs_path))[0] or "application/octet-stream"

        data = fs_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))

        # No-cache for JS so edits reload cleanly (mirrors the old Go server).
        if ext in {".js", ".mjs", ".wasm", ".css", ".html"}:
            self.send_header("Cache-Control", "no-cache, private, max-age=0")
            self.send_header("Pragma", "no-cache")

        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # ----- API routing -----
    def route_api_get(self):
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/api/health", "/api/"):
            self._send_json(200, {"status": "ok"})
            return

        # /api/jobs/{id}/events  -> SSE
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/events", path)
        if m:
            self.handle_sse(m.group(1))
            return

        # /api/jobs/{id}/manifest
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/manifest", path)
        if m:
            manifest = job_service.get_manifest(m.group(1))
            if manifest is None:
                self._send_error_json(404, "Manifest not found")
            else:
                self._send_json(200, _json_snapshot(manifest).encode("utf-8"))
            return

        # /api/jobs/{id}/stems/{name}
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/stems/([A-Za-z0-9_-]+)", path)
        if m:
            self.handle_get_stem(m.group(1), m.group(2), qs.get("format", ["wav"])[0])
            return

        # /api/jobs/{id}  -> snapshot
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)", path)
        if m:
            snap = job_service.get_job(m.group(1))
            if snap is None:
                self._send_error_json(404, "Job not found")
            else:
                self._send_json(200, _json_snapshot(snap).encode("utf-8"))
            return

        # /api/projects  -> list all saved projects
        if path == "/api/projects":
            self._send_json(200, project_service.list_projects())
            return

        # /api/projects/{id}/clips/{clip_id}  -> serve clip WAV
        m = re.fullmatch(r"/api/projects/([A-Za-z0-9_-]+)/clips/([A-Za-z0-9_-]+)", path)
        if m:
            data = project_service.load_project(m.group(1))
            if not data:
                self._send_error_json(404, "Project not found")
                return
            clip_path = data["clip_paths"].get(m.group(2))
            if not clip_path or not Path(clip_path).exists():
                self._send_error_json(404, "Clip not found")
                return
            wav = Path(clip_path).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Disposition", f'attachment; filename="{m.group(2)}.wav"')
            self.send_header("Content-Length", str(len(wav)))
            self._send_cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(wav)
            return

        # /api/projects/{id}  -> load project state
        m = re.fullmatch(r"/api/projects/([A-Za-z0-9_-]+)", path)
        if m:
            data = project_service.load_project(m.group(1))
            if not data:
                self._send_error_json(404, "Project not found")
                return
            self._send_json(200, {
                "meta": data["meta"],
                "state": data["state"],
                "clips": list(data["clip_paths"].keys()),
            })
            return

        self._send_error_json(404, "Not Found")

    def route_api_post(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/jobs/upload":
            self.handle_upload()
            return

        if path == "/api/transcribe":
            self.handle_transcribe()
            return

        if path == "/api/projects":
            self.handle_save_project_ext()
            return

        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)/cancel", path)
        if m:
            ok = job_service.cancel_job(m.group(1))
            if not ok:
                self._send_error_json(404, "Job not found or not cancellable")
            else:
                self._send_json(200, {"job_id": m.group(1), "status": "cancel_requested"})
            return

        self._send_error_json(404, "Not Found")

    def route_api_delete(self):
        parsed = urlparse(self.path)
        m = re.fullmatch(r"/api/jobs/([A-Za-z0-9_-]+)", parsed.path)
        if m:
            ok = job_service.delete_job(m.group(1))
            if not ok:
                self._send_error_json(404, "Job not found or not in terminal state")
                return
            self._send_no_content()
            return

        m = re.fullmatch(r"/api/projects/([A-Za-z0-9_-]+)", parsed.path)
        if m:
            ok = project_service.delete_project(m.group(1))
            if not ok:
                self._send_error_json(404, "Project not found")
                return
            self._send_json(200, {"status": "deleted", "project_id": m.group(1)})
            return

        self._send_error_json(404, "Not Found")

    # ----- handlers -----
    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _parse_multipart_all_safe(self):
        """Parse a multipart body (list-aware). Returns the fields dict, or
        None and sends an error response on failure."""
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._send_error_json(422, "Expected multipart/form-data")
            return None
        body = self._read_body()
        try:
            return parse_multipart_all(body, ctype)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(400, f"Malformed multipart body: {exc}")
            return None

    def handle_save_project_ext(self):
        """POST /api/projects — save a multitrack project.
        Delegates to project_handler.handle_save_project (split out so the
        heavy save logic lives in its own module)."""
        from project_handler import handle_save_project
        handle_save_project(self)

    def handle_upload(self):
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._send_error_json(422, "Expected multipart/form-data")
            return

        body = self._read_body()
        try:
            fields = parse_multipart(body, ctype)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(400, f"Malformed multipart body: {exc}")
            return

        file_field = fields.get("file")
        if not file_field:
            self._send_error_json(422, "Missing 'file' field")
            return

        filename = file_field.get("filename") or "upload.wav"
        if not validate_upload_filename(filename):
            self._send_error_json(422, "Unsupported upload file type")
            return

        # stems (optional, JSON array string)
        stems_raw = fields.get("stems", {}).get("data", b"").decode("utf-8", "replace") \
            if fields.get("stems") else ""
        if stems_raw:
            try:
                stem_list = json.loads(stems_raw)
                if not isinstance(stem_list, list):
                    raise ValueError("stems must be a JSON array")
            except Exception:
                self._send_error_json(422, "Invalid stems payload")
                return
        else:
            stem_list = ["vocals", "drums", "bass", "guitar", "piano", "other"]

        # Persist upload to the shared _incoming dir (same path the FastAPI app used).
        upload_dir = JOBS_DIR / "_incoming"
        upload_dir.mkdir(parents=True, exist_ok=True)
        safe_name = Path(filename).name
        # Include a short unique suffix to avoid collisions across reruns.
        target = upload_dir / f"{uuid.uuid4().hex[:6]}_{safe_name}"
        target.write_bytes(file_field["data"])

        payload = CreateJobRequest(
            source_type=SourceType.upload,
            filename=str(target),
            stems=stem_list,
        )
        try:
            snapshot = job_service.create_job(payload)
        except ValidationError as exc:
            self._send_error_json(422, str(exc))
            return
        except ActiveJobConflictError as exc:
            self._send_error_json(409, str(exc))
            return

        self._send_json(201, _json_snapshot(snapshot).encode("utf-8"))

    def handle_transcribe(self):
        """Audio -> notes via basic-pitch. Saves upload to a temp file, runs
        predict(), returns JSON {notes: [{start,duration,midi,pitch,amplitude}]}.

        basic-pitch is heavy (torch + ONNX); it is imported lazily here so the
        server starts fast and only pays the cost when transcription is used.
        """
        ctype = self.headers.get("Content-Type", "")
        if "multipart/form-data" not in ctype:
            self._send_error_json(422, "Expected multipart/form-data")
            return

        body = self._read_body()
        try:
            fields = parse_multipart(body, ctype)
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(400, f"Malformed multipart body: {exc}")
            return

        file_field = fields.get("file")
        if not file_field:
            self._send_error_json(422, "Missing 'file' field")
            return

        filename = file_field.get("filename") or "upload.wav"
        if not validate_upload_filename(filename):
            self._send_error_json(422, "Unsupported upload file type")
            return

        # Write to a temp file (basic-pitch wants a path, not bytes).
        suffix = Path(filename).suffix or ".wav"
        tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
        try:
            tmp.write(file_field["data"])
            tmp.close()

            try:
                # Deferred import: torch/ONNX are slow and only needed here.
                from basic_pitch.inference import predict
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(500, f"basic-pitch not available: {exc}")
                return

            try:
                _, midi_data, note_events = predict(tmp.name)
            except Exception as exc:  # noqa: BLE001
                self._send_error_json(500, f"Transcription failed: {exc}")
                return

            notes = []
            for start, end, midi_num, amplitude, _bends in note_events:
                name = NOTE_NAMES[((midi_num % 12) + 12) % 12]
                octave = midi_num // 12 - 1
                notes.append({
                    "start": round(float(start), 3),
                    "duration": round(float(end - start), 3),
                    "midi": int(midi_num),
                    "pitch": f"{name}{octave}",
                    "amplitude": round(float(amplitude), 3),
                })
            # Sort by start time for predictable rendering.
            notes.sort(key=lambda n: n["start"])
            self._send_json(200, {"notes": notes, "count": len(notes)})
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def handle_get_stem(self, job_id: str, stem_name: str, fmt: str):
        manifest = job_service.get_manifest(job_id)
        if manifest is None:
            self._send_error_json(404, "Job not found")
            return

        valid_formats = ["wav", "mp3", "flac", "ogg"]
        if fmt not in valid_formats:
            self._send_error_json(422, f"Invalid format. Must be one of: {valid_formats}")
            return

        audio_path = manifest.files.get(stem_name)
        if audio_path is None:
            self._send_error_json(404, f"Stem {stem_name} not found")
            return
        p = Path(audio_path)
        if not p.exists():
            self._send_error_json(404, "Audio file not found on disk")
            return

        if fmt == "wav":
            data = p.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "audio/wav")
            self.send_header(
                "Content-Disposition", f'attachment; filename="{stem_name}.wav"')
            self.send_header("Content-Length", str(len(data)))
            self._send_cors()
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(data)
            return

        # Non-wav: convert via ffmpeg (same config as the original backend).
        cfg = {
            "mp3": (".mp3", "audio/mpeg", ["-codec:a", "libmp3lame", "-b:a", "192k"]),
            "flac": (".flac", "audio/flac", ["-codec:a", "flac"]),
            "ogg": (".ogg", "audio/ogg", ["-codec:a", "libvorbis", "-b:a", "192k"]),
        }[fmt]
        suffix, media_type, codec_args = cfg
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(p), *codec_args, tmp_path],
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            self._send_error_json(500, "Failed to convert audio: "
                                  f"{exc.stderr.decode(errors='replace') if exc.stderr else exc}")
            return
        except Exception as exc:  # noqa: BLE001
            self._send_error_json(500, f"Conversion failed: {exc}")
            return

        data = Path(tmp_path).read_bytes()
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", media_type)
        self.send_header(
            "Content-Disposition", f'attachment; filename="{stem_name}{suffix}"')
        self.send_header("Content-Length", str(len(data)))
        self._send_cors()
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    # ----- SSE -----
    def handle_sse(self, job_id: str):
        snapshot = job_service.get_job(job_id)
        if snapshot is None:
            # Match the FastAPI behaviour: a job_failed frame with a detail string.
            self._begin_sse()
            self._sse_write("job_failed", '{"detail": "Job not found"}')
            self._sse_end()
            return

        self._begin_sse()
        self._sse_write("job_state", _json_snapshot(snapshot))

        queue = event_bus.subscribe(job_id)
        try:
            while True:
                event = event_bus.next_event(queue, timeout=15.0)
                if event is None:
                    # Heartbeat: also stop if the job reached a terminal state.
                    latest = job_service.get_job(job_id)
                    if latest is None:
                        self._sse_write("job_failed", '{"detail": "Job not found"}')
                        return
                    self._sse_write("heartbeat", _json_snapshot(latest))
                    if latest.status.value in {"done", "failed", "cancelled"}:
                        return
                    continue
                self._sse_write(event["event"], event["data"])
                if event["event"] in {"job_done", "job_failed", "job_cancelled"}:
                    return
        finally:
            event_bus.unsubscribe(job_id, queue)
            self._sse_end()

    def _begin_sse(self):
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")  # disable proxy buffering
        self._send_cors()
        self.end_headers()

    def _sse_write(self, event_name: str, data: str):
        # Standard SSE frame. data may already be JSON; if so send as-is.
        payload = f"event: {event_name}\ndata: {data}\n\n"
        try:
            self.wfile.write(payload.encode("utf-8"))
            self.wfile.flush()
        except BrokenPipeError:
            pass

    def _sse_end(self):
        try:
            self.wfile.flush()
        except Exception:
            pass


# --- main -------------------------------------------------------------------
def main():
    # Make sure the jobs root exists (JobStore does this too, but be defensive).
    JOBS_DIR.mkdir(parents=True, exist_ok=True)

    server = ThreadingHTTPServer((HOST, PORT), AudioMassHandler)
    server.daemon_threads = True
    print(f"Audiomass (plain stdlib, no FastAPI) serving:")
    print(f"  UI :  http://{HOST}:{PORT}/")
    print(f"  API:  http://{HOST}:{PORT}/api/jobs/upload  (HTDemucs stem separation)")
    print(f"  jobs root: {JOBS_DIR}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
