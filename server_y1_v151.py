#!/usr/bin/env python3
import base64, json, re, shutil, subprocess, tempfile, zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.5.1"
PORT = 8099
HA = Path("/homeassistant")
SHARE = Path("/share")
CC = HA / "custom_components"
CUSTOM = CC / "ecovacs"
CLIENT_BACKUP_ROOT = HA / "ecovacs_doctor_client_backups"
PROFILE = base64.b64decode("IiIiREVFQk9UIFkxIFBSTyBjb21wYXRpYmlsaXR5IHByb2ZpbGUuIiIiCmZyb20gX19mdXR1cmVfXyBpbXBvcnQgYW5ub3RhdGlvbnMKCmZyb20gZGVlYm90X2NsaWVudC5jYXBhYmlsaXRpZXMgaW1wb3J0ICgKICAgIENhcGFiaWxpdGllcywKICAgIENhcGFiaWxpdHlDbGVhbiwKICAgIENhcGFiaWxpdHlDbGVhbkFjdGlvbiwKICAgIENhcGFiaWxpdHlDdXN0b21Db21tYW5kLAogICAgQ2FwYWJpbGl0eUV2ZW50LAogICAgQ2FwYWJpbGl0eUV4ZWN1dGUsCiAgICBDYXBhYmlsaXR5TGlmZVNwYW4sCiAgICBDYXBhYmlsaXR5U2V0VHlwZXMsCiAgICBDYXBhYmlsaXR5U2V0dGluZ3MsCiAgICBDYXBhYmlsaXR5U3RhdHMsCiAgICBEZXZpY2VUeXBlLAopCmZyb20gZGVlYm90X2NsaWVudC5jb21tYW5kcy5qc29uLmNoYXJnZSBpbXBvcnQgQ2hhcmdlCmZyb20gZGVlYm90X2NsaWVudC5jb21tYW5kcy5qc29uLmNsZWFuIGltcG9ydCBDbGVhbkFyZWFWMiwgQ2xlYW5WMgpmcm9tIGRlZWJvdF9jbGllbnQuY29tbWFuZHMuanNvbi5jdXN0b20gaW1wb3J0IEN1c3RvbUNvbW1hbmQKZnJvbSBkZWVib3RfY2xpZW50LmNvbW1hbmRzLmpzb24uZmFuX3NwZWVkIGltcG9ydCBTZXRGYW5TcGVlZApmcm9tIGRlZWJvdF9jbGllbnQuY29tbWFuZHMuanNvbi5saWZlX3NwYW4gaW1wb3J0IFJlc2V0TGlmZVNwYW4KZnJvbSBkZWVib3RfY2xpZW50LmNvbnN0IGltcG9ydCBEYXRhVHlwZQpmcm9tIGRlZWJvdF9jbGllbnQuZXZlbnRzIGltcG9ydCAoCiAgICBBdmFpbGFiaWxpdHlFdmVudCwKICAgIEN1c3RvbUNvbW1hbmRFdmVudCwKICAgIEZhblNwZWVkRXZlbnQsCiAgICBGYW5TcGVlZExldmVsLAogICAgTGlmZVNwYW5FdmVudCwKICAgIFJlcG9ydFN0YXRzRXZlbnQsCiAgICBTdGF0ZUV2ZW50LAogICAgU3RhdHNFdmVudCwKICAgIFRvdGFsU3RhdHNFdmVudCwKKQpmcm9tIGRlZWJvdF9jbGllbnQubW9kZWxzIGltcG9ydCBTdGF0aWNEZXZpY2VJbmZvCgpZMVBST19QQVRDSF9WRVJTSU9OID0gIjEuNS4xIgoKZGVmIGdldF9kZXZpY2VfaW5mbygpIC0+IFN0YXRpY0RldmljZUluZm86CiAgICByZXR1cm4gU3RhdGljRGV2aWNlSW5mbygKICAgICAgICBEYXRhVHlwZS5KU09OLAogICAgICAgIENhcGFiaWxpdGllcygKICAgICAgICAgICAgZGV2aWNlX3R5cGU9RGV2aWNlVHlwZS5WQUNVVU0sCiAgICAgICAgICAgIGF2YWlsYWJpbGl0eT1DYXBhYmlsaXR5RXZlbnQoQXZhaWxhYmlsaXR5RXZlbnQsIFtdKSwKICAgICAgICAgICAgYmF0dGVyeT1Ob25lLAogICAgICAgICAgICBjaGFyZ2U9Q2FwYWJpbGl0eUV4ZWN1dGUoQ2hhcmdlKSwKICAgICAgICAgICAgY2xlYW49Q2FwYWJpbGl0eUNsZWFuKAogICAgICAgICAgICAgICAgYWN0aW9uPUNhcGFiaWxpdHlDbGVhbkFjdGlvbihjb21tYW5kPUNsZWFuVjIsIGFyZWE9Q2xlYW5BcmVhVjIpCiAgICAgICAgICAgICksCiAgICAgICAgICAgIGN1c3RvbT1DYXBhYmlsaXR5Q3VzdG9tQ29tbWFuZCgKICAgICAgICAgICAgICAgIGV2ZW50PUN1c3RvbUNvbW1hbmRFdmVudCwgZ2V0PVtdLCBzZXQ9Q3VzdG9tQ29tbWFuZAogICAgICAgICAgICApLAogICAgICAgICAgICBlcnJvcj1Ob25lLAogICAgICAgICAgICBmYW5fc3BlZWQ9Q2FwYWJpbGl0eVNldFR5cGVzKAogICAgICAgICAgICAgICAgZXZlbnQ9RmFuU3BlZWRFdmVudCwKICAgICAgICAgICAgICAgIGdldD1bXSwKICAgICAgICAgICAgICAgIHNldD1TZXRGYW5TcGVlZCwKICAgICAgICAgICAgICAgIHR5cGVzPSgKICAgICAgICAgICAgICAgICAgICBGYW5TcGVlZExldmVsLlFVSUVULAogICAgICAgICAgICAgICAgICAgIEZhblNwZWVkTGV2ZWwuTk9STUFMLAogICAgICAgICAgICAgICAgICAgIEZhblNwZWVkTGV2ZWwuTUFYLAogICAgICAgICAgICAgICAgICAgIEZhblNwZWVkTGV2ZWwuTUFYX1BMVVMsCiAgICAgICAgICAgICAgICApLAogICAgICAgICAgICApLAogICAgICAgICAgICBsaWZlX3NwYW49Q2FwYWJpbGl0eUxpZmVTcGFuKAogICAgICAgICAgICAgICAgZXZlbnQ9TGlmZVNwYW5FdmVudCwKICAgICAgICAgICAgICAgIGdldD1bXSwKICAgICAgICAgICAgICAgIHJlc2V0PVJlc2V0TGlmZVNwYW4sCiAgICAgICAgICAgICAgICB0eXBlcz0oKSwKICAgICAgICAgICAgKSwKICAgICAgICAgICAgbWFwPU5vbmUsCiAgICAgICAgICAgIG5ldHdvcms9Tm9uZSwKICAgICAgICAgICAgcGxheV9zb3VuZD1Ob25lLAogICAgICAgICAgICBzZXR0aW5ncz1DYXBhYmlsaXR5U2V0dGluZ3MoKSwKICAgICAgICAgICAgc3RhdGU9Q2FwYWJpbGl0eUV2ZW50KFN0YXRlRXZlbnQsIFtdKSwKICAgICAgICAgICAgc3RhdGlvbj1Ob25lLAogICAgICAgICAgICBzdGF0cz1DYXBhYmlsaXR5U3RhdHMoCiAgICAgICAgICAgICAgICBjbGVhbj1DYXBhYmlsaXR5RXZlbnQoU3RhdHNFdmVudCwgW10pLAogICAgICAgICAgICAgICAgcmVwb3J0PUNhcGFiaWxpdHlFdmVudChSZXBvcnRTdGF0c0V2ZW50LCBbXSksCiAgICAgICAgICAgICAgICB0b3RhbD1DYXBhYmlsaXR5RXZlbnQoVG90YWxTdGF0c0V2ZW50LCBbXSksCiAgICAgICAgICAgICksCiAgICAgICAgICAgIHdhdGVyPU5vbmUsCiAgICAgICAgKSwKICAgICkK").decode()

MATCH = re.compile(r"ecovacs|deebot|beepbop|cqyi87|30000|mqtt|capabilities|clean_V2|Error while setting up ecovacs", re.I)
SECRET = re.compile(r"(?i)(accessToken|refreshToken|authCode|token|api_key|secret)(['\" ]*[:=]['\" ]*)[^,'\"\s}]+")
EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")

def redact(s):
    return SECRET.sub(r"\1\2<redacted>", EMAIL.sub("<redacted-email>", str(s)))

def docker(args, timeout=35):
    try:
        p = subprocess.run(["docker"] + args, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except Exception as e:
        return 99, "", str(e)

def core():
    rc, out, _ = docker(["ps", "--format", "{{.ID}}\t{{.Names}}"])
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
    r = core_exec(["python", "-c",
        'import pathlib,deebot_client;p=pathlib.Path(deebot_client.__file__).parent;print(p);print(p/"hardware"/"cqyi87.py")'])
    lines = [x.strip() for x in r.get("stdout", "").splitlines() if x.strip()]
    return {
        "ok": bool(r.get("ok") and len(lines) >= 2),
        "package": lines[0] if lines else None,
        "target": lines[1] if len(lines) > 1 else None,
        "detail": r,
    }

def patch_status():
    p = client_paths()
    if not p["ok"]:
        return p
    r = core_exec(["sh", "-c",
        f"if [ -f '{p['target']}' ]; then grep 'Y1PRO_PATCH_VERSION' '{p['target']}' || true; else echo MISSING; fi"])
    detail = r.get("stdout", "").strip()
    return {
        "ok": True,
        "target": p["target"],
        "installed": "Y1PRO_PATCH_VERSION" in detail,
        "detail": detail,
    }

def install_patch():
    p = client_paths()
    if not p["ok"]:
        return {"ok": False, "message": "Could not locate deebot-client", "detail": p}
    cid, _ = core()
    target = p["target"]
    CLIENT_BACKUP_ROOT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = CLIENT_BACKUP_ROOT / f"cqyi87-{stamp}.py"
    absent = CLIENT_BACKUP_ROOT / f"cqyi87-{stamp}.absent"

    exists = core_exec(["sh", "-c", f"test -f '{target}'"])
    if exists.get("ok"):
        rc, _, err = docker(["cp", f"{cid}:{target}", str(backup)])
        if rc:
            return {"ok": False, "message": "Backup failed", "error": redact(err)}
    else:
        absent.write_text("absent before patch\n")

    with tempfile.NamedTemporaryFile("w", delete=False, suffix=".py") as f:
        f.write(PROFILE)
        tmp = f.name
    try:
        rc, _, err = docker(["cp", tmp, f"{cid}:{target}"])
    finally:
        Path(tmp).unlink(missing_ok=True)
    if rc:
        return {"ok": False, "message": "Copy failed", "error": redact(err)}

    verify_code = (
        "import importlib;importlib.invalidate_caches();"
        "m=importlib.import_module('deebot_client.hardware.cqyi87');"
        "i=m.get_device_info();c=i.capabilities;"
        "print(m.Y1PRO_PATCH_VERSION);print(i.data_type);print(c.device_type);"
        "print('life_span_types='+str(len(c.life_span.types)));"
        "print('stats_safe='+str(c.stats is not None))"
    )
    verify = core_exec(["python", "-c", verify_code])
    if not verify.get("ok"):
        if backup.exists():
            docker(["cp", str(backup), f"{cid}:{target}"])
        else:
            core_exec(["sh", "-c", f"rm -f '{target}'"])
        return {"ok": False, "message": "Validation failed; rolled back", "validation": verify}
    return {
        "ok": True,
        "message": "Y1 PRO cqyi87 profile 1.5.1 installed. Restart Core next.",
        "target": target,
        "validation": verify,
    }

def rollback():
    p = client_paths()
    if not p["ok"]:
        return {"ok": False, "message": "Could not locate deebot-client"}
    cid, _ = core()
    target = p["target"]
    items = sorted(
        list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.py")) +
        list(CLIENT_BACKUP_ROOT.glob("cqyi87-*.absent")),
        reverse=True,
    )
    if not items:
        return {"ok": False, "message": "No backup found"}
    latest = items[0]
    if latest.suffix == ".absent":
        r = core_exec(["sh", "-c", f"rm -f '{target}'"])
        return {"ok": r.get("ok", False), "message": "Patch removed. Restart Core next.", "detail": r}
    rc, _, err = docker(["cp", str(latest), f"{cid}:{target}"])
    return {
        "ok": rc == 0,
        "message": "Previous cqyi87.py restored. Restart Core next.",
        "error": redact(err),
    }

def quarantine():
    moved = []
    backup_root = HA / "ecovacs_doctor_backups"
    backup_root.mkdir(parents=True, exist_ok=True)
    candidates = []
    if CUSTOM.exists():
        candidates.append(CUSTOM)
    if CC.exists():
        candidates += list(CC.glob("ecovacs.disabled-*"))
    for src in candidates:
        dst = backup_root / f"ecovacs-{datetime.now():%Y%m%d-%H%M%S-%f}-{src.name}"
        shutil.move(str(src), str(dst))
        moved.append({"from": str(src), "to": str(dst)})
    return {"ok": True, "moved": moved}

def restart():
    cid, _ = core()
    if not cid:
        return {"ok": False, "message": "Core not found"}
    rc, _, err = docker(["restart", cid], 40)
    return {"ok": rc == 0, "message": "Restart requested" if rc == 0 else redact(err)}

def diagnose():
    cid, name = core()
    logs = []
    if cid:
        rc, out, err = docker(["logs", "--since", "30m", cid], 45)
        logs = [redact(x) for x in (out + err).splitlines() if MATCH.search(x)][-12000:]

    lower = [x.lower() for x in logs]
    last_supported = max((i for i, x in enumerate(lower) if "capabilities found for cqyi87" in x), default=-1)
    last_unsupported = max((i for i, x in enumerate(lower)
                            if 'device class "cqyi87" not recognized' in x or "no capabilities found for cqyi87" in x),
                           default=-1)
    joined_after_support = "\n".join(lower[last_supported + 1:] if last_supported >= 0 else lower)
    findings = []

    if last_unsupported > last_supported:
        findings.append({"severity": "HIGH", "code": "CQYI87_UNSUPPORTED",
                          "action": "Install Y1 PRO patch and restart Core."})
    elif last_supported >= 0:
        findings.append({"severity": "INFO", "code": "CQYI87_PROFILE_ACTIVE",
                          "meaning": "Home Assistant found the Y1 PRO capability profile."})

    if "'nonetype' object has no attribute 'types'" in joined_after_support:
        findings.append({"severity": "HIGH", "code": "LIFESPAN_CONTAINER_MISSING",
                          "action": "Install patch 1.5.1 and restart Core."})
    if "'nonetype' object has no attribute 'report'" in joined_after_support or "'nonetype' object has no attribute 'clean'" in joined_after_support:
        findings.append({"severity": "HIGH", "code": "STATS_CONTAINER_MISSING",
                          "action": "Install patch 1.5.1 and restart Core."})
    if 'unknown message "30000"' in joined_after_support:
        findings.append({"severity": "MEDIUM", "code": "Y1PRO_TELEMETRY_30000",
                          "action": "Control works; telemetry decoder remains the next phase."})
    if "success calling api" in joined_after_support and "'cmdname': 'clean_v2'" in joined_after_support:
        findings.append({"severity": "INFO", "code": "CLEAN_COMMAND_CONFIRMED",
                          "meaning": "The robot acknowledged clean_V2 successfully."})
    if "adding ecovacs vacuums to home assistant:" in joined_after_support:
        findings.append({"severity": "INFO", "code": "VACUUM_PLATFORM_REACHED",
                          "meaning": "Home Assistant reached the Ecovacs vacuum platform."})

    if not findings:
        findings.append({"severity": "INFO", "code": "NO_CURRENT_KNOWN_FAILURE"})

    r = {
        "version": VERSION,
        "generated": datetime.now().isoformat(),
        "environment": {
            "ha_version": core_exec(["python", "-c", "from homeassistant.const import __version__;print(__version__)"]),
            "deebot_client": core_exec(["python", "-c", 'import importlib.metadata as m;print(m.version("deebot-client"))']),
            "y1pro_patch": patch_status(),
        },
        "custom_component": {"present": CUSTOM.is_dir()},
        "findings": findings,
        "matched_logs": logs,
        "core_candidates": [{"id": cid, "name": name}] if cid else [],
    }
    SHARE.mkdir(parents=True, exist_ok=True)
    out = SHARE / f"deebot-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("REPORT.json", json.dumps(r, indent=2))
        z.writestr("MATCHED_CORE_LOG.txt", "\n".join(logs))
    r["file"] = str(out)
    return r

HTML = """<!doctype html><meta name=viewport content='width=device-width'><title>DEEBOT Y1 PRO Tools</title>
<style>body{font-family:system-ui;max-width:1050px;margin:24px auto;padding:0 18px;background:#111827;color:#e5e7eb}button{padding:11px 14px;margin:5px;border:0;border-radius:8px;font-weight:650}.p{background:#2563eb;color:white}.g{background:#16a34a;color:white}.w{background:#f59e0b}.d{background:#ef4444;color:white}pre{background:#030712;padding:14px;white-space:pre-wrap;max-height:650px;overflow:auto;border-radius:8px}</style>
<h1>DEEBOT Y1 PRO Diagnostics & Patch Manager</h1><p>Version <b>1.5.1</b></p>
<button class=p onclick="go('./api/diagnose')">Run full diagnosis</button>
<button class=g onclick="ask('./api/install','Install/update targeted cqyi87 profile? A rollback point will be created.')">Install Y1 PRO patch</button>
<button class=w onclick="ask('./api/rollback','Rollback latest Y1 PRO patch?')">Rollback Y1 PRO patch</button>
<button onclick="ask('./api/quarantine','Quarantine any custom Ecovacs copies?')">Quarantine custom Ecovacs</button>
<button class=d onclick="ask('./api/restart','Restart Home Assistant Core now?')">Restart Core</button>
<pre id=o>Ready.</pre>
<script>
async function go(u){o.textContent='Working...';try{let r=await fetch(u,{method:'POST'});o.textContent=JSON.stringify(await r.json(),null,2)}catch(e){o.textContent=String(e)}}
function ask(u,m){if(confirm(m))go(u)}
</script>"""

class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype="application/json"):
        if isinstance(body, str):
            body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("", "/"):
            return self.send(200, HTML, "text/html; charset=utf-8")
        return self.send(404, json.dumps({"error": "not found"}))

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            if path == "/api/diagnose":
                result = diagnose()
            elif path == "/api/install":
                result = install_patch()
            elif path == "/api/rollback":
                result = rollback()
            elif path == "/api/quarantine":
                result = quarantine()
            elif path == "/api/restart":
                result = restart()
            else:
                return self.send(404, json.dumps({"error": "not found"}))
            return self.send(200, json.dumps(result, indent=2))
        except Exception as e:
            return self.send(500, json.dumps({"error": redact(e)}))

    def log_message(self, *args):
        pass

ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
