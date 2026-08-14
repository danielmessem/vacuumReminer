#!/usr/bin/env python3
import json, os, re, socket, subprocess, urllib.request, urllib.error, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

PORT=8099; VERSION='0.3.1'; HA_CONFIG=Path('/homeassistant'); SHARE=Path('/share'); SUPERVISOR='http://supervisor'
SENSITIVE=re.compile(r'(token|password|secret|username|access_token|refresh_token|authorization|cookie)',re.I)
Y1_METHODS=['OnMajorMap','OnMapInfoV2','OnCachedMapInfo','GetMajorMap','GetMapTrace','GetMapInfoV2','GetCachedMapInfo','GetDeviceInfo']

def now(): return datetime.now(timezone.utc).isoformat()
def safe(k,v):
    if SENSITIVE.search(str(k)): return '***REDACTED***'
    if isinstance(v,dict): return {str(a):safe(a,b) for a,b in v.items()}
    if isinstance(v,list): return [safe('',x) for x in v]
    return v

def read(path,limit=500000):
    try:return path.read_text(errors='replace')[:limit]
    except Exception as e:return f'[read error: {e}]'

def api(path,method='GET',payload=None):
    token=os.environ.get('SUPERVISOR_TOKEN')
    if not token:return {'error':'SUPERVISOR_TOKEN unavailable'}
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(SUPERVISOR+path,data=data,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            raw=r.read().decode(errors='replace')
            try:return json.loads(raw)
            except:return {'raw':raw,'status':r.status}
    except urllib.error.HTTPError as e:
        return {'error':f'HTTP {e.code}: '+e.read().decode(errors='replace')[:4000]}
    except Exception as e:return {'error':str(e)}

def config_entries():
    p=HA_CONFIG/'.storage/core.config_entries'
    try:
        es=json.loads(read(p,5000000)).get('data',{}).get('entries',[])
        return {'count':len([e for e in es if str(e.get('domain','')).lower() in ('ecovacs','deebot')]),'entries':[safe('',e) for e in es if str(e.get('domain','')).lower() in ('ecovacs','deebot')]}
    except Exception as e:return {'error':str(e)}

def registry(name,key):
    try:
        d=json.loads(read(HA_CONFIG/'.storage'/name,5000000)); items=d.get('data',{}).get(key,[])
        return [safe('',x) for x in items if any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop'))]
    except Exception as e:return {'error':str(e)}

def states():
    s=api('/core/api/states'); out=[]
    if isinstance(s,list):
        for x in s:
            if 'vacuum' in x.get('entity_id','').lower() or any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop')):out.append(safe('',x))
    return out

def logs(lines=2000):
    d=api(f'/core/logs/latest?lines={lines}&no_colors'); text=d.get('raw','') if isinstance(d,dict) else json.dumps(d)
    relevant=[x for x in text.splitlines() if re.search(r'ecovacs|deebot|beepbop|LPATPGFR|Please update|unsupported|exception|traceback|error',x,re.I)]
    return {'lines_requested':lines,'match_count':len(relevant),'matching_lines':relevant[-2000:]}

def services():
    d=api('/core/api/services')
    if not isinstance(d,list):return d
    return [x for x in d if x.get('domain') in ('vacuum','ecovacs','deebot','homeassistant')]

def integration_info():
    result={'custom':[],'core_path':'/usr/src/homeassistant/homeassistant/components/ecovacs','core_visible':False}
    for p in [HA_CONFIG/'custom_components/ecovacs/manifest.json',HA_CONFIG/'custom_components/deebot/manifest.json']:
        if p.exists():result['custom'].append({'path':str(p),'manifest':safe('',json.loads(read(p)))})
    p=Path(result['core_path']); result['core_visible']=p.exists()
    return result

def network():
    tests={}
    for host in ['ecovacs.com','portal.ecovacs.com','api.ecovacs.com']:
        try:
            ip=socket.gethostbyname(host); tests[host]={'dns':'PASS','ip':ip}
        except Exception as e:tests[host]={'dns':'FAIL','error':str(e)}
        try:
            req=urllib.request.Request('https://'+host,method='HEAD',headers={'User-Agent':'DEEBOT-Diagnostics/'+VERSION})
            with urllib.request.urlopen(req,timeout=8) as r:tests[host]['https']='PASS'; tests[host]['status']=r.status
        except Exception as e:tests[host]['https']='FAIL'; tests[host]['https_error']=str(e)
    return tests

def diagnostic(extra=None):
    entries=config_entries(); result={'generated_at':now(),'add_on':{'version':VERSION},'environment':{'python':subprocess.run(['python3','--version'],capture_output=True,text=True).stdout.strip(),'arch':os.uname().machine,'hostname':socket.gethostname()},'home_assistant':safe('',api('/supervisor/info')),'core_config':safe('',api('/core/api/config')),'deebot_entities':states(),'config_entries':entries,'registry':{'devices':registry('core.device_registry','devices'),'entities':registry('core.entity_registry','entities')},'integration':integration_info(),'services':services(),'network':network(),'core_logs':logs(2000),'known_y1_pro_methods':Y1_METHODS}
    if extra:result['capture']=extra
    return result

def reload_ecovacs():
    entries=config_entries().get('entries',[]); targets=[e for e in entries if e.get('domain')=='ecovacs']
    if not targets:return {'error':'No Ecovacs config entry found'}
    eid=targets[0].get('entry_id')
    before=states(); before_time=now()
    call=api('/core/api/services/homeassistant/reload_config_entry','POST',{'entry_id':eid})
    import time; time.sleep(8)
    after=states(); after_time=now(); after_logs=logs(2000)
    return {'entry_id':eid,'started_at':before_time,'finished_at':after_time,'service_result':safe('',call),'before':before,'after':after,'logs_after_reload':after_logs}

def bundle(data=None):
    data=data or diagnostic(); stamp=datetime.now().strftime('%Y%m%d-%H%M%S'); out=SHARE/f'deebot-y1pro-diagnostic-{stamp}.zip'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('diagnostic.json',json.dumps(data,indent=2,default=str)); z.writestr('README.txt',f'DEEBOT Y1 PRO diagnostics v{VERSION}. Credentials/tokens are redacted.\n')
    return out

HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:1100px;margin:25px auto;padding:0 18px}.btn{padding:10px 14px;margin:4px;border:1px solid #bbb;border-radius:8px;background:#fff;cursor:pointer}.danger{border-color:#c66}.ok{padding:10px;background:#eef7ee;border-radius:8px}.bad{padding:10px;background:#fff0f0;border-radius:8px}pre{white-space:pre-wrap;background:#f5f5f5;padding:14px;border-radius:8px;max-height:500px;overflow:auto}.card{border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Read-only diagnostics. Version <b>0.3.1</b>.</p><button class="btn" onclick="run()">Run full diagnostic</button><button class="btn" onclick="reload()">Reload Ecovacs + capture</button><button class="btn" onclick="dl()">Download ZIP</button><button class="btn" onclick="jsondl()">Download JSON</button><div id="status" class="card">Ready.</div><div id="out"></div><script>const $=id=>document.getElementById(id);function show(d){$('out').innerHTML='<div class="card"><h2>Vacuum state</h2><pre>'+JSON.stringify(d.deebot_entities,null,2)+'</pre></div><div class="card"><h2>Network</h2><pre>'+JSON.stringify(d.network,null,2)+'</pre></div><div class="card"><h2>Integration</h2><pre>'+JSON.stringify({config_entries:d.config_entries,integration:d.integration},null,2)+'</pre></div><div class="card"><h2>Relevant logs</h2><pre>'+JSON.stringify(d.core_logs,null,2)+'</pre></div>'}async function run(){ $('status').textContent='Running diagnostic…';let r=await fetch('api/diagnostic');let d=await r.json();window.last=d;show(d);$('status').textContent='Diagnostic complete.'}async function reload(){if(!confirm('Reload the Ecovacs integration and capture the resulting state?'))return;$('status').textContent='Reloading Ecovacs and capturing errors…';let r=await fetch('api/reload',{method:'POST'});let d=await r.json();window.last=d;show(d);$('status').textContent=d.error?'Reload failed: '+d.error:'Reload capture complete.'}function save(b,n){let a=document.createElement('a');a.href=URL.createObjectURL(b);a.download=n;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000)}async function dl(){ $('status').textContent='Creating ZIP…';let r=await fetch('api/bundle',{method:'POST'});if(!r.ok){$('status').textContent='Bundle failed';return}save(await r.blob(),'deebot-y1pro-diagnostic.zip');$('status').textContent='ZIP downloaded.'}async function jsondl(){let r=await fetch('api/diagnostic');save(await r.blob(),'deebot-y1pro-diagnostic.json');$('status').textContent='JSON downloaded.'}</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def send(self,c,b,ctype='application/json',disp=None):
        b=b.encode() if isinstance(b,str) else b; self.send_response(c); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(b))); 
        if disp:self.send_header('Content-Disposition',disp)
        self.end_headers();self.wfile.write(b)
    def do_GET(self):
        if self.path in ('','/'):return self.send(200,HTML,'text/html; charset=utf-8')
        if self.path.startswith('/api/diagnostic'):return self.send(200,json.dumps(diagnostic(),indent=2,default=str))
        self.send(404,json.dumps({'error':'not found'}))
    def do_POST(self):
        if self.path.startswith('/api/reload'):
            try:return self.send(200,json.dumps(diagnostic(reload_ecovacs()),indent=2,default=str))
            except Exception as e:return self.send(500,json.dumps({'error':str(e)}))
        if self.path.startswith('/api/bundle'):
            try:
                o=bundle();return self.send(200,o.read_bytes(),'application/zip',f'attachment; filename="{o.name}"')
            except Exception as e:return self.send(500,json.dumps({'error':str(e)}))
        self.send(404,json.dumps({'error':'not found'}))
    def log_message(self,*_):pass

if __name__=='__main__':HTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
