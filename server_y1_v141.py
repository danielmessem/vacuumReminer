#!/usr/bin/env python3
import json,re,subprocess,zipfile,shutil,hashlib
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
VERSION='1.4.1';PORT=8099;SHARE=Path('/share');HA=Path('/homeassistant');CC=HA/'custom_components';CUSTOM=CC/'ecovacs';BACKUP_ROOT=HA/'ecovacs_doctor_backups'
MATCH=re.compile(r'ecovacs|deebot|beepbop|cqyi87|get_static_device_info|device verification|1013|update to the latest version|config_entries|30000|10000|p2p|mqtt',re.I)
SECRET=re.compile(r'(?i)(password|token|access_token|refresh_token|api_key|secret)(["\']?\s*[:=]\s*["\']?)[^,\s}\]]+');EMAIL=re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')
def redact(s):return SECRET.sub(r'\1\2<redacted>',EMAIL.sub('<redacted-email>',str(s)))
def docker(cmd,timeout=15):
 try:p=subprocess.run(['docker']+cmd,capture_output=True,text=True,timeout=timeout);return p.returncode,p.stdout,p.stderr
 except Exception as e:return 99,'',str(e)
def find_core():
 rc,o,e=docker(['ps','--format','{{.ID}}\t{{.Names}}']);r=[]
 for line in o.splitlines():
  x=line.split('\t',1)
  if len(x)==2 and 'homeassistant' in x[1].lower():r.append(x)
 return r
def core_exec(args,timeout=15):
 c=find_core()
 if not c:return {'ok':False,'error':'Home Assistant Core container not found'}
 rc,o,e=docker(['exec',c[0][0]]+args,timeout);return {'ok':rc==0,'stdout':redact(o),'stderr':redact(e),'rc':rc}
def snapshot(minutes='30m'):
 c=find_core();r={'core_candidates':[{'id':x[0],'name':x[1]} for x in c],'matched':[]}
 if not c:r['error']='Core container not found';return r
 rc,o,e=docker(['logs','--since',minutes,c[0][0]],30);raw=(o+e).splitlines();r['matched']=[redact(x) for x in raw if MATCH.search(x)][-12000:];return r
def folders():
 return {'active':CUSTOM.is_dir(),'legacy_disabled':[str(p) for p in sorted(CC.glob('ecovacs.disabled-*'))] if CC.exists() else [],'quarantined':[str(p) for p in sorted(BACKUP_ROOT.glob('ecovacs-*'),reverse=True)] if BACKUP_ROOT.exists() else []}
def custom_info():
 r={'present':CUSTOM.is_dir(),'path':str(CUSTOM),'manifest':None,'files':[]};r.update(folders())
 if CUSTOM.is_dir():
  m=CUSTOM/'manifest.json'
  if m.exists():
   try:r['manifest']=json.loads(m.read_text(errors='replace'))
   except Exception as e:r['manifest_error']=redact(e)
  for p in sorted(CUSTOM.rglob('*')):
   if p.is_file():
    try:r['files'].append({'path':str(p.relative_to(CUSTOM)),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    except:pass
 return r
def environment():return {'python':core_exec(['python','--version']),'ha_version':core_exec(['python','-c','from homeassistant.const import __version__;print(__version__)']),'deebot_client':core_exec(['python','-c','import importlib.metadata as m;print(m.version("deebot-client"))']),'ecovacs_module':core_exec(['python','-c','import homeassistant.components.ecovacs as e;print(e.__file__)'])}
def classify(lines,ci):
 j='\n'.join(lines).lower();f=[]
 if ci['active'] or ci['legacy_disabled']:f.append({'severity':'HIGH','code':'CUSTOM_COMPONENT_STILL_DISCOVERABLE','meaning':'An Ecovacs custom integration or renamed copy still exists under custom_components and can still be discovered by Home Assistant.','action':'Use Quarantine custom Ecovacs, then restart Core.'})
 if "unable to import component: no module named 'custom_components.ecovacs'" in j:f.append({'severity':'HIGH','code':'STALE_CUSTOM_DISCOVERY','meaning':'Home Assistant startup still classified Ecovacs as a custom integration even though the ecovacs folder name changed.','action':'Move all Ecovacs copies completely outside custom_components and restart.'})
 if 'get_static_device_info' in j:f.append({'severity':'HIGH','code':'STATIC_DEVICE_INFO_FAILURE','meaning':'Device discovery fails while resolving static Ecovacs device metadata.','action':'Retest after custom integration is fully quarantined.'})
 if 'please update to the latest version to continue' in j or "'1013'" in j:f.append({'severity':'HIGH','code':'ECOVACS_1013','meaning':'Ecovacs rejected the client version.','action':'Use current Home Assistant/deebot-client.'})
 if 'error setting up entry' in j and 'ecovacs' in j:f.append({'severity':'HIGH','code':'SETUP_FAILURE','meaning':'The Ecovacs config entry is failing during setup.','action':'Capture the native integration traceback after quarantine.'})
 if not f:f.append({'severity':'INFO','code':'NO_KNOWN_SIGNATURE','meaning':'No known signature found in recent Core logs.','action':'Reproduce the failure and run diagnosis again.'})
 return f
def diagnose():
 s=snapshot();ci=custom_info();r={'version':VERSION,'generated':datetime.now().isoformat(),'environment':environment(),'custom_component':ci,'findings':classify(s['matched'],ci),'matched_logs':s['matched'],'core_candidates':s.get('core_candidates',[])};SHARE.mkdir(parents=True,exist_ok=True);p=SHARE/f'deebot-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip'
 with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('REPORT.json',json.dumps(r,indent=2,default=str));z.writestr('MATCHED_CORE_LOG.txt','\n'.join(s['matched']))
 r['file']=str(p);return r
def quarantine():
 BACKUP_ROOT.mkdir(parents=True,exist_ok=True);moved=[]
 candidates=[]
 if CUSTOM.exists():candidates.append(CUSTOM)
 if CC.exists():candidates += list(CC.glob('ecovacs.disabled-*'))
 for src in candidates:
  dest=BACKUP_ROOT/f'ecovacs-{datetime.now():%Y%m%d-%H%M%S-%f}-{src.name}'
  shutil.move(str(src),str(dest));moved.append({'from':str(src),'to':str(dest)})
 return {'ok':True,'moved':moved,'message':'All Ecovacs custom integration copies were moved completely outside custom_components. Restart Home Assistant Core next.' if moved else 'No Ecovacs custom integration copies found under custom_components.'}
def restore():
 if CUSTOM.exists():return {'ok':False,'message':'An active custom Ecovacs directory already exists.'}
 if not BACKUP_ROOT.exists():return {'ok':False,'message':'No quarantine backup folder exists.'}
 b=sorted(BACKUP_ROOT.glob('ecovacs-*'),reverse=True)
 if not b:return {'ok':False,'message':'No quarantined Ecovacs backup found.'}
 shutil.move(str(b[0]),str(CUSTOM));return {'ok':True,'message':'Newest quarantined custom Ecovacs integration restored to custom_components/ecovacs.'}
def restart():
 c=find_core()
 if not c:return {'ok':False,'message':'Core container not found'}
 rc,o,e=docker(['restart',c[0][0]],30);return {'ok':rc==0,'message':'Restart requested' if rc==0 else redact(e)}
HTML=f'''<!doctype html><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{{font-family:system-ui;max-width:1050px;margin:24px auto;padding:0 18px;background:#111827;color:#e5e7eb}}button{{padding:11px 14px;margin:5px;border:0;border-radius:8px;font-weight:650}}.p{{background:#2563eb;color:white}}.w{{background:#f59e0b}}.d{{background:#ef4444;color:white}}.s{{background:#4b5563;color:white}}pre{{background:#030712;padding:14px;white-space:pre-wrap;max-height:650px;overflow:auto;border-radius:8px}}.card{{background:#1f2937;padding:15px;border-radius:12px;margin:12px 0}}</style><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>{VERSION}</b></p><div class="card"><button class="p" onclick="go('./api/diagnose')">Run full diagnosis</button><button class="w" onclick="ask('./api/quarantine','Move ALL custom Ecovacs copies outside custom_components? A backup will be retained.')">Quarantine custom Ecovacs</button><button class="s" onclick="ask('./api/restore','Restore newest quarantined Ecovacs backup?')">Restore custom Ecovacs</button><button class="d" onclick="ask('./api/restart','Restart Home Assistant Core now?')">Restart Core</button></div><pre id="o">Ready.</pre><script>async function go(u){{o.textContent='Working…';try{{let r=await fetch(u,{{method:'POST'}});o.textContent=JSON.stringify(await r.json(),null,2)}}catch(e){{o.textContent=String(e)}}}}function ask(u,m){{if(confirm(m))go(u)}}</script>'''
class H(BaseHTTPRequestHandler):
 def x(self,c,b,ct='application/json'):
  if isinstance(b,str):b=b.encode();self.send_response(c);self.send_header('Content-Type',ct);self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)
 def do_GET(self):return self.x(200,HTML,'text/html; charset=utf-8') if self.path.split('?',1)[0] in ('','/') else self.x(404,json.dumps({'error':'not found'}))
 def do_POST(self):
  p=self.path.split('?',1)[0]
  try:
   if p=='/api/diagnose':r=diagnose()
   elif p=='/api/quarantine':r=quarantine()
   elif p=='/api/restore':r=restore()
   elif p=='/api/restart':r=restart()
   else:return self.x(404,json.dumps({'error':'not found'}))
   return self.x(200,json.dumps(r,indent=2,default=str))
  except Exception as e:return self.x(500,json.dumps({'error':redact(e)}))
 def log_message(self,*a):pass
ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
