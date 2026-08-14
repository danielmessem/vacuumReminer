#!/usr/bin/env python3
"""Robust browser UI wrapper for the DEEBOT diagnostic server.

The deep-capture action is deliberately implemented as a normal HTML form POST
that returns the ZIP itself. This avoids JavaScript/fetch/ingress issues.
"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import server as core

VERSION = "0.9.4"

HTML = f'''<!doctype html>
<html><head><meta name="viewport" content="width=device-width">
<title>DEEBOT Diagnostics</title>
<style>
body{{font-family:system-ui;max-width:1000px;margin:25px auto;padding:0 18px}}
button{{padding:12px 18px;margin:6px 0;border:1px solid #999;border-radius:8px;background:#fff;font-size:16px;cursor:pointer}}
.card{{border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0}}
.warn{{padding:12px;background:#fff7e6;border-radius:8px;margin:12px 0}}
</style></head><body>
<h1>DEEBOT Y1 PRO Diagnostics</h1>
<p>Version <b>{VERSION}</b></p>
<div class="warn"><b>Deep Y1 PRO Capture</b><br>
This is a normal browser form submission. It temporarily enables Ecovacs debug logging,
reloads the integration, captures the Y1 PRO discovery failure, restores logging and
returns the ZIP directly to the browser.</div>
<form action="deep-download" method="post">
<button type="submit">Run Deep Capture + Download ZIP</button>
</form>
<div class="card"><b>Normal Diagnostic</b><br>
<a href="api/diagnostic"><button type="button">Run / View Normal Diagnostic</button></a></div>
<div class="card"><b>Core Inspection</b><br>
<a href="api/core-inspection-script"><button type="button">Show Core Inspection Script</button></a></div>
</body></html>'''

class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, status, body, content_type, disposition=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if disposition:
            self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("", "/"):
            return self.send_bytes(200, HTML.encode(), "text/html; charset=utf-8")
        if path == "/api/diagnostic":
            body = json.dumps(core.diagnostic(), indent=2, default=str).encode()
            return self.send_bytes(200, body, "application/json")
        if path == "/api/core-inspection-script":
            return self.send_bytes(200, core.core_inspection_script().encode(), "text/plain; charset=utf-8")
        return self.send_bytes(404, b'{"error":"not found"}', "application/json")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path != "/deep-download":
            return self.send_bytes(404, b'{"error":"not found"}', "application/json")
        try:
            cap = core.deep_capture()
            obj = core.diagnostic()
            obj["capture"] = cap
            out = core.make_bundle(obj)
            body = out.read_bytes()
            return self.send_bytes(
                200,
                body,
                "application/zip",
                f'attachment; filename="{out.name}"',
            )
        except Exception as exc:
            body = json.dumps({"ok": False, "error": str(exc)}, indent=2).encode()
            return self.send_bytes(500, body, "application/json")

    def log_message(self, *_):
        pass

if __name__ == "__main__":
    core.VERSION = VERSION
    HTTPServer(("0.0.0.0", core.PORT), Handler).serve_forever()
