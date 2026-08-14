from pathlib import Path

p = Path('/app/server.py')
s = p.read_text()
# Keep the runtime version synchronized with the add-on version.
s = s.replace("VERSION='0.9.1'", "VERSION='0.9.4'")
s = s.replace("VERSION='0.9.2'", "VERSION='0.9.4'")
s = s.replace("VERSION='0.9.3'", "VERSION='0.9.4'")
s = s.replace('Version <b>0.9.1</b>.', 'Version <b>0.9.4</b>.')
s = s.replace('Version <b>0.9.2</b>', 'Version <b>0.9.4</b>')
s = s.replace('Version <b>0.9.3</b>', 'Version <b>0.9.4</b>')

# Replace the JavaScript/fetch action with a plain browser navigation. This
# works reliably through Home Assistant ingress and does not depend on JS.
old = "async function deep(){if(!confirm('Enable temporary Ecovacs debug logging, reload the integration and capture the result?'))return;$('status').textContent='Running deep capture. Do not close this page…';let r=await fetch('api/deep',{method:'POST'});let d=await r.json();render(d);$('status').textContent=r.ok?'Deep capture complete.':'Deep capture failed.'}"
new = "function deep(){if(!confirm('Enable temporary Ecovacs debug logging, reload the integration and capture the result?'))return;$('status').textContent='Starting deep capture…';window.location.href='api/deep-download'}"
s = s.replace(old, new)

# The previous patch incorrectly added /api/deep-download to do_POST while
# the browser uses GET navigation. Add the download endpoint to do_GET.
marker = "        if self.path.startswith('/api/diagnostic'):\n"
route = "        if self.path.startswith('/api/deep-download'):\n            try:\n                capture=deep_capture(); o=bundle(diagnostic(capture)); return self.send(200,o.read_bytes(),'application/zip',f'attachment; filename=\"{o.name}\"')\n            except Exception as e:return self.send(500,json.dumps({'error':str(e)}))\n"
if route not in s:
    s = s.replace(marker, route + marker, 1)

p.write_text(s)
