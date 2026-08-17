#!/usr/bin/env python3
"""DEEBOT Y1 PRO diagnostics + one-button command laboratory."""
import json, os, re, socket, subprocess, threading, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from installed_client_inspector import inspect as inspect_client, core_inspection_script

VERSION = "1.1.8"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
TOKEN = os.environ.get("SUPERVISOR_TOKEN")
JOBS = {}
LOCK = threading.Lock()
MATCH = re.compile(r"ecovacs|deebot|beepbop|cqyi87|CARTESIAN|clean_V2|setWorkMode|getWorkMode|workState|motionState|p2p|cmdName|unsupported|exception|traceback|error|30000|10000", re.I)
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
    return {"lines_requested":lines,"match_count":len(m),"matching_lines":m[-15000:]}

def states():
    r=val(sup("/core/api/states")); return r if isinstance(r,list) else []

def service(domain,service,data=None):
    return sup(f"/core/api/services/{domain}/{service}","POST",data or {})

def logger(debug):
    level="debug" if debug else "info"
    return service("logger","set_level",{"homeassistant.components.ecovacs":level,"ecovacs":level,"deebot_client":level})

def ecovacs_reload():
    es=[e for e in entries() if e.get("entry_id")]
    if not es: return {"ok":False,"error":"No Ecovacs config entry found"}
    r=service("homeassistant","reload_config_entry",{"entry_id":es[0]["entry_id"]}); time.sleep(4); return r

def relevant_states():
    return [x for x in states() if re.search(r"ecovacs|deebot|beepbop",json.dumps(x),re.I)]

def evidence():
    l=logs(12000); text="\n".join(l["matching_lines"])
    return {"captured_at":now(),"cqyi87":[x for x in l["matching_lines"] if "cqyi87" in x],"clean_V2":[x for x in l["matching_lines"] if "clean_V2" in x],"work_mode_state":[x for x in l["matching_lines"] if re.search(r"workMode|setWorkMode|getWorkMode|workState|motionState",x,re.I)],"map_motion_10000_30000":[x for x in l["matching_lines"] if re.search(r"10000|30000",x)],"p2p":[x for x in l["matching_lines"] if "p2p" in x.lower()],"cmd_count":len(re.findall(r"cmdName",text))}

def snapshot():
    l=logs(8000)
    return {"timestamp":now(),"config_entries":redact(entries()),"states":relevant_states(),"logs":l,"client_inspection":inspect_client("\n".join(l["matching_lines"]))}

def make_zip(obj):
    SHARE.mkdir(parents=True,exist_ok=True)
    p=SHARE/f"deebot-y1pro-full-command-test-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("diagnostic.json",json.dumps(redact(obj),indent=2,default=str))
        z.writestr("core-inspection.sh",core_inspection_script())
        z.writestr("README.txt",f"DEEBOT Y1 PRO full command test v{VERSION}.\nThe test uses the existing Home Assistant Ecovacs services and captures Core/API/MQTT evidence.\n")
    return p

def event(job, percent, message, **extra):
    with LOCK:
        JOBS[job]["percent"]=percent; JOBS[job]["message"]=message
        JOBS[job]["events"].append({"time":now(),"percent":percent,"message":message,**extra})

def capture_stage(name, seconds=0):
    if seconds: time.sleep(seconds)
    return {"stage":name,"captured_at":now(),"states":relevant_states(),"evidence":evidence()}

def full_test(j):
    """Run the complete non-destructive HA command sequence and create one bundle."""
    try:
        event(j,3,"Taking baseline snapshot")
        before=snapshot()
        event(j,8,"Enabling Ecovacs / deebot_client DEBUG logging")
        logger(True)
        event(j,12,"Reloading Ecovacs integration")
        reload_result=ecovacs_reload()
        event(j,20,"Capturing post-reload state")
        stages=[capture_stage("after_reload",2)]

        event(j,27,"START CLEAN — vacuum.start")
        start_result=service("vacuum","start",{"entity_id":"vacuum.beepbop"})
        stages.append({"stage":"start_command","service_result":start_result})
        event(j,35,"Waiting 8 seconds for device state / MQTT traffic")
        stages.append(capture_stage("after_start",8))

        event(j,43,"PAUSE — vacuum.pause")
        pause_result=service("vacuum","pause",{"entity_id":"vacuum.beepbop"})
        stages.append({"stage":"pause_command","service_result":pause_result})
        stages.append(capture_stage("after_pause",4))

        event(j,52,"RESUME — vacuum.start")
        resume_result=service("vacuum","start",{"entity_id":"vacuum.beepbop"})
        stages.append({"stage":"resume_command","service_result":resume_result})
        stages.append(capture_stage("after_resume",6))

        event(j,65,"STOP — vacuum.stop")
        stop_result=service("vacuum","stop",{"entity_id":"vacuum.beepbop"})
        stages.append({"stage":"stop_command","service_result":stop_result})
        stages.append(capture_stage("after_stop",4))

        event(j,77,"RETURN TO BASE — vacuum.return_to_base")
        dock_result=service("vacuum","return_to_base",{"entity_id":"vacuum.beepbop"})
        stages.append({"stage":"dock_command","service_result":dock_result})
        stages.append(capture_stage("after_dock",6))

        event(j,90,"Restoring normal log levels")
        logger(False)
        event(j,94,"Taking final snapshot")
        after=snapshot()
        result={"version":VERSION,"started_at":JOBS[j]["started_at"],"finished_at":now(),"test":"full_command_sequence","note":"The current HA Ecovacs service layer exposes start/stop/pause/return_to_base; raw setWorkMode/getWorkMode/getWorkState are captured if the integration emits them during these operations, but are not falsely claimed as directly invoked.","before":before,"reload":reload_result,"stages":stages,"final":after,"summary":{"start":start_result,"pause":pause_result,"resume":resume_result,"stop":stop_result,"dock":dock_result}}
        event(j,97,"Building diagnostic ZIP")
        p=make_zip(result)
        with LOCK: JOBS[j].update(status="complete",percent=100,message="Complete",file=str(p),file_name=p.name)
    except Exception as e:
        try: logger(False)
        except Exception: pass
        with LOCK: JOBS[j].update(status="error",percent=100,message=str(e),error=str(e))

def start_job():
    j=datetime.now().strftime("%Y%m%d%H%M%S%f")
    with LOCK: JOBS[j]={"status":"running","percent":0,"message":"Starting","events":[],"started_at":now()}
    threading.Thread(target=full_test,args=(j,),daemon=True).start()
    return j

INDEX='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:950px;margin:25px auto;padding:0 18px}.card{border:1px solid #ddd;border-radius:10px;padding:18px;margin:12px 0}button{padding:12px 18px;margin:4px;border:1px solid #aaa;border-radius:8px;background:white;cursor:pointer;font-size:16px}.bar{height:18px;background:#ddd;border-radius:10px;overflow:hidden}.fill{height:100%;width:0;background:#1976d2}.out{background:#111;color:#eee;padding:12px;white-space:pre-wrap;font:12px monospace;max-height:500px;overflow:auto}.status{font-weight:600}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>VERSION</b></p><div class="card"><h2>Full Y1 PRO Command Test</h2><p>One button runs the complete safe test sequence, captures Home Assistant/Core/API/MQTT evidence at every stage, and creates one ZIP file.</p><button id="run">Run Full Test &amp; Generate File</button><div class="bar"><div id="fill" class="fill"></div></div><p id="status" class="status">Ready</p><pre id="out" class="out">Press the button to begin.</pre><p id="download"></p></div><script>(function(){const root=(location.pathname.endsWith('/')?location.pathname:location.pathname+'/');const u=p=>new URL(p,location.origin+root).toString();const run=document.getElementById('run'),fill=document.getElementById('fill'),status=document.getElementById('status'),out=document.getElementById('out'),download=document.getElementById('download');run.onclick=async()=>{run.disabled=true;download.innerHTML='';out.textContent='Starting full test…';try{const r=await fetch(u('api/full-test'),{method:'POST',cache:'no-store'});const j=await r.json();if(!r.ok||!j.job)throw Error(j.error||('HTTP '+r.status));const poll=async()=>{const s=await fetch(u('api/job/'+encodeURIComponent(j.job)+'?t='+Date.now()),{cache:'no-store'}).then(x=>x.json());fill.style.width=(s.percent||0)+'%';status.textContent=(s.percent||0)+'% — '+(s.message||'Working');out.textContent=(s.events||[]).map(e=>'['+e.time+'] '+e.message).join('\\n');out.scrollTop=out.scrollHeight;if(s.status==='complete'){download.innerHTML='<a href="'+u('api/download/'+encodeURIComponent(j.job))+'">Download Full Diagnostic ZIP</a>';run.disabled=false;return}if(s.status==='error'){status.textContent='ERROR — '+s.message;out.textContent+='\\n\\n'+(s.error||'');run.disabled=false;return}setTimeout(poll,500)};poll()}catch(e){status.textContent='ERROR';out.textContent=e.stack||e.message;run.disabled=false}}})();</script></body></html>'''

class H(BaseHTTPRequestHandler):
    def sendx(self,c,b,ct="application/json",fn=None):
        if isinstance(b,str): b=b.encode()
        self.send_response(c); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-store")
        if fn:self.send_header("Content-Disposition",f'attachment; filename="{fn}"')
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p=self.path.split("?",1)[0]
        if p in ("","/"): return self.sendx(200,INDEX.replace("VERSION",VERSION),"text/html; charset=utf-8")
        if p=="/api/health": return self.sendx(200,json.dumps({"ok":True,"version":VERSION,"time":now()}))
        if p=="/api/full-test": return self.sendx(202,json.dumps({"job":start_job(),"status":"started"}))
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
        p=self.path.split("?",1)[0]
        if p=="/api/full-test":return self.sendx(202,json.dumps({"job":start_job()}))
        return self.sendx(404,json.dumps({"error":"not found"}))
    def log_message(self,*a):pass

if __name__=="__main__": ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
