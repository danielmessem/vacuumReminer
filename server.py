#!/usr/bin/env python3
import json, os, re, socket, subprocess, urllib.request, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT = 8099
HA_CONFIG = Path('/homeassistant')
SHARE = Path('/share')
SUPERVISOR = 'http://supervisor'
SENSITIVE = re.compile(r'(token|password|secret|username|access_token|refresh_token|authorization|cookie)', re.I)
Y1_METHODS = ['OnMajorMap','OnMapInfoV2','OnCachedMapInfo','GetMajorMap','GetMapTrace','GetMapInfoV2','GetCachedMapInfo','GetDeviceInfo']


def now():
    return datetime.now(timezone.utc).isoformat()


def safe_value(k, v):
    if SENSITIVE.search(str(k)):
        return '***REDACTED***'
    if isinstance(v, dict):
        return {str(x): safe_value(x, y) for x, y in v.items()}
    if isinstance(v, list):
        return [safe_value('', x) for x in v]
    return v


def read_text(path, limit=500000):
    try:
        return path.read_text(errors='replace')[:limit]
    except Exception as e:
        return f'[read error: {e}]'


def ha_api(path):
    token = os.environ.get('SUPERVISOR_TOKEN')
    if not token:
        return {'error': 'SUPERVISOR_TOKEN unavailable'}
    req = urllib.request.Request(SUPERVISOR + path, headers={'Authorization': 'Bearer ' + token})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read().decode(errors='replace')
            try:
                return json.loads(raw)
            except Exception:
                return {'raw': raw}
    except Exception as e:
        return {'error': str(e)}


def supervisor_api(path):
    return ha_api(path)


def find_integration_sources():
    roots = [HA_CONFIG / 'custom_components']
    found = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob('*'):
                if not p.is_file() or p.suffix not in ('.py','.json','.yaml','.yml'):
                    continue
                text = read_text(p, 200000)
                if re.search(r'\b(deebot|ecovacs)\b', text, re.I):
                    found.append({'path': str(p), 'size': p.stat().st_size, 'hits': len(re.findall(r'deebot|ecovacs', text, re.I))})
        except Exception:
            pass
    return found[:1000]


def core_ecovacs_inventory():
    result = {'core_path': '/usr/src/homeassistant/homeassistant/components/ecovacs', 'visible': False, 'files': []}
    p = Path(result['core_path'])
    if p.exists():
        result['visible'] = True
        try:
            result['files'] = [str(x.relative_to(p)) for x in p.rglob('*') if x.is_file()][:1000]
        except Exception as e:
            result['error'] = str(e)
    return result


def method_sources():
    found = {m: [] for m in Y1_METHODS}
    for item in find_integration_sources():
        text = read_text(Path(item['path']), 500000)
        for m in Y1_METHODS:
            if re.search(r'\b' + re.escape(m) + r'\b', text):
                found[m].append(item['path'])
    core = core_ecovacs_inventory()
    if core['visible']:
        for rel in core['files']:
            p = Path(core['core_path']) / rel
            if p.suffix == '.py':
                text = read_text(p, 500000)
                for m in Y1_METHODS:
                    if re.search(r'\b' + re.escape(m) + r'\b', text):
                        found[m].append(str(p))
    return found


def config_entries():
    p = HA_CONFIG / '.storage/core.config_entries'
    if not p.exists():
        return {'error': 'core.config_entries not found'}
    try:
        data = json.loads(read_text(p, 5000000))
        entries = data.get('data', {}).get('entries', [])
        selected = []
        for e in entries:
            if str(e.get('domain', '')).lower() in ('ecovacs', 'deebot'):
                selected.append(safe_value('', e))
        return {'count': len(selected), 'entries': selected}
    except Exception as e:
        return {'error': str(e)}


def registry_file(name, limit=5000000):
    p = HA_CONFIG / '.storage' / name
    if not p.exists():
        return {'error': f'{name} not found'}
    try:
        return safe_value('', json.loads(read_text(p, limit)))
    except Exception as e:
        return {'error': str(e)}


def relevant_registry():
    device = registry_file('core.device_registry')
    entity = registry_file('core.entity_registry')
    def filter_items(data, key):
        if not isinstance(data, dict): return data
        items = data.get('data', {}).get(key, [])
        return [x for x in items if any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop'))]
    return {'devices': filter_items(device, 'devices'), 'entities': filter_items(entity, 'entities')}


def core_logs(lines=1000):
    data = supervisor_api(f'/core/logs/latest?lines={int(lines)}&no_colors')
    if isinstance(data, dict) and 'raw' in data:
        text = data['raw']
    else:
        text = json.dumps(data, default=str)
    relevant = [line for line in text.splitlines() if re.search(r'ecovacs|deebot|beepbop|LPATPGFR|Please update|unsupported', line, re.I)]
    return {'lines_requested': lines, 'matching_lines': relevant[-1000:], 'match_count': len(relevant)}


def integration_manifest():
    candidates = [HA_CONFIG / 'custom_components/ecovacs/manifest.json', HA_CONFIG / 'custom_components/deebot/manifest.json']
    for p in candidates:
        if p.exists():
            try:
                return {'path': str(p), 'manifest': safe_value('', json.loads(read_text(p)))}
            except Exception as e:
                return {'path': str(p), 'error': str(e)}
    return {'custom_manifest': False, 'note': 'No custom ecovacs/deebot manifest found; integration may be core.'}


def diagnostic():
    states = ha_api('/core/api/states')
    vacuum_states = []
    if isinstance(states, list):
        for s in states:
            eid = s.get('entity_id', '')
            attrs = s.get('attributes', {})
            if 'vacuum' in eid.lower() or 'deebot' in eid.lower() or 'ecovacs' in eid.lower() or any(x in json.dumps(attrs).lower() for x in ('ecovacs','deebot','beepbop')):
                vacuum_states.append(safe_value('', s))
    info = supervisor_api('/supervisor/info')
    core_config = ha_api('/core/api/config')
    services = ha_api('/core/api/services')
    return {
        'generated_at': now(),
        'hostname': socket.gethostname(),
        'add_on': {'version': '0.2.0'},
        'environment': {'python': subprocess.run(['python3','--version'], capture_output=True, text=True).stdout.strip(), 'arch': os.uname().machine},
        'home_assistant': safe_value('', info),
        'core_config': safe_value('', core_config),
        'deebot_entities': vacuum_states,
        'config_entries': config_entries(),
        'registry': relevant_registry(),
        'integration_manifest': integration_manifest(),
        'custom_source_inventory': find_integration_sources(),
        'core_ecovacs_inventory': core_ecovacs_inventory(),
        'methods': method_sources(),
        'services': [s for s in services if isinstance(s, dict) and s.get('domain') in ('vacuum','ecovacs','deebot')] if isinstance(services, list) else services,
        'core_logs': core_logs(1000),
        'known_y1_pro_methods': Y1_METHODS,
    }


def make_bundle():
    data = diagnostic()
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    out = SHARE / f'deebot-y1pro-diagnostic-{stamp}.zip'
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('diagnostic.json', json.dumps(data, indent=2, default=str))
        z.writestr('methods.json', json.dumps(data['methods'], indent=2))
        z.writestr('core-logs.json', json.dumps(data['core_logs'], indent=2))
        z.writestr('registry.json', json.dumps(data['registry'], indent=2))
        z.writestr('README.txt', 'DEEBOT Y1 PRO diagnostics. Credentials/tokens are redacted.\n')
    return str(out)

HTML = '''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:1200px;margin:30px auto;padding:0 18px}button{padding:10px 14px;margin:4px}pre{white-space:pre-wrap;background:#f4f4f4;padding:14px;border-radius:8px;overflow:auto}.card{border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Read-only diagnostics for the Home Assistant Ecovacs integration.</p><button onclick="run()">Run full diagnostic</button><button onclick="bundle()">Create diagnostic bundle</button><div id="out"><p>Ready.</p></div><script>async function run(){out.innerHTML='<p>Running...</p>';let r=await fetch('api/diagnostic');let d=await r.json();out.innerHTML='<div class="card"><h2>Vacuum</h2><pre>'+JSON.stringify(d.deebot_entities,null,2)+'</pre></div><div class="card"><h2>Integration</h2><pre>'+JSON.stringify({config_entries:d.config_entries,manifest:d.integration_manifest,methods:d.methods},null,2)+'</pre></div><div class="card"><h2>Relevant logs</h2><pre>'+JSON.stringify(d.core_logs,null,2)+'</pre></div><div class="card"><h2>Full diagnostic</h2><pre>'+JSON.stringify(d,null,2)+'</pre></div>'}async function bundle(){let r=await fetch('api/bundle',{method:'POST'});let d=await r.json();out.innerHTML='<h2>Bundle</h2><pre>'+JSON.stringify(d,null,2)+'</pre>'}</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def send(self, code, body, ctype='application/json'):
        b = body.encode() if isinstance(body, str) else body
        self.send_response(code); self.send_header('Content-Type', ctype); self.send_header('Content-Length', str(len(b))); self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path in ('/', ''): return self.send(200, HTML, 'text/html; charset=utf-8')
        if self.path.startswith('/api/diagnostic'): return self.send(200, json.dumps(diagnostic(), indent=2, default=str))
        self.send(404, json.dumps({'error': 'not found'}))
    def do_POST(self):
        if self.path.startswith('/api/bundle'):
            try: return self.send(200, json.dumps({'bundle': make_bundle()}))
            except Exception as e: return self.send(500, json.dumps({'error': str(e)}))
        self.send(404, json.dumps({'error': 'not found'}))
    def log_message(self, *_): pass

if __name__ == '__main__':
    HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()
