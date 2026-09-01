#!/usr/bin/env python3
"""Runtime wrapper for DEEBOT Y1 PRO Diagnostics 2.0.1.

Keeps the diagnostics server intact while fixing Home Assistant API token
discovery, tightening telemetry redaction, simplifying the room mapper UI,
adding copy/map diagnostics actions, and generating the Y1 PRO 1.7.2 profile
with map improvements plus active startup availability/state bootstrap.
"""
import json
import os
import re
import urllib.request
from pathlib import Path

import server_y1_v160 as s

VERSION = "2.0.1"
s.VERSION = VERSION


def _read_token_file(path: str):
    try:
        value = Path(path).read_text().strip()
        return value or None
    except Exception:
        return None


def supervisor_token():
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


def build_profile_172():
    """Build 1.7.2 from known-good 1.6.5 protocol profile."""
    src = Path("/app/cqyi87_profile.py")
    dst = Path("/app/cqyi87_profile_172.py")
    text = src.read_text()

    text = text.replace(
        "import base64\nimport lzma\n",
        "import base64\nfrom collections import Counter\nimport logging\nimport lzma\n",
        1,
    )
    text = text.replace(
        'Y1PRO_PATCH_VERSION = "1.6.5"\n_Y1PRO_PAUSED = False\n_Y1PRO_CHARGE_STATUS: bool | None = None\n',
        'Y1PRO_PATCH_VERSION = "1.7.2"\n_Y1PRO_PAUSED = False\n_Y1PRO_CHARGE_STATUS: bool | None = None\n_Y1PRO_MAP_DIAG_LOGGED = False\n_LOGGER = logging.getLogger(__name__)\n',
        1,
    )

    old_pixel = '''def _pixel_index(value: int) -> int:\n    if value <= 0:\n        return 0\n    if value <= 5:\n        return value\n    return 6 + ((value - 6) % 6)\n'''
    new_pixel = '''def _pixel_index(value: int) -> int:\n    if value <= 0 or value in (4, 5):\n        return 0\n    if value <= 3:\n        return value\n    return 6 + ((value - 6) % 6)\n'''
    if old_pixel not in text:
        raise RuntimeError("Could not locate pixel mapping block")
    text = text.replace(old_pixel, new_pixel, 1)

    marker = '        y_max = float(map_data.get("yMax", 0))\n'
    replacement = marker + '        unit_scale = 10.0 if 0 < resolution <= 10 else 1.0\n'
    if marker not in text:
        raise RuntimeError("Could not locate Y1 map coordinate block")
    text = text.replace(marker, replacement, 1)
    text = text.replace(
        '        y_mm = y_max - (row * resolution)\n',
        '        y_mm = (y_max - (row * resolution)) * unit_scale\n',
        1,
    )
    text = text.replace(
        '            x_mm = x_min + (col * resolution)\n',
        '            x_mm = (x_min + (col * resolution)) * unit_scale\n',
        1,
    )

    diag_marker = '''    if len(raw) > expected:\n        raw = raw[-expected:]\n\n    pieces: dict[int, bytearray] = {}\n'''
    diag_replacement = '''    if len(raw) > expected:\n        raw = raw[-expected:]\n\n    global _Y1PRO_MAP_DIAG_LOGGED\n    if not _Y1PRO_MAP_DIAG_LOGGED:\n        counts = Counter(raw)\n        common = ",".join(f"{value}:{count}" for value, count in counts.most_common(24))\n        _LOGGER.warning(\n            "Y1PRO_MAP_DIAG width=%s height=%s resolution=%s unit_scale=%s compressed_bytes=%s decoded_bytes=%s expected_bytes=%s values=%s",\n            width, height, resolution, unit_scale, len(packed), len(raw), expected, common\n        )\n        _Y1PRO_MAP_DIAG_LOGGED = True\n\n    pieces: dict[int, bytearray] = {}\n'''
    if diag_marker not in text:
        raise RuntimeError("Could not locate map diagnostic insertion point")
    text = text.replace(diag_marker, diag_replacement, 1)

    area_marker = '''    if isinstance(data.get("areas"), list) and mid:\n        rooms: list[Room] = []\n'''
    area_replacement = '''    if isinstance(data.get("areas"), list) and mid:\n        map_meta = data.get("mapData") if isinstance(data.get("mapData"), dict) else {}\n        try:\n            area_resolution = float(map_meta.get("resolution", 50) or 50)\n        except Exception:\n            area_resolution = 50.0\n        area_scale = 10.0 if 0 < area_resolution <= 10 else 1.0\n        rooms: list[Room] = []\n'''
    if area_marker not in text:
        raise RuntimeError("Could not locate room block")
    text = text.replace(area_marker, area_replacement, 1)
    text = text.replace(
        '            rooms.append(Room(name=name, id=rid, coordinates=f"{area.get(\'centerX\', 0)},{area.get(\'centerY\', 0)}"))\n',
        '            try:\n                cx = int(round(float(area.get("centerX", 0)) * area_scale))\n                cy = int(round(float(area.get("centerY", 0)) * area_scale))\n            except Exception:\n                cx = cy = 0\n            rooms.append(Room(name=name, id=rid, coordinates=f"{cx},{cy}"))\n',
        1,
    )

    old_positions = '''    positions: list[Position] = []\n    pos = data.get("pos")\n    if isinstance(pos, dict):\n        try:\n            positions.append(Position(PositionType.DEEBOT, int(pos.get("x", 0)), int(pos.get("y", 0)), int(pos.get("a", 0))))\n        except Exception:\n            pass\n    map_data = data.get("mapData")\n    if isinstance(map_data, dict):\n        charge = map_data.get("chargePos")\n        if isinstance(charge, dict):\n            try:\n                positions.append(Position(PositionType.CHARGER, int(charge.get("x", 0)), int(charge.get("y", 0)), int(charge.get("a", 0))))\n            except Exception:\n                pass\n        if _emit_y1_raster(event_bus, map_data):\n            handled = True\n'''
    new_positions = '''    positions: list[Position] = []\n    map_data = data.get("mapData")\n    coord_scale = 1.0\n    if isinstance(map_data, dict):\n        try:\n            map_resolution = float(map_data.get("resolution", 50) or 50)\n            coord_scale = 10.0 if 0 < map_resolution <= 10 else 1.0\n        except Exception:\n            coord_scale = 1.0\n        charge = map_data.get("chargePos")\n        if isinstance(charge, dict):\n            try:\n                positions.append(Position(PositionType.CHARGER, int(round(float(charge.get("x", 0)) * coord_scale)), int(round(float(charge.get("y", 0)) * coord_scale)), int(charge.get("a", 0))))\n            except Exception:\n                pass\n        if _emit_y1_raster(event_bus, map_data):\n            handled = True\n    pos = data.get("pos")\n    if isinstance(pos, dict):\n        try:\n            positions.append(Position(PositionType.DEEBOT, int(round(float(pos.get("x", 0)) * coord_scale)), int(round(float(pos.get("y", 0)) * coord_scale)), int(pos.get("a", 0))))\n        except Exception:\n            pass\n'''
    if old_positions not in text:
        raise RuntimeError("Could not locate position block")
    text = text.replace(old_positions, new_positions, 1)

    old_init = '''    def __init__(self, fields: list[str] | tuple[str, ...]) -> None:\n        self.fields = tuple(str(field) for field in fields)\n        super().__init__({"fields": list(self.fields)})\n'''
    new_init = '''    def __init__(self, fields: list[str] | tuple[str, ...], is_available_check: bool = False, bootstrap_state: bool = False) -> None:\n        self.fields = tuple(str(field) for field in fields)\n        self.is_available_check = bool(is_available_check)\n        self.bootstrap_state = bool(bootstrap_state)\n        super().__init__({"fields": list(self.fields)})\n'''
    if old_init not in text:
        raise RuntimeError("Could not locate field-command constructor")
    text = text.replace(old_init, new_init, 1)

    old_return = '''        return Y1ProStateMessage._handle_body_data_dict(event_bus, data) if isinstance(data, dict) else HandlingResult.analyse()\n'''
    new_return = '''        if isinstance(data, dict):\n            if self.is_available_check:\n                event_bus.notify(AvailabilityEvent(True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n            if self.bootstrap_state and isinstance(data.get("chargeStatus"), bool) and data.get("chargeStatus") is False:\n                event_bus.notify(StateEvent(State.IDLE))\n                return HandlingResult.success()\n            return result\n        return HandlingResult.analyse()\n'''
    if old_return not in text:
        raise RuntimeError("Could not locate field-command response return")
    text = text.replace(old_return, new_return, 1)

    old_availability = '            availability=CapabilityEvent(AvailabilityEvent, []),\n'
    new_availability = '            availability=CapabilityEvent(AvailabilityEvent, [Y1ProFieldCommand(["battery"], is_available_check=True), Y1ProFieldCommand(["chargeStatus"], is_available_check=True, bootstrap_state=True)]),\n'
    if old_availability not in text:
        raise RuntimeError("Could not locate availability capability")
    text = text.replace(old_availability, new_availability, 1)

    dst.write_text(text)
    return dst


try:
    s.PROFILE_PATH = build_profile_172()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO 1.7.2 profile: {exc}", flush=True)


# Surface map decoder diagnostics directly in Run diagnosis output.
_base_diagnose = s.diagnose


def diagnose_with_map_diag():
    result = _base_diagnose()
    _, _, raw = s.get_logs("30m")
    result["y1pro_map_diagnostics"] = [
        s.redact(line) for line in raw if "Y1PRO_MAP_DIAG" in line
    ][-20:]
    return result


s.diagnose = diagnose_with_map_diag


for old_version in ("v1.8.0", "v1.8.1", "v1.9.0", "v1.9.1", "v1.9.2", "v1.9.3", "v1.9.4", "v1.9.5", "v1.9.6", "v1.9.7", "v1.9.8", "v1.9.9", "v2.0.0"):
    s.HTML = s.HTML.replace(old_version, "v2.0.1")

s.HTML = s.HTML.replace(
    '<div class=roomTop><div><label>Vacuum</label><select id=roomVacuum><option value="">Loading...</option></select></div><div><label>Custom area ID</label>',
    '<div class=roomTop><div style="display:none"><select id=roomVacuum><option value=""></option></select></div><div><label>Custom area ID</label>',
)
s.HTML = s.HTML.replace('function selectedVacuum(){return roomVacuum.value||null}', 'function selectedVacuum(){return null}')
s.HTML = s.HTML.replace(
    "let current=roomVacuum.value;roomVacuum.innerHTML='';for(let e of (r.vacuum_entities||[])){let op=document.createElement('option');op.value=e.entity_id;op.textContent=(e.attributes&&e.attributes.friendly_name?e.attributes.friendly_name+' - ':'')+e.entity_id;roomVacuum.appendChild(op)}if(current)[...roomVacuum.options].forEach(x=>{if(x.value===current)x.selected=true});let saved=r.rooms||{};",
    "let saved=r.rooms||{};",
)
s.HTML = s.HTML.replace(
    '<button class=primary onclick=call(\'diagnose\')>Run diagnosis</button>',
    '<button class=primary onclick=call(\'diagnose\')>Run diagnosis</button><button onclick=mapDiagnostics()>Map diagnostics</button>',
)
s.HTML = s.HTML.replace(
    '<section class="card full"><h2>Output</h2><pre id=o>Ready.</pre></section>',
    '<section class="card full"><div style="display:flex;justify-content:space-between;align-items:center;gap:12px"><h2>Output</h2><button id=copyOutputBtn onclick=copyOutput()>Copy</button></div><pre id=o>Ready.</pre></section>',
)
s.HTML = s.HTML.replace(
    "async function post(p,b={}",
    "async function copyOutput(){let text=o.textContent||'';try{await navigator.clipboard.writeText(text);let old=copyOutputBtn.textContent;copyOutputBtn.textContent='Copied';setTimeout(()=>copyOutputBtn.textContent=old,1200)}catch(e){let ta=document.createElement('textarea');ta.value=text;document.body.appendChild(ta);ta.select();document.execCommand('copy');ta.remove();copyOutputBtn.textContent='Copied';setTimeout(()=>copyOutputBtn.textContent='Copy',1200)}}async function mapDiagnostics(){let r=await post('./api/diagnose');out({version:r.version||null,y1pro_map_diagnostics:r.y1pro_map_diagnostics||[],map_protocol_lines:(r.map_protocol_lines||[]).slice(-80)})}async function post(p,b={}",
)

if __name__ == "__main__":
    s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{s.PORT}; HA API token: {token_state}", flush=True)
    s.ThreadingHTTPServer(("0.0.0.0", s.PORT), s.Handler).serve_forever()
