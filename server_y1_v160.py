#!/usr/bin/env python3
import json, os, re, shutil, subprocess, urllib.request, zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

VERSION = "1.8.0"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
CC = HA / "custom_components"
CUSTOM = CC / "ecovacs"
CLIENT_BACKUP_ROOT = HA / "ecovacs_doctor_client_backups"
PROFILE_PATH = Path("/app/cqyi87_profile.py")
OBS_FILE = SHARE / "deebot-y1pro-observations.jsonl"
ACTIVE_FILE = SHARE / "deebot-y1pro-active-observation.json"
ROOM_FILE = SHARE / "deebot-y1pro-rooms.json"

MATCH = re.compile(r"ecovacs|deebot|cqyi87|30000|mqtt|capabilities|BatteryEvent|StateEvent|Error while setting up ecovacs", re.I)
TELEMETRY_MATCH = re.compile(r"30000|Received PUBLISH|Got message: topic=|Unknown message|BatteryEvent|StateEvent|AvailabilityEvent|40001|40007|40009|40011|40013|10000|10001|areaClean", re.I)
STATE_MATCH = re.compile(r"10000|BatteryEvent|StateEvent|chargeStatus|pauseSwitch|smartClean|areaClean|goCharge|status.?idle", re.I)

def now_iso():
    return datetime.now().astimezone().isoformat()

def redact(v):
    s = str(v)
    s = re.sub(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "<redacted-email>", s)
    s = re.sub(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}\b", "<redacted-device-id>", s)
    s = re.sub(r"(?i)(accessToken|refreshToken|authCode|token|api_key|secret)(['\" ]*[:=]['\" ]*)[^,'\"\s}]+", r"\1\2<redacted>", s)
    return s

def docker(args, timeout=35):
    try:
        p = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 99, "", str(e)

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

def ha_request(path, method="GET", data=None):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return {"ok": False, "error": "SUPERVISOR_TOKEN unavailable"}
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
    except Exception as e:
        return {"ok": False, "error": redact(e)}

def ha_vacuum_snapshot():
    r = ha_request("/api/states")
    if not r.get("ok"):
        return r
    rows = []
    safe_attrs = ("friendly_name", "battery_level", "battery_icon", "fan_speed", "fan_speed_list", "supported_features", "status")
    for item in r.get("data", []):
        eid = str(item.get("entity_id", ""))
        if not eid.startswith("vacuum."):
            continue
        attrs = item.get("attributes") or {}
        rows.append({
            "entity_id": eid,
            "state": item.get("state"),
            "attributes": {k: attrs.get(k) for k in safe_attrs if k in attrs},
            "last_changed": item.get("last_changed"),
            "last_updated": item.get("last_updated"),
        })
    return {"ok": True, "entities": rows}

def choose_vacuum(entity_id=None):
    snap = ha_vacuum_snapshot()
    if not snap.get("ok"):
        return None, snap.get("error", "Could not read Home Assistant vacuum entities")
    ids = [x["entity_id"] for x in snap.get("entities", [])]
    if entity_id:
        if entity_id not in ids:
            return None, f"Vacuum entity {entity_id} not found"
        return entity_id, None
    if len(ids) == 1:
        return ids[0], None
    if not ids:
        return None, "No vacuum entities found"
    return None, "Multiple vacuum entities found; choose one in the Room Mapper"

def ha_vacuum_service(service, entity_id):
    return ha_request(f"/api/services/vacuum/{service}", "POST", {"entity_id": entity_id})

def load_rooms():
    default = {"9": "Room2"}
    if not ROOM_FILE.exists():
        return default
    try:
        data = json.loads(ROOM_FILE.read_text(errors="replace"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items()}
    except Exception:
        pass
    return default

def save_room(area_id, label):
    try:
        area_id = int(area_id)
    except Exception:
        return {"ok": False, "message": "Area ID must be a number"}
    if area_id < 0 or area_id > 999:
        return {"ok": False, "message": "Area ID must be between 0 and 999"}
    label = str(label or "").strip()[:80]
    rooms = load_rooms()
    if label:
        rooms[str(area_id)] = label
    else:
        rooms.pop(str(area_id), None)
    SHARE.mkdir(parents=True, exist_ok=True)
    ROOM_FILE.write_text(json.dumps(rooms, indent=2))
    return {"ok": True, "message": f"Saved area {area_id} as {label}" if label else f"Cleared label for area {area_id}", "rooms": rooms}

def room_data():
    snap = ha_vacuum_snapshot()
    entities = snap.get("entities", []) if snap.get("ok") else []
    return {"ok": True, "rooms": load_rooms(), "vacuum_entities": entities}

def test_room(area_id, entity_id=None):
    try:
        area_id = int(area_id)
    except Exception:
        return {"ok": False, "message": "Area ID must be a number"}
    if area_id < 0 or area_id > 999:
        return {"ok": False, "message": "Area ID must be between 0 and 999"}
    eid, error = choose_vacuum(entity_id)
    if error:
        return {"ok": False, "message": error}
    params = {"cleanSwitch": True, "cleanMode": "area", "cleanValues": [area_id]}
    result = ha_request("/api/services/vacuum/send_command", "POST", {
        "entity_id": eid,
        "command": "40007",
        "params": params,
    })
    return {
        "ok": result.get("ok", False),
        "message": f"Sent room-clean test for area {area_id}" if result.get("ok") else "Home Assistant rejected the room-clean command",
        "entity_id": eid,
        "area_id": area_id,
        "label": load_rooms().get(str(area_id), ""),
        "command": "40007",
        "params": params,
        "ha_result": result,
    }

def return_dock(entity_id=None):
    eid, error = choose_vacuum(entity_id)
    if error:
        return {"ok": False, "message": error}
    r = ha_vacuum_service("return_to_base", eid)
    return {"ok": r.get("ok", False), "message": "Return to dock requested" if r.get("ok") else "Return to dock failed", "entity_id": eid, "ha_result": r}

def client_paths():
    r = core_exec(["python", "-c", 'import pathlib,deebot_client;p=pathlib.Path(deebot_client.__file__).parent;print(p);print(p/"hardware"/"cqyi87.py")'])
    x = [i.strip() for i in r.get("stdout", "").splitlines() if i.strip()]
    return {"ok": bool(r.get("ok") and len(x) >= 2), "package": x[0] if x else None, "target": x[1] if len(x) > 1 else None, "detail": r}

def patch_status():
    p = client_paths()
    if not p.get("ok"):
        return p
    r = core_exec(["sh", "-c", f"if [ -f '{p['target']}' ]; then grep 'Y1PRO_PATCH_VERSION' '{p['target']}' || true; else echo MISSING; fi"])
    d = r.get("stdout", "").strip()
    return {"ok": True, "target": p["target"], "installed": "Y1PRO_PATCH_VERSION" in d, "detail": d}

def install_patch():
    p = client_paths()
    if not p.get("ok"):
        return {"ok": False, "message": "Could not locate deebot-client", "detail": p}
    cid, _ = core()
    target = p["target"]
    CLIENT_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = CLIENT_BACKUP_ROOT / f"cqyi87-{stamp}.py"
    exists = core_exec(["sh", "-c", f"test -f '{target}'"])
    if exists.get("ok"):
        docker(["cp", f"{cid}:{target}", str(backup)])
    rc, _, err = docker(["cp", str(PROFILE_PATH), f"{cid}:{target}"])
    if rc:
        return {"ok": False, "message": "Copy failed", "error": redact(err)}
    verify = core_exec(["python", "-c", "import importlib;importlib.invalidate_caches();m=importlib.import_module('deebot_client.hardware.cqyi87');i=m.get_device_info();c=i.capabilities;print(m.Y1PRO_PATCH_VERSION);print(i.data_type);print(c.device_type);print('battery_enabled='+str(c.battery is not None));print('life_span_types='+str(len(c.life_span.types)));print('stats_safe='+str(c.stats is not None))"])
    return {"ok": verify.get("ok", False), "message": "Y1 PRO cqyi87 profile installed. Restart Core next." if verify.get("ok") else "Validation failed", "target": target, "validation": verify}

def rollback():
    p = client_paths()
    items = sorted(CLIENT_BACKUP_ROOT.glob("cqyi87-*.py"), reverse=True)
    if not p.get("ok") or not items:
        return {"ok": False, "message": "No backup found"}
    cid, _ = core()
    rc, _, err = docker(["cp", str(items[0]), f"{cid}:{p['target']}"])
    return {"ok": rc == 0, "message": "Previous cqyi87.py restored. Restart Core next.", "error": redact(err)}

def quarantine():
    moved = []
    root = HA / "ecovacs_doctor_backups"
    root.mkdir(parents=True, exist_ok=True)
    if CUSTOM.exists():
        dst = root / f"ecovacs-{datetime.now():%Y%m%d-%H%M%S-%f}"
        shutil.move(str(CUSTOM), str(dst))
        moved.append({"from": str(CUSTOM), "to": str(dst)})
    return {"ok": True, "moved": moved}

def restart():
    cid, _ = core()
    rc, _, err = docker(["restart", cid], 40) if cid else (1, "", "Core not found")
    return {"ok": rc == 0, "message": "Restart requested" if rc == 0 else redact(err)}

def get_logs(since="30m"):
    cid, name = core()
    _, out, err = docker(["logs", "--since", since, cid], 45) if cid else (1, "", "")
    return cid, name, (out + err).splitlines()

def load_observations():
    if not OBS_FILE.exists():
        return []
    rows = []
    for line in OBS_FILE.read_text(errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    return rows[-100:]

def observation_start(action):
    SHARE.mkdir(parents=True, exist_ok=True)
    r = {"started_at": now_iso(), "attempted_action": str(action or "unspecified")[:80]}
    ACTIVE_FILE.write_text(json.dumps(r))
    return {"ok": True, "message": "Observation capture started", **r}

def observation_finish(result, notes=""):
    if not ACTIVE_FILE.exists():
        return {"ok": False, "message": "No active observation."}
    r = json.loads(ACTIVE_FILE.read_text())
    r.update(finished_at=now_iso(), physical_result=str(result)[:100], notes=str(notes)[:500])
    _, _, raw = get_logs("3m")
    r["ha_vacuum_snapshot"] = ha_vacuum_snapshot()
    r["diagnostic_log_lines"] = [redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-300:]
    with OBS_FILE.open("a") as f:
        f.write(json.dumps(r) + "\n")
    ACTIVE_FILE.unlink(missing_ok=True)
    return {"ok": True, "message": "Observation saved", "observation": r}

def capture_telemetry():
    _, _, raw = get_logs("20m")
    selected = [redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-5000:]
    state_lines = [redact(x) for x in raw if STATE_MATCH.search(x)][-1000:]
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"deebot-y1pro-telemetry-{stamp}.zip"
    out = SHARE / filename
    report = {
        "version": VERSION,
        "generated": now_iso(),
        "window": "20m",
        "ha_vacuum_snapshot": ha_vacuum_snapshot(),
        "room_labels": load_rooms(),
        "observations": load_observations(),
        "state_battery_timeline": state_lines,
        "payload_lines": selected,
    }
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("TELEMETRY_REPORT.json", json.dumps(report, indent=2))
        z.writestr("ROOM_LABELS.json", json.dumps(load_rooms(), indent=2))
        z.writestr("STATE_BATTERY_TIMELINE.txt", "\n".join(state_lines))
        z.writestr("PAYLOAD_LINES.txt", "\n".join(selected))
    report["file"] = str(out)
    report["filename"] = filename
    report["download_url"] = "./download/" + filename
    return report

def diagnose():
    cid, name, raw = get_logs()
    logs = [redact(x) for x in raw if MATCH.search(x)][-12000:]
    state_lines = [redact(x) for x in raw if STATE_MATCH.search(x)][-1000:]
    return {
        "version": VERSION,
        "generated": now_iso(),
        "ha_vacuum_snapshot": ha_vacuum_snapshot(),
        "room_labels": load_rooms(),
        "state_battery_timeline": state_lines,
        "environment": {
            "core_container": {"found": bool(cid), "name": name},
            "ha_version": core_exec(["python", "-c", "import homeassistant.const as c;print(c.__version__)"]) if cid else None,
            "deebot_client": core_exec(["python", "-c", "import importlib.metadata as m;print(m.version('deebot-client'))"]) if cid else None,
        },
        "y1pro_patch": patch_status(),
        "observations": load_observations(),
        "logs": logs,
    }

HTML = f'''<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>DEEBOT Y1 PRO</title>
<style>
:root{{--bg:#091119;--p:#121c26;--line:#273747;--text:#edf5fb;--muted:#91a7b9}}
*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(#081019,#0d1620);color:var(--text);font-family:system-ui;min-height:100vh}}.wrap{{max-width:1120px;margin:auto;padding:28px 18px}}header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}}h1{{margin:0;font-size:30px}}.sub,p{{color:var(--muted)}}.badge{{background:#102b40;color:#8ed0ff;border:1px solid #285d84;padding:7px 11px;border-radius:999px;font-weight:700}}.grid{{display:grid;grid-template-columns:1.1fr .9fr;gap:16px}}.card{{background:var(--p);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 15px 35px #0005}}.full{{grid-column:1/-1}}h2{{font-size:18px;margin:0 0 7px}}h3{{font-size:14px;margin:16px 0 8px;color:#c9d9e4}}label{{display:block;font-size:12px;font-weight:700;margin:12px 0 6px;color:#bed0dd}}select,input{{width:100%;background:#0b141c;color:white;border:1px solid #324658;border-radius:10px;padding:11px}}button,a.dl{{background:#1a2936;color:white;border:1px solid #385064;border-radius:10px;padding:10px 13px;margin:5px 4px 5px 0;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}}button:hover,a.dl:hover{{border-color:#5d829f}}.primary{{background:#1684e5;border-color:#4aa9ff}}.good{{background:#163927;border-color:#34734d;color:#9ae5b7}}.warn{{background:#3b2d16;border-color:#70572c;color:#ffdb93}}.danger{{background:#421d23;border-color:#78333d;color:#ffb0b8}}pre{{background:#070c11;border:1px solid #1e2c38;border-radius:13px;padding:15px;min-height:150px;max-height:480px;overflow:auto;white-space:pre-wrap;color:#bed3e2}}.actions{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}#downloadBox{{display:none;margin:12px 0;padding:12px;border:1px solid #34734d;background:#10291d;border-radius:12px}}.roomTop{{display:grid;grid-template-columns:1fr 140px 160px;gap:8px;align-items:end}}.roomGrid{{display:grid;grid-template-columns:70px 1fr 105px 78px;gap:7px;align-items:center}}.roomGrid .head{{font-size:11px;color:var(--muted);font-weight:800;text-transform:uppercase;padding:5px 2px}}.idbox{{font-weight:800;color:#90cdfa;background:#0b141c;border:1px solid #273747;padding:10px;border-radius:9px;text-align:center}}.mini{{padding:9px 8px;margin:0}}.hint{{font-size:12px;color:var(--muted)}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}.full{{grid-column:auto}}.actions{{grid-template-columns:1fr}}.roomTop{{grid-template-columns:1fr}}.roomGrid{{grid-template-columns:55px 1fr 82px 65px}}}}
</style></head><body><div class=wrap>
<header><div><h1>DEEBOT Y1 PRO</h1><div class=sub>Diagnostics & compatibility patch manager</div></div><div class=badge>v{VERSION}</div></header>
<main class=grid>
<section class="card full"><h2>Room mapper</h2><p>Test an Ecovacs area ID, see which physical room the robot goes to, then give that ID a useful name. Labels are saved across updates.</p>
<div class=roomTop><div><label>Vacuum</label><select id=roomVacuum><option value="">Loading...</option></select></div><div><label>Custom area ID</label><input id=customArea type=number min=0 max=999 placeholder="e.g. 1"></div><button class=primary onclick=testCustomRoom()>Test custom ID</button></div>
<div style="margin-top:8px"><button class=warn onclick=returnDock()>Return to dock</button><span class=hint>Use this after identifying the room.</span></div>
<h3>Area IDs</h3><div id=roomRows class=roomGrid></div>
</section>
<section class=card><h2>Guided protocol observation</h2><p>Record an action and what the robot physically does. Relevant logs and the live HA vacuum state are captured automatically.</p><label>Attempted action</label><select id=attempt><option>Start cleaning</option><option>Pause</option><option>Resume</option><option>Return to dock</option><option>Clean a specific room</option><option>Fan speed - Quiet</option><option>Fan speed - Normal</option><option>Fan speed - Max</option><option>Other official app action</option></select><button class=primary onclick=startObs()>Start capture</button><label>Physical result</label><select id=result><option>Started cleaning</option><option>Paused</option><option>Resumed cleaning</option><option>Returned to dock</option><option>Cleaned selected room</option><option>Changed fan speed</option><option>No physical response</option><option>Other / unexpected</option></select><label>Notes</label><input id=notes placeholder="Optional notes"><button class=good onclick=finishObs()>Save result</button></section>
<section class=card><h2>Tools</h2><p>Diagnosis includes live Home Assistant vacuum state plus a focused state/battery timeline.</p><div class=actions><button class=primary onclick=call('diagnose')>Run diagnosis</button><button onclick=captureTelemetry()>Capture telemetry</button><button onclick=call('install')>Install / Repair Patch</button><button class=warn onclick=call('rollback')>Rollback Patch</button><button class=warn onclick=call('quarantine')>Quarantine Custom Ecovacs</button><button class=danger onclick=call('restart')>Restart Core</button></div><div id=downloadBox><strong>Telemetry ZIP ready</strong><br><a id=downloadLink class="dl good" href="#" download>Download ZIP</a></div></section>
<section class="card full"><h2>Output</h2><pre id=o>Ready.</pre></section>
</main></div>
<script>
async function post(p,b={{}}){{let r=await fetch(p,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(b)}});return r.json()}}
async function getj(p){{let r=await fetch(p);return r.json()}}
function out(x){{o.textContent=JSON.stringify(x,null,2)}}
async function call(x){{downloadBox.style.display='none';o.textContent='Working...';out(await post('./api/'+x))}}
async function captureTelemetry(){{downloadBox.style.display='none';o.textContent='Capturing telemetry...';let r=await post('./api/telemetry');out(r);if(r.download_url){{downloadLink.href=r.download_url;downloadLink.textContent='Download '+(r.filename||'telemetry ZIP');downloadBox.style.display='block'}}}}
async function startObs(){{out(await post('./api/observe/start',{{attempted_action:attempt.value}}))}}
async function finishObs(){{out(await post('./api/observe/finish',{{physical_result:result.value,notes:notes.value}}))}}
function selectedVacuum(){{return roomVacuum.value||null}}
async function testRoom(id){{o.textContent='Sending area '+id+'...';out(await post('./api/rooms/test',{{area_id:id,entity_id:selectedVacuum()}}))}}
async function testCustomRoom(){{if(customArea.value==='')return;await testRoom(parseInt(customArea.value,10))}}
async function returnDock(){{out(await post('./api/rooms/dock',{{entity_id:selectedVacuum()}}))}}
async function saveRoom(id){{let el=document.getElementById('label-'+id);let r=await post('./api/rooms/save',{{area_id:id,label:el.value}});out(r);if(r.ok)loadRooms()}}
async function loadRooms(){{let r=await getj('./api/rooms');let current=roomVacuum.value;roomVacuum.innerHTML='';for(let e of (r.vacuum_entities||[])){{let op=document.createElement('option');op.value=e.entity_id;op.textContent=(e.attributes&&e.attributes.friendly_name?e.attributes.friendly_name+' - ':'')+e.entity_id;roomVacuum.appendChild(op)}}if(current)[...roomVacuum.options].forEach(x=>{{if(x.value===current)x.selected=true}});let saved=r.rooms||{{}};let ids=new Set();for(let i=1;i<=20;i++)ids.add(i);Object.keys(saved).forEach(x=>ids.add(parseInt(x,10)));let arr=[...ids].filter(Number.isFinite).sort((a,b)=>a-b);roomRows.innerHTML='<div class=head>ID</div><div class=head>Room label</div><div class=head>Test</div><div class=head>Save</div>';for(let id of arr){{let lab=(saved[String(id)]||'').replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');roomRows.insertAdjacentHTML('beforeend','<div class=idbox>'+id+'</div><input id="label-'+id+'" value="'+lab+'" placeholder="Unknown room"><button class="mini primary" onclick="testRoom('+id+')">Test clean</button><button class="mini good" onclick="saveRoom('+id+')">Save</button>')}}}}
loadRooms();
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def sendj(self, obj, status=200):
        b = json.dumps(obj, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p.rstrip("/").endswith("/api/rooms"):
            return self.sendj(room_data())
        marker = "/download/"
        if marker in p:
            filename = unquote(p.split(marker, 1)[1]).split("/")[-1]
            if not re.fullmatch(r"deebot-y1pro-telemetry-\d{8}-\d{6}\.zip", filename):
                return self.sendj({"ok": False, "message": "Invalid telemetry filename"}, 400)
            f = SHARE / filename
            if not f.exists():
                return self.sendj({"ok": False, "message": "Telemetry file not found"}, 404)
            b = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
            return
        b = HTML.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_POST(self):
        p = self.path.rstrip("/")
        n = int(self.headers.get("Content-Length", "0") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            body = {}
        funcs = {"diagnose": diagnose, "telemetry": capture_telemetry, "install": install_patch, "rollback": rollback, "quarantine": quarantine, "restart": restart}
        for key, fn in funcs.items():
            if p.endswith("/api/" + key):
                return self.sendj(fn())
        if p.endswith("/api/observe/start"):
            return self.sendj(observation_start(body.get("attempted_action")))
        if p.endswith("/api/observe/finish"):
            return self.sendj(observation_finish(body.get("physical_result"), body.get("notes")))
        if p.endswith("/api/rooms/test"):
            return self.sendj(test_room(body.get("area_id"), body.get("entity_id")))
        if p.endswith("/api/rooms/save"):
            return self.sendj(save_room(body.get("area_id"), body.get("label")))
        if p.endswith("/api/rooms/dock"):
            return self.sendj(return_dock(body.get("entity_id")))
        self.sendj({"ok": False}, 404)

    def log_message(self, fmt, *args):
        pass

if __name__ == "__main__":
    SHARE.mkdir(parents=True, exist_ok=True)
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
