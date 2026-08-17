ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}
RUN apk add --no-cache python3
WORKDIR /app
COPY server_lab.py /app/server.py
COPY installed_client_inspector.py /app/installed_client_inspector.py
COPY run.sh /run.sh
RUN python3 - <<'PY'
from pathlib import Path
p=Path('/app/server.py')
s=p.read_text()
old='''    def sendx(self,c,b,ct="application/json",fn=None):
        if isinstance(b,str): b=b.encode(); self.send_response(c); self.send_header("Content-Type",ct); self.send_header("Content-Length",str(len(b))); self.send_header("Cache-Control","no-store")
        if fn:self.send_header("Content-Disposition",f'attachment; filename="{fn}"')
        self.end_headers(); self.wfile.write(b)
'''
new='''    def sendx(self,c,b,ct="application/json",fn=None):
        if isinstance(b,str): b=b.encode()
        self.send_response(c)
        self.send_header("Content-Type",ct)
        self.send_header("Content-Length",str(len(b)))
        self.send_header("Cache-Control","no-store")
        if fn: self.send_header("Content-Disposition",f'attachment; filename="{fn}"')
        self.end_headers()
        self.wfile.write(b)
'''
if old not in s: raise SystemExit('sendx pattern not found')
p.write_text(s.replace(old,new))
PY
RUN python3 -m py_compile /app/server.py && chmod a+x /run.sh
CMD ["/run.sh"]
