#!/usr/bin/env python3
import base64,json,re,subprocess,tempfile,zipfile,shutil
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

VERSION="1.5.0"
PORT=8099
HA=Path("/homeassistant")
SHARE=Path("/share")
CC=HA/"custom_components"
CUSTOM=CC/"ecovacs"
BACKUP_ROOT=HA/"ecovacs_doctor_backups"
CLIENT_BACKUP_ROOT=HA/"ecovacs_doctor_client_backups"
PROFILE=base64.b64decode("IiIiREVFQk9UIFkxIFBSTyBjb21wYXRpYmlsaXR5IHByb2ZpbGUuIiIiCmZyb20gX19mdXR1cmVfXyBpbXBvcnQgYW5ub3RhdGlvbnMKZnJvbSBkZWVib3RfY2xpZW50LmNhcGFiaWxpdGllcyBpbXBvcnQgQ2FwYWJpbGl0aWVzLCBDYXBhYmlsaXR5Q2xlYW4sIENhcGFiaWxpdHlDbGVhbkFjdGlvbiwgQ2FwYWJpbGl0eUN1c3RvbUNvbW1hbmQsIENhcGFiaWxpdHlFdmVudCwgQ2FwYWJpbGl0eUV4ZWN1dGUsIENhcGFiaWxpdHlTZXRUeXBlcywgQ2FwYWJpbGl0eVNldHRpbmdzLCBEZXZpY2VUeXBlCmZyb20gZGVlYm90X2NsaWVudC5jb21tYW5kcy5qc29uLmNoYXJnZSBpbXBvcnQgQ2hhcmdlCmZyb20gZGVlYm90X2NsaWVudC5jb21tYW5kcy5qc29uLmNsZWFuIGltcG9ydCBDbGVhbkFyZWFWMiwgQ2xlYW5WMgpmcm9tIGRlZWJvdF9jbGllbnQuY29tbWFuZHMuanNvbi5jdXN0b20gaW1wb3J0IEN1c3RvbUNvbW1hbmQKZnJvbSBkZWVib3RfY2xpZW50LmNvbW1hbmRzLmpzb24uZmFuX3NwZWVkIGltcG9ydCBTZXRGYW5TcGVlZApmcm9tIGRlZWJvdF9jbGllbnQuY29uc3QgaW1wb3J0IERhdGFUeXBlCmZyb20gZGVlYm90X2NsaWVudC5ldmVudHMgaW1wb3J0IEF2YWlsYWJpbGl0eUV2ZW50LCBDdXN0b21Db21tYW5kRXZlbnQsIEZhblNwZWVkRXZlbnQsIEZhblNwZWVkTGV2ZWwsIFN0YXRlRXZlbnQKZnJvbSBkZWVib3RfY2xpZW50Lm1vZGVscyBpbXBvcnQgU3RhdGljRGV2aWNlSW5mbwpZMVBST19QQVRDSF9WRVJTSU9OID0gIjEuNS4wIgpkZWYgZ2V0X2RldmljZV9pbmZvKCkgLT4gU3RhdGljRGV2aWNlSW5mbzoKICAgIHJldHVybiBTdGF0aWNEZXZpY2VJbmZvKAogICAgICAgIERhdGFUeXBlLkpTT04sCiAgICAgICAgQ2FwYWJpbGl0aWVzKAogICAgICAgICAgICBkZXZpY2VfdHlwZT1EZXZpY2VUeXBlLlZBQ1VVTSwKICAgICAgICAgICAgYXZhaWxhYmlsaXR5PUNhcGFiaWxpdHlFdmVudChBdmFpbGFiaWxpdHlFdmVudCwgW10pLAogICAgICAgICAgICBiYXR0ZXJ5PU5vbmUsCiAgICAgICAgICAgIGNoYXJnZT1DYXBhYmlsaXR5RXhlY3V0ZShDaGFyZ2UpLAogICAgICAgICAgICBjbGVhbj1DYXBhYmlsaXR5Q2xlYW4oYWN0aW9uPUNhcGFiaWxpdHlDbGVhbkFjdGlvbihjb21tYW5kPUNsZWFuVjIsIGFyZWE9Q2xlYW5BcmVhVjIpKSwKICAgICAgICAgICAgY3VzdG9tPUNhcGFiaWxpdHlDdXN0b21Db21tYW5kKGV2ZW50PUN1c3RvbUNvbW1hbmRFdmVudCwgZ2V0PVtdLCBzZXQ9Q3VzdG9tQ29tbWFuZCksCiAgICAgICAgICAgIGVycm9yPU5vbmUsCiAgICAgICAgICAgIGZhbl9zcGVlZD1DYXBhYmlsaXR5U2V0VHlwZXMoZXZlbnQ9RmFuU3BlZWRFdmVudCwgZ2V0PVtdLCBzZXQ9U2V0RmFuU3BlZWQsIHR5cGVzPShGYW5TcGVlZExldmVsLlFVSUVULCBGYW5TcGVlZExldmVsLk5PUk1BTCwgRmFuU3BlZWRMZXZlbC5NQVgsIEZhblNwZWVkTGV2ZWwuTUFYX1BMVVMpKSwKICAgICAgICAgICAgbGlmZV9zcGFuPU5vbmUsCiAgICAgICAgICAgIG1hcD1Ob25lLAogICAgICAgICAgICBuZXR3b3JrPU5vbmUsCiAgICAgICAgICAgIHBsYXlfc291bmQ9Tm9uZSwKICAgICAgICAgICAgc2V0dGluZ3M9Q2FwYWJpbGl0eVNldHRpbmdzKCksCiAgICAgICAgICAgIHN0YXRlPUNhcGFiaWxpdHlFdmVudChTdGF0ZUV2ZW50LCBbXSksCiAgICAgICAgICAgIHN0YXRpb249Tm9uZSwKICAgICAgICAgICAgc3RhdHM9Tm9uZSwKICAgICAgICAgICAgd2F0ZXI9Tm9uZSwKICAgICAgICApLAogICAgKQo=").decode()
MATCH=re.compile(r"ecovacs|deebot|beepbop|cqyi87|30000|mqtt|capabilities|not supported",re.I)

def docker(args,timeout=30):
    try:
        p=subprocess.run(["docker"]+args,capture_output=True,text=True,timeout=timeout)
        return p.returncode,p.stdout,p.stderr
    except Exception as e:
        return 99,"",str(e)

def core():
    rc,o,e=docker(["ps","--format","{{.ID}}\t{{.Names}}"])
    for line in o.splitlines():
        x=line.split("\t",1)
        if len(x)==2 and "homeassistant" in x[1].lower():
            return x[0],x[1]
    return None,None

def core_exec(args,timeout=30):
    cid,_=core()
    if not cid:return {"ok":False,"error":"Home Assistant Core container not found"}
    rc,o,e=docker(["exec",cid]+args,timeout)
    return {"ok":rc==0,"stdout":o,"stderr":e,"rc":rc}

def paths():
    r=core_exec(["python","-c",'import pathlib,deebot_client;p=pathlib.Path(deebot_client.__file__).parent;print(p);print(p/"hardware"/"cqyi87.py")'])
    lines=[x.strip() for x in r.get("stdout","").splitlines() if x.strip()]
    return {"ok":r.get("ok") and len(lines)>=2,"package":lines[0] if lines else None,"target":lines[1] if len(lines)>1 else None,"detail":r}

def patch_status():
    p=paths()
    if not p["ok"]:return p
    r=core_exec(["sh","-c",f"if [ -f '{p['target']}' ]; then grep 'Y1PRO_PATCH_VERSION' '{p['target']}' || true; else echo MISSING; fi"])
    return {"ok":True,"target":p["target"],"installed":"Y1PRO_PATCH_VERSION" in r.get("stdout",""),"detail":r.get("stdout","").strip()}

def install_patch():
    p=paths()
    if not p["ok"]:return {"ok":False,"message":"Could not locate deebot-client","detail":p}
    cid,_=core();target=p["target"]
    CLIENT_BACKUP_ROOT.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup=CLIENT_BACKUP_ROOT/f"cqyi87-{stamp}.py"
    absent=CLIENT_BACKUP_ROOT/f"cqyi87-{stamp}.absent"
    exists=core_exec(["sh","-c",f"test -f '{target}'"])
    if exists.get("ok"):
        rc,o,e=docker(["cp",f"{cid}:{target}",str(backup)])
        if rc:return {"ok":False,"message":"Backup failed","error":e}
    else:
        absent.write_text("absent before patch\n")
    with tempfile.NamedTemporaryFile("w",delete=False,suffix=".py") as f:
        f.write(PROFILE);tmp=f.name
    try:
        rc,o,e=docker(["cp",tmp,f"{cid}:{target}"])
    finally:
        Path(tmp).unlink(missing_ok=True)
    if rc:return {"ok":False,"message":"Copy failed","error":e}
    verify=core_exec(["python","-c","import importlib;importlib.invalidate_caches();m=importlib.import_module('deebot_client.hardware.cqyi87');i=m.get_device_info();print(m.Y1PRO_PATCH_VERSION);print(i.data_type);print(i.capabilities.device_type)"])
    if not verify.get("ok"):
        if backup.exists():docker(["cp",str(backup),f"{cid}:{target}"])
        else:core_exec(["sh","-c",f"rm -f '{target}'"])
        return {"ok":False,"message":"Validation failed; rolled back","validation":verify}
    return {"ok":True,"message":"Y1 PRO cqyi87 profile installed. Restart Core next.","target":target,"validation":verify}

def rollback():
    p=paths()
    if not p["ok"]:return {"ok":False,"message":"Could not locate deebot-client"}
    cid,_=core();target=p["target"]
    items=sorted(list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.py"))+list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.absent")),reverse=True)
    if not items:return {"ok":False,"message":"No backup found"}
    latest=items[0]
    if latest.suffix==".absent":
        r=core_exec(["sh","-c",f"rm -f '{target}'"])
        return {"ok":r.get("ok",False),"message":"Patch removed. Restart Core next.","detail":r}
    rc,o,e=docker(["cp",str(latest),f"{cid}:{target}"])
    return {"ok":rc==0,"message":"Previous cqyi87.py restored. Restart Core next.","error":e}

def quarantine():
    BACKUP_ROOT.mkdir(parents=True,exist_ok=True);moved=[]
    candidates=[]
    if CUSTOM.exists():candidates.append(CUSTOM)
    if CC.exists():candidates+=list(CC.glob("ecovacs.disabled-*"))
    for src in candidates:
        dst=BACKUP_ROOT/f"ecovacs-{datetime.now():%Y%m%d-%H%M%S-%f}-{src.name}"
        shutil.move(str(src),str(dst));moved.append({"from":str(src),"to":str(dst)})
    return {"ok":True,"moved":moved}

def restart():
    cid,_=core()
    if not cid:return {"ok":False,"message":"Core not found"}
    rc,o,e=docker(["restart",cid])
    return {"ok":rc==0,"message":"Restart requested" if rc==0 else e}

def diagnose():
    cid,name=core();logs=[]
    if cid:
        rc,o,e=docker(["logs","--since","45m",cid],40)
        logs=[x for x in (o+e).splitlines() if MATCH.search(x)][-12000:]
    joined="\n".join(logs).lower();findings=[]
    if 'device class "cqyi87" not recognized' in joined or "no capabilities found for cqyi87" in joined:
        findings.append({"severity":"HIGH","code":"CQYI87_UNSUPPORTED","action":"Install Y1 PRO patch and restart Core."})
    if 'unknown message "30000"' in joined:
        findings.append({"severity":"MEDIUM","code":"Y1PRO_TELEMETRY_30000","action":"Basic control may work; telemetry decoder is still required."})
    if not findings:findings.append({"severity":"INFO","code":"NO_CURRENT_KNOWN_FAILURE"})
    r={"version":VERSION,"generated":datetime.now().isoformat(),"environment":{
        "ha_version":core_exec(["python","-c","from homeassistant.const import __version__;print(__version__)"]),
        "deebot_client":core_exec(["python","-c",'import importlib.metadata as m;print(m.version("deebot-client"))']),
        "y1pro_patch":patch_status()
    },"custom_component":{"present":CUSTOM.is_dir()},"findings":findings,"matched_logs":logs,"core_candidates":[{"id":cid,"name":name}] if cid else []}
    SHARE.mkdir(parents=True,exist_ok=True)
    out=SHARE/f"deebot-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(out,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("REPORT.json",json.dumps(r,indent=2))
        z.writestr("MATCHED_CORE_LOG.txt","\n".join(logs))
    r["file"]=str(out);return r

HTML="""<!doctype html><meta name=viewport content='width=device-width'><title>DEEBOT Y1 PRO Tools</title>
<style>body{font-family:system-ui;max-width:1050px;margin:24px auto;padding:0 18px;background:#111827;color:#e5e7eb}button{padding:11px 14px;margin:5px;border:0;border-radius:8px;font-weight:650}.p{background:#2563eb;color:white}.g{background:#16a34a;color:white}.w{background:#f59e0b}.d{background:#ef4444;color:white}pre{background:#030712;padding:14px;white-space:pre-wrap;max-height:650px;overflow:auto;border-radius:8px}</style>
<h1>DEEBOT Y1 PRO Diagnostics & Patch Manager</h1><p>Version <b>1.5.0</b></p>
<button class=p onclick="go('./api/diagnose')">Run full diagnosis</button>
<button class=g onclick="ask('./api/install','Install targeted cqyi87 profile? A rollback point will be created.')">Install Y1 PRO patch</button>
<button class=w onclick="ask('./api/rollback','Rollback latest Y1 PRO patch?')">Rollback Y1 PRO patch</button>
<button onclick="ask('./api/quarantine','Quarantine any custom Ecovacs copies?')">Quarantine custom Ecovacs</button>
<button class=d onclick="ask('./api/restart','Restart Home Assistant Core now?')">Restart Core</button>
<p>v1.5.0 adds a conservative cqyi87 profile. Known-bad battery/map/water/stat polling stays disabled. MQTT message 30000 is detected but not decoded yet.</p><pre id=o>Ready.</pre>
<script>async function go(u){o.textContent='Working…';try{let r=await fetch(u,{method:'POST'});o.textContent=JSON.stringify(await r.json(),null,2)}catch(e){o.textContent=String(e)}}function ask(u,m){if(confirm(m))go(u)}</script>"""

class H(BaseHTTPRequestHandler):
    def sendj(self,obj,code=200,ct="application/json"):
        b=obj if isinstance(obj,bytes) else (obj.encode() if isinstance(obj,str) else json.dumps(obj,indent=2).encode())
        self.send_response(code);self.send_header("Content-Type",ct);self.send_header("Content-Length",str(len(b)));self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(b)
    def do_GET(self):
        self.sendj(HTML,200,"text/html; charset=utf-8")
    def do_POST(self):
        p=self.path.split("?",1)[0]
        try:
            if p.endswith("/api/diagnose"):r=diagnose()
            elif p.endswith("/api/install"):r=install_patch()
            elif p.endswith("/api/rollback"):r=rollback()
            elif p.endswith("/api/quarantine"):r=quarantine()
            elif p.endswith("/api/restart"):r=restart()
            else:return self.sendj({"error":"not found"},404)
            self.sendj(r)
        except Exception as e:self.sendj({"error":str(e)},500)
    def log_message(self,*a):pass

ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
