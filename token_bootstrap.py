#!/usr/bin/env python3
"""Recover the Home Assistant Supervisor/Core token when Supervisor does not inject it."""
import os
import re
import subprocess

existing = os.environ.get("SUPERVISOR_TOKEN")
if existing:
    print(existing, end="")
    raise SystemExit(0)

try:
    out = subprocess.check_output(
        ["docker", "inspect", "homeassistant", "--format", "{{range .Config.Env}}{{println .}}{{end}}"],
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=10,
    )
except Exception:
    raise SystemExit(1)

for line in out.splitlines():
    if line.startswith("SUPERVISOR_TOKEN="):
        token = line.split("=", 1)[1].strip()
        if token:
            print(token, end="")
            raise SystemExit(0)
raise SystemExit(1)
