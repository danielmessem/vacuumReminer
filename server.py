#!/usr/bin/env python3
import json, os, re, socket, subprocess, time, urllib.request, urllib.error, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from installed_client_inspector import inspect as inspect_client, core_inspection_script

PORT=8099; VERSION='0.9.9'; HA_CONFIG=Path('/homeassistant'); SHARE=Path('/share'); SUPERVISOR='http://supervisor'
SENSITIVE=re.compile(r'(token|password|secret|username|access_token|refresh_token|authorization|cookie)',re.I)
LOG_RE=re.compile(r'ecovacs|deebot|beepbop|LPATPGFR|cqyi87|CARTESIAN|y30|please update|unsupported|exception|traceback|auth|discover|error|deebot[-_ ]?client',re.I)

def now(): return datetime.now(timezone.utc).isoformat()
def safe(k,v):
    if SENSITIVE.search(str(k)): return '***REDACTED***'
    if isinstance(v,dict): return {str(a):safe(a,b) for a,b in v.items()}
    if isinstance(v,list): return [safe('',x) for x in v]
    return v

def write_core_script():
    p=HA_CONFIG/'deebot-y1pro-core-inspection.sh'
    try:
        p.write_text(core_inspection_script()); p.chmod(0o755)
        return {'ok':True,'path':str(p)}
    except Exception as e:return {'ok':False,'error':str(e)}

def api(path,method='GET',payload=None,headers=None):
    token=os.environ.get('SUPERVISOR_TOKEN')
    if not token:return {'ok':False,'error':'SUPERVISOR_TOKEN unavailable'}
    data=json.dumps(payload).encode() if payload is not None else None
    h={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    if headers:h.update(headers)
    try:
        with urllib.request.urlopen(urllib.request.Request(SUPERVISOR+path,data=data,method=method,headers=h),timeout=45) as r:
            raw=r.read().decode(errors='replace')
            try: raw=json.loads(raw)
            except Exception: pass
            return {'ok':True,'status':r.status,'data':safe('',raw)}
    except urllib.error.HTTPError as e:return {'ok':False,'status':e.code,'error':e.read().decode(errors='replace')[:10000]}
    except Exception as e:return {'ok':False,'error':str(e)}

def data(r): return r.get('data') if isinstance(r,dict) and r.get('ok') else r

def config_entries():
    try:
        es=json.loads((HA_CONFIG/'.storage/core.config_entries').read_text(errors='replace')).get('data',{}).get('entries',[])
        es=[e for e in es if str(e.get('domain','')).lower() in ('ecovacs','deebot')]
        return {'count':len(es),'entries':[safe('',e) for e in es]}
    except Exception as e:return {'error':str(e)}

def registry(name,key):
    try:
        d=json.loads((HA_CONFIG/'.storage'/name).read_text(errors='replace')); items=d.get('data',{}).get(key,[])
        return [safe('',x) for x in items if any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop'))]
    except Exception as e:return {'error':str(e)}

def states():
    s=data(api('/core/api/states')); out=[]
    if isinstance(s,list):
        for x in s:
            if 'vacuum' in x.get('entity_id','').lower() or any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop')):out.append(safe('',x))
    return out

def logs(lines=5000):
    r=api(f'/core/logs?lines={lines}&no_colors',headers={'Accept':'text/plain'}); d=data(r); text=d if isinstance(d,str) else json.dumps(d,default=str)
    hits=[x for x in text.splitlines() if LOG_RE.search(x)]
    return {'lines_requested':lines,'total_lines':len(text.splitlines()),'match_count':len(hits),'matching_lines':hits[-5000:]}

def error_log():
    r=api('/core/api/error_log'); d=data(r); return d if isinstance(d,str) else json.dumps(d,default=str)

def set_debug(enabled):
    levels={'homeassistant.components.ecovacs':'debug','ecovacs':'debug','deebot_client':'debug'} if enabled else {'homeassistant.components.ecovacs':'info','ecovacs':'info','deebot_client':'info'}
    return api('/core/api/services/logger/set_level','POST',levels)

def snapshot():
    l=logs(); return {'timestamp':now(),'config_entries':config_entries(),'devices':registry('core.device_registry','devices'),'entities':registry('core.entity_registry','entities'),'states':states(),'logs':l,'error_log':error_log(),'client_inspection':inspect_client('\\n'.join(l['matching_lines']))}

def reload_ecovacs():
    entries=config_entries().get('entries',[]); targets=[e for e in entries if e.get('domain')=='ecovacs']
    if not targets:return {'error':'No Ecovacs config entry found'}
    eid=targets[0].get('entry_id'); call=api('/core/api/services/homeassistant/reload_config_entry','POST',{'entry_id':eid}); time.sleep(12)
    return {'entry_id':eid,'service_result':safe('',call)}

def diagnostic():
    return {'generated_at':now(),'add_on':{'version':VERSION},'environment':{'python':subprocess.run(['python3','--version'],capture_output=True,text=True).stdout.strip(),'arch':os.uname().machine,'hostname':socket.gethostname()},'home_assistant':safe('',api('/supervisor/info')),'config_entries':config_entries(),'states':states(),'registry':{'devices':registry('core.device_registry','devices'),'entities':registry('core.entity_registry','entities')},'core_logs':logs(),'error_log':error_log(),'client_inspection':inspect_client(''),'core_inspection_script':core_inspection_script()}

def deep_capture():
    started=now(); write_core_script(); before=snapshot(); enabled=set_debug(True); time.sleep(2); reload_result=reload_ecovacs(); time.sleep(5); captured=logs(10000); err=error_log(); disabled=set_debug(False); after=snapshot()
    return {'started_at':started,'debug_enabled':safe('',enabled),'before':before,'reload':reload_result,'capture':{'logs':captured,'error_log':err},'debug_restored':safe('',disabled),'final_state':after,'core_inspection_script':core_inspection_script()}

def make_bundle(obj):
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S'); out=SHARE/f'deebot-y1pro-deep-diagnostic-{stamp}.zip'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('diagnostic.json',json.dumps(obj,indent=2,default=str)); z.writestr('core-inspection.sh',core_inspection_script()); z.writestr('README.txt',f'DEEBOT Y1 PRO diagnostics v{VERSION}. Sensitive values are redacted.\n')
    return out

HTML=f'''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{{font-family:system-ui;max-width:1000px;margin:25px auto;padding:0 18px}}.btn{{padding:11px 15px;margin:4px;border:1px solid #bbb;border-radius:8px;background:#fff;cursor:pointer}}.card{{border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0}}.warn{{padding:12px;background:#fff7e6;border-radius:8px;margin:12px 0}}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>{VERSION}</b></p><div class="warn"><b>Deep Y1 PRO Capture</b><br>Writes the Core inspection script directly to /config and downloads the diagnostic ZIP.</div><form action="api/deep" method="post"><button class="btn" type="submit">Run Deep Capture + Download ZIP</button></form><div class="card"><a href="api/diagnostic">Run Normal Diagnostic</a></div><div class="card"><a href="api/core-inspection-script">Show Core Inspection Script</a></div></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def send(self,c,b,ctype='application/json',disp=None):
        b=b.encode() if isinstance(b,str) else b; self.send_response(c); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(b))); self.send_header('Cache-Control','no-store')
        if disp:self.send_header('Content-Disposition',disp)
        self.end_headers(); self.wfile.write(b)
    def do_GET(self):
        if self.path in ('','/'): return self.send(200,HTML,'text/html; charset=utf-8')
        if self.path.startswith('/api/diagnostic'): return self.send(200,json.dumps(diagnostic(),indent=2,default=str))
        if self.path.startswith('/api/core-inspection-script'):
            write_core_script(); return self.send(200,core_inspection_script(),'text/plain; charset=utf-8')
        return self.send(404,json.dumps({'error':'not found'}))
    def do_POST(self):
        if self.path.startswith('/api/deep'):
            try:
                cap=deep_capture(); out=make_bundle({'generated_at':now(),'add_on':{'version':VERSION},'capture':cap,'core_script_written':write_core_script()}); return self.send(200,out.read_bytes(),'application/zip',f'attachment; filename="{out.name}"')
            except Exception as e:return self.send(500,json.dumps({'ok':False,'error':str(e)}))
        return self.send(404,json.dumps({'error':'not found'}))
    def log_message(self,*_): pass

if __name__=='__main__':
    write_core_script()
    HTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
