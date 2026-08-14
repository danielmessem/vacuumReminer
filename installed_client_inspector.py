#!/usr/bin/env python3
"""Best-effort DEEBOT client inspection plus safe Core-side Y1 Pro analysis."""
import importlib.metadata as md
import re
import sys
from pathlib import Path

TARGETS=["deebot_client","deebot-client","ecovacs"]
PATTERNS=["cqyi87","Device class","SUPPORTED_MODELS","hardware","cd45","30000","CARTESIAN_BLACK_INT","y30_ww_h_y30h5"]

def package_info():
 out={"python":sys.version,"packages_visible_to_addon":{}}
 for name in TARGETS:
  try:
   d=md.distribution(name); out["packages_visible_to_addon"][name]={"version":d.version,"location":str(d.locate_file(""))}
  except Exception as e: out["packages_visible_to_addon"][name]={"installed":False,"error":str(e)}
 return out

def local_source_search():
 hits=[]
 for root in [Path("/usr/local/lib"),Path("/opt"),Path("/app")]:
  if not root.exists(): continue
  try:
   for p in root.rglob("*.py"):
    if len(hits)>=2000: break
    try:
     text=p.read_text(errors="replace"); matched=[x for x in PATTERNS if re.search(re.escape(x),text,re.I)]
     if matched: hits.append({"path":str(p),"matches":matched})
    except Exception: pass
  except Exception: pass
 return hits

def installed_client_fingerprint(core_logs=""):
 text=core_logs or ""; evidence=[line[-2000:] for line in text.splitlines() if re.search(r"deebot|ecovacs|cqyi87|device class|deebot-client|version",line,re.I)]
 versions=sorted(set(re.findall(r"deebot[-_ ]?client[^0-9]{0,20}([0-9]+(?:\.[0-9]+)+)",text,re.I)))
 return {"core_filesystem_direct_access":False,"reason":"The diagnostic add-on is a separate container and cannot directly read Home Assistant Core site-packages.","versions_seen_in_core_logs":versions,"core_log_evidence":evidence[-1000:]}

CORE_INSPECTION_SCRIPT=r'''#!/usr/bin/env bash
set -u
OUT="/config/deebot-y1pro-core-inspection-$(date +%Y%m%d-%H%M%S).json"
TMP="${OUT}.tmp"
python3 - <<'PY' > "$TMP"
import asyncio,json,pathlib,re,sys,importlib
from importlib import metadata
PATTERNS=["cqyi87","SUPPORTED_MODELS","cd45","30000","Device class","not recognized","CARTESIAN_BLACK_INT","y30_ww_h_y30h5"]
ROOT=pathlib.Path('/usr/local/lib/python3.14/site-packages/deebot_client')
result={'python':sys.version,'homeassistant_version':None,'deebot_client':{},'ecovacs_manifest':{},'source_hits':[],'source_excerpts':[],'hardware_profiles':[],'candidate_profiles':[]}
try:
 import homeassistant; result['homeassistant_version']=getattr(homeassistant,'__version__','unknown')
except Exception as e: result['homeassistant_import_error']=str(e)
try:
 import deebot_client; result['deebot_client']={'module_file':getattr(deebot_client,'__file__',None),'version':getattr(deebot_client,'__version__','unknown')}
except Exception as e: result['deebot_client']={'import_error':str(e)}
for n in ('deebot-client','ecovacs'):
 try:
  d=metadata.distribution(n); result['deebot_client'].setdefault('distributions',{})[n]={'version':d.version,'location':str(d.locate_file(''))}
 except Exception: pass
manifest=pathlib.Path('/usr/src/homeassistant/homeassistant/components/ecovacs/manifest.json')
if manifest.exists():
 try: result['ecovacs_manifest']=json.loads(manifest.read_text(errors='replace'))
 except Exception as e: result['ecovacs_manifest']={'error':str(e)}
for base in [ROOT,pathlib.Path('/usr/src/homeassistant/homeassistant/components/ecovacs')]:
 if not base.exists(): continue
 try:
  for f in base.rglob('*'):
   if not f.is_file() or f.suffix not in ('.py','.json','.toml','.yaml','.yml'): continue
   try: text=f.read_text(errors='replace')
   except: continue
   m=[x for x in PATTERNS if x.lower() in text.lower()]
   if m:
    result['source_hits'].append({'path':str(f),'matches':m,'size':f.stat().st_size})
    lines=text.splitlines(); rel=[]
    for i,line in enumerate(lines):
     if any(x.lower() in line.lower() for x in PATTERNS): rel.extend([(j+1,lines[j][:500]) for j in range(max(0,i-3),min(len(lines),i+4))])
    result['source_excerpts'].append({'path':str(f),'lines':rel[:300]})
 except Exception: pass
hw=ROOT/'hardware'
if hw.exists():
 for f in sorted(hw.glob('*.py')):
  if f.name=='__init__.py': continue
  name=f.stem
  try:
   mod=importlib.import_module('deebot_client.hardware.'+name); info=mod.get_device_info(); caps=getattr(info,'capabilities',None); doc=(mod.__doc__ or '').strip().splitlines()[0] if mod.__doc__ else ''
   capnames=[a for a in ('clean','map','network','play_sound','settings','state','stats','water','life_span') if caps is not None and getattr(caps,a,None) is not None]
   result['hardware_profiles'].append({'class':name,'description':doc,'capabilities':capnames,'source':str(f)})
  except Exception as e: result['hardware_profiles'].append({'class':name,'error':str(e),'source':str(f)})
for p in result['hardware_profiles']:
 s=(p.get('description','')+' '+p.get('class','')).lower(); score=sum(3 for k in ('y1','y30','cartesian','n8','n10','u2') if k in s)
 if any(x in s for x in ('omni','t30','t50')): score-=2
 if 'water' in p.get('capabilities',[]): score+=1
 if 'clean' in p.get('capabilities',[]): score+=1
 if score>0: result['candidate_profiles'].append({'class':p['class'],'description':p.get('description',''),'score':score,'capabilities':p.get('capabilities',[])})
result['candidate_profiles'].sort(key=lambda x:x['score'],reverse=True)
try:
 from deebot_client.hardware import get_static_device_info
 async def probe(): return await get_static_device_info('cqyi87')
 result['cqyi87_probe']={'recognized':asyncio.run(probe()) is not None}
except Exception as e: result['cqyi87_probe']={'recognized':False,'error':str(e)}
try:
 relevant=[]
 for f in (ROOT/'commands').rglob('*.py'):
  try:
   t=f.read_text(errors='replace')
   if any(x in t for x in ('GetCleanInfo','GetMapInfo','GetMapTrace','GetWaterInfo','GetFanSpeed','SetFanSpeed','30000')): relevant.append(str(f))
  except: pass
 result['relevant_command_modules']=relevant
except Exception: pass
print(json.dumps(result,indent=2,default=str))
PY
mv "$TMP" "$OUT"
echo "WROTE:$OUT"
'''

def core_inspection_script(): return CORE_INSPECTION_SCRIPT

def inspect(core_logs=""):
 return {"package_info_in_diagnostic_container":package_info(),"local_source_hits_in_diagnostic_container":local_source_search(),"core_runtime":installed_client_fingerprint(core_logs),"core_inspection_script_available":True,"important":"Run the generated read-only script inside Home Assistant Core/Terminal. It writes one JSON file under /config and does not install, modify, restart, or download anything."}
