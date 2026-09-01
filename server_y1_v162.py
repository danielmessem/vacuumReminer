#!/usr/bin/env python3
import json, os, re, shutil, subprocess, urllib.error, urllib.request, zipfile
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION="1.6.2"; PORT=8099
HA=Path('/homeassistant'); SHARE=Path('/share'); CC=HA/'custom_components'; CUSTOM=CC/'ecovacs'
CLIENT_BACKUP_ROOT=HA/'ecovacs_doctor_client_backups'; PROFILE_PATH=Path('/app/cqyi87_profile.py')
OBS_FILE=SHARE/'deebot-y1pro-observations.jsonl'; ACTIVE_FILE=SHARE/'deebot-y1pro-active-observation.json'; ENTITY_FILE=SHARE/'deebot-y1pro-selected-entity.txt'
SUPERVISOR='http://supervisor/core/api'
TELEMETRY_MATCH=re.compile(r'ecovacs|deebot|cqyi87|mqtt|Received PUBLISH|Got message: topic=|Unknown message|BatteryEvent|StateEvent|FanSpeedEvent|AvailabilityEvent|clean_V2|setSpeed|40001|40009|40011|40013|10000|10001|onFwBuryPoint',re.I)
EMAIL=re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b'); UUID=re.compile(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}\b')
def now_iso(): return datetime.now().astimezone().isoformat()
def redact(v): return UUID.sub('<redacted-device-id>',EMAIL.sub('<redacted-email>',str(v)))
def docker(args,timeout=35):
    try:
        p=subprocess.run(['docker']+args,capture_output=True,text=True,timeout=timeout); return p.returncode,p.stdout,p.stderr
    except Exception as e: return 99,'',str(e)
def core():
    _,out,_=docker(['ps','--format','{{.ID}}\t{{.Names}}'])
    for line in out.splitlines():
        p=line.split('\t',1)
        if len(p)==2 and 'homeassistant' in p[1].lower(): return p[0],p[1]
    return None,None
def core_exec(args,timeout=30):
    cid,_=core()
    if not cid:return {'ok':False,'error':'Home Assistant Core container not found'}
    rc,out,err=docker(['exec',cid]+args,timeout); return {'ok':rc==0,'stdout':redact(out),'stderr':redact(err),'rc':rc}
def client_paths():
    r=core_exec(['python','-c','import pathlib,deebot_client;p=pathlib.Path(deebot_client.__file__).parent;print(p);print(p/"hardware"/"cqyi87.py")']); lines=[x.strip() for x in r.get('stdout','').splitlines() if x.strip()]
    return {'ok':bool(r.get('ok') and len(lines)>=2),'target':lines[1] if len(lines)>1 else None}
def patch_status():
    p=client_paths()
    if not p['ok']: return p
    r=core_exec(['sh','-c',f"grep 'Y1PRO_PATCH_VERSION' '{p['target']}' 2>/dev/null || true"]); d=r.get('stdout','').strip(); return {'ok':True,'installed':'Y1PRO_PATCH_VERSION' in d,'detail':d}
def install_patch():
    p=client_paths()
    if not p['ok'] or not PROFILE_PATH.exists(): return {'ok':False,'message':'Could not locate client/profile'}
    cid,_=core(); target=p['target']; CLIENT_BACKUP_ROOT.mkdir(parents=True,exist_ok=True); backup=CLIENT_BACKUP_ROOT/f"cqyi87-{datetime.now():%Y%m%d-%H%M%S-%f}.py"
    if core_exec(['sh','-c',f"test -f '{target}'"]).get('ok'): docker(['cp',f'{cid}:{target}',str(backup)])
    rc,_,err=docker(['cp',str(PROFILE_PATH),f'{cid}:{target}']);
    if rc:return {'ok':False,'message':'Copy failed','error':redact(err)}
    v=core_exec(['python','-c',"import importlib;importlib.invalidate_caches();m=importlib.import_module('deebot_client.hardware.cqyi87');print(m.Y1PRO_PATCH_VERSION)"])
    return {'ok':v.get('ok',False),'message':'Profile installed. Restart Core next.' if v.get('ok') else 'Validation failed','validation':v}
def rollback(): return {'ok':False,'message':'Use previous diagnostic release rollback if needed'}
def quarantine():
    moved=[]; root=HA/'ecovacs_doctor_backups'; root.mkdir(parents=True,exist_ok=True)
    if CUSTOM.exists():
        dst=root/f"ecovacs-{datetime.now():%Y%m%d-%H%M%S}"; shutil.move(str(CUSTOM),str(dst)); moved.append(str(dst))
    return {'ok':True,'moved':moved}
def restart():
    cid,_=core();
    if not cid:return {'ok':False,'message':'Core not found'}
    rc,_,err=docker(['restart',cid],40); return {'ok':rc==0,'message':'Restart requested' if rc==0 else redact(err)}
def get_logs(since='30m'):
    cid,name=core();
    if not cid:return None,None,[]
    _,out,err=docker(['logs','--since',since,cid],45); return cid,name,(out+err).splitlines()
def ha_api(path,method='GET',payload=None):
    token=os.environ.get('SUPERVISOR_TOKEN')
    if not token:return {'ok':False,'error':'SUPERVISOR_TOKEN unavailable'}
    data=json.dumps(payload).encode() if payload is not None else None
    req=urllib.request.Request(SUPERVISOR+path,data=data,method=method,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=20) as resp:
            raw=resp.read().decode('utf-8','replace'); return {'ok':True,'status':resp.status,'data':json.loads(raw) if raw else None}
    except Exception as e:return {'ok':False,'error':redact(e)}
def vacuum_candidates():
    r=ha_api('/states'); out=[]
    if not r.get('ok') or not isinstance(r.get('data'),list): return out
    for x in r['data']:
        eid=str(x.get('entity_id',''))
        if not eid.startswith('vacuum.'): continue
        a=x.get('attributes') or {}; out.append({'entity_id':eid,'name':a.get('friendly_name') or eid,'state':x.get('state')})
    return out
def selected_entity(requested=None):
    candidates=vacuum_candidates(); ids={x['entity_id'] for x in candidates}
    if requested and requested in ids:
        ENTITY_FILE.write_text(requested); return requested
    if ENTITY_FILE.exists():
        s=ENTITY_FILE.read_text().strip()
        if s in ids:return s
    for c in candidates:
        txt=(c['entity_id']+' '+str(c['name'])).lower()
        if any(k in txt for k in ('beepbop','ecovacs','deebot')):
            ENTITY_FILE.write_text(c['entity_id']); return c['entity_id']
    if len(candidates)==1:
        ENTITY_FILE.write_text(candidates[0]['entity_id']); return candidates[0]['entity_id']
    return None
ACTION_SERVICE={'Start cleaning':'start','Pause':'pause','Resume':'start','Return to dock':'return_to_base','Stop cleaning':'stop'}
def observation_start(action,execute=False,entity_id=None):
    SHARE.mkdir(parents=True,exist_ok=True); action=str(action or 'unspecified')[:80]; rec={'started_at':now_iso(),'attempted_action':action,'initiated_by':'diagnostics_addon' if execute else 'external'}; ACTIVE_FILE.write_text(json.dumps(rec,indent=2))
    if not execute:return {'ok':True,'message':'Observation capture started',**rec}
    service=ACTION_SERVICE.get(action)
    if not service:return {'ok':False,'message':'Action cannot be sent automatically yet'}
    entity=selected_entity(entity_id)
    if not entity:
        return {'ok':False,'message':'Select the vacuum entity first','candidates':vacuum_candidates()}
    rec['entity_id']=entity; rec['ha_service']='vacuum.'+service; rec['command_sent_at']=now_iso(); call=ha_api(f'/services/vacuum/{service}','POST',{'entity_id':entity}); rec['command_result']={'ok':call.get('ok',False),'status':call.get('status'),'error':call.get('error','')}; ACTIVE_FILE.write_text(json.dumps(rec,indent=2))
    return {'ok':call.get('ok',False),'message':'Command sent. What did the robot physically do?' if call.get('ok') else 'HA service call failed','entity_id':entity,'ha_service':rec['ha_service'],'command_result':rec['command_result']}
def observation_finish(result,notes=''):
    if not ACTIVE_FILE.exists():return {'ok':False,'message':'No active observation'}
    rec=json.loads(ACTIVE_FILE.read_text()); rec['finished_at']=now_iso(); rec['physical_result']=str(result or '')[:100]; rec['notes']=str(notes or '')[:500]; _,_,raw=get_logs('3m'); rec['diagnostic_log_lines']=[redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-350:]
    with OBS_FILE.open('a',encoding='utf-8') as f:f.write(json.dumps(rec,ensure_ascii=False)+'\n')
    ACTIVE_FILE.unlink(missing_ok=True); return {'ok':True,'message':'Saved','observation':rec}
def load_observations(hours=24):
    if not OBS_FILE.exists():return []
    cutoff=datetime.now().astimezone()-timedelta(hours=hours); rows=[]
    for line in OBS_FILE.read_text(errors='replace').splitlines():
        try:
            r=json.loads(line); dt=datetime.fromisoformat(r.get('finished_at',r.get('started_at')))
            if dt>=cutoff:rows.append(r)
        except:pass
    return rows[-100:]
def capture_telemetry():
    cid,name,raw=get_logs('20m'); selected=[redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-5000:]; obs=load_observations(); out=SHARE/f"deebot-y1pro-telemetry-{datetime.now():%Y%m%d-%H%M%S}.zip"; report={'version':VERSION,'generated':now_iso(),'observations':obs,'matched_lines':selected}
    with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('TELEMETRY_REPORT.json',json.dumps(report,indent=2));z.writestr('USER_OBSERVATIONS.json',json.dumps(obs,indent=2));z.writestr('MATCHED_CORE_LOG.txt','\n'.join(selected))
    return {'ok':True,'file':str(out),'observations':len(obs)}
def diagnose(): return {'version':VERSION,'vacuum_candidates':vacuum_candidates(),'selected_entity':selected_entity(),'patch':patch_status(),'observations':load_observations()}

HTML="""<!doctype html><meta name=viewport content='width=device-width'><title>DEEBOT Y1 PRO Tools</title><style>body{font-family:system-ui;max-width:1000px;margin:24px auto;padding:0 18px;background:#111827;color:#e5e7eb}button,select,input{padding:12px 14px;margin:5px;border:0;border-radius:8px;font-weight:650}.p{background:#2563eb;color:white}.g{background:#16a34a;color:white}.card{border:1px solid #374151;border-radius:10px;padding:16px;margin:14px 0;background:#1f2937}select,input{background:#fff;color:#111827}pre{background:#030712;padding:14px;white-space:pre-wrap;max-height:600px;overflow:auto;border-radius:8px}.hint{color:#9ca3af}</style><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>1.6.2</b></p><div class=card><h2>One-click physical command test</h2><p class=hint>Select the Y1 PRO once, then choose an action. The add-on sends it and only asks what physically happened.</p><label>Vacuum: </label><select id=entity></select><button onclick='loadEntities()'>Refresh</button><br><select id=attempt><option>Start cleaning</option><option>Pause</option><option>Resume</option><option>Return to dock</option><option>Stop cleaning</option></select><button class=p onclick='runTest()'>Run command & capture</button><div id=answer style='display:none'><p><b>What did the robot physically do?</b></p><select id=result><option>Started cleaning</option><option>Paused</option><option>Resumed cleaning</option><option>Returned to dock</option><option>Stopped cleaning</option><option>No physical response</option><option>Other / unexpected</option></select><input id=notes placeholder='Optional note'><button class=g onclick='finishObs()'>Save result</button></div><p id=obs>Loading vacuum entities...</p></div><button onclick="go('./api/diagnose')">Run diagnosis</button><button onclick="go('./api/telemetry')">Export telemetry</button><pre id=o>Ready.</pre><script>async function post(u,b){let r=await fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:b?JSON.stringify(b):null});return await r.json()}async function loadEntities(){let j=await post('./api/entities');entity.innerHTML='';(j.candidates||[]).forEach(x=>{let op=document.createElement('option');op.value=x.entity_id;op.textContent=x.name+' ('+x.entity_id+') — '+x.state;if(j.selected_entity===x.entity_id)op.selected=true;entity.appendChild(op)});obs.textContent=entity.options.length?'Ready.':'No vacuum entities found.'}async function runTest(){answer.style.display='none';let j=await post('./api/test/run',{attempted_action:attempt.value,entity_id:entity.value});o.textContent=JSON.stringify(j,null,2);obs.textContent=j.message;if(j.ok)answer.style.display='block'}async function finishObs(){let j=await post('./api/observe/finish',{physical_result:result.value,notes:notes.value});o.textContent=JSON.stringify(j,null,2);obs.textContent=j.ok?'Saved. Choose the next action.':j.message;answer.style.display='none'}async function go(u){o.textContent=JSON.stringify(await post(u),null,2)}loadEntities()</script>"""
class Handler(BaseHTTPRequestHandler):
    def sendj(self,code,b,ctype='application/json'):
        if isinstance(b,str):b=b.encode(); self.send_response(code); self.send_header('Content-Type',ctype); self.send_header('Content-Length',str(len(b))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(b)
    def readj(self):
        try:n=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(n).decode()) if n else {}
        except:return {}
    def do_GET(self):
        if self.path.split('?',1)[0] in ('','/'):return self.sendj(200,HTML,'text/html; charset=utf-8')
        return self.sendj(404,json.dumps({'error':'not found'}))
    def do_POST(self):
        p=self.path.split('?',1)[0]; b=self.readj()
        if p=='/api/entities':r={'ok':True,'candidates':vacuum_candidates(),'selected_entity':selected_entity()}
        elif p=='/api/test/run':r=observation_start(b.get('attempted_action'),True,b.get('entity_id'))
        elif p=='/api/observe/finish':r=observation_finish(b.get('physical_result'),b.get('notes',''))
        elif p=='/api/diagnose':r=diagnose()
        elif p=='/api/telemetry':r=capture_telemetry()
        elif p=='/api/install':r=install_patch()
        elif p=='/api/quarantine':r=quarantine()
        elif p=='/api/restart':r=restart()
        else:return self.sendj(404,json.dumps({'error':'not found'}))
        return self.sendj(200,json.dumps(r,indent=2))
    def log_message(self,*args):pass
SHARE.mkdir(parents=True,exist_ok=True); ThreadingHTTPServer(('0.0.0.0',PORT),Handler).serve_forever()
