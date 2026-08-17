ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.20
FROM ${BUILD_FROM}

RUN apk add --no-cache python3

WORKDIR /app
COPY server.py /app/server.py
COPY server_fixed.py /app/server_fixed.py
COPY installed_client_inspector.py /app/installed_client_inspector.py
COPY run.sh /run.sh

# Make the web UI work correctly when Home Assistant serves it through
# an Ingress URL such as /api/hassio_ingress/<token> (with or without a
# trailing slash).  The browser must retain the complete Ingress prefix
# when calling the app's API endpoints.
RUN python3 - <<'PY'
from pathlib import Path
p = Path('/app/server.py')
s = p.read_text()
s = s.replace('VERSION = "1.1.1"', 'VERSION = "1.1.3"')
s = s.replace("fetch('api/deep'", "fetch((location.pathname.endsWith('/') ? location.pathname : location.pathname + '/') + 'api/deep'")
s = s.replace("fetch('api/job/'+j.job)", "fetch((location.pathname.endsWith('/') ? location.pathname : location.pathname + '/')+'api/job/'+j.job)")
s = s.replace("'<a href=\"api/download/'+s.job+'\">Download diagnostic ZIP</a>'", "'<a href=\"'+(location.pathname.endsWith('/') ? location.pathname : location.pathname + '/')+'api/download/'+s.job+'\">Download diagnostic ZIP</a>'")
p.write_text(s)
PY

RUN chmod a+x /run.sh

CMD ["/run.sh"]
