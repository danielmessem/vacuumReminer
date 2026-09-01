#!/usr/bin/env python3
"""Runtime wrapper for DEEBOT Y1 PRO Diagnostics 1.9.8.

Keeps the main diagnostics server intact while fixing Home Assistant API token
discovery, tightening telemetry redaction, simplifying the room mapper UI,
adding a copy button for diagnostic output, and generating the Y1 PRO 1.6.6
profile with corrected map coordinate units.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

import server_y1_v160 as s

VERSION = "1.9.8"
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

_base_redact = s.redact


def redact(value):
    text = _base_redact(value)
    text = re.sub(r"(/cqyi87/)[^/\s]+(/)", r"\1<redacted-resource>\2", text, flags=re.I)
    return text


s.redact = redact


# Build the 1.6.6 profile from the known-good 1.6.5 source. The Y1 map metadata
# uses centimetre-scale coordinates when resolution is a small value (observed
# as 5). deebot-client's native renderer expects millimetres, so 1.6.5 rendered
# a recognisable map about 10x too small internally, making every raster cell
# appear huge. Expand those map coordinates by 10 before mapping to the native
# 50 mm grid. Vacuum command/state protocol is intentionally unchanged.
def build_scaled_profile():
    src = Path("/app/cqyi87_profile.py")
    dst = Path("/app/cqyi87_profile_166.py")
    text = src.read_text()
    text = text.replace('Y1PRO_PATCH_VERSION = "1.6.5"', 'Y1PRO_PATCH_VERSION = "1.6.6"', 1)
    marker = '        y_max = float(map_data.get("yMax", 0))\n'
    replacement = (
        marker
        + '        # Y1 map coordinates are centimetre-scale when resolution is small.\n'
        + '        # Native deebot-client map coordinates are millimetres.\n'
        + '        unit_scale = 10.0 if 0 < resolution <= 10 else 1.0\n'
    )
    if marker not in text:
        raise RuntimeError("Could not locate Y1 map coordinate block")
    text = text.replace(marker, replacement, 1)
    old_y = '        y_mm = y_max - (row * resolution)\n'
    new_y = '        y_mm = (y_max - (row * resolution)) * unit_scale\n'
    old_x = '            x_mm = x_min + (col * resolution)\n'
    new_x = '            x_mm = (x_min + (col * resolution)) * unit_scale\n'
    if old_y not in text or old_x not in text:
        raise RuntimeError("Could not locate Y1 raster scale formulas")
    text = text.replace(old_y, new_y, 1).replace(old_x, new_x, 1)
    dst.write_text(text)
    return dst


try:
    s.PROFILE_PATH = build_scaled_profile()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO 1.6.6 profile: {exc}", flush=True)


for old_version in ("v1.8.0", "v1.8.1", "v1.9.0", "v1.9.1", "v1.9.2", "v1.9.3", "v1.9.4", "v1.9.5", "v1.9.6", "v1.9.7"):
    s.HTML = s.HTML.replace(old_version, "v1.9.8")

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

# Add a copy action directly above the shared JSON output panel.
s.HTML = s.HTML.replace(
    '<section class="card full"><h2>Output</h2><pre id=o>Ready.</pre></section>',
    '<section class="card full"><div style="display:flex;justify-content:space-between;align-items:center;gap:12px"><h2>Output</h2><button id=copyOutputBtn onclick=copyOutput()>Copy</button></div><pre id=o>Ready.</pre></section>',
)
s.HTML = s.HTML.replace(
    "async function post(p,b={}",
    "async function copyOutput(){let text=o.textContent||'';try{await navigator.clipboard.writeText(text);let old=copyOutputBtn.textContent;copyOutputBtn.textContent='Copied';setTimeout(()=>copyOutputBtn.textContent=old,1200)}catch(e){let ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();copyOutputBtn.textContent='Copied';setTimeout(()=>copyOutputBtn.textContent='Copy',1200)}}async function post(p,b={}",
)

if __name__ == "__main__":
    s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{s.PORT}; HA API token: {token_state}",
        flush=True,
    )
    s.ThreadingHTTPServer(("0.0.0.0", s.PORT), s.Handler).serve_forever()
