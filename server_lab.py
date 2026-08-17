#!/usr/bin/env python3
"""DEEBOT Y1 PRO diagnostics + command laboratory."""
import json, os, re, socket, subprocess, threading, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from installed_client_inspector import inspect as inspect_client, core_inspection_script

VERSION = "1.1.6"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
TOKEN = os.environ.get("SUPERVISOR_TOKEN")
JOBS = {}
LOCK = threading.Lock()
MATCH = re.compile(r"ecovacs|deebot|beepbop|cqyi87|CARTESIAN|clean_V2|setWorkMode|getWorkMode|workState|motionState|p2p|cmdName|unsupported|exception|traceback|error", re.I)
SECRET = re.compile(r"token|password|secret|authorization|cookie|access_token|refresh_token", re.I)

def now(): return datetime.now(timezone.utc).isoformat()
def redact(x):
    if isinstance(x,dict): return {k:("***REDACTED***" if SECRET.search(str(k)) else redact(v)) for k,v in x.items()}
    if isinstance(x,list): return [redact(v) for v in x]
    return x

def sup(path,method="GET",payload=None,accept="application/json"):
    if not TOKEN: return {"ok":False,"error":"SUPERVISOR_TOKEN unavailable"}
    body=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request("http://supervisor"+path,data=body,method=method,headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json","Accept":accept})
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read().decode(errors="replace")
            if "application/json" in r.headers.get("Content-Type",""):
                try: raw=json.loads(raw)
                except Exception: pass
            return {"ok":True,"status":r.status,"data":redact(raw)}
    except urllib.error.HTTPError as e: return {"ok":False,"status":e.code,"error":e.read().decode(errors="replace")[:5000]}
    except Exception as e: return {"ok":False,"error":str(e)}

def val(r): return r.get("data") if isinstance(r,dict) and r.get("ok") else r

def entries():
    try: return [e for e in json.loads((HA/".storage/core.config_entries").read_text()).get("data",{}).get("entries",[]) if e.get("domain")=="ecovacs"]
    except Exception as e: return [{"error":str(e)}]

def logs(lines=5000):
    r=val(sup(f"/core/logs?lines={lines}&no_colors",accept="text/plain")); text=r if isinstance(r,str) else json.dumps(r,default=str)
    m=[x for x in text.splitlines() if MATCH.search(x)]
    return {"lines_requested":lines,"match_count":len(m),"matching_lines":m[-10000:]}

def states():
    r=val(sup("/core/api/states")); return r if isinstance(r,list) else []

def service(domain,service,data):
    return sup(f"/core/api/services/{domain}/{service}","POST",data or {})

def logger(debug):
    level="debug" if debug else "info"
    return service("logger","set_level",{"homeassistant.components.ecovacs":level,"ecovacs":level,"deebot_client":level})

def ecovacs_reload():
    es=[e for e in entries() if e.get("entry_id")]
    if not es: return {"ok":False,"error":"No Ecovacs config entry found"}
    r=service("homeassistant","reload_config_entry",{"entry_id":es[0]["entry_id"]}); time.sleep(4); return r

def evidence():
    l=logs(10000); text="\n".join(l["matching_lines"])
    return {"captured_at":now(),"cqyi87":[x for x in l["matching_lines"] if "cqyi87" in x],"clean_V2":[x for x in l["matching_lines"] if "clean_V2" in x],"work_mode_state":[x for x in l["matching_lines"] if re.search(r"workMode|setWorkMode|getWorkMode|workState|motionState",x,re.I)],"p2p":[x for x in l["matching_lines"] if "p2p" in x.lower()],"cmd_count":len(re.findall(r"cmdName",text))}

def snapshot(): return {"timestamp":now(),"config_entries":redact(entries()),"states":[x for x in states() if re.search(r"ecovacs|deebot|beepbop",json.dumps(x),re.I)],"logs":logs(),"client_inspection":inspect_client("\n".join(logs()["matching_lines"]))}

def make_zip(obj):
    SHARE.mkdir(parents=True,exist_ok=True); p=SHARE/f"deebot-y1pro-deep-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("diagnostic.json",json.dumps(redact(obj),indent=2,default=str)); z.writestr("core-inspection.sh",core_inspection_script()); z.writestr("README.txt",f"DEEBOT Y1 PRO Diagnostics v{VERSION}\n")
    return p

def deep(j):
    try:
        with LOCK: JOBS[j]["message"]="Baseline"; JOBS[j]["percent"]=10
        before=snapshot(); logger(True)
        with LOCK: JOBS[j]["message"]="Reloading Ecovacs integration"; JOBS[j]["percent"]=25
        reload_result=ecovacs_reload(); time.sleep(5)
        with LOCK: JOBS[j]["message"]="Capturing command traffic"; JOBS[j]["percent"]=55
        cap=evidence(); logger(False)
        with LOCK: JOBS[j]["message"]="Building ZIP"; JOBS[j]["percent"]=90
        p=make_zip({"version":VERSION,"before":before,"reload":reload_result,"evidence":cap,"after":snapshot()})
        with LOCK: JOBS[j].update(status="complete",percent=100,message="Complete",file=str(p))
    except Exception as e:
        try: logger(False)
        except Exception: pass
        with LOCK: JOBS[j].update(status="error",percent=100,message=str(e))

def start_deep():
    j=datetime.now().strftime("%Y%m%d%H%M%S%f")
    with LOCK: JOBS[j]={"status":"running","percent":0,"message":"Starting","events":[],"started_at":now()}
    threading.Thread(target=deep,args=(j,),daemon=True).start(); return j

def lab(action):
    """Exercise the existing HA Ecovacs entity while collecting raw Core log evidence."""
    before=logs(3000)
    logger(True)
    results=[]
    if action=="start": results.append({"action":"vacuum.start","result":service("vacuum","start",{"entity_id":"vacuum.beepbop"})})
    elif action=="stop": results.append({"action":"vacuum.stop","result":service("vacuum","stop",{"entity_id":"vacuum.beepbop"})})
    elif action=="dock": results.append({"action":"vacuum.return_to_base","result":service("vacuum","return_to_base",{"entity_id":"vacuum.beepbop"})})
    elif action=="pause": results.append({"action":"vacuum.pause","result":service("vacuum","pause",{"entity_id":"vacuum.beepbop"})})
    elif action=="state": pass
    else: return {"ok":False,"error":"unknown lab action"}
    time.sleep(3); after=logs(5000); logger(False)
    text="\n".join(after["matching_lines"])
    return {"ok":True,"action":action,"timestamp":now(),"service_results":results,"before":before,"after":after,"command_evidence":{"clean_V2":[x for x in after["matching_lines"] if "clean_V2" in x],"work_mode_state":[x for x in after["matching_lines"] if re.search(r"workMode|workState|motionState",x,re.I)],"p2p":[x for x in after["matching_lines"] if "p2p" in x.lower()],"cmd_count":len(re.findall(r"cmdName",text))},"states":[x for x in states() if "beepbop" in json.dumps(x).lower()]}

INDEX='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:950px;margin:25px auto;padding:0 18px}.card{border:1px solid #ddd;border-radius:10px;padding:18px;margin:12px 0}button{padding:10px 14px;margin:4px;border:1px solid #aaa;border-radius:8px;background:white;cursor:pointer}.out{background:#111;color:#eee;padding:12px;white-space:pre-wrap;font:12px monospace;max-height:500px;overflow:auto}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>VERSION</b></p><div class="card"><h2>Command Laboratory</h2><p>These buttons use the existing Home Assistant Ecovacs integration and capture the resulting Core/API/MQTT evidence. They do not directly bypass HA.</p><button onclick="go('state')">Read state/log evidence</button><button onclick="go('start')">START CLEAN</button><button onclick="go('stop')">STOP</button><button onclick="go('pause')">PAUSE</button><button onclick="go('dock')">RETURN TO BASE</button><pre id="out" class="out">Ready</pre></div><div class="card"><h2>Deep Capture</h2><a href="./api/deep">Run Deep Capture</a> | <a href="./api/health">Health</a></div><script>async function go(a){const o=document.getElementById('out');o.textContent='Running '+a+'…';try{const r=await fetch('./api/lab/'+a+'?t='+Date.now(),{cache:'no-store'});const t=await r.text();o.textContent='HTTP '+r.status+'\\n\\n'+t}catch(e){o.textContent='ERROR\\n'+e}}</script></body></html>'''

class H(BaseHTTPRequestHandler):
    def sendx(self,c,b,ct="application/json",fn=None):
        if isinstance(b,str): b=b.encode(); self.send_response(c); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-store")
        if fn:self.send_header("Content-Disposition",f'attachment; filename="{fn}"')
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p=self.path.split("?",1)[0]
        if p in ("","/"): return self.sendx(200,INDEX.replace("VERSION",VERSION),"text/html; charset=utf-8")
        if p=="/api/health": return self.sendx(200,json.dumps({"ok":True,"version":VERSION,"time":now()}))
        if p=="/api/deep":
            j=start_deep(); return self.sendx(200,json.dumps({"job":j,"status":"started"}))
        m=re.fullmatch(r"/api/lab/(start|stop|pause|dock|state)",p)
        if m:return self.sendx(200,json.dumps(lab(m.group(1)),indent=2,default=str))
        m=re.fullmatch(r"/api/job/([A-Za-z0-9_-]+)",p)
        if m:
            with LOCK:x=dict(JOBS.get(m.group(1),{"status":"not_found"}))
            return self.sendx(200,json.dumps(x,default=str))
        m=re.fullmatch(r"/api/download/([A-Za-z0-9_-]+)",p)
        if m:
            with LOCK:x=JOBS.get(m.group(1))
            if not x or x.get("status")!="complete":return self.sendx(404,json.dumps({"error":"not ready"}))
            q=Path(x["file"])
            if not q.is_file():return self.sendx(404,json.dumps({"error":"diagnostic file missing"}))
            return self.sendx(200,q.read_bytes(),"application/zip",q.name)
        if p=="/api/diagnostic":return self.sendx(200,json.dumps(snapshot(),indent=2,default=str))
        if p=="/api/core-inspection-script":return self.sendx(200,core_inspection_script(),"text/plain")
        return self.sendx(404,json.dumps({"error":"not found"}))
    def do_POST(self):
        if self.path.split("?",1)[0]=="/api/deep":return self.sendx(202,json.dumps({"job":start_deep()}))
        return self.sendx(404,json.dumps({"error":"not found"}))
    def log_message(self,*a):pass

if __name__=="__main__": ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
