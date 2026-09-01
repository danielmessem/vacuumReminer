#!/usr/bin/env python3
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.6.0"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
CC = HA / "custom_components"
CUSTOM = CC / "ecovacs"
CLIENT_BACKUP_ROOT = HA / "ecovacs_doctor_client_backups"
PROFILE_PATH = Path("/app/cqyi87_profile.py")
OBS_FILE = SHARE / "deebot-y1pro-observations.jsonl"
ACTIVE_FILE = SHARE / "deebot-y1pro-active-observation.json"

MATCH = re.compile(
    r"ecovacs|deebot|beepbop|cqyi87|30000|mqtt|capabilities|clean_V2|setSpeed|"
    r"BatteryEvent|StateEvent|PositionsEvent|MapTraceEvent|FanSpeedEvent|"
    r"Error while setting up ecovacs",
    re.I,
)
TELEMETRY_MATCH = re.compile(
    r"30000|Received PUBLISH|Got message: topic=|Unknown message|BatteryEvent|"
    r"StateEvent|PositionsEvent|MapTraceEvent|FanSpeedEvent|AvailabilityEvent|"
    r"clean_V2|setSpeed|getBattery|getPos|getMapTrace|getChargeState|getWorkState|"
    r"40001|40009|40011|40013|10000|10001",
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


def now_iso():
    return datetime.now().astimezone().isoformat()


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
    return {"ok": True, "target": paths["target"], "installed": "Y1PRO_PATCH_VERSION" in detail, "detail": detail}


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
    return {"ok": True, "message": "Y1 PRO cqyi87 profile installed. Restart Core next.", "target": target, "validation": verify}


def rollback():
    paths = client_paths()
    if not paths["ok"]:
        return {"ok": False, "message": "Could not locate deebot-client"}
    cid, _ = core()
    target = paths["target"]
    items = sorted(list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.py")) + list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.absent")), reverse=True)
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
    if CUSTOM.exists(): candidates.append(CUSTOM)
    if CC.exists(): candidates += list(CC.glob("ecovacs.disabled-*"))
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


def load_observations(hours=24):
    if not OBS_FILE.exists():
        return []
    cutoff = datetime.now().astimezone() - timedelta(hours=hours)
    rows = []
    for line in OBS_FILE.read_text(errors="replace").splitlines():
        try:
            row = json.loads(line)
            finished = datetime.fromisoformat(row.get("finished_at", row.get("started_at")))
            if finished >= cutoff:
                rows.append(row)
        except Exception:
            continue
    return rows[-100:]


def observation_start(attempted_action):
    SHARE.mkdir(parents=True, exist_ok=True)
    rec = {"started_at": now_iso(), "attempted_action": str(attempted_action or "unspecified")[:80]}
    ACTIVE_FILE.write_text(json.dumps(rec, indent=2))
    return {"ok": True, "message": "Observation capture started", **rec}


def observation_finish(physical_result, notes=""):
    if not ACTIVE_FILE.exists():
        return {"ok": False, "message": "No active observation. Press Start capture first."}
    try:
        rec = json.loads(ACTIVE_FILE.read_text())
    except Exception:
        rec = {"started_at": now_iso(), "attempted_action": "unknown"}
    rec["finished_at"] = now_iso()
    rec["physical_result"] = str(physical_result or "unspecified")[:100]
    rec["notes"] = str(notes or "")[:500]
    _, _, raw = get_logs("3m")
    selected = [redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-300:]
    rec["diagnostic_log_lines"] = selected
    with OBS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try: ACTIVE_FILE.unlink()
    except Exception: pass
    return {"ok": True, "message": "Observation saved and will be included in telemetry exports", "observation": rec}


def capture_telemetry():
    cid, name, raw = get_logs("20m")
    if not cid:
        return {"ok": False, "message": "Core not found"}
    selected = [redact(line) for line in raw if TELEMETRY_MATCH.search(line)][-5000:]
    lower = "\n".join(selected).lower()
    summary = {
        "message_30000_seen": "30000" in lower,
        "unknown_30000_seen": 'unknown message "30000"' in lower,
        "fan_speed_event_seen": "fanspeedevent" in lower,
        "state_event_seen": "stateevent" in lower,
        "battery_event_seen": "batteryevent" in lower,
        "position_event_seen": "positionsevent" in lower,
        "map_trace_event_seen": "maptraceevent" in lower,
        "availability_true_seen": "availabilityevent(available=true)" in lower,
        "clean_response_seen": "clean_v2" in lower and '"code":0' in lower.replace(" ", ""),
    }
    payload_lines = [line for line in selected if "got message: topic=" in line.lower() or "unknown message" in line.lower()]
    event_lines = [line for line in selected if "notify subscribers with" in line.lower() or "event is the same" in line.lower()]
    observations = load_observations(24)
    markers = [
        "USER_OBSERVATION " + json.dumps({k: v for k, v in obs.items() if k != "diagnostic_log_lines"}, ensure_ascii=False)
        for obs in observations
    ]
    report = {
        "version": VERSION,
        "generated": now_iso(),
        "window": "20m",
        "summary": summary,
        "observations": observations,
        "payload_lines": payload_lines[-1200:],
        "event_lines": event_lines[-1200:],
        "core_candidate": {"id": "<redacted-container-id>", "name": name},
    }
    SHARE.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = SHARE / f"deebot-y1pro-telemetry-{stamp}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("TELEMETRY_REPORT.json", json.dumps(report, indent=2))
        z.writestr("PAYLOAD_LINES.txt", "\n".join(markers + payload_lines[-1200:]))
        z.writestr("EVENT_LINES.txt", "\n".join(event_lines[-1200:]))
        z.writestr("USER_OBSERVATIONS.json", json.dumps(observations, indent=2))
    report["file"] = str(out)
    return report


def diagnose():
    cid, name, raw = get_logs("30m")
    logs = [redact(x) for x in raw if MATCH.search(x)][-12000:] if cid else []
    lower = [x.lower() for x in logs]
    last_supported = max((i for i, x in enumerate(lower) if "capabilities found for cqyi87" in x), default=-1)
    last_unsupported = max((i for i, x in enumerate(lower) if 'device class "cqyi87" not recognized' in x or "no capabilities found for cqyi87" in x), default=-1)
    findings = []
    if last_unsupported > last_supported:
        findings.append({"severity": "HIGH", "code": "CQYI87_UNSUPPORTED", "action": "Install Y1 PRO patch and restart Core."})
    elif last_supported >= 0:
        findings.append({"severity": "INFO", "code": "CQYI87_PROFILE_ACTIVE", "meaning": "Home Assistant found the Y1 PRO capability profile."})
    if not findings:
        findings.append({"severity": "INFO", "code": "NO_CURRENT_KNOWN_FAILURE"})
    report = {
        "version": VERSION,
        "generated": now_iso(),
        "environment": {
            "ha_version": core_exec(["python", "-c", "from homeassistant.const import __version__;print(__version__)"]),
            "deebot_client": core_exec(["python", "-c", 'import importlib.metadata as m;print(m.version("deebot-client"))']),
            "y1pro_patch": patch_status(),
        },
        "custom_component": {"present": CUSTOM.is_dir()},
        "findings": findings,
        "observations": load_observations(24),
        "matched_logs": logs,
        "core_candidates": [{"id": "<redacted-container-id>", "name": name}] if cid else [],
    }
    SHARE.mkdir(parents=True, exist_ok=True)
    out = SHARE / f"deebot-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("REPORT.json", json.dumps(report, indent=2))
        z.writestr("MATCHED_CORE_LOG.txt", "\n".join(logs))
        z.writestr("USER_OBSERVATIONS.json", json.dumps(report["observations"], indent=2))
    report["file"] = str(out)
    return report


HTML = """<!doctype html><meta name=viewport content='width=device-width'><title>DEEBOT Y1 PRO Tools</title>
<style>body{font-family:system-ui;max-width:1050px;margin:24px auto;padding:0 18px;background:#111827;color:#e5e7eb}button,select,input{padding:11px 14px;margin:5px;border:0;border-radius:8px;font-weight:650}.p{background:#2563eb;color:white}.g{background:#16a34a;color:white}.w{background:#f59e0b}.d{background:#ef4444;color:white}.t{background:#7c3aed;color:white}.card{border:1px solid #374151;border-radius:10px;padding:14px;margin:14px 0;background:#1f2937}select,input{background:#fff;color:#111827;max-width:95%}pre{background:#030712;padding:14px;white-space:pre-wrap;max-height:650px;overflow:auto;border-radius:8px}.hint{color:#9ca3af;font-size:.92rem}</style>
<h1>DEEBOT Y1 PRO Diagnostics & Patch Manager</h1><p>Version <b>1.6.0</b></p>
<div class=card><h2>Guided protocol test</h2><p class=hint>1. Choose the action you are about to trigger. 2. Start capture. 3. Trigger it in HA or the Ecovacs app. 4. Select what the robot physically did and save.</p>
<select id=attempt><option>Start cleaning</option><option>Pause</option><option>Resume</option><option>Return to dock</option><option>Stop cleaning</option><option>Fan speed - Quiet</option><option>Fan speed - Normal</option><option>Fan speed - Max</option><option>Other official app action</option></select>
<button class=p onclick='startObs()'>Start capture</button><br>
<select id=result><option>Started cleaning</option><option>Paused</option><option>Resumed cleaning</option><option>Returned to dock</option><option>Stopped cleaning</option><option>Changed fan speed</option><option>No physical response</option><option>Other / unexpected</option></select>
<input id=notes placeholder='Optional note, e.g. HA said Cleaning but robot stayed still'>
<button class=g onclick='finishObs()'>Save physical result</button><p id=obs>Ready for a protocol test.</p></div>
<button class=p onclick="go('./api/diagnose')">Run full diagnosis</button>
<button class=t onclick="go('./api/telemetry')">Capture Y1 PRO telemetry</button>
<button class=g onclick="ask('./api/install','Install/update targeted cqyi87 profile? A rollback point will be created.')">Install Y1 PRO patch</button>
<button class=w onclick="ask('./api/rollback','Rollback latest Y1 PRO patch?')">Rollback Y1 PRO patch</button>
<button onclick="ask('./api/quarantine','Quarantine any custom Ecovacs copies?')">Quarantine custom Ecovacs</button>
<button class=d onclick="ask('./api/restart','Restart Home Assistant Core now?')">Restart Core</button>
<pre id=o>Ready.</pre>
<script>
async function post(u,b){let r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):null});return await r.json()}
async function go(u){o.textContent='Working...';try{o.textContent=JSON.stringify(await post(u),null,2)}catch(e){o.textContent=String(e)}}
function ask(u,m){if(confirm(m))go(u)}
async function startObs(){try{let j=await post('./api/observe/start',{attempted_action:attempt.value});obs.textContent='CAPTURING: '+j.attempted_action+' — now perform the action.';o.textContent=JSON.stringify(j,null,2)}catch(e){obs.textContent=String(e)}}
async function finishObs(){try{let j=await post('./api/observe/finish',{physical_result:result.value,notes:notes.value});obs.textContent=j.ok?'Saved. You can run another test or export telemetry.':j.message;o.textContent=JSON.stringify(j,null,2)}catch(e){obs.textContent=String(e)}}
</script>"""


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, body, ctype="application/json"):
        if isinstance(body, str): body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        try:
            n = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
        except Exception:
            return {}

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("", "/"):
            return self.send_json(200, HTML, "text/html; charset=utf-8")
        return self.send_json(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            body = self.read_json()
            if path == "/api/diagnose": result = diagnose()
            elif path == "/api/telemetry": result = capture_telemetry()
            elif path == "/api/install": result = install_patch()
            elif path == "/api/rollback": result = rollback()
            elif path == "/api/quarantine": result = quarantine()
            elif path == "/api/restart": result = restart()
            elif path == "/api/observe/start": result = observation_start(body.get("attempted_action"))
            elif path == "/api/observe/finish": result = observation_finish(body.get("physical_result"), body.get("notes", ""))
            else: return self.send_json(404, json.dumps({"error": "not found"}))
            return self.send_json(200, json.dumps(result, indent=2))
        except Exception as exc:
            return self.send_json(500, json.dumps({"error": redact(exc)}))

    def log_message(self, *args):
        pass


SHARE.mkdir(parents=True, exist_ok=True)
ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
