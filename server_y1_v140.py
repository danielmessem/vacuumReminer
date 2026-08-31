#!/usr/bin/env python3
import json,re,subprocess,threading,time,zipfile,os,shutil,hashlib
from datetime import datetime
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
VERSION='1.4.0';PORT=8099;SHARE=Path('/share');HA=Path('/homeassistant');CUSTOM=HA/'custom_components'/'ecovacs';JOBS={};LOCK=threading.Lock()
MATCH=re.compile(r'ecovacs|deebot|beepbop|cqyi87|get_static_device_info|device verification|1013|update to the latest version|config_entries|30000|10000|p2p|mqtt',re.I)
SECRET=re.compile(r'(?i)(password|token|access_token|refresh_token|api_key|secret)(["\']?\s*[:=]\s*["\']?)[^,\s}\]]+')
EMAIL=re.compile(r'(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b')
def redact(s): return SECRET.sub(r'\1\2<redacted>',EMAIL.sub('<redacted-email>',str(s)))
def docker(cmd,timeout=15):
 try:
  p=subprocess.run(['docker']+cmd,capture_output=True,text=True,timeout=timeout);return p.returncode,p.stdout,p.stderr
 except Exception as e:return 99,'',str(e)
def find_core():
 rc,o,e=docker(['ps','--format','{{.ID}}\t{{.Names}}']);out=[]
 for line in o.splitlines():
  x=line.split('\t',1)
  if len(x)==2 and 'homeassistant' in x[1].lower():out.append(x)
 return out
def core_exec(args,timeout=15):
 cores=find_core()
 if not cores:return {'ok':False,'error':'Home Assistant Core container not found'}
 rc,o,e=docker(['exec',cores[0][0]]+args,timeout);return {'ok':rc==0,'stdout':redact(o),'stderr':redact(e),'rc':rc}
def snapshot(minutes='30m'):
 cores=find_core();r={'core_candidates':[{'id':x[0],'name':x[1]} for x in cores],'matched':[],'raw':[]}
 if not cores:r['error']='Core container not found';return r
 rc,o,e=docker(['logs','--since',minutes,cores[0][0]],30);raw=(o+e).splitlines();r['raw']=[redact(x) for x in raw[-20000:]];r['matched']=[redact(x) for x in raw if MATCH.search(x)][-12000:];return r
def custom_info():
 r={'present':CUSTOM.is_dir(),'path':str(CUSTOM),'manifest':None,'files':[],'backups':[]}
 if CUSTOM.is_dir():
  m=CUSTOM/'manifest.json'
  if m.exists():
   try:r['manifest']=json.loads(m.read_text(errors='replace'))
   except Exception as e:r['manifest_error']=redact(e)
  for p in sorted(CUSTOM.rglob('*')):
   if p.is_file():
    try:r['files'].append({'path':str(p.relative_to(CUSTOM)),'size':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    except:pass
 if CUSTOM.parent.exists():r['backups']=[p.name for p in sorted(CUSTOM.parent.glob('ecovacs.disabled-*'),reverse=True)]
 return r
def environment():
 return {'python':core_exec(['python','--version']),'ha_version':core_exec(['python','-c','import homeassistant;print(homeassistant.__version__)']),'deebot_client':core_exec(['python','-c','import importlib.metadata as m;print(m.version("deebot-client"))']),'ecovacs_module':core_exec(['python','-c','import homeassistant.components.ecovacs as e;print(e.__file__)'])}
def classify(lines,ci):
 j='\n'.join(lines).lower();f=[]
 if ci['present']:f.append({'severity':'HIGH','code':'CUSTOM_COMPONENT_SHADOWING_CORE','meaning':'/config/custom_components/ecovacs is active and overrides the built-in Home Assistant Ecovacs integration.','action':'Disable the custom component, restart Core, and test the built-in integration.'})
 if 'get_static_device_info' in j:f.append({'severity':'HIGH','code':'STATIC_DEVICE_INFO_FAILURE','meaning':'Device discovery fails while resolving static Ecovacs device metadata.','action':'Compare device class and installed deebot-client version; test Core after removing custom shadowing.'})
 if 'device verification required' in j:f.append({'severity':'HIGH','code':'DEVICE_VERIFICATION','meaning':'Ecovacs requires account/device verification.','action':'Use current HA reauthentication/verification flow and capture subsequent traceback.'})
 if 'please update to the latest version to continue' in j or "'1013'" in j:f.append({'severity':'HIGH','code':'ECOVACS_1013','meaning':'Ecovacs rejected the client version.','action':'Use current Home Assistant/deebot-client rather than an obsolete pinned client.'})
 if 'error setting up entry' in j and 'ecovacs' in j:f.append({'severity':'HIGH','code':'SETUP_FAILURE','meaning':'The Ecovacs config entry is failing during setup.','action':'Use this report to identify the exact discovery/authentication stage.'})
 if not f:f.append({'severity':'INFO','code':'NO_KNOWN_SIGNATURE','meaning':'No known signature found in recent Core logs.','action':'Reproduce the failure and run diagnosis again.'})
 return f
def diagnose():
 s=snapshot();ci=custom_info();r={'version':VERSION,'generated':datetime.now().isoformat(),'environment':environment(),'custom_component':ci,'findings':classify(s['matched'],ci),'matched_logs':s['matched'],'core_candidates':s.get('core_candidates',[])}
 SHARE.mkdir(parents=True,exist_ok=True);p=SHARE/f'deebot-diagnostic-{datetime.now():%Y%m%d-%H%M%S}.zip'
 with zipfile.ZipFile(p,'w',zipfile.ZIP_DEFLATED) as z:z.writestr('REPORT.json',json.dumps(r,indent=2,default=str));z.writestr('MATCHED_CORE_LOG.txt','\n'.join(s['matched']))
 r['file']=str(p);return r
def disable_custom():
 if not CUSTOM.exists():return {'ok':False,'message':'No active custom_components/ecovacs directory exists.'}
 dest=CUSTOM.parent/f'ecovacs.disabled-{datetime.now():%Y%m%d-%H%M%S}';shutil.move(str(CUSTOM),str(dest));return {'ok':True,'backup':str(dest),'message':'Custom Ecovacs disabled. Restart Home Assistant Core, then test the built-in integration.'}
def restore_custom():
 if CUSTOM.exists():return {'ok':False,'message':'An active custom Ecovacs directory already exists.'}
 b=sorted(CUSTOM.parent.glob('ecovacs.disabled-*'),reverse=True)
 if not b:return {'ok':False,'message':'No disabled backup found.'}
 shutil.move(str(b[0]),str(CUSTOM));return {'ok':True,'message':'Newest custom Ecovacs backup restored.'}
def restart():
 cores=find_core()
 if not cores:return {'ok':False,'message':'Core container not found'}
 rc,o,e=docker(['restart',cores[0][0]],30);return {'ok':rc==0,'message':'Restart requested' if rc==0 else redact(e)}
HTML=f'''<!doctype html><meta name="viewport" content="width=device-width"><title>DEEBOT Diagnostics</title><style>body{{font-family:system-ui;max-width:1050px;margin:24px auto;padding:0 18px;background:#111827;color:#e5e7eb}}button{{padding:11px 14px;margin:5px;border:0;border-radius:8px;font-weight:650}}.p{{background:#2563eb;color:white}}.w{{background:#f59e0b}}.d{{background:#ef4444;color:white}}.s{{background:#4b5563;color:white}}pre{{background:#030712;padding:14px;white-space:pre-wrap;max-height:650px;overflow:auto;border-radius:8px}}.card{{background:#1f2937;padding:15px;border-radius:12px;margin:12px 0}}</style><h1>DEEBOT Y1 PRO Diagnostics</h1><p>Version <b>{VERSION}</b> — diagnosis plus controlled Ecovacs recovery.</p><div class="card"><button class="p" onclick="go('./api/diagnose')">Run full diagnosis</button><button class="w" onclick="ask('./api/disable','Disable custom Ecovacs? A timestamped backup will be kept.')">Disable custom Ecovacs</button><button class="s" onclick="ask('./api/restore','Restore newest custom Ecovacs backup?')">Restore custom Ecovacs</button><button class="d" onclick="ask('./api/restart','Restart Home Assistant Core now?')">Restart Core</button></div><pre id="o">Ready.</pre><script>async function go(u){{o.textContent='Working…';try{{let r=await fetch(u,{{method:'POST'}});o.textContent=JSON.stringify(await r.json(),null,2)}}catch(e){{o.textContent=String(e)}}}}function ask(u,m){{if(confirm(m))go(u)}}</script>'''
class H(BaseHTTPRequestHandler):
 def x(self,c,b,ct='application/json'):
  if isinstance(b,str):b=b.encode();self.send_response(c);self.send_header('Content-Type',ct);self.send_header('Content-Length',str(len(b)));self.send_header('Cache-Control','no-store');self.end_headers();self.wfile.write(b)
 def do_GET(self):return self.x(200,HTML,'text/html; charset=utf-8') if self.path.split('?',1)[0] in ('','/') else self.x(404,json.dumps({'error':'not found'}))
 def do_POST(self):
  p=self.path.split('?',1)[0]
  try:
   if p=='/api/diagnose':r=diagnose()
   elif p=='/api/disable':r=disable_custom()
   elif p=='/api/restore':r=restore_custom()
   elif p=='/api/restart':r=restart()
   else:return self.x(404,json.dumps({'error':'not found'}))
   return self.x(200,json.dumps(r,indent=2,default=str))
  except Exception as e:return self.x(500,json.dumps({'error':redact(e)}))
 def log_message(self,*a):pass
ThreadingHTTPServer(('0.0.0.0',PORT),H).serve_forever()
