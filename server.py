#!/usr/bin/env python3
import json, os, re, socket, subprocess, time, urllib.request, urllib.error, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from installed_client_inspector import inspect as inspect_client, core_inspection_script

PORT=8099; VERSION='0.9.1'; HA_CONFIG=Path('/homeassistant'); SHARE=Path('/share'); SUPERVISOR='http://supervisor'
SENSITIVE=re.compile(r'(token|password|secret|username|access_token|refresh_token|authorization|cookie)',re.I)
LOG_RE=re.compile(r'ecovacs|deebot|beepbop|LPATPGFR|cqyi87|CARTESIAN|y30|please update|unsupported|exception|traceback|auth|discover|error|deebot[-_ ]?client',re.I)
Y1_METHODS=['OnMajorMap','OnMapInfoV2','OnCachedMapInfo','GetMajorMap','GetMapTrace','GetMapInfoV2','GetCachedMapInfo','GetDeviceInfo']

def now(): return datetime.now(timezone.utc).isoformat()
def safe(k,v):
    if SENSITIVE.search(str(k)): return '***REDACTED***'
    if isinstance(v,dict): return {str(a):safe(a,b) for a,b in v.items()}
    if isinstance(v,list): return [safe('',x) for x in v]
    return v

def read(path,limit=5000000):
    try:return path.read_text(errors='replace')[:limit]
    except Exception as e:return f'[read error: {e}]'

def api(path,method='GET',payload=None,headers=None):
    token=os.environ.get('SUPERVISOR_TOKEN')
    if not token:return {'ok':False,'error':'SUPERVISOR_TOKEN unavailable'}
    data=json.dumps(payload).encode() if payload is not None else None
    h={'Authorization':'Bearer '+token,'Content-Type':'application/json'}
    if headers:h.update(headers)
    req=urllib.request.Request(SUPERVISOR+path,data=data,method=method,headers=h)
    try:
        with urllib.request.urlopen(req,timeout=30) as r:
            raw=r.read().decode(errors='replace')
            try:return {'ok':True,'status':r.status,'data':safe('',json.loads(raw))}
            except:return {'ok':True,'status':r.status,'data':raw}
    except urllib.error.HTTPError as e:return {'ok':False,'status':e.code,'error':e.read().decode(errors='replace')[:10000]}
    except Exception as e:return {'ok':False,'error':str(e)}

def data(r): return r.get('data') if isinstance(r,dict) and r.get('ok') else r

def config_entries():
    try:
        es=json.loads(read(HA_CONFIG/'.storage/core.config_entries')).get('data',{}).get('entries',[])
        selected=[e for e in es if str(e.get('domain','')).lower() in ('ecovacs','deebot')]
        return {'count':len(selected),'entries':[safe('',e) for e in selected]}
    except Exception as e:return {'error':str(e)}

def registry(name,key):
    try:
        d=json.loads(read(HA_CONFIG/'.storage'/name)); items=d.get('data',{}).get(key,[])
        return [safe('',x) for x in items if any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop'))]
    except Exception as e:return {'error':str(e)}

def states():
    s=data(api('/core/api/states')); out=[]
    if isinstance(s,list):
        for x in s:
            if 'vacuum' in x.get('entity_id','').lower() or any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop')):out.append(safe('',x))
    return out

def core_logs(lines=5000):
    r=api(f'/core/logs?lines={lines}&no_colors',headers={'Accept':'text/plain'}); d=data(r); text=d if isinstance(d,str) else json.dumps(d,default=str)
    relevant=[x for x in text.splitlines() if LOG_RE.search(x)]
    return {'endpoint':'/core/logs','lines_requested':lines,'total_lines':len(text.splitlines()),'match_count':len(relevant),'matching_lines':relevant[-5000:],'request':{k:v for k,v in r.items() if k!='data'}}

def supervisor_logs(lines=500):
    r=api(f'/supervisor/logs?lines={lines}&no_colors',headers={'Accept':'text/plain'}); d=data(r); text=d if isinstance(d,str) else json.dumps(d,default=str)
    relevant=[x for x in text.splitlines() if re.search(r'ecovacs|deebot|addon|diagnostic',x,re.I)]
    return {'lines_requested':lines,'match_count':len(relevant),'matching_lines':relevant[-500:],'request':{k:v for k,v in r.items() if k!='data'}}

def error_log():
    r=api('/core/api/error_log'); d=data(r); return {'content':d if isinstance(d,str) else json.dumps(d,default=str),'request':{k:v for k,v in r.items() if k!='data'}}

def services():
    d=data(api('/core/api/services')); return [x for x in d if x.get('domain') in ('vacuum','ecovacs','deebot','homeassistant','logger')] if isinstance(d,list) else d

def integration_info():
    result={'custom':[],'core_path':'/usr/src/homeassistant/homeassistant/components/ecovacs','core_visible':False}
    for p in [HA_CONFIG/'custom_components/ecovacs/manifest.json',HA_CONFIG/'custom_components/deebot/manifest.json']:
        if p.exists():
            try:result['custom'].append({'path':str(p),'manifest':safe('',json.loads(read(p)))})
            except Exception as e:result['custom'].append({'path':str(p),'error':str(e)})
    result['core_visible']=Path(result['core_path']).exists(); return result

def network():
    out={}
    for host in ['ecovacs.com','portal.ecovacs.com','api.ecovacs.com']:
        t={}
        try:t['dns']='PASS';t['ip']=socket.gethostbyname(host)
        except Exception as e:t['dns']='FAIL';t['error']=str(e)
        try:
            req=urllib.request.Request('https://'+host,method='HEAD',headers={'User-Agent':'DEEBOT-Diagnostics/'+VERSION})
            with urllib.request.urlopen(req,timeout=8) as r:t['https']='PASS';t['status']=r.status
        except Exception as e:t['https']='FAIL';t['https_error']=str(e)
        out[host]=t
    return out

def set_debug(enabled=True):
    levels={'homeassistant.components.ecovacs':'debug','ecovacs':'debug','deebot_client':'debug'} if enabled else {'homeassistant.components.ecovacs':'info','ecovacs':'info','deebot_client':'info'}
    return api('/core/api/services/logger/set_level','POST',levels)

def snapshot():
    logs=core_logs(5000)
    return {'timestamp':now(),'config_entries':config_entries(),'devices':registry('core.device_registry','devices'),'entities':registry('core.entity_registry','entities'),'states':states(),'logs':logs,'error_log':error_log(),'client_inspection':inspect_client('\n'.join(logs.get('matching_lines',[])))}

def reload_ecovacs():
    entries=config_entries().get('entries',[]); targets=[e for e in entries if e.get('domain')=='ecovacs']
    if not targets:return {'error':'No Ecovacs config entry found'}
    eid=targets[0].get('entry_id'); before=snapshot(); call=api('/core/api/services/homeassistant/reload_config_entry','POST',{'entry_id':eid}); time.sleep(10); after=snapshot()
    return {'entry_id':eid,'service_result':safe('',call),'before':before,'after':after,'discovery_diff':{'devices_before':len(before['devices']),'devices_after':len(after['devices']),'entities_before':len(before['entities']),'entities_after':len(after['entities']),'new_devices':[x for x in after['devices'] if x not in before['devices']],'new_entities':[x for x in after['entities'] if x not in before['entities']]}}

def deep_capture():
    before=snapshot(); debug_result=set_debug(True); reload_result=reload_ecovacs(); time.sleep(4); debug_logs=core_logs(5000); debug_error=error_log(); restore_result=set_debug(False); after=snapshot()
    return {'started_at':before['timestamp'],'debug_enabled':safe('',debug_result),'reload':reload_result,'debug_capture':{'logs':debug_logs,'error_log':debug_error},'debug_restored':safe('',restore_result),'final_state':after,'client_inspection':inspect_client('\n'.join(debug_logs.get('matching_lines',[])))}

def diagnostic(extra=None):
    result={'generated_at':now(),'add_on':{'version':VERSION},'environment':{'python':subprocess.run(['python3','--version'],capture_output=True,text=True).stdout.strip(),'arch':os.uname().machine,'hostname':socket.gethostname()},'home_assistant':safe('',api('/supervisor/info')),'core_config':safe('',api('/core/api/config')),'deebot_entities':states(),'config_entries':config_entries(),'registry':{'devices':registry('core.device_registry','devices'),'entities':registry('core.entity_registry','entities')},'integration':integration_info(),'services':services(),'network':network(),'core_logs':core_logs(5000),'supervisor_logs':supervisor_logs(500),'error_log':error_log(),'client_inspection':inspect_client(''),'known_y1_pro_methods':Y1_METHODS}
    if extra:result['capture']=extra
    return result

def bundle(obj):
    stamp=datetime.now().strftime('%Y%m%d-%H%M%S'); out=SHARE/f'deebot-y1pro-diagnostic-{stamp}.zip'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('diagnostic.json',json.dumps(obj,indent=2,default=str)); z.writestr('README.txt',f'DEEBOT Y1 PRO diagnostics v{VERSION}. Credentials/tokens are redacted.\n')
    return out

HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:1100px;margin:25px auto;padding:0 18px}.btn{padding:10px 14px;margin:4px;border:1px solid #bbb;border-radius:8px;background:#fff;cursor:pointer}.warn{padding:12px;background:#fff7e6;border-radius:8px;margin:12px 0}.card{border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0}pre{white-space:pre-wrap;background:#f5f5f5;padding:14px;border-radius:8px;max-height:600px;overflow:auto}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>0.9.1</b>.</p><div class="warn"><b>Core-side Installed Client Inspection</b><br>Generate a one-shot, read-only script to run inside Home Assistant Core/Terminal. It inspects the real deebot-client installation, version, hardware modules, cqyi87, cd45, 30000 handlers and Ecovacs source, then writes one JSON file under /config.<br><button class="btn" onclick="corecmd()">Show Core Inspection Script</button> <button class="btn" onclick="copycmd()">Copy Script</button></div><div class="warn"><b>Deep Ecovacs Debug Capture</b><br>Temporarily enables Ecovacs debug logging, reloads the integration, captures the failure, then restores logging to info.<br><button class="btn" onclick="deep()">Deep Debug Capture</button></div><button class="btn" onclick="run()">Run Full Diagnostic</button><button class="btn" onclick="zip()">Download ZIP</button><button class="btn" onclick="jsondl()">Download JSON</button><div id="status" class="card">Ready.</div><div id="out"></div><script>const $=x=>document.getElementById(x);let script='';function render(d){$('out').innerHTML='<div class="card"><h2>Result</h2><pre>'+JSON.stringify(d,null,2)+'</pre></div>'}async function run(){$('status').textContent='Running…';let r=await fetch('api/diagnostic');render(await r.json());$('status').textContent='Complete.'}async function corecmd(){let r=await fetch('api/core-inspection-script');script=await r.text();$('out').innerHTML='<div class="card"><h2>Run this in Home Assistant Terminal</h2><button class="btn" onclick="copycmd()">Copy</button><pre id="cmd"></pre></div>';$('cmd').textContent=script;$('status').textContent='Script ready.'}async function copycmd(){if(!script){let r=await fetch('api/core-inspection-script');script=await r.text()}await navigator.clipboard.writeText(script);$('status').textContent='Script copied.'}async function deep(){if(!confirm('Enable temporary Ecovacs debug logging, reload the integration and capture the result?'))return;$('status').textContent='Running deep capture. Do not close this page…';let r=await fetch('api/deep',{method:'POST'});let d=await r.json();render(d);$('status').textContent=r.ok?'Deep capture complete.':'Deep capture failed.'}function zip(){$('status').textContent='Creating ZIP…';window.location.href='api/bundle-download';setTimeout(()=>{$('status').textContent='ZIP download requested.'},1000)}async function jsondl(){let r=await fetch('api/diagnostic');if(!r.ok)return;let b=await r.blob();let a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='deebot-y1pro-diagnostic.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);$('status').textContent='JSON downloaded.'}</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def send(self,c,b,ctype='application/json',disp=None):
        b=b.encode() if isinstance(b,str) else b; self.send_response(c); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(b))); self.send_header('Cache-Control','no-store');
        if disp:self.send_header('Content-Disposition',disp)
        self.end_headers();self.wfile.write(b)
    def do_GET(self):
        if self.path in ('','/'):return self.send(200,HTML,'text/html; charset=utf-8')
        if self.path.startswith('/api/diagnostic'):return self.send(200,json.dumps(diagnostic(),indent=2,default=str))
        if self.path.startswith('/api/client'):return self.send(200,json.dumps(inspect_client('\n'.join(core_logs(5000).get('matching_lines',[]))),indent=2,default=str))
        if self.path.startswith('/api/core-inspection-script'):return self.send(200,core_inspection_script(),'text/plain; charset=utf-8')
        if self.path.startswith('/api/bundle-download'):
            try:o=bundle(diagnostic());return self.send(200,o.read_bytes(),'application/zip',f'attachment; filename="{o.name}"')
            except Exception as e:return self.send(500,json.dumps({'error':str(e)}))
        return self.send(404,json.dumps({'error':'not found'}))
    def do_POST(self):
        if self.path.startswith('/api/deep'):
            try:return self.send(200,json.dumps(diagnostic(deep_capture()),indent=2,default=str))
            except Exception as e:return self.send(500,json.dumps({'error':str(e)}))
        return self.send(404,json.dumps({'error':'not found'}))
    def log_message(self,*_):pass

if __name__=='__main__':HTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
