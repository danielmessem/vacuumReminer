#!/usr/bin/env python3
"""Runtime wrapper for DEEBOT Y1 PRO Diagnostics 1.9.4.

Keeps the main diagnostics server intact while fixing Home Assistant API token
discovery, tightening telemetry redaction, and simplifying the room mapper UI for
a single Y1 PRO.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

import server_y1_v160 as s

VERSION = "1.9.4"
s.VERSION = VERSION


def _read_token_file(path: str):
    try:
        value = Path(path).read_text().strip()
        return value or None
    except Exception:
        return None


def supervisor_token():
    """Resolve only this add-on's own Supervisor token; never inspect Core secrets."""
    for key in ("SUPERVISOR_TOKEN", "HASSIO_TOKEN"):
        value = os.environ.get(key)
        if value:
            return value
    for path in (
        "/run/s6/container_environment/SUPERVISOR_TOKEN",
        "/run/secrets/SUPERVISOR_TOKEN",
    ):
        value = _read_token_file(path)
        if value:
            return value
    return None


def ha_request(path, method="GET", data=None):
    token = supervisor_token()
    if not token:
        return {
            "ok": False,
            "error": (
                "Home Assistant API token was not injected into the Diagnostics add-on. "
                "The add-on already requests homeassistant_api access; stop and start the add-on once after updating."
            ),
            "token_sources_checked": [
                "SUPERVISOR_TOKEN environment",
                "HASSIO_TOKEN compatibility environment",
                "/run/s6/container_environment/SUPERVISOR_TOKEN",
                "/run/secrets/SUPERVISOR_TOKEN",
            ],
        }
    body = None if data is None else json.dumps(data).encode()
    try:
        req = urllib.request.Request(
            "http://supervisor/core" + path,
            data=body,
            method=method,
            headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode()
            return {"ok": True, "data": json.loads(raw) if raw else None}
    except Exception as exc:
        return {"ok": False, "error": s.redact(exc)}


s.ha_request = ha_request

# Preserve the base redactor, then additionally hide the device MQTT resource
# segment that follows /cqyi87/ in diagnostic topic paths.
_base_redact = s.redact


def redact(value):
    text = _base_redact(value)
    text = re.sub(r"(/cqyi87/)[^/\s]+(/)", r"\1<redacted-resource>\2", text, flags=re.I)
    return text


s.redact = redact

# Stamp the actual package version into the UI regardless of the base server's
# source version.
for old_version in ("v1.8.0", "v1.8.1", "v1.9.0", "v1.9.1", "v1.9.2", "v1.9.3"):
    s.HTML = s.HTML.replace(old_version, "v1.9.4")

# Keep the room mapper focused on this Y1 PRO. The backend auto-selects when
# exactly one vacuum exists and refuses rather than commanding the wrong device
# when multiple vacuums exist.
s.HTML = s.HTML.replace(
    '<div class=roomTop><div><label>Vacuum</label><select id=roomVacuum><option value="">Loading...</option></select></div><div><label>Custom area ID</label>',
    '<div class=roomTop><div style="display:none"><select id=roomVacuum><option value=""></option></select></div><div><label>Custom area ID</label>',
)
s.HTML = s.HTML.replace(
    'function selectedVacuum(){return roomVacuum.value||null}',
    'function selectedVacuum(){return null}',
)
s.HTML = s.HTML.replace(
    "let current=roomVacuum.value;roomVacuum.innerHTML='';for(let e of (r.vacuum_entities||[])){let op=document.createElement('option');op.value=e.entity_id;op.textContent=(e.attributes&&e.attributes.friendly_name?e.attributes.friendly_name+' - ':'')+e.entity_id;roomVacuum.appendChild(op)}if(current)[...roomVacuum.options].forEach(x=>{if(x.value===current)x.selected=true});let saved=r.rooms||{};",
    "let saved=r.rooms||{};",
)

if __name__ == "__main__":
    s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{s.PORT}; HA API token: {token_state}",
        flush=True,
    )
    s.ThreadingHTTPServer(("0.0.0.0", s.PORT), s.Handler).serve_forever()
