#!/usr/bin/env python3
"""DEEBOT Y1 PRO diagnostic web application."""
import json, os, re, socket, subprocess, threading, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from installed_client_inspector import inspect as inspect_client, core_inspection_script

PORT = 8099
VERSION = "1.1.2"
HA_CONFIG = Path("/homeassistant")
SHARE = Path("/share")
SUPERVISOR = "http://supervisor"
JOBS = {}
LOCK = threading.Lock()
LOG_RE = re.compile(r"ecovacs|deebot|beepbop|cqyi87|CARTESIAN|y30|unsupported|exception|traceback|auth|discover|error|deebot[-_ ]?client|GetDeviceList|GetGlobalDeviceList|clean_V2|setWorkMode|getWorkMode|workState|motionState|p2p", re.I)
SENSITIVE = re.compile(r"token|password|secret|authorization|cookie|access_token|refresh_token", re.I)


def now():
    return datetime.now(timezone.utc).isoformat()


def redact(value):
    if isinstance(value, dict):
        return {k: ("***REDACTED***" if SENSITIVE.search(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    return value


def supervisor(path, method="GET", payload=None, accept="application/json"):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        return {"ok": False, "error": "SUPERVISOR_TOKEN unavailable"}
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(SUPERVISOR + path, data=body, method=method, headers={"Authorization": "Bearer " + token, "Content-Type": "application/json", "Accept": accept})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            raw = response.read().decode(errors="replace")
            if "application/json" in response.headers.get("Content-Type", ""):
                try: raw = json.loads(raw)
                except Exception: pass
            return {"ok": True, "status": response.status, "data": redact(raw)}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status": exc.code, "error": exc.read().decode(errors="replace")[:10000]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def data(response):
    return response.get("data") if isinstance(response, dict) and response.get("ok") else response


def core_logs(lines=5000):
    result = supervisor(f"/core/logs?lines={lines}&no_colors", accept="text/plain")
    text = data(result)
    if not isinstance(text, str): text = json.dumps(text, default=str)
    matching = [line for line in text.splitlines() if LOG_RE.search(line)]
    return {"lines_requested": lines, "total_lines": len(text.splitlines()), "match_count": len(matching), "matching_lines": matching[-10000:]}


def error_log():
    result = data(supervisor("/core/api/error_log", accept="text/plain"))
    return result if isinstance(result, str) else json.dumps(result, default=str)


def config_entries():
    try:
        entries = json.loads((HA_CONFIG / ".storage/core.config_entries").read_text()).get("data", {}).get("entries", [])
        return [e for e in entries if str(e.get("domain", "")).lower() == "ecovacs"]
    except Exception as exc:
        return [{"error": str(exc)}]


def states():
    result = data(supervisor("/core/api/states"))
    if not isinstance(result, list): return []
    return [redact(x) for x in result if "vacuum" in x.get("entity_id", "").lower() or any(q in json.dumps(x).lower() for q in ("ecovacs", "deebot", "beepbop"))]


def set_debug(enabled):
    level = "debug" if enabled else "info"
    return supervisor("/core/api/services/logger/set_level", "POST", {"homeassistant.components.ecovacs": level, "ecovacs": level, "deebot_client": level})


def reload_ecovacs():
    entries = [e for e in config_entries() if "entry_id" in e]
    if not entries: return {"ok": False, "error": "No Ecovacs config entry found"}
    entry_id = entries[0]["entry_id"]
    result = supervisor("/core/api/services/homeassistant/reload_config_entry", "POST", {"entry_id": entry_id})
    time.sleep(5)
    return {"entry_id": entry_id, "result": result}


def snapshot():
    logs = core_logs()
    return {"timestamp": now(), "config_entries": redact(config_entries()), "states": states(), "logs": logs, "error_log": error_log(), "client_inspection": inspect_client("\n".join(logs["matching_lines"]))}


def make_bundle(obj):
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SHARE / f"deebot-y1pro-deep-diagnostic-{stamp}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostic.json", json.dumps(redact(obj), indent=2, default=str))
        archive.writestr("core-inspection.sh", core_inspection_script())
        archive.writestr("README.txt", f"DEEBOT Y1 PRO Diagnostics v{VERSION}. Sensitive values are redacted.\n")
    return path


def progress(job, percent, message):
    with LOCK:
        JOBS[job]["percent"] = percent
        JOBS[job]["message"] = message
        JOBS[job]["events"].append({"time": now(), "percent": percent, "message": message})


def deep_capture(job):
    try:
        progress(job, 5, "Preparing Core inspection script")
        script = HA_CONFIG / "deebot-y1pro-core-inspection.sh"
        script.write_text(core_inspection_script()); script.chmod(0o755)
        progress(job, 15, "Taking baseline snapshot")
        before = snapshot()
        progress(job, 25, "Enabling Ecovacs / deebot_client DEBUG logging")
        set_debug(True)
        progress(job, 35, "Reloading the Home Assistant Ecovacs integration")
        reload_result = reload_ecovacs()
        progress(job, 45, "Waiting for Y1 PRO discovery and command traffic")
        time.sleep(8)
        progress(job, 60, "Collecting Core logs and API evidence")
        captured = core_logs(10000); errors = error_log()
        progress(job, 72, "Analysing cqyi87 / clean_V2 / work-mode evidence")
        text = "\n".join(captured["matching_lines"])
        evidence = {"cqyi87_lines": [x for x in captured["matching_lines"] if "cqyi87" in x], "clean_v2_lines": [x for x in captured["matching_lines"] if "clean_V2" in x], "work_mode_lines": [x for x in captured["matching_lines"] if re.search(r"workMode|setWorkMode|getWorkMode|workState|motionState", x, re.I)], "p2p_lines": [x for x in captured["matching_lines"] if "p2p" in x.lower()], "command_count": len(re.findall(r"cmdName", text))}
        progress(job, 82, "Restoring normal log levels")
        set_debug(False)
        progress(job, 90, "Taking final snapshot")
        after = snapshot()
        result = {"started_at": JOBS[job]["started_at"], "finished_at": now(), "add_on_version": VERSION, "before": before, "reload": reload_result, "capture": {"logs": captured, "error_log": errors, "evidence": evidence}, "after": after}
        progress(job, 96, "Building diagnostic ZIP")
        output = make_bundle(result)
        with LOCK: JOBS[job].update(status="complete", percent=100, message="Complete", file=str(output))
    except Exception as exc:
        try: set_debug(False)
        except Exception: pass
        with LOCK: JOBS[job].update(status="error", percent=100, message=str(exc), error=str(exc))


def diagnostic():
    return {"generated_at": now(), "add_on_version": VERSION, "environment": {"python": subprocess.run(["python3", "--version"], capture_output=True, text=True).stdout.strip(), "arch": os.uname().machine, "hostname": socket.gethostname()}, "config_entries": redact(config_entries()), "states": states(), "core_logs": core_logs(), "error_log": error_log(), "client_inspection": inspect_client("")}


HTML = """<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:1050px;margin:25px auto;padding:0 18px}button{padding:11px 15px;margin:4px;border:1px solid #bbb;border-radius:8px;background:#fff;cursor:pointer}.card{border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0}#log{background:#111;color:#eee;padding:12px;border-radius:8px;min-height:180px;white-space:pre-wrap;font:12px monospace;max-height:500px;overflow:auto}.bar{height:18px;background:#ddd;border-radius:10px;overflow:hidden}.fill{height:100%;width:0%;background:#1976d2}.status{font-weight:600}a{text-decoration:none}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>VERSION_PLACEHOLDER</b></p><div class="card"><h2>Deep Y1 PRO Capture</h2><p>Captures the Y1 PRO / cqyi87 traffic and shows live progress.</p><button id="run" type="button">Run Deep Capture</button><div class="bar"><div id="fill" class="fill"></div></div><p class="status" id="status">Ready</p><div id="log">Press Run Deep Capture to start.</div><p id="download"></p></div><div class="card"><a href="api/diagnostic">Run Normal Diagnostic</a> &nbsp; | &nbsp; <a href="api/core-inspection-script">Show Core Inspection Script</a></div><script>
(function(){
 const root=(location.pathname.endsWith('/')?location.pathname:location.pathname+'/');
 const url=(p)=>new URL(p,location.origin+root).toString();
 const run=document.getElementById('run'), status=document.getElementById('status'), log=document.getElementById('log'), fill=document.getElementById('fill'), download=document.getElementById('download');
 async function runCapture(){
  run.disabled=true; status.textContent='Starting…'; log.textContent='Connecting to diagnostics server…'; download.innerHTML='';
  try{
   const r=await fetch(url('api/deep'),{method:'POST',cache:'no-store'});
   const text=await r.text(); let j; try{j=JSON.parse(text)}catch(e){throw new Error('Server returned HTTP '+r.status+': '+text.slice(0,500))}
   if(!r.ok||!j.job) throw new Error(j.error||('HTTP '+r.status));
   status.textContent='0% — Job started'; log.textContent='Job '+j.job+' started.';
   const poll=async()=>{
    try{
     const r2=await fetch(url('api/job/'+encodeURIComponent(j.job)),{cache:'no-store'}); const s=await r2.json();
     fill.style.width=(s.percent||0)+'%'; status.textContent=(s.percent||0)+'% — '+(s.message||'Working'); log.textContent=(s.events||[]).map(e=>'['+e.time+'] '+e.message).join('\n'); log.scrollTop=log.scrollHeight;
     if(s.status==='complete'){download.innerHTML='<a href="'+url('api/download/'+encodeURIComponent(j.job))+'">Download diagnostic ZIP</a>';run.disabled=false;return;}
     if(s.status==='error'){status.textContent='ERROR — '+s.message;run.disabled=false;return;}
     setTimeout(poll,500);
    }catch(e){status.textContent='Polling error: '+e.message;run.disabled=false;}
   }; poll();
  }catch(e){status.textContent='ERROR — '+e.message;log.textContent=e.stack||e.message;run.disabled=false;}
 }
 run.addEventListener('click',runCapture);
})();
</script></body></html>""".replace("VERSION_PLACEHOLDER", VERSION)


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status, body, content_type="application/json", disposition=None):
        if isinstance(body, str): body = body.encode()
        self.send_response(status); self.send_header("Content-Type", content_type); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
        if disposition: self.send_header("Content-Disposition", disposition)
        self.end_headers(); self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("", "/"): return self.send_bytes(200, HTML, "text/html; charset=utf-8")
        if path == "/api/health": return self.send_bytes(200, json.dumps({"ok": True, "version": VERSION, "time": now()}))
        if path == "/api/diagnostic": return self.send_bytes(200, json.dumps(diagnostic(), indent=2, default=str))
        if path == "/api/core-inspection-script": return self.send_bytes(200, core_inspection_script(), "text/plain; charset=utf-8")
        match = re.fullmatch(r"/api/job/([A-Za-z0-9_-]+)", path)
        if match:
            with LOCK: result = dict(JOBS.get(match.group(1), {"status":"not_found","percent":0,"message":"Job not found","events":[]}))
            return self.send_bytes(200, json.dumps(result, default=str))
        match = re.fullmatch(r"/api/download/([A-Za-z0-9_-]+)", path)
        if match:
            with LOCK: job = JOBS.get(match.group(1))
            if not job or job.get("status") != "complete": return self.send_bytes(404, json.dumps({"error":"not ready"}))
            p = Path(job["file"]); return self.send_bytes(200, p.read_bytes(), "application/zip", f'attachment; filename="{p.name}"')
        return self.send_bytes(404, json.dumps({"error":"not found"}))

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/deep": return self.send_bytes(404, json.dumps({"error":"not found"}))
        job = datetime.now().strftime("%Y%m%d%H%M%S%f")
        with LOCK: JOBS[job] = {"started_at": now(), "status":"running", "percent":0, "message":"Starting", "events":[]}
        threading.Thread(target=deep_capture, args=(job,), daemon=True).start()
        return self.send_bytes(202, json.dumps({"job":job}))

    def log_message(self, *_): pass


if __name__ == "__main__":
    Path("/homeassistant/deebot-y1pro-core-inspection.sh").write_text(core_inspection_script())
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
