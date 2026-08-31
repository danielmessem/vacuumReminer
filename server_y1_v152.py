#!/usr/bin/env python3
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.5.2"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
CC = HA / "custom_components"
CUSTOM = CC / "ecovacs"
CLIENT_BACKUP_ROOT = HA / "ecovacs_doctor_client_backups"
PROFILE_PATH = Path("/app/cqyi87_profile.py")

MATCH = re.compile(
    r"ecovacs|deebot|beepbop|cqyi87|30000|mqtt|capabilities|clean_V2|setSpeed|"
    r"BatteryEvent|StateEvent|PositionsEvent|MapTraceEvent|FanSpeedEvent|"
    r"Error while setting up ecovacs",
    re.I,
)
TELEMETRY_MATCH = re.compile(
    r"30000|Received PUBLISH|Got message: topic=|Unknown message|BatteryEvent|"
    r"StateEvent|PositionsEvent|MapTraceEvent|FanSpeedEvent|AvailabilityEvent|"
    r"clean_V2|setSpeed|getBattery|getPos|getMapTrace|getChargeState|getWorkState",
    re.I,
)

SECRET = re.compile(
    r"(?i)(accessToken|refreshToken|authCode|token|api_key|secret)"
    r"(['\" ]*[:=]['\" ]*)[^,'\"\s}]+"
)
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
SERIAL = re.compile(r"\bE\d{14,}\b")
KEYED_ID = re.compile(
    r"(?i)(['\"]?(?:userId|userid|uid|ucUid|ecovacsUid|did|homeId|resource)['\"]?\s*[:=]\s*['\"])[^'\"\s,}]+(['\"])")
MQTT_CLIENT = re.compile(r"client_id=b?['\"][^'\"]+@ecouser/[^'\"]+['\"]", re.I)
MQTT_TOPIC_UUID = re.compile(r"(?<=/)[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}(?=/)")


def redact(value):
    s = str(value)
    s = EMAIL.sub("<redacted-email>", s)
    s = SECRET.sub(r"\1\2<redacted>", s)
    s = KEYED_ID.sub(r"\1<redacted>\2", s)
    s = UUID.sub("<redacted-device-id>", s)
    s = SERIAL.sub("<redacted-serial>", s)
    s = MQTT_CLIENT.sub("client_id='<redacted-mqtt-client>'", s)
    s = MQTT_TOPIC_UUID.sub("<redacted-device-id>", s)
    return s


def docker(args, timeout=35):
    try:
        p = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as exc:
        return 99, "", str(exc)


def core():
    _, out, _ = docker(["ps", "--format", "{{.ID}}\t{{.Names}}"])
    for line in out.splitlines():
        parts = line.split("\t", 1)
        if len(parts) == 2 and "homeassistant" in parts[1].lower():
            return parts[0], parts[1]
    return None, None


def core_exec(args, timeout=30):
    cid, _ = core()
    if not cid:
        return {"ok": False, "error": "Home Assistant Core container not found"}
    rc, out, err = docker(["exec", cid] + args, timeout)
    return {"ok": rc == 0, "stdout": redact(out), "stderr": redact(err), "rc": rc}


def client_paths():
    result = core_exec([
        "python", "-c",
        'import pathlib,deebot_client;p=pathlib.Path(deebot_client.__file__).parent;print(p);print(p/"hardware"/"cqyi87.py")'
    ])
    lines = [x.strip() for x in result.get("stdout", "").splitlines() if x.strip()]
    return {
        "ok": bool(result.get("ok") and len(lines) >= 2),
        "package": lines[0] if lines else None,
        "target": lines[1] if len(lines) > 1 else None,
        "detail": result,
    }


def patch_status():
    paths = client_paths()
    if not paths["ok"]:
        return paths
    result = core_exec([
        "sh", "-c",
        f"if [ -f '{paths['target']}' ]; then grep 'Y1PRO_PATCH_VERSION' '{paths['target']}' || true; else echo MISSING; fi"
    ])
    detail = result.get("stdout", "").strip()
    return {
        "ok": True,
        "target": paths["target"],
        "installed": "Y1PRO_PATCH_VERSION" in detail,
        "detail": detail,
    }


def install_patch():
    paths = client_paths()
    if not paths["ok"]:
        return {"ok": False, "message": "Could not locate deebot-client", "detail": paths}
    if not PROFILE_PATH.exists():
        return {"ok": False, "message": "Bundled cqyi87 profile is missing"}

    cid, _ = core()
    target = paths["target"]
    CLIENT_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = CLIENT_BACKUP_ROOT / f"cqyi87-{stamp}.py"
    absent = CLIENT_BACKUP_ROOT / f"cqyi87-{stamp}.absent"

    exists = core_exec(["sh", "-c", f"test -f '{target}'"])
    if exists.get("ok"):
        rc, _, err = docker(["cp", f"{cid}:{target}", str(backup)])
        if rc:
            return {"ok": False, "message": "Backup failed", "error": redact(err)}
    else:
        absent.write_text("absent before patch\n")

    rc, _, err = docker(["cp", str(PROFILE_PATH), f"{cid}:{target}"])
    if rc:
        return {"ok": False, "message": "Copy failed", "error": redact(err)}

    verify_code = (
        "import importlib;importlib.invalidate_caches();"
        "m=importlib.import_module('deebot_client.hardware.cqyi87');"
        "i=m.get_device_info();c=i.capabilities;"
        "print(m.Y1PRO_PATCH_VERSION);print(i.data_type);print(c.device_type);"
        "print('life_span_types='+str(len(c.life_span.types)));"
        "print('stats_safe='+str(c.stats is not None))"
    )
    verify = core_exec(["python", "-c", verify_code])
    if not verify.get("ok"):
        if backup.exists():
            docker(["cp", str(backup), f"{cid}:{target}"])
        else:
            core_exec(["sh", "-c", f"rm -f '{target}'"])
        return {"ok": False, "message": "Validation failed; rolled back", "validation": verify}

    return {
        "ok": True,
        "message": "Y1 PRO cqyi87 profile installed. Restart Core next.",
        "target": target,
        "validation": verify,
    }


def rollback():
    paths = client_paths()
    if not paths["ok"]:
        return {"ok": False, "message": "Could not locate deebot-client"}
    cid, _ = core()
    target = paths["target"]
    items = sorted(
        list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.py")) +
        list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.absent")),
        reverse=True,
    )
    if not items:
        return {"ok": False, "message": "No backup found"}
    latest = items[0]
    if latest.suffix == ".absent":
        result = core_exec(["sh", "-c", f"rm -f '{target}'"])
        return {"ok": result.get("ok", False), "message": "Patch removed. Restart Core next.", "detail": result}
    rc, _, err = docker(["cp", str(latest), f"{cid}:{target}"])
    return {"ok": rc == 0, "message": "Previous cqyi87.py restored. Restart Core next.", "error": redact(err)}


def quarantine():
    moved = []
    backup_root = HA / "ecovacs_doctor_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    candidates = []
    if CUSTOM.exists():
        candidates.append(CUSTOM)
    if CC.exists():
        candidates += list(CC.glob("ecovacs.disabled-*"))
    for src in candidates:
        dst = backup_root / f"ecovacs-{datetime.now():%Y%m%d-%H%M%S-%f}-{src.name}"
        shutil.move(str(src), str(dst))
        moved.append({"from": str(src), "to": str(dst)})
    return {"ok": True, "moved": moved}


def restart():
    cid, _ = core()
    if not cid:
        return {"ok": False, "message": "Core not found"}
    rc, _, err = docker(["restart", cid], 40)
    return {"ok": rc == 0, "message": "Restart requested" if rc == 0 else redact(err)}


def get_logs(since="30m"):
    cid, name = core()
    if not cid:
        return None, None, []
    _, out, err = docker(["logs", "--since", since, cid], 45)
    return cid, name, (out + err).splitlines()


def capture_telemetry():
    cid, name, raw = get_logs("20m")
    if not cid:
        return {"ok": False, "message": "Core not found"}

    selected = [redact(line) for line in raw if TELEMETRY_MATCH.search(line)]
    selected = selected[-5000:]
    lower = "\n".join(selected).lower()

    summary = {
        "message_30000_seen": '30000' in lower,
        "unknown_30000_seen": 'unknown message "30000"' in lower,
        "fan_speed_event_seen": "fanspeedevent" in lower,
        "state_event_seen": "stateevent" in lower,
        "battery_event_seen": "batteryevent" in lower,
        "position_event_seen": "positionsevent" in lower,
        "map_trace_event_seen": "maptraceevent" in lower,
        "availability_true_seen": "availabilityevent(available=true)" in lower,
        "clean_response_seen": "clean_v2" in lower and '"code":0' in lower.replace(" ", ""),
    }

    payload_lines = [
        line for line in selected
        if "got message: topic=" in line.lower() or "unknown message" in line.lower()
    ]
    event_lines = [
        line for line in selected
        if "notify subscribers with" in line.lower() or "event is the same" in line.lower()
    ]

    report = {
        "version": VERSION,
        "generated": datetime.now().isoformat(),
        "window": "20m",
        "summary": summary,
        "payload_lines": payload_lines[-1200:],
        "event_lines": event_lines[-1200:],
        "core_candidate": {"id": "<redacted-container-id>", "name": name},
    }

    SHARE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = SHARE / f"deebot-y1pro-telemetry-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("TELEMETRY_REPORT.json", json.dumps(report, indent=2))
        z.writestr("PAYLOAD_LINES.txt", "\n".join(payload_lines[-1200:]))
        z.writestr("EVENT_LINES.txt", "\n".join(event_lines[-1200:]))
    report["file"] = str(out)
    return report


def diagnose():
    cid, name, raw = get_logs("30m")
    logs = [redact(x) for x in raw if MATCH.search(x)][-12000:] if cid else []
    lower = [x.lower() for x in logs]

    last_supported = max((i for i, x in enumerate(lower) if "capabilities found for cqyi87" in x), default=-1)
    last_unsupported = max((i for i, x in enumerate(lower) if 'device class "cqyi87" not recognized' in x or "no capabilities found for cqyi87" in x), default=-1)
    after = lower[last_supported + 1:] if last_supported >= 0 else lower
    joined_after = "\n".join(after)
    findings = []

    if last_unsupported > last_supported:
        findings.append({"severity": "HIGH", "code": "CQYI87_UNSUPPORTED", "action": "Install Y1 PRO patch and restart Core."})
    elif last_supported >= 0:
        findings.append({"severity": "INFO", "code": "CQYI87_PROFILE_ACTIVE", "meaning": "Home Assistant found the Y1 PRO capability profile."})

    if "error while setting up ecovacs platform" in joined_after:
        findings.append({"severity": "HIGH", "code": "CURRENT_ECOVACS_PLATFORM_ERROR", "action": "Review the latest Ecovacs platform traceback."})
    if 'unknown message "30000"' in joined_after:
        findings.append({"severity": "MEDIUM", "code": "Y1PRO_TELEMETRY_30000", "action": "Use Capture Y1 PRO telemetry and share the result."})
    if "fanspeedevent" in joined_after:
        findings.append({"severity": "INFO", "code": "FAN_SPEED_EVENT_CONFIRMED", "meaning": "Fan-speed commands are producing Home Assistant events."})
    if "success calling api" in joined_after and "'cmdname': 'clean_v2'" in joined_after:
        findings.append({"severity": "INFO", "code": "CLEAN_COMMAND_CONFIRMED", "meaning": "The robot acknowledged clean_V2 successfully."})
    if "adding ecovacs vacuums to home assistant:" in joined_after:
        findings.append({"severity": "INFO", "code": "VACUUM_PLATFORM_REACHED", "meaning": "Home Assistant reached the Ecovacs vacuum platform."})
    if not findings:
        findings.append({"severity": "INFO", "code": "NO_CURRENT_KNOWN_FAILURE"})

    report = {
        "version": VERSION,
        "generated": datetime.now().isoformat(),
        "environment": {
            "ha_version": core_exec(["python", "-c", "from homeassistant.const import __version__;print(__version__)"]),
            "deebot_client": core_exec(["python", "-c", 'import importlib.metadata as m;print(m.version("deebot-client"))']),
            "y1pro_patch": patch_status(),
        },
        "custom_component": {"present": CUSTOM.is_dir()},
        "findings": findings,
        "matched_logs": logs,
        "core_candidates": [{"id": "<redacted-container-id>", "name": name}] if cid else [],
    }

    SHARE.mkdir(parents=True, exist_ok=True)
    out = SHARE / f"deebot-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("REPORT.json", json.dumps(report, indent=2))
        z.writestr("MATCHED_CORE_LOG.txt", "\n".join(logs))
    report["file"] = str(out)
    return report


HTML = """<!doctype html><meta name=viewport content='width=device-width'><title>DEEBOT Y1 PRO Tools</title>
<style>body{font-family:system-ui;max-width:1050px;margin:24px auto;padding:0 18px;background:#111827;color:#e5e7eb}button{padding:11px 14px;margin:5px;border:0;border-radius:8px;font-weight:650}.p{background:#2563eb;color:white}.g{background:#16a34a;color:white}.w{background:#f59e0b}.d{background:#ef4444;color:white}.t{background:#7c3aed;color:white}pre{background:#030712;padding:14px;white-space:pre-wrap;max-height:650px;overflow:auto;border-radius:8px}</style>
<h1>DEEBOT Y1 PRO Diagnostics & Patch Manager</h1><p>Version <b>1.5.2</b></p>
<button class=p onclick="go('./api/diagnose')">Run full diagnosis</button>
<button class=t onclick="go('./api/telemetry')">Capture Y1 PRO telemetry</button>
<button class=g onclick="ask('./api/install','Install/update targeted cqyi87 profile? A rollback point will be created.')">Install Y1 PRO patch</button>
<button class=w onclick="ask('./api/rollback','Rollback latest Y1 PRO patch?')">Rollback Y1 PRO patch</button>
<button onclick="ask('./api/quarantine','Quarantine any custom Ecovacs copies?')">Quarantine custom Ecovacs</button>
<button class=d onclick="ask('./api/restart','Restart Home Assistant Core now?')">Restart Core</button>
<pre id=o>Ready.</pre>
<script>async function go(u){o.textContent='Working...';try{let r=await fetch(u,{method:'POST'});o.textContent=JSON.stringify(await r.json(),null,2)}catch(e){o.textContent=String(e)}}function ask(u,m){if(confirm(m))go(u)}</script>"""


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("", "/"):
            return self.send_json(200, HTML, "text/html; charset=utf-8")
        return self.send_json(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/diagnose":
                result = diagnose()
            elif path == "/api/telemetry":
                result = capture_telemetry()
            elif path == "/api/install":
                result = install_patch()
            elif path == "/api/rollback":
                result = rollback()
            elif path == "/api/quarantine":
                result = quarantine()
            elif path == "/api/restart":
                result = restart()
            else:
                return self.send_json(404, json.dumps({"error": "not found"}))
            return self.send_json(200, json.dumps(result, indent=2))
        except Exception as exc:
            return self.send_json(500, json.dumps({"error": redact(exc)}))

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
