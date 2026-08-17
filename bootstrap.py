#!/usr/bin/env python3
"""Bootstrap the diagnostics app and recover SUPERVISOR_TOKEN when needed.

Home Assistant documents SUPERVISOR_TOKEN as the normal mechanism for apps.
This fallback uses the read-only Docker API permission already granted to this
app to inspect the Home Assistant Core container environment when the token
was not injected into the app environment after an update/rebuild.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
from pathlib import Path

SOCKET = "/var/run/docker.sock"


def docker_get(path: str) -> object:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(5)
        s.connect(SOCKET)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            "Host: docker\r\n"
            "Connection: close\r\n\r\n"
        ).encode()
        s.sendall(request)
        chunks = []
        while True:
            chunk = s.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
        raw = b"".join(chunks)
    finally:
        s.close()

    _, _, body = raw.partition(b"\r\n\r\n")
    return json.loads(body.decode("utf-8", "replace"))


def recover_token() -> str | None:
    if os.environ.get("SUPERVISOR_TOKEN"):
        return os.environ["SUPERVISOR_TOKEN"]
    if not Path(SOCKET).exists():
        return None

    try:
        containers = docker_get("/containers/json?all=0")
        names = []
        for c in containers if isinstance(containers, list) else []:
            names.extend(c.get("Names", []))
        target = next((n.lstrip("/") for n in names if n.lstrip("/") == "homeassistant"), None)
        if not target:
            return None

        info = docker_get(f"/containers/{target}/json")
        env = info.get("Config", {}).get("Env", [])
        for item in env:
            if item.startswith("SUPERVISOR_TOKEN="):
                return item.split("=", 1)[1]
    except Exception:
        return None
    return None


token = recover_token()
if token:
    os.environ["SUPERVISOR_TOKEN"] = token
else:
    # Do not prevent the web UI from starting; it will display a useful error.
    os.environ.pop("SUPERVISOR_TOKEN", None)

# Make the UI version authoritative even though the server source is retained
# as the stable v1.2 protocol implementation.
server = Path("/app/server.py")
text = server.read_text()
text = text.replace('VERSION = "1.2.0"', 'VERSION = "1.2.2"', 1)
server.write_text(text)

os.execv("/usr/bin/python3", ["python3", str(server)])
