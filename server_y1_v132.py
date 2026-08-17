#!/usr/bin/env python3
import json,re,subprocess,threading,time,zipfile,os,signal
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
VERSION='1.3.2';PORT=8099;SHARE=Path('/share');JOBS={};LOCK=threading.Lock()
MATCH=re.compile(r'ecovacs|deebot|beepbop|cqyi87|CARTESIAN|clean_V2|setWorkMode|getWorkMode|getWorkState|workState|motionState|30000|10000|p2p|cmdName',re.I)

def docker_available():
    try:
        p=subprocess.run(['docker','version','--format','{{.ServerVersion}}'],capture_output=True,text=True,timeout=5)
        return {'ok':p.returncode==0,'version':p.stdout.strip(),'error':p.stderr.strip()}
    except Exception as e:return {'ok':False,'error':str(e)}

def find_core():
    names=[]
    try:
        p=subprocess.run(['docker','ps','--format','{{.ID}}\t{{.Names}}'],capture_output=True,text=True,timeout=5)
        for line in p.stdout.splitlines():
            parts=line.split('\t',1)
            if len(parts)==2 and ('homeassistant' in parts[1].lower() or parts[1].lower() in ('home-assistant','homeassistant')): names.append(parts)
    except Exception:pass
    return names

def snapshot():
    d=docker_available(); cores=find_core(); result={'docker':d,'core_candidates':[{'id':a,'name':b} for a,b in cores],'lines':[],'error':None}
    if not cores: result['error']='Home Assistant Core container not found via Docker API'; return result
    target=cores[0][0]
    try:
        p=subprocess.run(['docker','logs','--since','20m',target],capture_output=True,text=True,timeout=30)
        raw=p.stdout+p.stderr; result['lines']=raw.splitlines()[-20000:]; result['matched']=[x for x in result['lines'] if MATCH.search(x)][-12000:]; result['exit_code']=p.returncode
        if p.returncode!=0: result['error']=p.stderr.strip() or 'docker logs failed'
    except Exception as e: result['error']=str(e)
    return result

def analyse(lines):
    return {'10000_count':sum('10000' in x for x in lines),'30000_count':sum('30000' in x for x in lines),'clean_V2':[x for x in lines if 'clean_V2' in x][-200:],'work_mode':[x for x in lines if re.search(r'workMode|workState|motionState|getWorkState|setWorkMode',x,re.I)][-200:],'mqtt_p2p':[x for x in lines if re.search(r'mqtt|p2p',x,re.I)][-200:]}

def makezip(o):
    SHARE.mkdir(parents=True,exist_ok=True);p=SHARE/f"deebot-y1pro-protocol-{datetime.now():%Y%m%d-%H%M%S}.zip"
    with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('REPORT.json',json.dumps(o,indent=2,default=str));z.writestr('PROTOCOL_SUMMARY.txt',json.dumps(o['analysis'],indent=2));z.writestr('RAW_CORE_LOG.txt','\n'.join(o.get('raw',[])));z.writestr('DEEBOT_MATCHED_LOG.txt','\n'.join(o.get('matched',[])));z.writestr('SERVICE_CALLS.json',json.dumps(o['steps'],indent=2,default=str));z.writestr('README.txt',f'DEEBOT Y1 PRO Diagnostics v{VERSION}\n')
    return p

def newjob():
    j=datetime.now().strftime('%Y%m%d%H%M%S%f');
    with LOCK:JOBS[j]={'status':'running','percent':0,'message':'Starting','steps':[],'raw':[],'matched':[]}
    threading.Thread(target=worker,args=(j,),daemon=True).start();return j

def worker(j):
    try:
        base=snapshot()
        with LOCK:JOBS[j].update(percent=5,message='Docker/Core access: '+('OK' if base['docker']['ok'] else 'FAILED'))
        JOBS[j]['raw']=base['lines'];JOBS[j]['matched']=base['matched']
        with LOCK:JOBS[j].update(percent=15,message='Running protocol test')
        deadline=time.time()+90
        while time.time()<deadline:
            with LOCK:done=JOBS[j].get('finished')
            if done:break
            time.sleep(.5)
        with LOCK:JOBS[j].update(percent=85,message='Capturing final live Core logs')
        final=snapshot();
        allraw=(base['lines'][-5000:]+final['lines'][-15000:]);allmatch=(base['matched'][-3000:]+final['matched'][-12000:])
        o={'version':VERSION,'docker_access':final['docker'],'core_candidates':final['core_candidates'],'capture_error':final['error'],'steps':JOBS[j]['steps'],'raw':allraw,'matched':allmatch,'analysis':analyse(allmatch)}
        p=makezip(o)
        with LOCK:JOBS[j].update(status='complete',percent=100,message='Complete',file=str(p),analysis=o['analysis'])
    except Exception as e:
        with LOCK:JOBS[j].update(status='error',percent=100,message='ERROR: '+str(e))

HTML=f'''<!doctype html><meta name="viewport" content="width=device-width"><title>DEEBOT Y1 PRO Diagnostics</title><style>body{{font-family:system-ui;max-width:1000px;margin:25px auto;padding:0 18px}}button{{padding:12px 16px;border:1px solid #aaa;border-radius:8px;background:white}}pre{{background:#111;color:#eee;padding:12px;white-space:pre-wrap;max-height:600px;overflow:auto}}.bar{{height:18px;background:#ddd}}#fill{{height:100%;width:0%;background:#1976d2}}</style><h1>DEEBOT Y1 PRO Protocol Diagnostics</h1><p>Version <b>{VERSION}</b></p><button id="b" onclick="run()">Run Full Protocol Test & Generate File</button><div class="bar"><div id="fill"></div></div><p id="s">Ready</p><pre id="o">Press the button to start.</pre><script>
function H(){{try{{let e=window.top.document.querySelector('home-assistant');if(e&&e.hass)return e.hass}}catch(e){{}}try{{if(window.parent.hass)return window.parent.hass}}catch(e){{}}return null}}
async function call(name,data){{let h=H();if(!h||!h.callService)throw Error('Authenticated Home Assistant frontend connection unavailable');return h.callService('vacuum','send_command',{{entity_id:'vacuum.beepbop',command:name,params:data||{{}}}})}}
async function step(j,name,fn){{try{{let r=await fn();await fetch('./api/step/'+j,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,status:'ok',result:r||null,time:new Date().toISOString()}})}})}}catch(e){{await fetch('./api/step/'+j,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{name,status:'error',error:String(e),time:new Date().toISOString()}})}});throw e}}}}
async function run(){{let b=document.getElementById('b'),o=document.getElementById('o'),s=document.getElementById('s'),f=document.getElementById('fill');b.disabled=true;let j=(await fetch('./api/deep',{{method:'POST'}}).then(r=>r.json())).job;let poll=async()=>{{let x=await fetch('./api/job/'+j+'?x='+Date.now()).then(r=>r.json());f.style.width=x.percent+'%';s.textContent=x.percent+'% — '+x.message;o.textContent=(x.steps||[]).map(e=>e.name+': '+e.status+(e.error?' — '+e.error:'')).join('\\n');if(x.status==='complete'){{o.innerHTML+='\\n\\n<a href="./api/download/'+j+'">Download diagnostic ZIP</a>\\n\\n'+JSON.stringify(x.analysis||{{}},null,2);b.disabled=false}}else if(x.status==='error'){{o.textContent+='\\n'+x.message;b.disabled=false}}else setTimeout(poll,500)}};poll();try{{await step(j,'setWorkMode VACUUM',()=>call('setWorkMode',{{mode:1}}));await new Promise(r=>setTimeout(r,3000));await step(j,'getWorkMode',()=>call('getWorkMode'));await step(j,'getWorkState',()=>call('getWorkState'));await step(j,'clean_V2 START',()=>call('clean_V2',{{act:'start',content:{{type:'auto'}}}}));await new Promise(r=>setTimeout(r,10000));await step(j,'getWorkState after clean',()=>call('getWorkState'));await step(j,'clean_V2 STOP',()=>call('clean_V2',{{act:'stop'}}));await new Promise(r=>setTimeout(r,3000));await fetch('./api/finish/'+j,{{method:'POST'}})}}catch(e){{o.textContent+='\\nERROR: '+e;await fetch('./api/finish/'+j,{{method:'POST'}})}}}}
</script>'''

class Hdl(BaseHTTPRequestHandler):
 def sendx(self,c,b,ct='application/json',fn=None):
  if isinstance(b,str):b=b.encode();self.send_response(c);self.send_header('Content-Type',ct);self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');
  if fn:self.send_header('Content-Disposition',f'attachment; filename="{fn}"')
  self.end_headers();self.wfile.write(b)
 def do_GET(self):
  p=self.path.split('?',1)[0]
  if p in ('','/'):return self.sendx(200,HTML,'text/html; charset=utf-8')
  m=re.fullmatch(r'/api/job/([A-Za-z0-9_-]+)',p)
  if m:
   with LOCK:x=dict(JOBS.get(m.group(1),{'status':'not_found'}));x['steps']=list(x.get('steps',[]))
   return self.sendx(200,json.dumps(x))
  m=re.fullmatch(r'/api/download/([A-Za-z0-9_-]+)',p)
  if m:
   with LOCK:x=JOBS.get(m.group(1))
   if not x or x.get('status')!='complete':return self.sendx(404,json.dumps({'error':'not ready'}))
   q=Path(x['file']);return self.sendx(200,q.read_bytes(),'application/zip',q.name) if q.is_file() else self.sendx(404,json.dumps({'error':'file missing'}))
  return self.sendx(404,json.dumps({'error':'not found'}))
 def do_POST(self):
  p=self.path.split('?',1)[0]
  if p=='/api/deep':return self.sendx(200,json.dumps({'job':newjob()}))
  m=re.fullmatch(r'/api/step/([A-Za-z0-9_-]+)',p)
  if m:
   n=int(self.headers.get('Content-Length','0'));d=json.loads(self.rfile.read(n) or b'{}')
   with LOCK:JOBS.get(m.group(1),{}).setdefault('steps',[]).append(d)
   return self.sendx(200,json.dumps({'ok':True}))
  m=re.fullmatch(r'/api/finish/([A-Za-z0-9_-]+)',p)
  if m:
   with LOCK:
    if m.group(1) in JOBS:JOBS[m.group(1)]['finished']=True
   return self.sendx(200,json.dumps({'ok':True}))
  return self.sendx(404,json.dumps({'error':'not found'}))
 def log_message(self,*a):pass
ThreadingHTTPServer(('0.0.0.0',PORT),Hdl).serve_forever()
