#!/usr/bin/env python3
"""Best-effort DEEBOT client inspection plus a safe Core-side inspection script."""
import importlib.metadata as md
import os
import re
import subprocess
import sys
from pathlib import Path

TARGETS = ["deebot_client", "deebot-client", "ecovacs"]
PATTERNS = ["cqyi87", "Device class", "SUPPORTED_MODELS", "hardware", "cd45", "30000"]


def package_info():
    out = {"python": sys.version, "packages_visible_to_addon": {}}
    for name in TARGETS:
        try:
            d = md.distribution(name)
            out["packages_visible_to_addon"][name] = {
                "version": d.version,
                "location": str(d.locate_file("")),
                "files": [str(x) for x in (d.files or []) if "deebot" in str(x).lower() or "ecovacs" in str(x).lower()][:500],
            }
        except Exception as e:
            out["packages_visible_to_addon"][name] = {"installed": False, "error": str(e)}
    return out


def local_source_search():
    roots = [Path("/usr/local/lib"), Path("/opt"), Path("/app")]
    hits = []
    for root in roots:
        if not root.exists():
            continue
        try:
            for p in root.rglob("*.py"):
                if len(hits) >= 2000:
                    break
                try:
                    text = p.read_text(errors="replace")
                    matched = [x for x in PATTERNS if re.search(re.escape(x), text, re.I)]
                    if matched:
                        hits.append({"path": str(p), "matches": matched})
                except Exception:
                    pass
        except Exception:
            pass
    return hits


def installed_client_fingerprint(core_logs=""):
    text = core_logs or ""
    evidence = [line[-2000:] for line in text.splitlines() if re.search(r"deebot|ecovacs|cqyi87|device class|deebot-client|version", line, re.I)]
    versions = sorted(set(re.findall(r"deebot[-_ ]?client[^0-9]{0,20}([0-9]+(?:\.[0-9]+)+)", text, re.I)))
    return {
        "core_filesystem_direct_access": False,
        "reason": "The diagnostic add-on is a separate container and cannot directly read Home Assistant Core site-packages.",
        "versions_seen_in_core_logs": versions,
        "core_log_evidence": evidence[-1000:],
    }


# This script is intentionally read-only: it gathers package/source/version information,
# redacts obvious credentials, and writes one JSON result. It does not install packages,
# modify HA, restart services, or execute anything fetched from the network.
CORE_INSPECTION_SCRIPT = r'''#!/usr/bin/env bash
set -u
OUT="/config/deebot-y1pro-core-inspection-$(date +%Y%m%d-%H%M%S).json"
TMP="${OUT}.tmp"
python3 - <<'PY' > "$TMP"
import json, os, re, sys, subprocess, pathlib, importlib.util
from importlib import metadata

patterns = ["cqyi87", "SUPPORTED_MODELS", "cd45", "30000", "Device class", "not recognized"]
roots = [pathlib.Path('/usr/local/lib'), pathlib.Path('/usr/lib'), pathlib.Path('/usr/src/homeassistant/homeassistant/components/ecovacs')]

def scan():
    hits=[]
    for root in roots:
        if not root.exists(): continue
        try:
            for p in root.rglob('*'):
                if len(hits)>=2000: break
                if not p.is_file() or p.suffix not in ('.py','.json','.toml','.yaml','.yml'): continue
                try: text=p.read_text(errors='replace')[:1000000]
                except Exception: continue
                m=[x for x in patterns if x.lower() in text.lower()]
                if m: hits.append({'path':str(p),'matches':m,'size':p.stat().st_size})
        except Exception: pass
    return hits

result={'python':sys.version,'homeassistant_version':None,'deebot_client':{},'ecovacs_manifest':{},'source_hits':scan(),'commands':{}}
try:
    import homeassistant
    result['homeassistant_version']=getattr(homeassistant,'__version__','unknown')
except Exception as e: result['homeassistant_import_error']=str(e)
try:
    import deebot_client
    result['deebot_client']={'module_file':getattr(deebot_client,'__file__',None),'version':getattr(deebot_client,'__version__','unknown')}
except Exception as e: result['deebot_client']={'import_error':str(e)}
for name in ('deebot-client','ecovacs'):
    try:
        d=metadata.distribution(name)
        result['deebot_client'].setdefault('distributions',{})[name]={'version':d.version,'location':str(d.locate_file(''))}
    except Exception: pass
manifest=pathlib.Path('/usr/src/homeassistant/homeassistant/components/ecovacs/manifest.json')
if manifest.exists():
    try: result['ecovacs_manifest']=json.loads(manifest.read_text(errors='replace'))
    except Exception as e: result['ecovacs_manifest']={'error':str(e)}
# Focused source excerpts for the exact compatibility problem.
excerpts=[]
for item in result['source_hits']:
    if not any(x in item['matches'] for x in ('cqyi87','SUPPORTED_MODELS','cd45','30000','Device class')): continue
    p=pathlib.Path(item['path'])
    try:
        lines=p.read_text(errors='replace').splitlines()
        relevant=[]
        for i,line in enumerate(lines):
            if any(x.lower() in line.lower() for x in patterns):
                relevant.extend([(i+1, lines[j][:500]) for j in range(max(0,i-3), min(len(lines),i+4))])
        excerpts.append({'path':str(p),'lines':relevant[:300]})
    except Exception: pass
result['source_excerpts']=excerpts
print(json.dumps(result,indent=2,default=str))
PY
mv "$TMP" "$OUT"
echo "WROTE:$OUT"
'''


def core_inspection_script():
    return CORE_INSPECTION_SCRIPT


def inspect(core_logs=""):
    return {
        "package_info_in_diagnostic_container": package_info(),
        "local_source_hits_in_diagnostic_container": local_source_search(),
        "core_runtime": installed_client_fingerprint(core_logs),
        "core_inspection_script_available": True,
        "important": "Run the generated read-only script inside Home Assistant Core/Terminal. It writes a JSON file under /config and does not install, modify, restart, or download anything.",
    }
