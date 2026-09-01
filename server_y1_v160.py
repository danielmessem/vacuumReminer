#!/usr/bin/env python3
import json,os,re,shutil,subprocess,urllib.request,zipfile
from datetime import datetime,timedelta
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
VERSION="1.7.0";PORT=8099;HA=Path('/homeassistant');SHARE=Path('/share');CC=HA/'custom_components';CUSTOM=CC/'ecovacs';CLIENT_BACKUP_ROOT=HA/'ecovacs_doctor_client_backups';PROFILE_PATH=Path('/app/cqyi87_profile.py');OBS_FILE=SHARE/'deebot-y1pro-observations.jsonl';ACTIVE_FILE=SHARE/'deebot-y1pro-active-observation.json'
MATCH=re.compile(r'ecovacs|deebot|beepbop|cqyi87|30000|mqtt|capabilities|clean_V2|setSpeed|BatteryEvent|StateEvent|PositionsEvent|MapTraceEvent|FanSpeedEvent|Error while setting up ecovacs',re.I);TELEMETRY_MATCH=re.compile(r'30000|Received PUBLISH|Got message: topic=|Unknown message|BatteryEvent|StateEvent|PositionsEvent|MapTraceEvent|FanSpeedEvent|AvailabilityEvent|clean_V2|setSpeed|getBattery|getPos|getMapTrace|getChargeState|getWorkState|40001|40009|40011|40013|10000|10001',re.I);STATE_MATCH=re.compile(r'10000|BatteryEvent|StateEvent|chargeStatus|pauseSwitch|smartClean|goCharge|status.?idle',re.I)
def now_iso():return datetime.now().astimezone().isoformat()
def redact(v):
 s=str(v);s=re.sub(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b','<redacted-email>',s);s=re.sub(r'\b[0-9a-fA-F]{8}-[0-9a-fA-F-]{27,36}\b','<redacted-device-id>',s);s=re.sub(r'(?i)(accessToken|refreshToken|authCode|token|api_key|secret)([\'\" ]*[:=][\'\" ]*)[^,\'\"\s}]+',r'\1\2<redacted>',s);return s
def docker(a,t=35):
 try:p=subprocess.run(['docker']+a,capture_output=True,text=True,timeout=t);return p.returncode,p.stdout,p.stderr
 except Exception as e:return 99,'',str(e)
def core():
 _,out,_=docker(['ps','--format','{{.ID}}\t{{.Names}}'])
 for l in out.splitlines():
  p=l.split('\t',1)
  if len(p)==2 and 'homeassistant' in p[1].lower():return p[0],p[1]
 return None,None
def core_exec(a,t=30):
 cid,_=core()
 if not cid:return {'ok':False,'error':'Home Assistant Core container not found'}
 rc,out,err=docker(['exec',cid]+a,t);return {'ok':rc==0,'stdout':redact(out),'stderr':redact(err),'rc':rc}
def ha_api(path='/api/states'):
 token=os.environ.get('SUPERVISOR_TOKEN')
 if not token:return {'ok':False,'error':'SUPERVISOR_TOKEN unavailable'}
 try:
  req=urllib.request.Request('http://supervisor/core'+path,headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
  with urllib.request.urlopen(req,timeout=12) as r:return {'ok':True,'data':json.loads(r.read().decode())}
 except Exception as e:return {'ok':False,'error':redact(e)}
def ha_vacuum_snapshot():
 r=ha_api('/api/states')
 if not r.get('ok'):return r
 rows=[]
 safe_attrs=('friendly_name','battery_level','battery_icon','fan_speed','fan_speed_list','supported_features','status')
 for item in r.get('data',[]):
  eid=str(item.get('entity_id',''))
  if not eid.startswith('vacuum.'):continue
  attrs=item.get('attributes') or {}
  rows.append({'entity_id':eid,'state':item.get('state'),'attributes':{k:attrs.get(k) for k in safe_attrs if k in attrs},'last_changed':item.get('last_changed'),'last_updated':item.get('last_updated')})
 return {'ok':True,'entities':rows}
def client_paths():
 r=core_exec(['python','-c','import pathlib,deebot_client;p=pathlib.Path(deebot_client.__file__).parent;print(p);print(p/"hardware"/"cqyi87.py")']);x=[i.strip() for i in r.get('stdout','').splitlines() if i.strip()];return {'ok':bool(r.get('ok') and len(x)>=2),'package':x[0] if x else None,'target':x[1] if len(x)>1 else None,'detail':r}
def patch_status():
 p=client_paths()
 if not p['ok']:return p
 r=core_exec(['sh','-c',f"if [ -f '{p['target']}' ]; then grep 'Y1PRO_PATCH_VERSION' '{p['target']}' || true; else echo MISSING; fi"]);d=r.get('stdout','').strip();return {'ok':True,'target':p['target'],'installed':'Y1PRO_PATCH_VERSION' in d,'detail':d}
def install_patch():
 p=client_paths()
 if not p['ok']:return {'ok':False,'message':'Could not locate deebot-client','detail':p}
 cid,_=core();target=p['target'];CLIENT_BACKUP_ROOT.mkdir(parents=True,exist_ok=True);stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f');backup=CLIENT_BACKUP_ROOT/f'cqyi87-{stamp}.py';exists=core_exec(['sh','-c',f"test -f '{target}'"])
 if exists.get('ok'):docker(['cp',f'{cid}:{target}',str(backup)])
 rc,_,err=docker(['cp',str(PROFILE_PATH),f'{cid}:{target}'])
 if rc:return {'ok':False,'message':'Copy failed','error':redact(err)}
 verify=core_exec(['python','-c',"import importlib;importlib.invalidate_caches();m=importlib.import_module('deebot_client.hardware.cqyi87');i=m.get_device_info();c=i.capabilities;print(m.Y1PRO_PATCH_VERSION);print(i.data_type);print(c.device_type);print('battery_enabled='+str(c.battery is not None));print('life_span_types='+str(len(c.life_span.types)));print('stats_safe='+str(c.stats is not None))"])
 return {'ok':verify.get('ok',False),'message':'Y1 PRO cqyi87 profile installed. Restart Core next.' if verify.get('ok') else 'Validation failed','target':target,'validation':verify}
def rollback():
 p=client_paths();items=sorted(CLIENT_BACKUP_ROOT.glob('cqyi87-*.py'),reverse=True)
 if not p.get('ok') or not items:return {'ok':False,'message':'No backup found'}
 cid,_=core();rc,_,err=docker(['cp',str(items[0]),f"{cid}:{p['target']}"]);return {'ok':rc==0,'message':'Previous cqyi87.py restored. Restart Core next.','error':redact(err)}
def quarantine():
 moved=[];root=HA/'ecovacs_doctor_backups';root.mkdir(parents=True,exist_ok=True)
 if CUSTOM.exists():dst=root/f"ecovacs-{datetime.now():%Y%m%d-%H%M%S-%f}";shutil.move(str(CUSTOM),str(dst));moved.append({'from':str(CUSTOM),'to':str(dst)})
 return {'ok':True,'moved':moved}
def restart():
 cid,_=core();rc,_,err=docker(['restart',cid],40) if cid else (1,'','Core not found');return {'ok':rc==0,'message':'Restart requested' if rc==0 else redact(err)}
def get_logs(s='30m'):
 cid,name=core();_,out,err=docker(['logs','--since',s,cid],45) if cid else (1,'','');return cid,name,(out+err).splitlines()
def load_observations(h=24):
 if not OBS_FILE.exists():return []
 rows=[]
 for l in OBS_FILE.read_text(errors='replace').splitlines():
  try:rows.append(json.loads(l))
  except:pass
 return rows[-100:]
def observation_start(a):SHARE.mkdir(parents=True,exist_ok=True);r={'started_at':now_iso(),'attempted_action':str(a or 'unspecified')[:80]};ACTIVE_FILE.write_text(json.dumps(r));return {'ok':True,'message':'Observation capture started',**r}
def observation_finish(result,notes=''):
 if not ACTIVE_FILE.exists():return {'ok':False,'message':'No active observation.'}
 r=json.loads(ACTIVE_FILE.read_text());r.update(finished_at=now_iso(),physical_result=str(result)[:100],notes=str(notes)[:500]);_,_,raw=get_logs('3m');r['ha_vacuum_snapshot']=ha_vacuum_snapshot();r['diagnostic_log_lines']=[redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-300:]
 with OBS_FILE.open('a') as f:f.write(json.dumps(r)+'\n')
 ACTIVE_FILE.unlink(missing_ok=True);return {'ok':True,'message':'Observation saved','observation':r}
def capture_telemetry():
 cid,name,raw=get_logs('20m');selected=[redact(x) for x in raw if TELEMETRY_MATCH.search(x)][-5000:];state_lines=[redact(x) for x in raw if STATE_MATCH.search(x)][-1000:];stamp=datetime.now().strftime('%Y%m%d-%H%M%S');out=SHARE/f'deebot-y1pro-telemetry-{stamp}.zip';report={'version':VERSION,'generated':now_iso(),'window':'20m','ha_vacuum_snapshot':ha_vacuum_snapshot(),'observations':load_observations(),'state_battery_timeline':state_lines,'payload_lines':selected}
 with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('TELEMETRY_REPORT.json',json.dumps(report,indent=2));z.writestr('STATE_BATTERY_TIMELINE.txt','\n'.join(state_lines));z.writestr('PAYLOAD_LINES.txt','\n'.join(selected))
 report['file']=str(out);return report
def diagnose():
 cid,name,raw=get_logs();logs=[redact(x) for x in raw if MATCH.search(x)][-12000:];state_lines=[redact(x) for x in raw if STATE_MATCH.search(x)][-1000:]
 return {'version':VERSION,'generated':now_iso(),'ha_vacuum_snapshot':ha_vacuum_snapshot(),'state_battery_timeline':state_lines,'environment':{'core_container':{'found':bool(cid),'name':name},'ha_version':core_exec(['python','-c','import homeassistant.const as c;print(c.__version__)']) if cid else None,'deebot_client':core_exec(['python','-c',"import importlib.metadata as m;print(m.version('deebot-client'))"]) if cid else None},'y1pro_patch':patch_status(),'observations':load_observations(),'logs':logs}
HTML=f'''<!doctype html><html><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>DEEBOT Y1 PRO</title><style>:root{{--bg:#091119;--p:#121c26;--line:#273747;--text:#edf5fb;--muted:#91a7b9;--blue:#3da2ff;--green:#57d58c}}*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(#081019,#0d1620);color:var(--text);font-family:system-ui;min-height:100vh}}.wrap{{max-width:1050px;margin:auto;padding:28px 18px}}header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}}h1{{margin:0;font-size:30px}}.sub,p{{color:var(--muted)}}.badge{{background:#102b40;color:#8ed0ff;border:1px solid #285d84;padding:7px 11px;border-radius:999px;font-weight:700}}.grid{{display:grid;grid-template-columns:1.15fr .85fr;gap:16px}}.card{{background:var(--p);border:1px solid var(--line);border-radius:18px;padding:20px;box-shadow:0 15px 35px #0005}}.full{{grid-column:1/-1}}h2{{font-size:17px;margin:0 0 7px}}label{{display:block;font-size:12px;font-weight:700;margin:12px 0 6px;color:#bed0dd}}select,input{{width:100%;background:#0b141c;color:white;border:1px solid #324658;border-radius:10px;padding:11px}}button{{background:#1a2936;color:white;border:1px solid #385064;border-radius:10px;padding:10px 13px;margin:5px 4px 5px 0;font-weight:700;cursor:pointer}}button:hover{{border-color:#5d829f}}.primary{{background:#1684e5;border-color:#4aa9ff}}.good{{background:#163927;border-color:#34734d;color:#9ae5b7}}.warn{{background:#3b2d16;border-color:#70572c;color:#ffdb93}}.danger{{background:#421d23;border-color:#78333d;color:#ffb0b8}}pre{{background:#070c11;border:1px solid #1e2c38;border-radius:13px;padding:15px;min-height:150px;max-height:480px;overflow:auto;white-space:pre-wrap;color:#bed3e2}}.actions{{display:grid;grid-template-columns:1fr 1fr;gap:6px}}@media(max-width:760px){{.grid{{grid-template-columns:1fr}}.full{{grid-column:auto}}.actions{{grid-template-columns:1fr}}}}</style></head><body><div class=wrap><header><div><h1>DEEBOT Y1 PRO</h1><div class=sub>Diagnostics & compatibility patch manager</div></div><div class=badge>v{VERSION}</div></header><main class=grid><section class=card><h2>Guided protocol observation</h2><p>Record an action and what the robot physically does. Relevant logs and the live HA vacuum state are captured automatically.</p><label>Attempted action</label><select id=attempt><option>Start cleaning</option><option>Pause</option><option>Resume</option><option>Return to dock</option><option>Clean a specific room</option><option>Fan speed - Quiet</option><option>Fan speed - Normal</option><option>Fan speed - Max</option><option>Other official app action</option></select><button class=primary onclick=startObs()>Start capture</button><label>Physical result</label><select id=result><option>Started cleaning</option><option>Paused</option><option>Resumed cleaning</option><option>Returned to dock</option><option>Cleaned selected room</option><option>Changed fan speed</option><option>No physical response</option><option>Other / unexpected</option></select><label>Notes</label><input id=notes placeholder="Optional notes"><button class=good onclick=finishObs()>Save result</button></section><section class=card><h2>Tools</h2><p>Diagnosis now includes live Home Assistant vacuum state plus a focused state/battery timeline.</p><div class=actions><button class=primary onclick=call('diagnose')>Run diagnosis</button><button onclick=call('telemetry')>Capture telemetry</button><button onclick=call('install')>Install / Repair Patch</button><button class=warn onclick=call('rollback')>Rollback Patch</button><button class=warn onclick=call('quarantine')>Quarantine Custom Ecovacs</button><button class=danger onclick=call('restart')>Restart Core</button></div></section><section class="card full"><h2>Output</h2><pre id=o>Ready.</pre></section></main></div><script>async function post(p,b={{}}){{let r=await fetch(p,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(b)}});return r.json()}}async function call(x){{o.textContent='Working…';o.textContent=JSON.stringify(await post('./api/'+x),null,2)}}async function startObs(){{o.textContent=JSON.stringify(await post('./api/observe/start',{{attempted_action:attempt.value}}),null,2)}}async function finishObs(){{o.textContent=JSON.stringify(await post('./api/observe/finish',{{physical_result:result.value,notes:notes.value}}),null,2)}}</script></body></html>'''
class H(BaseHTTPRequestHandler):
 def sendj(self,x,s=200):b=json.dumps(x,indent=2).encode();self.send_response(s);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_GET(self):b=HTML.encode();self.send_response(200);self.send_header('Content-Type','text/html');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
 def do_POST(self):
  p=self.path.rstrip('/');n=int(self.headers.get('Content-Length','0') or 0)
  try:b=json.loads(self.rfile.read(n) or b'{}')
  except:b={}
  funcs={'diagnose':diagnose,'telemetry':capture_telemetry,'install':install_patch,'rollback':rollback,'quarantine':quarantine,'restart':restart}
  for k,f in funcs.items():
   if p.endswith('/api/'+k):return self.sendj(f())
  if p.endswith('/api/observe/start'):return self.sendj(observation_start(b.get('attempted_action')))
  if p.endswith('/api/observe/finish'):return self.sendj(observation_finish(b.get('physical_result'),b.get('notes')))
  self.sendj({'ok':False},404)
 def log_message(self,fmt,*args):pass
if __name__=='__main__':SHARE.mkdir(parents=True,exist_ok=True);print(f'DEEBOT Y1 PRO Diagnostics {VERSION} on :{PORT}',flush=True);ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
