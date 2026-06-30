#!/usr/bin/env python3
"""
status_writer.py  --  called by Claude Code hooks.

Each Claude Code hook event runs this script with a status word as the first
argument (working / waiting / done / idle / end). The script reads the hook's
JSON payload on stdin (which contains `cwd`, `session_id`, `tool_name`, ...),
and writes a tiny JSON status file to ~/.claude-status/<project>.json.

The panel (monitor.py) watches that folder and draws the lights.

This file has NO third-party dependencies on purpose: it must start fast and
never slow Claude down. Keep it that way if you tweak it.
"""

import sys
import os
import json
import time
import re
import hashlib

STATUS_DIR = os.path.expanduser(os.environ.get("CLAUDE_STATUS_DIR", "~/.claude-status"))

# Statuses the panel understands. `end` removes the signal.
VALID = {"working", "waiting", "done", "idle", "end"}


def key_for(cwd: str) -> str:
    """One stable filename per project directory."""
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "_", cwd.strip("/"))
    if not cleaned:
        cleaned = hashlib.md5(cwd.encode()).hexdigest()[:10]
    return cleaned[:120]


def read_arg(flag, default=None):
    if flag in sys.argv:
        i = sys.argv.index(flag)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def main():
    status = sys.argv[1] if len(sys.argv) > 1 else "working"
    if status not in VALID:
        status = "working"
    label = read_arg("--label", "")

    # Hook payload arrives on stdin as JSON.
    payload = {}
    try:
        if not sys.stdin.isatty():
            raw = sys.stdin.read()
            if raw.strip():
                payload = json.loads(raw)
    except Exception:
        payload = {}

    cwd = payload.get("cwd") or os.getcwd()
    session_id = payload.get("session_id", "")
    tool = payload.get("tool_name", "")

    project = os.path.basename(cwd.rstrip("/")) or cwd

    os.makedirs(STATUS_DIR, exist_ok=True)
    path = os.path.join(STATUS_DIR, key_for(cwd) + ".json")

    if status == "end":
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        return

    now = time.time()

    # Preserve when the CURRENT status began, so the panel can show elapsed time.
    prev = {}
    if os.path.exists(path):
        try:
            with open(path) as f:
                prev = json.load(f)
        except Exception:
            prev = {}
    status_since = prev.get("status_since", now) if prev.get("status") == status else now

    record = {
        "project": project,
        "path": cwd,
        "status": status,
        "label": label,
        "session_id": session_id,
        "last_tool": tool,
        "updated_at": now,
        "status_since": status_since,
    }

    # Atomic write so the panel never reads a half-written file.
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(record, f)
    os.replace(tmp, path)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # A status writer must never crash a Claude Code hook.
        pass
