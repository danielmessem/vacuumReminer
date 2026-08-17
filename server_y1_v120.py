#!/usr/bin/env python3
"""DEEBOT Y1 PRO protocol diagnostics v1.2.0."""
import base64, json, os, re, threading, time, urllib.error, urllib.request, zipfile
from collections import Counter
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.2.0"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
TOKEN = os.environ.get("SUPERVISOR_TOKEN")
JOBS = {}
LOCK = threading.Lock()
MATCH = re.compile(r"ecovacs|deebot|beepbop|cqyi87|CARTESIAN|clean_V2|setWorkMode|getWorkMode|workState|motionState|30000|10000|p2p|cmdName|unsupported|exception|traceback|error", re.I)
SECRET = re.compile(r"token|password|secret|authorization|cookie|access_token|refresh_token", re.I)


def now(): return datetime.now(timezone.utc).isoformat()

def redact(x):
    if isinstance(x, dict): return {k: ("***REDACTED***" if SECRET.search(str(k)) else redact(v)) for k,v in x.items()}
    if isinstance(x, list): return [redact(v) for v in x]
    return x

def sup(path, method="GET", payload=None, accept="application/json"):
    if not TOKEN: return {"ok": False, "error": "SUPERVISOR_TOKEN unavailable"}
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request("http://supervisor" + path, data=body, method=method,
        headers={"Authorization":"Bearer "+TOKEN,"Content-Type":"application/json","Accept":accept})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode(errors="replace")
            if "application/json" in r.headers.get("Content-Type",""):
                try: raw = json.loads(raw)
                except Exception: pass
            return {"ok":True,"status":r.status,"data":redact(raw)}
    except urllib.error.HTTPError as e: return {"ok":False,"status":e.code,"error":e.read().decode(errors="replace")[:10000]}
    except Exception as e: return {"ok":False,"error":str(e)}

def val(r): return r.get("data") if isinstance(r,dict) and r.get("ok") else r

def service(domain,name,data): return sup(f"/core/api/services/{domain}/{name}","POST",data)

def entries():
    try:
        return [e for e in json.loads((HA/".storage/core.config_entries").read_text()).get("data",{}).get("entries",[]) if e.get("domain")=="ecovacs"]
    except Exception as e: return [{"error":str(e)}]

def logs(lines=12000):
    r=val(sup(f"/core/logs?lines={lines}&no_colors",accept="text/plain"))
    text=r if isinstance(r,str) else json.dumps(r,default=str)
    m=[x for x in text.splitlines() if MATCH.search(x)]
    return m[-12000:]

def states():
    r=val(sup("/core/api/states"))
    return [redact(x) for x in r] if isinstance(r,list) else []

def logger(debug):
    return service("logger","set_level",{"homeassistant.components.ecovacs":"debug" if debug else "info","ecovacs":"debug" if debug else "info","deebot_client":"debug" if debug else "info"})

def parse_payload(line):
    m=re.search(r"payload=b'(.*)'$",line)
    if not m: return None
    try: return json.loads(m.group(1))
    except Exception: return None

def protocol_analysis(lines):
    p100=[]; p300=[]; work=[]; clean=[]
    for line in lines:
        p=parse_payload(line)
        if not p: continue
        if "10000" in line: p100.append(p)
        if "30000" in line: p300.append(p)
        if re.search(r"workMode|workState|motionState",line,re.I): work.append(line)
        if "clean_V2" in line: clean.append(line)
    events=[]
    for p in p100:
        data=p.get("body",{}).get("data",{})
        if not isinstance(data,dict): continue
        h=p.get("header",{})
        for k,v in data.items():
            if k in ("battery","cleanArea","cleanTime","pauseSwitch","status","chargeStatus","message","dormant","cleanLogReport"):
                events.append({"type":"10000","ts":h.get("ts"),"field":k,"value":v})
    positions=[]; map_variants=Counter()
    for p in p300:
        data=p.get("body",{}).get("data",{})
        if not isinstance(data,dict): continue
        h=p.get("header",{})
        if "pos" in data:
            pos=data["pos"]
            positions.append({"ts":h.get("ts"),"mapId":data.get("mapId"),"x":pos.get("x"),"y":pos.get("y"),"angle":pos.get("a"),"i":pos.get("i")})
            map_variants["mapTraceData"] += 1
        if "mapMinorData" in data: map_variants["mapMinorData"] += 1
        if "mapData" in data: map_variants["mapData"] += 1
    transitions=[]
    last={}
    for e in sorted(events,key=lambda x:str(x.get("ts"))):
        k=e["field"]
        if last.get(k)!=e["value"]:
            transitions.append(e); last[k]=e["value"]
    return {
        "message_10000_count":len(p100),"message_30000_count":len(p300),
        "10000_fields":dict(Counter(e["field"] for e in events)),
        "10000_transitions":transitions,
        "30000_variants":dict(map_variants),
        "position_count":len(positions),
        "first_position":positions[0] if positions else None,
        "last_position":positions[-1] if positions else None,
        "position_bounds":({"min_x":min(x["x"] for x in positions if isinstance(x["x"],(int,float))),"max_x":max(x["x"] for x in positions if isinstance(x["x"],(int,float))),"min_y":min(x["y"] for x in positions if isinstance(x["y"],(int,float))),"max_y":max(x["y"] for x in positions if isinstance(x["y"],(int,float)))} if positions else None),
        "work_state_log_lines":work[-100:],
        "clean_v2_log_lines":clean[-100:],
        "interpretation":{
            "battery": "10000 contains battery percentage updates; current client labels 10000 unknown.",
            "clean_state": "10000 contains status/chargeStatus/pauseSwitch events; these are strong candidates for Y1 PRO work-state telemetry.",
            "movement": "30000 contains position x/y and map trace/map data; current client labels 30000 unknown.",
            "control": "Compare 10000 status transitions immediately before/after clean_V2 and work-mode commands to determine whether the robot actually enters cleaning state."
        }
    }

def capture(label, seconds=4):
    logger(True); before=logs(5000); time.sleep(seconds); after=logs(12000); logger(False)
    return {"label":label,"before_tail":before[-300:],"after_tail":after[-3000:],"protocol_analysis":protocol_analysis(after)}

def run_service_test(label, domain="vacuum", name=None, data=None):
    logger(True); before=logs(3000)
    result=service(domain,name,data or {}) if name else {"ok":False,"error":"no service"}
    time.sleep(4); after=logs(12000); states_after=states(); logger(False)
    return {"label":label,"service":f"{domain}.{name}","data":data,"result":result,"states":states_after,"protocol_analysis":protocol_analysis(after),"log_tail":after[-3000:]}

def snapshot():
    lines=logs(5000)
    return {"timestamp":now(),"config_entries":redact(entries()),"states":states(),"protocol_analysis":protocol_analysis(lines),"logs":lines[-3000:]}

def make_zip(obj):
    SHARE.mkdir(parents=True,exist_ok=True)
    p=SHARE/f"deebot-y1pro-protocol-{datetime.now():%Y%m%d-%H%M%S}.zip"
    analysis=obj.get("protocol_analysis",{})
    with zipfile.ZipFile(p,"w",zipfile.ZIP_DEFLATED) as z:
        z.writestr("REPORT.json",json.dumps(redact(obj),indent=2,default=str))
        z.writestr("PROTOCOL_SUMMARY.txt",summary(analysis))
        z.writestr("README.txt",f"DEEBOT Y1 PRO Protocol Diagnostics v{VERSION}\nGenerated {now()}\n")
    return p

def summary(a):
    return """DEEBOT Y1 PRO PROTOCOL SUMMARY\n===============================\n\n10000 is treated as a device-state/event channel. The observed payload fields are retained with timestamped transitions.\n30000 is treated as a map/position channel. Position samples and map-data variants are summarised.\n\nThis report is evidence from the device logs; it does not claim that a field's semantics are fully proven beyond the observed payload names/values.\n\n""" + json.dumps(a,indent=2,default=str)

def deep(job):
    try:
        with LOCK: JOBS[job].update(percent=5,message="Baseline protocol snapshot")
        before=snapshot()
        with LOCK: JOBS[job].update(percent=15,message="Reloading Ecovacs integration")
        es=[e for e in entries() if e.get("entry_id")]
        reload_result=service("homeassistant","reload_config_entry",{"entry_id":es[0]["entry_id"]}) if es else {"ok":False,"error":"No Ecovacs config entry"}
        time.sleep(5)
        with LOCK: JOBS[job].update(percent=30,message="Testing work-mode command")
        wm=run_service_test("set_work_mode_vacuum","vacuum","send_command",{"entity_id":"vacuum.beepbop","command":"setWorkMode","params":{"mode":1}})
        with LOCK: JOBS[job].update(percent=45,message="Testing clean_V2")
        start=run_service_test("clean_v2_start","vacuum","send_command",{"entity_id":"vacuum.beepbop","command":"clean_V2","params":{"act":"start","content":{"type":"auto"}}})
        with LOCK: JOBS[job].update(percent=60,message="Capturing 10000/30000 telemetry")
        telemetry=capture("post_clean_telemetry",8)
        with LOCK: JOBS[job].update(percent=72,message="Stopping cleaning")
        stop=run_service_test("clean_v2_stop","vacuum","send_command",{"entity_id":"vacuum.beepbop","command":"clean_V2","params":{"act":"stop"}})
        with LOCK: JOBS[job].update(percent=84,message="Final protocol snapshot")
        after=snapshot()
        combined=logs(12000); analysis=protocol_analysis(combined)
        obj={"version":VERSION,"before":before,"reload":reload_result,"work_mode_test":wm,"clean_start_test":start,"telemetry":telemetry,"clean_stop_test":stop,"after":after,"protocol_analysis":analysis}
        with LOCK: JOBS[job].update(percent=94,message="Generating protocol report")
        p=make_zip(obj)
        with LOCK: JOBS[job].update(status="complete",percent=100,message="Complete",file=str(p))
    except Exception as e:
        try: logger(False)
        except Exception: pass
        with LOCK: JOBS[job].update(status="error",percent=100,message=str(e))

def start_deep():
    j=datetime.now().strftime("%Y%m%d%H%M%S%f")
    with LOCK: JOBS[j]={"status":"running","percent":0,"message":"Starting","started_at":now()}
    threading.Thread(target=deep,args=(j,),daemon=True).start(); return j

HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Y1 PRO Protocol Diagnostics</title><style>body{font-family:system-ui;max-width:1000px;margin:25px auto;padding:0 18px}.card{border:1px solid #ddd;border-radius:10px;padding:18px;margin:12px 0}button{padding:12px 16px;margin:4px;border:1px solid #aaa;border-radius:8px;background:white;cursor:pointer}.out{background:#111;color:#eee;padding:12px;white-space:pre-wrap;font:12px monospace;max-height:600px;overflow:auto}.bar{height:18px;background:#ddd;border-radius:9px;overflow:hidden}.fill{height:100%;width:0%;background:#1976d2}</style></head><body><h1>DEEBOT Y1 PRO Protocol Diagnostics</h1><p>Version <b>VERSION</b></p><div class="card"><h2>One-button protocol capture</h2><p>Captures work-mode control, clean_V2, and the Y1 PRO 10000/30000 telemetry channels, then generates a ZIP containing raw evidence and a decoded protocol summary.</p><button id="run" onclick="run()">Run Protocol Test & Generate File</button><div class="bar"><div id="fill" class="fill"></div></div><p id="status">Ready</p><pre id="out" class="out">Press the button to start.</pre></div><script>async function run(){let b=document.getElementById('run'),o=document.getElementById('out'),s=document.getElementById('status'),f=document.getElementById('fill');b.disabled=true;o.textContent='Starting…';try{let r=await fetch('./api/deep',{method:'POST'}),j=await r.json();if(!j.job)throw Error(JSON.stringify(j));async function poll(){let x=await fetch('./api/job/'+j.job+'?t='+Date.now()).then(r=>r.json());f.style.width=x.percent+'%';s.textContent=x.percent+'% — '+x.message;o.textContent=(x.events||[]).map(e=>e.message).join('\\n');if(x.status==='complete'){o.textContent+='\\n\\nProtocol report ready.';o.innerHTML+='\\n<a href="./api/download/'+j.job+'">Download Protocol Diagnostic ZIP</a>';b.disabled=false}else if(x.status==='error'){o.textContent+='\\nERROR: '+x.message;b.disabled=false}else setTimeout(poll,700)}poll()}catch(e){o.textContent='ERROR: '+e;b.disabled=false}} </script></body></html>'''.replace('VERSION',VERSION)

class H(BaseHTTPRequestHandler):
    def sendx(self,c,b,ct="application/json",fn=None):
        if isinstance(b,str): b=b.encode()
        self.send_response(c); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-store")
        if fn: self.send_header("Content-Disposition",f'attachment; filename="{fn}"')
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        p=self.path.split("?",1)[0]
        if p in ("","/"): return self.sendx(200,HTML,"text/html; charset=utf-8")
        if p=="/api/health": return self.sendx(200,json.dumps({"ok":True,"version":VERSION,"time":now()}))
        m=re.fullmatch(r"/api/job/([A-Za-z0-9_-]+)",p)
        if m:
            with LOCK: x=dict(JOBS.get(m.group(1),{"status":"not_found"}))
            return self.sendx(200,json.dumps(x,default=str))
        m=re.fullmatch(r"/api/download/([A-Za-z0-9_-]+)",p)
        if m:
            with LOCK: x=JOBS.get(m.group(1))
            if not x or x.get("status")!="complete": return self.sendx(404,json.dumps({"error":"not ready"}))
            q=Path(x["file"])
            if not q.is_file(): return self.sendx(404,json.dumps({"error":"diagnostic file missing"}))
            return self.sendx(200,q.read_bytes(),"application/zip",q.name)
        return self.sendx(404,json.dumps({"error":"not found"}))
    def do_POST(self):
        if self.path.split("?",1)[0]=="/api/deep": return self.sendx(202,json.dumps({"job":start_deep()}))
        return self.sendx(404,json.dumps({"error":"not found"}))
    def log_message(self,*a): pass

if __name__=="__main__": ThreadingHTTPServer(("0.0.0.0",PORT),H).serve_forever()
