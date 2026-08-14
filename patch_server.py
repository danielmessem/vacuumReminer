from pathlib import Path
import re

p = Path('/app/server.py')
s = p.read_text()

# Keep runtime version synchronized with the manifest.
s = re.sub(r"VERSION='[^']+'", "VERSION='0.9.5'", s, count=1)
s = re.sub(r'Version <b>0\.9\.[0-9]+</b>', 'Version <b>0.9.5</b>', s)

# Plain browser navigation is more reliable through Home Assistant ingress.
s = re.sub(
    r"async function deep\(\)\{.*?\}",
    "function deep(){if(!confirm('Run the complete Y1 PRO capture? The Ecovacs integration will be reloaded once.'))return;document.getElementById('status').textContent='Starting deep capture. The download will begin when complete…';window.location.assign('api/deep-download')}",
    s,
    count=1,
    flags=re.S,
)

# Replace the server's GET handler with a single, known-good implementation.
start = s.find('    def do_GET(self):')
post = s.find('    def do_POST(self):')
if start != -1 and post != -1 and post > start:
    get_handler = '''    def do_GET(self):
        if self.path in ('','/'):
            return self.send(200,HTML,'text/html; charset=utf-8')
        if self.path.startswith('/api/deep-download'):
            try:
                obj = diagnostic()
                obj['capture'] = deep_capture()
                out = make_bundle(obj)
                return self.send(200,out.read_bytes(),'application/zip',f'attachment; filename="{out.name}"')
            except Exception as e:
                return self.send(500,json.dumps({'ok':False,'error':str(e)}))
        if self.path.startswith('/api/diagnostic'):
            return self.send(200,json.dumps(diagnostic(),indent=2,default=str))
        if self.path.startswith('/api/core-inspection-script'):
            return self.send(200,core_inspection_script(),'text/plain; charset=utf-8')
        if self.path.startswith('/api/download/'):
            p=SHARE/self.path.split('/api/download/',1)[1]
            if p.exists() and p.is_file():
                return self.send(200,p.read_bytes(),'application/zip',f'attachment; filename="{p.name}"')
        return self.send(404,json.dumps({'error':'not found'}))

'''
    s = s[:start] + get_handler + s[post:]

p.write_text(s)
