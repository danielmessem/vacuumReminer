#!/usr/bin/env python3
import json
import re
import shutil
import subprocess
import zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.6.5"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
CC = HA / "custom_components"
CUSTOM = CC / "ecovacs"
CLIENT_BACKUP_ROOT = HA / "ecovacs_doctor_client_backups"
PROFILE_PATH = Path("/app/cqyi87_profile.py")
OBS_FILE = SHARE / "deebot-y1pro-observations.jsonl"
ACTIVE_FILE = SHARE / "deebot-y1pro-active-observation.json"

MATCH = re.compile(r"ecovacs|deebot|beepbop|cqyi87|30000|mqtt|capabilities|clean_V2|setSpeed|BatteryEvent|StateEvent|PositionsEvent|MapTraceEvent|FanSpeedEvent|Error while setting up ecovacs", re.I)
TELEMETRY_MATCH = re.compile(r"30000|Received PUBLISH|Got message: topic=|Unknown message|BatteryEvent|StateEvent|PositionsEvent|MapTraceEvent|FanSpeedEvent|AvailabilityEvent|clean_V2|setSpeed|getBattery|getPos|getMapTrace|getChargeState|getWorkState|40001|40009|40011|40013|10000|10001", re.I)
SECRET = re.compile(r"(?i)(accessToken|refreshToken|authCode|token|api_key|secret)(['\" ]*[:=]['\" ]*)[^,'\"\s}]+")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
SERIAL = re.compile(r"\bE\d{14,}\b")
KEYED_ID = re.compile(r"(?i)(['\"]?(?:userId|userid|uid|ucUid|ecovacsUid|did|homeId|resource)['\"]?\s*[:=]\s*['\"])[^'\"\s,}]+(['\"])")
MQTT_CLIENT = re.compile(r"client_id=b?['\"][^'\"]+@ecouser/[^'\"]+['\"]", re.I)
MQTT_TOPIC_UUID = re.compile(r"(?<=/)[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}(?=/)")

def now_iso(): return datetime.now().astimezone().isoformat()
def redact(value):
    s=str(value); s=EMAIL.sub("<redacted-email>",s); s=SECRET.sub(r"\1\2<redacted>",s); s=KEYED_ID.sub(r"\1<redacted>\2",s); s=UUID.sub("<redacted-device-id>",s); s=SERIAL.sub("<redacted-serial>",s); s=MQTT_CLIENT.sub("client_id='<redacted-mqtt-client>'",s); s=MQTT_TOPIC_UUID.sub("<redacted-device-id>",s); return s

def docker(args,timeout=35):
    try:
        p=subprocess.run(["docker"]+args,capture_output=True,text=True,timeout=timeout); return p.returncode,p.stdout,p.stderr
    except Exception as exc:return 99,"",str(exc)
def core():
    _,out,_=docker(["ps","--format","{{.ID}}\t{{.Names}}"])
    for line in out.splitlines():
        parts=line.split("\t",1)
        if len(parts)==2 and "homeassistant" in parts[1].lower():return parts[0],parts[1]
    return None,None
def core_exec(args,timeout=30):
    cid,_=core()
    if not cid:return {"ok":False,"error":"Home Assistant Core container not found"}
    rc,out,err=docker(["exec",cid]+args,timeout); return {"ok":rc==0,"stdout":redact(out),"stderr":redact(err),"rc":rc}
def client_paths():
    r=core_exec(["python","-c",'import pathlib,deebot_client;p=pathlib.Path(deebot_client.__file__).parent;print(p);print(p/"hardware"/"cqyi87.py")']); lines=[x.strip() for x in r.get("stdout","").splitlines() if x.strip()]; return {"ok":bool(r.get("ok") and len(lines)>=2),"package":lines[0] if lines else None,"target":lines[1] if len(lines)>1 else None,"detail":r}
def patch_status():
    p=client_paths()
    if not p["ok"]:return p
    r=core_exec(["sh","-c",f"if [ -f '{p['target']}' ]; then grep 'Y1PRO_PATCH_VERSION' '{p['target']}' || true; else echo MISSING; fi"]); d=r.get("stdout","").strip(); return {"ok":True,"target":p["target"],"installed":"Y1PRO_PATCH_VERSION" in d,"detail":d}
def install_patch():
    p=client_paths()
    if not p["ok"]:return {"ok":False,"message":"Could not locate deebot-client","detail":p}
    if not PROFILE_PATH.exists():return {"ok":False,"message":"Bundled cqyi87 profile is missing"}
    cid,_=core(); target=p["target"]; CLIENT_BACKUP_ROOT.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f"); backup=CLIENT_BACKUP_ROOT/f"cqyi87-{stamp}.py"; absent=CLIENT_BACKUP_ROOT/f"cqyi87-{stamp}.absent"; exists=core_exec(["sh","-c",f"test -f '{target}'"])
    if exists.get("ok"):
        rc,_,err=docker(["cp",f"{cid}:{target}",str(backup)])
        if rc:return {"ok":False,"message":"Backup failed","error":redact(err)}
    else:absent.write_text("absent before patch\n")
    rc,_,err=docker(["cp",str(PROFILE_PATH),f"{cid}:{target}"])
    if rc:return {"ok":False,"message":"Copy failed","error":redact(err)}
    verify=core_exec(["python","-c","import importlib;importlib.invalidate_caches();m=importlib.import_module('deebot_client.hardware.cqyi87');i=m.get_device_info();c=i.capabilities;print(m.Y1PRO_PATCH_VERSION);print(i.data_type);print(c.device_type);print('life_span_types='+str(len(c.life_span.types)));print('stats_safe='+str(c.stats is not None))"])
    if not verify.get("ok"):
        if backup.exists():docker(["cp",str(backup),f"{cid}:{target}"])
        else:core_exec(["sh","-c",f"rm -f '{target}'"])
        return {"ok":False,"message":"Validation failed; rolled back","validation":verify}
    return {"ok":True,"message":"Y1 PRO cqyi87 profile installed. Restart Core next.","target":target,"validation":verify}
def rollback():
    p=client_paths()
    if not p["ok"]:return {"ok":False,"message":"Could not locate deebot-client"}
    cid,_=core(); target=p["target"]; items=sorted(list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.py"))+list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.absent")),reverse=True)
    if not items:return {"ok":False,"message":"No backup found"}
    latest=items[0]
    if latest.suffix==".absent":
        r=core_exec(["sh","-c",f"rm -f '{target}'"]); return {"ok":r.get("ok",False),"message":"Patch removed. Restart Core next.","detail":r}
    rc,_,err=docker(["cp",str(latest),f"{cid}:{target}"]); return {"ok":rc==0,"message":"Previous cqyi87.py restored. Restart Core next.","error":redact(err)}
def quarantine():
    moved=[]; root=HA/"ecovacs_doctor_backups"; root.mkdir(parents=True,exist_ok=True); candidates=[]
    if CUSTOM.exists():candidates.append(CUSTOM)
    if CC.exists():candidates+=list(CC.glob("ecovacs.disabled-*"))
    for src in candidates:
        dst=root/f"ecovacs-{datetime.now():%Y%m%d-%H%M%S-%f}-{src.name}"; shutil.move(str(src),str(dst)); moved.append({"from":str(src),"to":str(dst)})
    return {"ok":True,"moved":moved}
def restart():
    cid,_=core()
    if not cid:return {"ok":False,"message":"Core not found"}
    rc,_,err=docker(["restart",cid],40); return {"ok":rc==0,"message":"Restart requested" if rc==0 else redact(err)}
def get_logs(since="30m"):
    cid,name=core()
    if not cid:return None,None,[]
    _,out,err=docker(["logs","--since",since,cid],45); return cid,name,(out+err).splitlines()
def load_observations(hours=24):
    if not OBS_FILE.exists():return []
    cutoff=datetime.now().astimezone()-timedelta(hours=hours); rows=[]
    for line in OBS_FILE.read_text(errors="replace").splitlines():
        try:
            row=json.loads(line); finished=datetime.fromisoformat(row.get("finished_at",row.get("started_at")))
            if finished>=cutoff:rows.append(row)
        except Exception:continue
    return rows[-100:]
def observation_start(attempted_action):
    SHARE.mkdir(parents=True,exist_ok=True); rec={"started_at":now_iso(),"attempted_action":str(attempted_action or "unspecified")[:80]}; ACTIVE_FILE.write_text(json.dumps(rec,indent=2)); return {"ok":True,"message":"Observation capture started",**rec}
def observation_finish(physical_result,notes=""):
    if not ACTIVE_FILE.exists():return {"ok":False,"message":"No active observation. Press Start capture first."}
    try:rec=json.loads(ACTIVE_FILE.read_text())
    except Exception:rec={"started_at":now_iso(),"attempted_action":"unknown"}
    rec["finished_at"]=now_iso(); rec["physical_result"]=str(physical_result or "unspecified")[:100]; rec["notes"]=str(notes or "")[:500]; _,_,raw=get_logs("3m"); rec["diagnostic_log_lines"]=[redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-300:]
    with OBS_FILE.open("a",encoding="utf-8") as f:f.write(json.dumps(rec,ensure_ascii=False)+"\n")
    try:ACTIVE_FILE.unlink()
    except Exception:pass
    return {"ok":True,"message":"Observation saved and will be included in telemetry exports","observation":rec}
def capture_telemetry():
    cid,name,raw=get_logs("20m")
    if not cid:return {"ok":False,"message":"Core not found"}
    selected=[redact(line) for line in raw if TELEMETRY_MATCH.search(line)][-5000:]; lower="\n".join(selected).lower(); summary={"message_30000_seen":"30000" in lower,"unknown_30000_seen":'unknown message "30000"' in lower,"fan_speed_event_seen":"fanspeedevent" in lower,"state_event_seen":"stateevent" in lower,"battery_event_seen":"batteryevent" in lower,"position_event_seen":"positionsevent" in lower,"map_trace_event_seen":"maptraceevent" in lower,"availability_true_seen":"availabilityevent(available=true)" in lower,"clean_response_seen":"clean_v2" in lower and '"code":0' in lower.replace(" ","")}; payload=[line for line in selected if "got message: topic=" in line.lower() or "unknown message" in line.lower()]; events=[line for line in selected if "notify subscribers with" in line.lower() or "event is the same" in line.lower()]; observations=load_observations(24); markers=["USER_OBSERVATION "+json.dumps({k:v for k,v in obs.items() if k!="diagnostic_log_lines"},ensure_ascii=False) for obs in observations]; report={"version":VERSION,"generated":now_iso(),"window":"20m","summary":summary,"observations":observations,"payload_lines":payload[-1200:],"event_lines":events[-1200:],"core_candidate":{"id":"<redacted-container-id>","name":name}}; SHARE.mkdir(parents=True,exist_ok=True); stamp=datetime.now().strftime("%Y%m%d-%H%M%S"); out=SHARE/f"deebot-y1pro-telemetry-{stamp}.zip"
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:z.writestr("TELEMETRY_REPORT.json",json.dumps(report,indent=2)); z.writestr("PAYLOAD_LINES.txt","\n".join(markers+payload[-1200:])); z.writestr("EVENT_LINES.txt","\n".join(events[-1200:])); z.writestr("USER_OBSERVATIONS.json",json.dumps(observations,indent=2))
    report["file"]=str(out); return report
def diagnose():
    cid,name,raw=get_logs("30m"); logs=[redact(x) for x in raw if MATCH.search(x)][-12000:] if cid else []; return {"version":VERSION,"generated":now_iso(),"environment":{"core_container":{"found":bool(cid),"name":name},"ha_version":core_exec(["python","-c","import homeassistant.const as c; print(c.__version__)"]) if cid else None,"deebot_client":core_exec(["python","-c","import importlib.metadata as m; print(m.version('deebot-client'))"]) if cid else None},"y1pro_patch":patch_status(),"observations":load_observations(24),"logs":logs}

HTML=f'''<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>DEEBOT Y1 PRO Diagnostics</title><style>body{{font-family:system-ui;margin:20px;max-width:1000px}}button,select,input{{padding:10px;margin:5px}}pre{{white-space:pre-wrap;background:#111;color:#eee;padding:12px;max-height:500px;overflow:auto}}.card{{border:1px solid #ccc;border-radius:12px;padding:16px;margin:12px 0}}label{{font-weight:600}}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics & Patch Manager</h1><p>Version <b>{VERSION}</b></p><div class=card><h2>Guided protocol observation</h2><p>1. Choose what you are about to try. 2. Start capture. 3. Trigger it in Home Assistant or the official Ecovacs app. 4. Tell me what the robot physically did.</p><label>Attempted action</label><select id=attempt><option>Start cleaning</option><option>Pause</option><option>Resume</option><option>Return to dock</option><option>Fan speed - Quiet</option><option>Fan speed - Normal</option><option>Fan speed - Max</option><option>Other official app action</option></select><button onclick=startObs()>Start capture</button><br><label>Physical result</label><select id=result><option>Started cleaning</option><option>Paused</option><option>Resumed cleaning</option><option>Returned to dock</option><option>Changed fan speed</option><option>No physical response</option><option>Other / unexpected</option></select><input id=notes placeholder="Optional notes"><button onclick=finishObs()>Save physical result</button></div><div class=card><button onclick=call('diagnose')>Run diagnosis</button><button onclick=call('telemetry')>Capture Y1 PRO telemetry</button><button onclick=call('install')>Install / Repair Y1 PRO Patch</button><button onclick=call('rollback')>Rollback Patch</button><button onclick=call('quarantine')>Quarantine Custom Ecovacs</button><button onclick=call('restart')>Restart Core</button></div><pre id=o>Ready.</pre><script>async function post(path,body={{}}){{let r=await fetch(path,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(body)}});return await r.json()}}async function call(x){{o.textContent='Working...';o.textContent=JSON.stringify(await post('./api/'+x),null,2)}}async function startObs(){{o.textContent=JSON.stringify(await post('./api/observe/start',{{attempted_action:attempt.value}}),null,2)}}async function finishObs(){{o.textContent=JSON.stringify(await post('./api/observe/finish',{{physical_result:result.value,notes:notes.value}}),null,2)}}</script></body></html>'''
class Handler(BaseHTTPRequestHandler):
    def sendj(self,code,b,ctype="application/json"):
        if isinstance(b,str):b=b.encode()
        self.send_response(code); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):self.sendj(200,HTML,"text/html; charset=utf-8")
    def do_POST(self):
        try:
            n=int(self.headers.get("Content-Length","0")); body=json.loads(self.rfile.read(n) or b"{}")
        except Exception:body={}
        p=self.path.rstrip("/").split("/")[-1]
        if self.path.endswith("/api/observe/start"):r=observation_start(body.get("attempted_action"))
        elif self.path.endswith("/api/observe/finish"):r=observation_finish(body.get("physical_result"),body.get("notes",""))
        elif p=="diagnose":r=diagnose()
        elif p=="telemetry":r=capture_telemetry()
        elif p=="install":r=install_patch()
        elif p=="rollback":r=rollback()
        elif p=="quarantine":r=quarantine()
        elif p=="restart":r=restart()
        else:r={"ok":False,"message":"Unknown endpoint"}
        self.sendj(200,json.dumps(r,indent=2))
    def log_message(self,fmt,*args):print(fmt%args,flush=True)
if __name__=="__main__":
    print(f"DEEBOT Y1 PRO Diagnostics v{VERSION} listening on {PORT}",flush=True); ThreadingHTTPServer(("0.0.0.0",PORT),Handler).serve_forever()
