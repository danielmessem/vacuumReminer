#!/usr/bin/env python3
"""DEEBOT Y1 PRO protocol diagnostics v1.3.1.

Uses the Docker API/CLI to capture Home Assistant Core's actual container logs
while the browser drives the authenticated HA service calls. No Supervisor
credential is required.
"""
import json
import re
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.3.1"
PORT = 8099
SHARE = Path("/share")
JOBS = {}
LOCK = threading.Lock()
MATCH = re.compile(
    r"ecovacs|deebot|beepbop|cqyi87|CARTESIAN|clean_V2|setWorkMode|"
    r"getWorkMode|getWorkState|workState|motionState|30000|10000|p2p|"
    r"cmdName|unsupported|exception|traceback|error|warning",
    re.I,
)


def docker_names():
    try:
        p = subprocess.run(
            ["docker", "ps", "--format", "{{.ID}}\t{{.Names}}"],
            capture_output=True, text=True, timeout=10,
        )
        if p.returncode:
            return [], p.stderr.strip()
        rows = [x.split("\t", 1) for x in p.stdout.splitlines() if "\t" in x]
        return [r for r in rows if re.search(r"homeassistant", r[1], re.I)], ""
    except Exception as e:
        return [], str(e)


def core_logs(since="30s"):
    """Read the real HA Core container log, not /core/logs API output."""
    containers, err = docker_names()
    if not containers:
        return [], {"ok": False, "error": "Home Assistant container not found", "detail": err}
    out = []
    errors = []
    for cid, name in containers:
        try:
            p = subprocess.run(
                ["docker", "logs", "--since", since, "--timestamps", cid],
                capture_output=True, text=True, timeout=20,
            )
            if p.returncode:
                errors.append({"container": name, "error": p.stderr.strip()})
                continue
            for line in (p.stdout + p.stderr).splitlines():
                if MATCH.search(line):
                    out.append(line)
        except Exception as e:
            errors.append({"container": name, "error": str(e)})
    # Preserve order while removing duplicates caused by stdout/stderr overlap.
    seen = set()
    unique = []
    for line in out:
        if line not in seen:
            seen.add(line)
            unique.append(line)
    return unique[-20000:], {"ok": bool(unique), "containers": containers, "errors": errors}


def analyse(lines):
    c100 = sum("10000" in x for x in lines)
    c300 = sum("30000" in x for x in lines)
    return {
        "10000_count": c100,
        "30000_count": c300,
        "clean_V2": [x for x in lines if "clean_V2" in x][-200:],
        "work_mode_and_state": [
            x for x in lines if re.search(r"workMode|workState|motionState", x, re.I)
        ][-200:],
        "p2p": [x for x in lines if "p2p" in x.lower()][-200:],
        "message_10000": [x for x in lines if "10000" in x][-200:],
        "message_30000": [x for x in lines if "30000" in x][-200:],
    }


def makezip(obj):
    SHARE.mkdir(parents=True, exist_ok=True)
    p = SHARE / f"deebot-y1pro-protocol-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("REPORT.json", json.dumps(obj, indent=2, default=str))
        z.writestr("PROTOCOL_SUMMARY.txt", json.dumps(obj["analysis"], indent=2, default=str))
        z.writestr("README.txt", f"DEEBOT Y1 PRO Diagnostics v{VERSION}\n")
    return p


def collector(job):
    """Poll Docker logs during the entire browser-driven test."""
    seen = set()
    while True:
        with LOCK:
            if JOBS.get(job, {}).get("collector_stop"):
                break
        lines, meta = core_logs("3s")
        with LOCK:
            JOBS[job].setdefault("capture_meta", []).append(meta)
            buf = JOBS[job].setdefault("live_logs", [])
            for line in lines:
                if line not in seen:
                    seen.add(line)
                    buf.append(line)
            if len(buf) > 30000:
                del buf[:-30000]
        time.sleep(0.5)


def worker(j):
    try:
        with LOCK:
            JOBS[j].update(percent=5, message="Starting direct Core log capture")
        before, before_meta = core_logs("5m")
        with LOCK:
            JOBS[j]["before"] = before[-4000:]
            JOBS[j]["before_capture"] = before_meta
        t = threading.Thread(target=collector, args=(j,), daemon=True)
        t.start()
        with LOCK:
            JOBS[j].update(percent=15, message="Ready — run commands from the authenticated HA session")
        deadline = time.time() + 120
        while time.time() < deadline:
            with LOCK:
                done = JOBS[j].get("finished")
            if done:
                break
            time.sleep(0.25)
        with LOCK:
            JOBS[j]["collector_stop"] = True
            JOBS[j].update(percent=90, message="Finalising direct Core log capture")
        t.join(timeout=3)
        after, after_meta = core_logs("2m")
        with LOCK:
            live = list(JOBS[j].get("live_logs", []))
            steps = list(JOBS[j].get("steps", []))
        # Include both the continuously collected stream and a final window.
        combined = []
        seen = set()
        for line in live + after:
            if line not in seen:
                seen.add(line)
                combined.append(line)
        analysis = analyse(combined)
        obj = {
            "version": VERSION,
            "steps": steps,
            "before": before[-4000:],
            "after": combined[-20000:],
            "capture": {
                "before": before_meta,
                "polls": JOBS[j].get("capture_meta", []),
                "final": after_meta,
                "log_capture_method": "docker logs from Home Assistant Core container",
            },
            "analysis": analysis,
        }
        with LOCK:
            JOBS[j].update(percent=95, message="Generating diagnostic ZIP")
        p = makezip(obj)
        with LOCK:
            JOBS[j].update(status="complete", percent=100, message="Complete", file=str(p))
    except Exception as e:
        with LOCK:
            JOBS[j].update(status="error", percent=100, message=str(e))


def newjob():
    j = datetime.now().strftime("%Y%m%d%H%M%S%f")
    with LOCK:
        JOBS[j] = {"status": "running", "percent": 0, "message": "Starting", "steps": []}
    threading.Thread(target=worker, args=(j,), daemon=True).start()
    return j


HTML = f'''<!doctype html><meta name="viewport" content="width=device-width">
<title>DEEBOT Y1 PRO Diagnostics</title>
<style>body{{font-family:system-ui;max-width:1000px;margin:25px auto;padding:0 18px}}
button{{padding:12px 16px;border:1px solid #aaa;border-radius:8px;background:white}}
pre{{background:#111;color:#eee;padding:12px;white-space:pre-wrap;max-height:600px;overflow:auto}}
.bar{{height:18px;background:#ddd}}#fill{{height:100%;width:0%;background:#1976d2}}</style>
<h1>DEEBOT Y1 PRO Protocol Diagnostics</h1><p>Version <b>{VERSION}</b></p>
<button id="b" onclick="run()">Run Full Protocol Test & Generate File</button>
<div class="bar"><div id="fill"></div></div><p id="s">Ready</p><pre id="o">Press the button to start.</pre>
<script>
function H(){{try{{let e=window.top.document.querySelector('home-assistant');if(e&&e.hass)return e.hass}}catch(e){{}}try{{if(window.parent.hass)return window.parent.hass}}catch(e){{}}return null}}
async function call(name,data){{let h=H();if(!h||!h.callService)throw Error('Authenticated Home Assistant frontend connection unavailable');return h.callService('vacuum','send_command',{{entity_id:'vacuum.beepbop',command:name,params:data||{{}}}})}}
async function step(j,name,fn){{try{{let r=await fn();await fetch('./api/step/'+j,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,status:'ok',result:r||null}})}})}}catch(e){{await fetch('./api/step/'+j,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,status:'error',error:String(e)}})}});throw e}}}}
async function run(){{let b=document.getElementById('b'),o=document.getElementById('o'),s=document.getElementById('s'),f=document.getElementById('fill');b.disabled=true;let r=await fetch('./api/deep',{{method:'POST'}});let j=(await r.json()).job;let poll=async()=>{{let x=await fetch('./api/job/'+j+'?x='+Date.now()).then(r=>r.json());f.style.width=x.percent+'%';s.textContent=x.percent+'% — '+x.message;o.textContent=(x.steps||[]).map(e=>e.name+': '+e.status+(e.error?' — '+e.error:'')).join('\\n');if(x.status==='complete'){{o.innerHTML+='\\n\\n<a href="./api/download/'+j+'">Download diagnostic ZIP</a>';b.disabled=false}}else if(x.status==='error'){{o.textContent+='\\nERROR: '+x.message;b.disabled=false}}else setTimeout(poll,500)}};poll();try{{await step(j,'setWorkMode VACUUM',()=>call('setWorkMode',{{mode:1}}));await new Promise(r=>setTimeout(r,3000));await step(j,'getWorkMode',()=>call('getWorkMode'));await step(j,'getWorkState',()=>call('getWorkState'));await step(j,'clean_V2 START',()=>call('clean_V2',{{act:'start',content:{{type:'auto'}}}}));await new Promise(r=>setTimeout(r,10000));await step(j,'getWorkState after clean',()=>call('getWorkState'));await step(j,'clean_V2 STOP',()=>call('clean_V2',{{act:'stop'}}));await new Promise(r=>setTimeout(r,3000));await fetch('./api/finish/'+j,{{method:'POST'}})}}catch(e){{o.textContent+='\\nERROR: '+e;await fetch('./api/finish/'+j,{{method:'POST'}})}}}}
</script>'''


class Hdl(BaseHTTPRequestHandler):
    def sendx(self, c, b, ct="application/json", fn=None):
        if isinstance(b, str):
            b = b.encode()
        self.send_response(c)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        if fn:
            self.send_header("Content-Disposition", f'attachment; filename="{fn}"')
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path.split("?", 1)[0]
        if p in ("", "/"):
            return self.sendx(200, HTML, "text/html; charset=utf-8")
        m = re.fullmatch(r"/api/job/([A-Za-z0-9_-]+)", p)
        if m:
            with LOCK:
                x = dict(JOBS.get(m.group(1), {"status": "not_found"}))
                x["steps"] = list(x.get("steps", []))
            return self.sendx(200, json.dumps(x, default=str))
        m = re.fullmatch(r"/api/download/([A-Za-z0-9_-]+)", p)
        if m:
            with LOCK:
                x = JOBS.get(m.group(1))
            if not x or x.get("status") != "complete":
                return self.sendx(404, json.dumps({"error": "not ready"}))
            q = Path(x["file"])
            if not q.is_file():
                return self.sendx(404, json.dumps({"error": "file missing"}))
            return self.sendx(200, q.read_bytes(), "application/zip", q.name)
        return self.sendx(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        p = self.path.split("?", 1)[0]
        if p == "/api/deep":
            return self.sendx(200, json.dumps({"job": newjob()}))
        m = re.fullmatch(r"/api/step/([A-Za-z0-9_-]+)", p)
        if m:
            n = int(self.headers.get("Content-Length", "0"))
            d = json.loads(self.rfile.read(n) or b"{}")
            with LOCK:
                if m.group(1) in JOBS:
                    JOBS[m.group(1)].setdefault("steps", []).append(d)
            return self.sendx(200, json.dumps({"ok": True}))
        m = re.fullmatch(r"/api/finish/([A-Za-z0-9_-]+)", p)
        if m:
            with LOCK:
                if m.group(1) in JOBS:
                    JOBS[m.group(1)]["finished"] = True
            return self.sendx(200, json.dumps({"ok": True}))
        return self.sendx(404, json.dumps({"error": "not found"}))

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("0.0.0.0", PORT), Hdl).serve_forever()
