#!/usr/bin/env python3
import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.6.1"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
CC = HA / "custom_components"
CUSTOM = CC / "ecovacs"
CLIENT_BACKUP_ROOT = HA / "ecovacs_doctor_client_backups"
PROFILE_PATH = Path("/app/cqyi87_profile.py")
OBS_FILE = SHARE / "deebot-y1pro-observations.jsonl"
ACTIVE_FILE = SHARE / "deebot-y1pro-active-observation.json"
SUPERVISOR = "http://supervisor/core/api"

TELEMETRY_MATCH = re.compile(
    r"ecovacs|deebot|cqyi87|mqtt|Received PUBLISH|Got message: topic=|Unknown message|"
    r"BatteryEvent|StateEvent|FanSpeedEvent|AvailabilityEvent|clean_V2|setSpeed|"
    r"40001|40009|40011|40013|10000|10001|onFwBuryPoint",
    re.I,
)
SECRET = re.compile(r"(?i)(accessToken|refreshToken|authCode|token|api_key|secret)(['\" ]*[:=]['\" ]*)[^,'\"\s}]+")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
SERIAL = re.compile(r"\bE\d{14,}\b")
KEYED_ID = re.compile(r"(?i)(['\"]?(?:userId|userid|uid|ucUid|ecovacsUid|did|homeId|resource)['\"]?\s*[:=]\s*['\"])[^'\"\s,}]+(['\"])")
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
    r = core_exec(["python", "-c", 'import pathlib,deebot_client;p=pathlib.Path(deebot_client.__file__).parent;print(p);print(p/"hardware"/"cqyi87.py")'])
    lines = [x.strip() for x in r.get("stdout", "").splitlines() if x.strip()]
    return {"ok": bool(r.get("ok") and len(lines) >= 2), "package": lines[0] if lines else None, "target": lines[1] if len(lines) > 1 else None, "detail": r}


def patch_status():
    p = client_paths()
    if not p["ok"]: return p
    r = core_exec(["sh", "-c", f"if [ -f '{p['target']}' ]; then grep 'Y1PRO_PATCH_VERSION' '{p['target']}' || true; else echo MISSING; fi"])
    detail = r.get("stdout", "").strip()
    return {"ok": True, "target": p["target"], "installed": "Y1PRO_PATCH_VERSION" in detail, "detail": detail}


def install_patch():
    p = client_paths()
    if not p["ok"]: return {"ok": False, "message": "Could not locate deebot-client", "detail": p}
    if not PROFILE_PATH.exists(): return {"ok": False, "message": "Bundled cqyi87 profile is missing"}
    cid, _ = core(); target = p["target"]
    CLIENT_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = CLIENT_BACKUP_ROOT / f"cqyi87-{stamp}.py"
    absent = CLIENT_BACKUP_ROOT / f"cqyi87-{stamp}.absent"
    if core_exec(["sh", "-c", f"test -f '{target}'"]).get("ok"):
        rc, _, err = docker(["cp", f"{cid}:{target}", str(backup)])
        if rc: return {"ok": False, "message": "Backup failed", "error": redact(err)}
    else: absent.write_text("absent before patch\n")
    rc, _, err = docker(["cp", str(PROFILE_PATH), f"{cid}:{target}"])
    if rc: return {"ok": False, "message": "Copy failed", "error": redact(err)}
    verify = core_exec(["python", "-c", "import importlib;importlib.invalidate_caches();m=importlib.import_module('deebot_client.hardware.cqyi87');i=m.get_device_info();print(m.Y1PRO_PATCH_VERSION);print(i.data_type);print(i.capabilities.device_type)"])
    if not verify.get("ok"):
        if backup.exists(): docker(["cp", str(backup), f"{cid}:{target}"])
        else: core_exec(["sh", "-c", f"rm -f '{target}'"])
        return {"ok": False, "message": "Validation failed; rolled back", "validation": verify}
    return {"ok": True, "message": "Y1 PRO cqyi87 profile installed. Restart Core next.", "validation": verify}


def rollback():
    p = client_paths()
    if not p["ok"]: return {"ok": False, "message": "Could not locate deebot-client"}
    cid, _ = core(); target = p["target"]
    items = sorted(list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.py")) + list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.absent")), reverse=True)
    if not items: return {"ok": False, "message": "No backup found"}
    latest = items[0]
    if latest.suffix == ".absent":
        r = core_exec(["sh", "-c", f"rm -f '{target}'"])
        return {"ok": r.get("ok", False), "message": "Patch removed. Restart Core next."}
    rc, _, err = docker(["cp", str(latest), f"{cid}:{target}"])
    return {"ok": rc == 0, "message": "Previous cqyi87.py restored. Restart Core next.", "error": redact(err)}


def quarantine():
    moved = []
    root = HA / "ecovacs_doctor_backups"; root.mkdir(parents=True, exist_ok=True)
    candidates = ([CUSTOM] if CUSTOM.exists() else []) + (list(CC.glob("ecovacs.disabled-*")) if CC.exists() else [])
    for src in candidates:
        dst = root / f"ecovacs-{datetime.now():%Y%m%d-%H%M%S-%f}-{src.name}"
        shutil.move(str(src), str(dst)); moved.append({"from": str(src), "to": str(dst)})
    return {"ok": True, "moved": moved}


def restart():
    cid, _ = core()
    if not cid: return {"ok": False, "message": "Core not found"}
    rc, _, err = docker(["restart", cid], 40)
    return {"ok": rc == 0, "message": "Restart requested" if rc == 0 else redact(err)}


def get_logs(since="30m"):
    cid, name = core()
    if not cid: return None, None, []
    _, out, err = docker(["logs", "--since", since, cid], 45)
    return cid, name, (out + err).splitlines()


def ha_api(path, method="GET", payload=None):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token: return {"ok": False, "error": "SUPERVISOR_TOKEN unavailable"}
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(SUPERVISOR + path, data=data, method=method, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try: body = json.loads(raw) if raw else None
            except Exception: body = raw
            return {"ok": True, "status": resp.status, "data": body}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.read().decode("utf-8", "replace")[:2000]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def vacuum_entity():
    r = ha_api("/states")
    if not r.get("ok") or not isinstance(r.get("data"), list): return None
    vacs = [x for x in r["data"] if str(x.get("entity_id", "")).startswith("vacuum.")]
    for x in vacs:
        txt = json.dumps(x).lower()
        if "beepbop" in txt or "ecovacs" in txt or "deebot" in txt: return x["entity_id"]
    return vacs[0]["entity_id"] if len(vacs) == 1 else None


ACTION_SERVICE = {
    "Start cleaning": "start",
    "Pause": "pause",
    "Resume": "start",
    "Return to dock": "return_to_base",
    "Stop cleaning": "stop",
}


def observation_start(attempted_action, execute=False):
    SHARE.mkdir(parents=True, exist_ok=True)
    action = str(attempted_action or "unspecified")[:80]
    rec = {"started_at": now_iso(), "attempted_action": action, "initiated_by": "diagnostics_addon" if execute else "external"}
    ACTIVE_FILE.write_text(json.dumps(rec, indent=2))
    if not execute:
        return {"ok": True, "message": "Observation capture started", **rec}
    service = ACTION_SERVICE.get(action)
    if not service:
        rec["command_result"] = {"ok": False, "error": "Action cannot be sent automatically yet"}
        ACTIVE_FILE.write_text(json.dumps(rec, indent=2))
        return {"ok": False, "message": "This action is observation-only", **rec}
    entity = vacuum_entity()
    if not entity:
        rec["command_result"] = {"ok": False, "error": "Could not uniquely identify the vacuum entity"}
        ACTIVE_FILE.write_text(json.dumps(rec, indent=2))
        return {"ok": False, "message": "Could not identify the vacuum entity", **rec}
    sent_at = now_iso()
    call = ha_api(f"/services/vacuum/{service}", "POST", {"entity_id": entity})
    rec["command_sent_at"] = sent_at
    rec["ha_service"] = f"vacuum.{service}"
    rec["command_result"] = {"ok": call.get("ok", False), "status": call.get("status"), "error": redact(call.get("error", "")) if not call.get("ok") else ""}
    ACTIVE_FILE.write_text(json.dumps(rec, indent=2))
    return {"ok": call.get("ok", False), "message": "Command sent. Tell me what the robot physically did." if call.get("ok") else "HA service call failed", "attempted_action": action, "ha_service": rec["ha_service"], "command_sent_at": sent_at, "command_result": rec["command_result"]}


def observation_finish(physical_result, notes=""):
    if not ACTIVE_FILE.exists(): return {"ok": False, "message": "No active observation."}
    try: rec = json.loads(ACTIVE_FILE.read_text())
    except Exception: rec = {"started_at": now_iso(), "attempted_action": "unknown"}
    rec["finished_at"] = now_iso(); rec["physical_result"] = str(physical_result or "unspecified")[:100]; rec["notes"] = str(notes or "")[:500]
    _, _, raw = get_logs("3m")
    rec["diagnostic_log_lines"] = [redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-350:]
    with OBS_FILE.open("a", encoding="utf-8") as f: f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    try: ACTIVE_FILE.unlink()
    except Exception: pass
    return {"ok": True, "message": "Saved", "observation": rec}


def load_observations(hours=24):
    if not OBS_FILE.exists(): return []
    cutoff = datetime.now().astimezone() - timedelta(hours=hours); rows = []
    for line in OBS_FILE.read_text(errors="replace").splitlines():
        try:
            row = json.loads(line); dt = datetime.fromisoformat(row.get("finished_at", row.get("started_at")))
            if dt >= cutoff: rows.append(row)
        except Exception: pass
    return rows[-100:]


def capture_telemetry():
    cid, name, raw = get_logs("20m")
    if not cid: return {"ok": False, "message": "Core not found"}
    selected = [redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-5000:]
    observations = load_observations(24)
    report = {"version": VERSION, "generated": now_iso(), "window": "20m", "observations": observations, "matched_lines": selected, "core_candidate": {"id": "<redacted-container-id>", "name": name}}
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S"); out = SHARE / f"deebot-y1pro-telemetry-{stamp}.zip"
    markers = ["USER_OBSERVATION " + json.dumps({k:v for k,v in o.items() if k != "diagnostic_log_lines"}, ensure_ascii=False) for o in observations]
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("TELEMETRY_REPORT.json", json.dumps(report, indent=2))
        z.writestr("MATCHED_CORE_LOG.txt", "\n".join(markers + selected))
        z.writestr("USER_OBSERVATIONS.json", json.dumps(observations, indent=2))
    report["file"] = str(out); return report


def diagnose():
    return {"version": VERSION, "generated": now_iso(), "vacuum_entity_found": bool(vacuum_entity()), "patch": patch_status(), "observations": load_observations(24)}


HTML = """<!doctype html><meta name=viewport content='width=device-width'><title>DEEBOT Y1 PRO Tools</title>
<style>body{font-family:system-ui;max-width:1000px;margin:24px auto;padding:0 18px;background:#111827;color:#e5e7eb}button,select,input{padding:12px 14px;margin:5px;border:0;border-radius:8px;font-weight:650}.p{background:#2563eb;color:white}.g{background:#16a34a;color:white}.w{background:#f59e0b}.d{background:#ef4444;color:white}.t{background:#7c3aed;color:white}.card{border:1px solid #374151;border-radius:10px;padding:16px;margin:14px 0;background:#1f2937}select,input{background:#fff;color:#111827;max-width:95%}pre{background:#030712;padding:14px;white-space:pre-wrap;max-height:600px;overflow:auto;border-radius:8px}.hint{color:#9ca3af}.big{font-size:1.05rem}</style>
<h1>DEEBOT Y1 PRO Diagnostics & Patch Manager</h1><p>Version <b>1.6.1</b></p>
<div class=card><h2>One-click physical command test</h2><p class=hint>Select an action. The add-on sends it through Home Assistant and starts capture. You only tell us what physically happened.</p>
<select id=attempt><option>Start cleaning</option><option>Pause</option><option>Resume</option><option>Return to dock</option><option>Stop cleaning</option></select>
<button class=p onclick='runTest()'>Run command & capture</button>
<div id=answer style='display:none'><p class=big><b>What did the robot physically do?</b></p>
<select id=result><option>Started cleaning</option><option>Paused</option><option>Resumed cleaning</option><option>Returned to dock</option><option>Stopped cleaning</option><option>No physical response</option><option>Other / unexpected</option></select>
<input id=notes placeholder='Optional note'><button class=g onclick='finishObs()'>Save result</button></div><p id=obs>Ready.</p></div>
<button class=p onclick="go('./api/diagnose')">Run diagnosis</button><button class=t onclick="go('./api/telemetry')">Export telemetry</button>
<button class=g onclick="ask('./api/install','Install/update targeted cqyi87 profile?')">Install Y1 PRO patch</button><button class=w onclick="ask('./api/rollback','Rollback latest Y1 PRO patch?')">Rollback patch</button><button onclick="ask('./api/quarantine','Quarantine custom Ecovacs copies?')">Quarantine custom Ecovacs</button><button class=d onclick="ask('./api/restart','Restart Home Assistant Core now?')">Restart Core</button>
<pre id=o>Ready.</pre>
<script>async function post(u,b){let r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):null});return await r.json()}async function go(u){o.textContent='Working...';try{o.textContent=JSON.stringify(await post(u),null,2)}catch(e){o.textContent=String(e)}}function ask(u,m){if(confirm(m))go(u)}async function runTest(){answer.style.display='none';obs.textContent='Sending '+attempt.value+'...';let j=await post('./api/test/run',{attempted_action:attempt.value});o.textContent=JSON.stringify(j,null,2);obs.textContent=j.message;if(j.ok)answer.style.display='block'}async function finishObs(){let j=await post('./api/observe/finish',{physical_result:result.value,notes:notes.value});o.textContent=JSON.stringify(j,null,2);obs.textContent=j.ok?'Saved. Choose the next action.':j.message;answer.style.display='none';notes.value=''}</script>"""


class Handler(BaseHTTPRequestHandler):
    def send_json(self, code, body, ctype="application/json"):
        if isinstance(body, str): body = body.encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(body)
    def read_json(self):
        try:
            n=int(self.headers.get("Content-Length","0")); return json.loads(self.rfile.read(n).decode()) if n else {}
        except Exception: return {}
    def do_GET(self):
        if self.path.split("?",1)[0] in ("","/"): return self.send_json(200,HTML,"text/html; charset=utf-8")
        return self.send_json(404,json.dumps({"error":"not found"}))
    def do_POST(self):
        path=self.path.split("?",1)[0]; body=self.read_json()
        try:
            if path=="/api/test/run": result=observation_start(body.get("attempted_action"),True)
            elif path=="/api/observe/start": result=observation_start(body.get("attempted_action"),False)
            elif path=="/api/observe/finish": result=observation_finish(body.get("physical_result"),body.get("notes",""))
            elif path=="/api/diagnose": result=diagnose()
            elif path=="/api/telemetry": result=capture_telemetry()
            elif path=="/api/install": result=install_patch()
            elif path=="/api/rollback": result=rollback()
            elif path=="/api/quarantine": result=quarantine()
            elif path=="/api/restart": result=restart()
            else: return self.send_json(404,json.dumps({"error":"not found"}))
            return self.send_json(200,json.dumps(result,indent=2))
        except Exception as exc: return self.send_json(500,json.dumps({"error":redact(exc)}))
    def log_message(self,*args): pass

SHARE.mkdir(parents=True, exist_ok=True)
ThreadingHTTPServer(("0.0.0.0",PORT),Handler).serve_forever()
