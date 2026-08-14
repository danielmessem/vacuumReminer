#!/usr/bin/env python3
import json, os, re, socket, subprocess, time, urllib.request, urllib.error, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
PORT=8099; VERSION='0.4.1'; HA_CONFIG=Path('/homeassistant'); SHARE=Path('/share'); SUPERVISOR='http://supervisor'
SENSITIVE=re.compile(r'(token|password|secret|username|access_token|refresh_token|authorization|cookie)',re.I)
Y1_METHODS=['OnMajorMap','OnMapInfoV2','OnCachedMapInfo','GetMajorMap','GetMapTrace','GetMapInfoV2','GetCachedMapInfo','GetDeviceInfo']
LOG_RE=re.compile(r'ecovacs|deebot|beepbop|LPATPGFR|cqyi87|please update|unsupported|exception|traceback|auth|discover',re.I)
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
    if not token:return {'ok':False,'error':'SUPERVISOR_TOKEN unavailable'}
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(SUPERVISOR+path,data=data,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=20) as r:
            raw=r.read().decode(errors='replace')
            try:return {'ok':True,'status':r.status,'data':safe('',json.loads(raw))}
            except:return {'ok':True,'status':r.status,'data':raw}
    except urllib.error.HTTPError as e:return {'ok':False,'status':e.code,'error':e.read().decode(errors='replace')[:5000]}
    except Exception as e:return {'ok':False,'error':str(e)}
def data(r): return r.get('data') if isinstance(r,dict) and r.get('ok') else r
def config_entries():
    try:
        es=json.loads(read(HA_CONFIG/'.storage/core.config_entries',5000000)).get('data',{}).get('entries',[]); selected=[e for e in es if str(e.get('domain','')).lower() in ('ecovacs','deebot')]
        return {'count':len(selected),'entries':[safe('',e) for e in selected]}
    except Exception as e:return {'error':str(e)}
def registry(name,key):
    try:
        d=json.loads(read(HA_CONFIG/'.storage'/name,5000000)); items=d.get('data',{}).get(key,[])
        return [safe('',x) for x in items if any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop'))]
    except Exception as e:return {'error':str(e)}
def states():
    s=data(api('/core/api/states')); out=[]
    if isinstance(s,list):
        for x in s:
            if 'vacuum' in x.get('entity_id','').lower() or any(q in json.dumps(x).lower() for q in ('ecovacs','deebot','beepbop')):out.append(safe('',x))
    return out
def logs(lines=3000):
    r=api(f'/core/logs/latest?lines={lines}&no_colors'); d=data(r); text=d if isinstance(d,str) else json.dumps(d,default=str); relevant=[x for x in text.splitlines() if LOG_RE.search(x)]
    return {'lines_requested':lines,'total_lines':len(text.splitlines()),'match_count':len(relevant),'matching_lines':relevant[-3000:],'request':{k:v for k,v in r.items() if k!='data'}}
def error_log():
    r=api('/core/api/error_log'); d=data(r); return {'content':d if isinstance(d,str) else json.dumps(d,default=str),'request':{k:v for k,v in r.items() if k!='data'}}
def services():
    d=data(api('/core/api/services')); return [x for x in d if x.get('domain') in ('vacuum','ecovacs','deebot','homeassistant')] if isinstance(d,list) else d
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
def base_snapshot(): return {'timestamp':now(),'config_entries':config_entries(),'devices':registry('core.device_registry','devices'),'entities':registry('core.entity_registry','entities'),'states':states(),'logs':logs(3000),'error_log':error_log()}
def reload_ecovacs():
    entries=config_entries().get('entries',[]); targets=[e for e in entries if e.get('domain')=='ecovacs']
    if not targets:return {'error':'No Ecovacs config entry found'}
    eid=targets[0].get('entry_id'); before=base_snapshot(); call=api('/core/api/services/homeassistant/reload_config_entry','POST',{'entry_id':eid}); time.sleep(8); after=base_snapshot()
    return {'entry_id':eid,'service_result':safe('',call),'before':before,'after':after,'discovery_diff':{'devices_before':len(before['devices']),'devices_after':len(after['devices']),'entities_before':len(before['entities']),'entities_after':len(after['entities']),'new_devices':[x for x in after['devices'] if x not in before['devices']],'new_entities':[x for x in after['entities'] if x not in before['entities']]}}
def diagnostic(extra=None):
    result={'generated_at':now(),'add_on':{'version':VERSION},'environment':{'python':subprocess.run(['python3','--version'],capture_output=True,text=True).stdout.strip(),'arch':os.uname().machine,'hostname':socket.gethostname()},'home_assistant':safe('',api('/supervisor/info')),'core_config':safe('',api('/core/api/config')),'deebot_entities':states(),'config_entries':config_entries(),'registry':{'devices':registry('core.device_registry','devices'),'entities':registry('core.entity_registry','entities')},'integration':integration_info(),'services':services(),'network':network(),'core_logs':logs(3000),'error_log':error_log(),'known_y1_pro_methods':Y1_METHODS}
    if extra:result['capture']=extra
    return result
def bundle(obj=None):
    obj=obj or diagnostic(); stamp=datetime.now().strftime('%Y%m%d-%H%M%S'); out=SHARE/f'deebot-y1pro-diagnostic-{stamp}.zip'
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('diagnostic.json',json.dumps(obj,indent=2,default=str)); z.writestr('README.txt',f'DEEBOT Y1 PRO diagnostics v{VERSION}. Credentials/tokens are redacted.\n')
    return out
HTML='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:1100px;margin:25px auto;padding:0 18px}.btn{padding:10px 14px;margin:4px;border:1px solid #bbb;border-radius:8px;background:#fff;cursor:pointer}.warn{padding:12px;background:#fff7e6;border-radius:8px;margin:12px 0}.card{border:1px solid #ddd;border-radius:10px;padding:14px;margin:12px 0}pre{white-space:pre-wrap;background:#f5f5f5;padding:14px;border-radius:8px;max-height:600px;overflow:auto}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>0.4.1</b>. Read-only except for the controlled Ecovacs reload test.</p><div class="warn"><b>Discovery test</b><br>Reloads the Ecovacs config entry, waits 8 seconds, then compares device/entity state and captures logs.<br><button class="btn" onclick="reload()">Reload Ecovacs + Capture Discovery</button></div><button class="btn" onclick="run()">Run Full Diagnostic</button><button class="btn" onclick="zip()">Download ZIP</button><button class="btn" onclick="jsondl()">Download JSON</button><div id="status" class="card">Ready.</div><div id="out"></div><script>const $=x=>document.getElementById(x);function render(d){$('out').innerHTML='<div class="card"><h2>Result</h2><pre>'+JSON.stringify(d,null,2)+'</pre></div>'}async function run(){$('status').textContent='Running…';let r=await fetch('api/diagnostic');render(await r.json());$('status').textContent='Complete.'}async function reload(){if(!confirm('Reload Ecovacs and capture discovery?'))return;$('status').textContent='Reloading Ecovacs and capturing before/after state…';let r=await fetch('api/reload',{method:'POST'});let d=await r.json();render(d);$('status').textContent=d.capture?.error||d.error?'Reload failed':'Discovery capture complete.'}function zip(){$('status').textContent='Creating ZIP…';window.location.href='api/bundle-download';setTimeout(()=>{$('status').textContent='ZIP download requested.'},1000)}async function jsondl(){let r=await fetch('api/diagnostic');if(!r.ok){$('status').textContent='JSON download failed';return}let b=await r.blob();let a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='deebot-y1pro-diagnostic.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);$('status').textContent='JSON downloaded.'}</script></body></html>'''
class Handler(BaseHTTPRequestHandler):
    def send(self,c,b,ctype='application/json',disp=None):
        b=b.encode() if isinstance(b,str) else b; self.send_response(c); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(b))); self.send_header('Cache-Control','no-store');
        if disp:self.send_header('Content-Disposition',disp)
        self.end_headers();self.wfile.write(b)
    def do_GET(self):
        if self.path in ('','/'):return self.send(200,HTML,'text/html; charset=utf-8')
        if self.path.startswith('/api/diagnostic'):return self.send(200,json.dumps(diagnostic(),indent=2,default=str))
        if self.path.startswith('/api/bundle-download'):
            try:o=bundle();return self.send(200,o.read_bytes(),'application/zip',f'attachment; filename="{o.name}"')
            except Exception as e:return self.send(500,json.dumps({'error':str(e)}))
        return self.send(404,json.dumps({'error':'not found'}))
    def do_POST(self):
        if self.path.startswith('/api/reload'):
            try:return self.send(200,json.dumps(diagnostic(reload_ecovacs()),indent=2,default=str))
            except Exception as e:return self.send(500,json.dumps({'error':str(e)}))
        return self.send(404,json.dumps({'error':'not found'}))
    def log_message(self,*_):pass
if __name__=='__main__':HTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
