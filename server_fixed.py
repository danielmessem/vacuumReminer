#!/usr/bin/env python3
"""Stable browser UI for DEEBOT diagnostics."""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
import server as core

VERSION = "0.9.8"
HTML = f'''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{{font-family:system-ui;max-width:900px;margin:30px auto;padding:0 18px}}button{{font-size:16px;padding:12px 18px;border:1px solid #aaa;border-radius:8px;background:#fff;cursor:pointer}}.card{{padding:16px;border:1px solid #ddd;border-radius:10px;margin:14px 0}}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><div class="card">Version <b>{VERSION}</b></div><div class="card"><h2>Deep Y1 PRO capture</h2><p>Runs the complete capture and returns the ZIP directly.</p><form action="." method="post"><button type="submit">Run Deep Capture + Download ZIP</button></form></div><div class="card"><a href="api/diagnostic">Run normal diagnostic</a></div><div class="card"><a href="api/core-inspection-script">Show Core inspection script</a></div></body></html>'''

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

    def capture(self):
        cap = core.deep_capture()
        obj = core.diagnostic()
        obj["capture"] = cap
        out = core.make_bundle(obj)
        return out.read_bytes(), out.name

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("", "/"):
            return self.send_bytes(200, HTML.encode(), "text/html; charset=utf-8")
        if path == "/api/diagnostic":
            try:
                return self.send_bytes(200, json.dumps(core.diagnostic(), indent=2, default=str).encode(), "application/json")
            except Exception as exc:
                return self.send_bytes(500, json.dumps({"ok": False, "error": str(exc)}).encode(), "application/json")
        if path == "/api/core-inspection-script":
            return self.send_bytes(200, core.core_inspection_script().encode(), "text/plain; charset=utf-8")
        return self.send_bytes(404, b'{"error":"not found"}', "application/json")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path not in ("", "/", "."):
            return self.send_bytes(404, b'{"error":"not found"}', "application/json")
        try:
            body, name = self.capture()
            return self.send_bytes(200, body, "application/zip", f'attachment; filename="{name}"')
        except Exception as exc:
            return self.send_bytes(500, json.dumps({"ok": False, "error": str(exc)}, indent=2).encode(), "application/json")

    def log_message(self, *_):
        pass

if __name__ == "__main__":
    core.VERSION = VERSION
    HTTPServer(("0.0.0.0", core.PORT), Handler).serve_forever()
