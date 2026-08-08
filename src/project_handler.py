"""Project save handler for the stdlib AudioMass server.

Provides handle_save_project(handler), called when POST /api/projects arrives.
Delegates the on-disk persistence to project_service.save_project.
"""
from __future__ import annotations

import re
import tempfile
import uuid


_SAFE = re.compile(r"[^A-Za-z0-9_-]")


def handle_save_project(handler) -> None:
    """Save a multitrack project: name + state JSON + clip WAVs."""
    fields = handler._parse_multipart_all_safe()
    if fields is None:
        return

    name_part = fields.get("name", [{}])[0]
    raw_name = name_part.get("data", b"Untitled Project")
    name = raw_name.decode("utf-8", "replace") or "Untitled Project"

    state_part = fields.get("state", [{}])[0]
    raw_state = state_part.get("data", b"{}")
    state_json = raw_state.decode("utf-8", "replace") or "{}"

    clip_parts = fields.get("clips", [])

    # Stage each clip to a system-generated temp file (NamedTemporaryFile
    # creates its own safe path; we never build one from user input). We map
    # the sanitized clip id -> that temp file path.
    clip_files: dict[str, str] = {}
    opened_temps = []  # keep refs so they exist until project_service copies them
    try:
        for cp in clip_parts:
            raw_fn = cp.get("filename") or "clip.wav"
            # Reduce to a safe id: drop dirs, drop .wav, keep [A-Za-z0-9_-] only.
            base = raw_fn.split("/")[-1].split("\\")[-1]
            if base.endswith(".wav"):
                base = base[:-4]
            clip_id = _SAFE.sub("_", base)
            if not clip_id:
                clip_id = "clip"

            tf = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            tf.write(cp["data"])
            tf.close()
            opened_temps.append(tf.name)
            clip_files[clip_id] = tf.name

        from services import project_service
        project_id = uuid.uuid4().hex[:12]
        try:
            meta = project_service.save_project(
                project_id=project_id,
                name=name,
                state_json=state_json,
                clip_files=clip_files,
            )
        except Exception as exc:  # noqa: BLE001
            handler._send_error_json(500, str(exc))
            return
        handler._send_json(201, meta)
    finally:
        import os as _os
        for t in opened_temps:
            try:
                _os.unlink(t)
            except OSError:
                pass
