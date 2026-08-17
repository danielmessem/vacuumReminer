#!/usr/bin/env python3
"""DEEBOT Y1 PRO diagnostics - robust ingress UI."""
import json, os, re, socket, subprocess, threading, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from installed_client_inspector import inspect as inspect_client, core_inspection_script

VERSION = "1.1.3"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
TOKEN = os.environ.get("SUPERVISOR_TOKEN")
JOBS = {}
LOCK = threading.Lock()
MATCH = re.compile(r"ecovacs|deebot|beepbop|cqyi87|CARTESIAN|y30|unsupported|exception|traceback|auth|discover|error|deebot[-_ ]?client|GetDeviceList|GetGlobalDeviceList|clean_V2|setWorkMode|getWorkMode|workState|motionState|p2p", re.I)
SECRET = re.compile(r"token|password|secret|authorization|cookie|access_token|refresh_token", re.I)

def now(): return datetime.now(timezone.utc).isoformat()
def redact(x):
    if isinstance(x, dict): return {k:("***REDACTED***" if SECRET.search(str(k)) else redact(v)) for k,v in x.items()}
    if isinstance(x, list): return [redact(v) for v in x]
    return x

def sup(path, method="GET", payload=None, accept="application/json"):
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

def logs(lines=5000):
    r=val(sup(f"/core/logs?lines={lines}&no_colors",accept="text/plain")); text=r if isinstance(r,str) else json.dumps(r,default=str)
    m=[x for x in text.splitlines() if MATCH.search(x)]
    return {"lines_requested":lines,"total_lines":len(text.splitlines()),"match_count":len(m),"matching_lines":m[-10000:]}

def error_log():
    r=val(sup("/core/api/error_log",accept="text/plain")); return r if isinstance(r,str) else json.dumps(r,default=str)

def entries():
    try: return [e for e in json.loads((HA/".storage/core.config_entries").read_text()).get("data",{}).get("entries",[]) if str(e.get("domain"))=="ecovacs"]
    except Exception as e: return [{"error":str(e)}]

def states():
    r=val(sup("/core/api/states")); return [redact(x) for x in r] if isinstance(r,list) else []

def logger(debug):
    level="debug" if debug else "info"
    return sup("/core/api/services/logger/set_level","POST",{"homeassistant.components.ecovacs":level,"ecovacs":level,"deebot_client":level})

def reload_ecovacs():
    es=[e for e in entries() if e.get("entry_id")]
    if not es: return {"ok":False,"error":"No Ecovacs config entry found"}
    eid=es[0]["entry_id"]; r=sup("/core/api/services/homeassistant/reload_config_entry","POST",{"entry_id":eid}); time.sleep(5)
    return {"entry_id":eid,"result":r}

def snapshot():
    l=logs(); return {"timestamp":now(),"config_entries":redact(entries()),"states":[x for x in states() if "ecovacs" in json.dumps(x).lower() or "deebot" in json.dumps(x).lower() or "beepbop" in json.dumps(x).lower()],"logs":l,"error_log":error_log(),"client_inspection":inspect_client("\n".join(l["matching_lines"]))}

def bundle(obj):
    p=SHARE/f"deebot-y1pro-deep-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("diagnostic.json",json.dumps(redact(obj),indent=2,default=str)); z.writestr("core-inspection.sh",core_inspection_script()); z.writestr("README.txt",f"DEEBOT Y1 PRO Diagnostics v{VERSION}.\n")
    return p

def event(j,p,msg):
    with LOCK: JOBS[j].update(percent=p,message=msg); JOBS[j]["events"].append({"time":now(),"percent":p,"message":msg})

def capture(j):
    try:
        event(j,5,"Preparing inspection script"); (HA/"deebot-y1pro-core-inspection.sh").write_text(core_inspection_script())
        event(j,15,"Taking baseline snapshot"); before=snapshot()
        event(j,25,"Enabling DEBUG logging"); logger(True)
        event(j,35,"Reloading Ecovacs integration"); reload_result=reload_ecovacs()
        event(j,45,"Waiting for Y1 PRO traffic"); time.sleep(8)
        event(j,60,"Collecting Core logs"); cap=logs(10000); err=error_log(); text="\n".join(cap["matching_lines"])
        evidence={"cqyi87_lines":[x for x in cap["matching_lines"] if "cqyi87" in x],"clean_V2_lines":[x for x in cap["matching_lines"] if "clean_V2" in x],"work_mode_lines":[x for x in cap["matching_lines"] if re.search(r"workMode|setWorkMode|getWorkMode|workState|motionState",x,re.I)],"p2p_lines":[x for x in cap["matching_lines"] if "p2p" in x.lower()],"command_count":len(re.findall(r"cmdName",text))}
        event(j,75,"Analysing command and P2P evidence"); logger(False)
        event(j,88,"Taking final snapshot"); after=snapshot()
        event(j,95,"Building diagnostic ZIP"); p=bundle({"started_at":JOBS[j]["started_at"],"finished_at":now(),"version":VERSION,"before":before,"reload":reload_result,"capture":{"logs":cap,"error_log":err,"evidence":evidence},"after":after})
        with LOCK: JOBS[j].update(status="complete",percent=100,message="Complete",file=str(p))
    except Exception as e:
        try: logger(False)
        except Exception: pass
        with LOCK: JOBS[j].update(status="error",percent=100,message=str(e),error=str(e))

def start_job():
    j=datetime.now().strftime("%Y%m%d%H%M%S%f")
    with LOCK: JOBS[j]={"started_at":now(),"status":"running","percent":0,"message":"Starting","events":[]}
    threading.Thread(target=capture,args=(j,),daemon=True).start(); return j

def page(job=None):
    if not job: return INDEX.replace("VERSION",VERSION)
    return PROGRESS.replace("JOB",job).replace("VERSION",VERSION)

INDEX='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:900px;margin:25px auto;padding:0 18px}.card{border:1px solid #ddd;border-radius:10px;padding:18px;margin:12px 0}button{padding:12px 18px;border:1px solid #aaa;border-radius:8px;background:white;font-size:16px;cursor:pointer}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>VERSION</b></p><div class="card"><h2>Deep Y1 PRO Capture</h2><p>This starts the diagnostic job immediately and opens its live progress page.</p><form action="./api/deep" method="get"><button type="submit">Run Deep Capture</button></form></div><div class="card"><a href="./api/diagnostic">Run Normal Diagnostic</a> | <a href="./api/health">Health</a> | <a href="./api/core-inspection-script">Inspection Script</a></div></body></html>'''

PROGRESS='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Capture</title><style>body{font-family:system-ui;max-width:900px;margin:25px auto;padding:0 18px}.bar{height:20px;background:#ddd;border-radius:10px;overflow:hidden}.fill{height:100%;background:#1976d2;width:0}.log{background:#111;color:#eee;padding:12px;border-radius:8px;white-space:pre-wrap;font:12px monospace;min-height:220px;max-height:500px;overflow:auto}</style></head><body><h1>DEEBOT Y1 PRO Deep Capture</h1><p>Version <b>VERSION</b> · Job <code>JOB</code></p><div class="bar"><div id="f" class="fill"></div></div><h3 id="s">Starting…</h3><div id="l" class="log">Starting diagnostic job…</div><p id="d"></p><script>(function(){const base='./job/JOB';function poll(){fetch(base+'?t='+Date.now(),{cache:'no-store'}).then(r=>r.json()).then(x=>{document.getElementById('f').style.width=(x.percent||0)+'%';document.getElementById('s').textContent=(x.percent||0)+'% — '+(x.message||'Working');document.getElementById('l').textContent=(x.events||[]).map(e=>'['+e.time+'] '+e.message).join('\\n');if(x.status==='complete'){document.getElementById('d').innerHTML='<a href="../download/JOB">Download diagnostic ZIP</a>'}else if(x.status==='error'){document.getElementById('s').textContent='ERROR — '+x.message}else setTimeout(poll,500)}).catch(e=>{document.getElementById('s').textContent='Polling error — '+e;setTimeout(poll,2000)})}poll()})()</script></body></html>'''

class H(BaseHTTPRequestHandler):
    def send(self,code,body,ctype="application/json"):
        if isinstance(body,str): body=body.encode(); self.send_response(code); self.send_header("Content-Type",ctype); self.send_header("Content-Length",str(len(body))); self.send_header("Cache-Control","no-store"); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        p=self.path.split("?",1)[0]
        if p in ("","/"): return self.send(200,page(),"text/html; charset=utf-8")
        if p=="/api/health": return self.send(200,json.dumps({"ok":True,"version":VERSION,"time":now()}))
        if p=="/api/deep": return self.send(200,page(start_job()),"text/html; charset=utf-8")
        if p=="/api/diagnostic": return self.send(200,json.dumps({"generated_at":now(),"version":VERSION,"environment":{"python":subprocess.run(["python3","--version"],capture_output=True,text=True).stdout.strip(),"arch":os.uname().machine,"hostname":socket.gethostname()},"config_entries":redact(entries()),"states":states(),"core_logs":logs(),"error_log":error_log(),"client_inspection":inspect_client("")},indent=2,default=str))
        if p=="/api/core-inspection-script": return self.send(200,core_inspection_script(),"text/plain")
        m=re.fullmatch(r"/api/job/([A-Za-z0-9_-]+)",p)
        if m:
            with LOCK: x=dict(JOBS.get(m.group(1),{"status":"not_found","percent":0,"message":"Job not found","events":[]}))
            return self.send(200,json.dumps(x,default=str))
        m=re.fullmatch(r"/api/download/([A-Za-z0-9_-]+)",p)
        if m:
            with LOCK: x=JOBS.get(m.group(1))
            if not x or x.get("status")!="complete": return self.send(404,json.dumps({"error":"not ready"}))
            q=Path(x["file"]); return self.send(200,q.read_bytes(),"application/zip")
        return self.send(404,json.dumps({"error":"not found"}))
    def do_POST(self):
        if self.path.split("?",1)[0]=="/api/deep": return self.send(202,json.dumps({"job":start_job()}))
        return self.send(404,json.dumps({"error":"not found"}))
    def log_message(self,*a): pass

if __name__=="__main__": ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
