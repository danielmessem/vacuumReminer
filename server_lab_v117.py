#!/usr/bin/env python3
"""DEEBOT Y1 PRO diagnostics and command laboratory."""
import json, os, re, socket, subprocess, threading, time, urllib.error, urllib.request, zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from installed_client_inspector import inspect as inspect_client, core_inspection_script

VERSION="1.1.8"; PORT=8099; HA=Path('/homeassistant'); SHARE=Path('/share'); TOKEN=os.environ.get('SUPERVISOR_TOKEN')
JOBS={}; LOCK=threading.Lock()
MATCH=re.compile(r'ecovacs|deebot|beepbop|cqyi87|CARTESIAN|clean_V2|setWorkMode|getWorkMode|workState|motionState|30000|10000|p2p|cmdName|unsupported|exception|traceback|error',re.I)
SECRET=re.compile(r'token|password|secret|authorization|cookie|access_token|refresh_token',re.I)

def now(): return datetime.now(timezone.utc).isoformat()
def redact(x):
    if isinstance(x,dict): return {k:('***REDACTED***' if SECRET.search(str(k)) else redact(v)) for k,v in x.items()}
    if isinstance(x,list): return [redact(v) for v in x]
    return x

def sup(path,method='GET',payload=None,accept='application/json'):
    if not TOKEN:return {'ok':False,'error':'SUPERVISOR_TOKEN unavailable'}
    body=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request('http://supervisor'+path,data=body,method=method,headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json','Accept':accept})
    try:
        with urllib.request.urlopen(req,timeout=45) as r:
            raw=r.read().decode(errors='replace')
            if 'application/json' in r.headers.get('Content-Type',''):
                try: raw=json.loads(raw)
                except Exception: pass
            return {'ok':True,'status':r.status,'data':redact(raw)}
    except urllib.error.HTTPError as e:return {'ok':False,'status':e.code,'error':e.read().decode(errors='replace')[:10000]}
    except Exception as e:return {'ok':False,'error':str(e)}

def val(r): return r.get('data') if isinstance(r,dict) and r.get('ok') else r
def service(domain,name,data): return sup(f'/core/api/services/{domain}/{name}','POST',data)
def entries():
    try:return [e for e in json.loads((HA/'.storage/core.config_entries').read_text()).get('data',{}).get('entries',[]) if e.get('domain')=='ecovacs']
    except Exception as e:return [{'error':str(e)}]
def logs(lines=5000):
    r=val(sup(f'/core/logs?lines={lines}&no_colors',accept='text/plain')); text=r if isinstance(r,str) else json.dumps(r,default=str)
    m=[x for x in text.splitlines() if MATCH.search(x)]; return {'lines_requested':lines,'match_count':len(m),'matching_lines':m[-12000:]}
def states():
    r=val(sup('/core/api/states')); return [redact(x) for x in r if isinstance(r,list) and ('beepbop' in json.dumps(x).lower() or 'ecovacs' in json.dumps(x).lower() or 'deebot' in json.dumps(x).lower())]
def logger(debug):return service('logger','set_level',{'homeassistant.components.ecovacs':'debug' if debug else 'info','ecovacs':'debug' if debug else 'info','deebot_client':'debug' if debug else 'info'})
def evidence():
    l=logs(10000); a=l['matching_lines']; text='\n'.join(a)
    return {'captured_at':now(),'cqyi87':[x for x in a if 'cqyi87' in x],'clean_V2':[x for x in a if 'clean_V2' in x],'work_mode_state':[x for x in a if re.search(r'workMode|setWorkMode|getWorkMode|workState|motionState',x,re.I)],'messages_10000':[x for x in a if '10000' in x],'messages_30000':[x for x in a if '30000' in x],'p2p':[x for x in a if 'p2p' in x.lower()],'cmd_count':len(re.findall(r'cmdName',text))}
def snapshot():
    l=logs(); return {'timestamp':now(),'config_entries':redact(entries()),'states':states(),'logs':l,'client_inspection':inspect_client('\n'.join(l['matching_lines']))}
def zip_bundle(obj):
    SHARE.mkdir(parents=True,exist_ok=True); p=SHARE/f'deebot-y1pro-deep-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip'
    with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('diagnostic.json',json.dumps(redact(obj),indent=2,default=str)); z.writestr('core-inspection.sh',core_inspection_script()); z.writestr('README.txt',f'DEEBOT Y1 PRO Diagnostics v{VERSION}\n')
    return p

def run_lab(name,command=None,params=None,service_name=None):
    logger(True); before=logs(3000)
    if service_name: result=service('vacuum',service_name,{'entity_id':'vacuum.beepbop'})
    else: result=service('vacuum','send_command',{'entity_id':'vacuum.beepbop','command':command,'params':params or {}})
    time.sleep(4); after=logs(7000); st=states(); logger(False)
    return {'ok':True,'test':name,'request':{'command':command,'params':params,'service':service_name},'service_result':result,'before':before,'after':after,'states':st,'evidence':evidence()}

def deep(job):
    try:
        with LOCK:JOBS[job].update(percent=10,message='Baseline')
        before=snapshot(); logger(True)
        with LOCK:JOBS[job].update(percent=25,message='Reloading Ecovacs integration')
        es=[e for e in entries() if e.get('entry_id')]; reload_result=service('homeassistant','reload_config_entry',{'entry_id':es[0]['entry_id']}) if es else {'ok':False,'error':'No Ecovacs config entry'}; time.sleep(5)
        with LOCK:JOBS[job].update(percent=60,message='Capturing Y1 PRO traffic')
        cap=evidence(); logger(False)
        with LOCK:JOBS[job].update(percent=90,message='Building diagnostic ZIP')
        p=zip_bundle({'version':VERSION,'before':before,'reload':reload_result,'evidence':cap,'after':snapshot()})
        with LOCK:JOBS[job].update(status='complete',percent=100,message='Complete',file=str(p))
    except Exception as e:
        try:logger(False)
        except Exception:pass
        with LOCK:JOBS[job].update(status='error',percent=100,message=str(e))
def start_deep():
    j=datetime.now().strftime('%Y%m%d%H%M%S%f')
    with LOCK:JOBS[j]={'status':'running','percent':0,'message':'Starting','events':[],'started_at':now()}
    threading.Thread(target=deep,args=(j,),daemon=True).start(); return j

INDEX='''<!doctype html><html><head><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{font-family:system-ui;max-width:1000px;margin:25px auto;padding:0 18px}.card{border:1px solid #ddd;border-radius:10px;padding:18px;margin:12px 0}button{padding:10px 14px;margin:4px;border:1px solid #aaa;border-radius:8px;background:white;cursor:pointer}.out{background:#111;color:#eee;padding:12px;white-space:pre-wrap;font:12px monospace;max-height:600px;overflow:auto}</style></head><body><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>VERSION</b></p><div class="card"><h2>Y1 PRO Command Laboratory</h2><p>Each test calls the existing Home Assistant <code>vacuum.beepbop</code> service, then captures the raw Core/API/MQTT log evidence.</p><button onclick="go('getworkmode')">getWorkMode</button><button onclick="go('setvacuum')">setWorkMode → VACUUM (1)</button><button onclick="go('setboth')">setWorkMode → VACUUM_AND_MOP (0)</button><button onclick="go('getworkstate')">getWorkState</button><button onclick="go('cleanv2')">clean_V2 START</button><button onclick="go('stopv2')">clean_V2 STOP</button><button onclick="go('start')">HA START</button><button onclick="go('stop')">HA STOP</button><button onclick="go('dock')">RETURN TO BASE</button><pre id="out" class="out">Ready</pre></div><div class="card"><h2>Deep Capture</h2><button onclick="deep()">Run Deep Capture</button> <a href="./api/health">Health</a><div id="p"></div></div><script>async function go(a){const o=document.getElementById('out');o.textContent='Running '+a+'…';try{const r=await fetch('./api/lab/'+a+'?t='+Date.now(),{cache:'no-store'});o.textContent='HTTP '+r.status+'\\n\\n'+await r.text()}catch(e){o.textContent='ERROR\\n'+e}}async function deep(){const o=document.getElementById('p');o.textContent='Starting…';try{const r=await fetch('./api/deep',{method:'POST'});const j=await r.json();if(!j.job){o.textContent=JSON.stringify(j);return}const poll=async()=>{const s=await fetch('./api/job/'+j.job+'?t='+Date.now()).then(x=>x.json());o.textContent=s.percent+'% — '+s.message+'\\n'+(s.events||[]).map(x=>x.message).join('\\n');if(s.status==='complete')o.innerHTML+='\\n<a href="./api/download/'+j.job+'">Download diagnostic ZIP</a>';else if(s.status!=='error')setTimeout(poll,500)};poll()}catch(e){o.textContent='ERROR '+e}}</script></body></html>'''

class H(BaseHTTPRequestHandler):
    def sendx(self,c,b,ct='application/json',fn=None):
        if isinstance(b,str):b=b.encode()
        self.send_response(c);self.send_header('Content-Type',ct);self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store')
        if fn:self.send_header('Content-Disposition',f'attachment; filename="{fn}"')
        self.end_headers();self.wfile.write(b)
    def do_GET(self):
        p=self.path.split('?',1)[0]
        if p in ('','/'):return self.sendx(200,INDEX.replace('VERSION',VERSION),'text/html; charset=utf-8')
        if p=='/api/health':return self.sendx(200,json.dumps({'ok':True,'version':VERSION,'time':now()}))
        if p=='/api/deep':return self.sendx(202,json.dumps({'job':start_deep()}))
        tests={'getworkmode':('getWorkMode',{}),'setvacuum':('setWorkMode',{'mode':1}),'setboth':('setWorkMode',{'mode':0}),'getworkstate':('getWorkState',{}),'cleanv2':('clean_V2',{'act':'start','content':{'type':'auto'}}),'stopv2':('clean_V2',{'act':'stop'}),'start':(None,None),'stop':(None,None),'dock':(None,None)}
        if p.startswith('/api/lab/'):
            a=p.rsplit('/',1)[-1]
            if a in tests:
                c,pa=tests[a]
                try:r=run_lab(a,c,pa,{'start':'start','stop':'stop','dock':'return_to_base'}.get(a))
                except Exception as e:r={'ok':False,'error':str(e)}
                return self.sendx(200,json.dumps(r,indent=2,default=str))
        m=re.fullmatch(r'/api/job/([A-Za-z0-9_-]+)',p)
        if m:
            with LOCK:x=dict(JOBS.get(m.group(1),{'status':'not_found'}))
            return self.sendx(200,json.dumps(x,default=str))
        m=re.fullmatch(r'/api/download/([A-Za-z0-9_-]+)',p)
        if m:
            with LOCK:x=JOBS.get(m.group(1))
            if not x or x.get('status')!='complete':return self.sendx(404,json.dumps({'error':'not ready'}))
            q=Path(x['file'])
            if not q.is_file():return self.sendx(404,json.dumps({'error':'diagnostic file missing'}))
            return self.sendx(200,q.read_bytes(),'application/zip',q.name)
        if p=='/api/diagnostic':return self.sendx(200,json.dumps(snapshot(),indent=2,default=str))
        if p=='/api/core-inspection-script':return self.sendx(200,core_inspection_script(),'text/plain')
        return self.sendx(404,json.dumps({'error':'not found'}))
    def do_POST(self):
        if self.path.split('?',1)[0]=='/api/deep':return self.sendx(202,json.dumps({'job':start_deep()}))
        return self.sendx(404,json.dumps({'error':'not found'}))
    def log_message(self,*a):pass

if __name__=='__main__':ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
