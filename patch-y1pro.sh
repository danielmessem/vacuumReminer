#!/bin/sh
set -eu

CORE=homeassistant
PKG=/usr/local/lib/python3.14/site-packages/deebot_client
HW="$PKG/hardware"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="/config/deebot-y1pro-backup-$STAMP"

echo "Backing up current Y1 Pro profile to $BACKUP"
docker exec "$CORE" sh -c "mkdir -p '$BACKUP' && cp -a '$PKG/hardware/cqyi87.py' '$BACKUP/'"

docker exec "$CORE" python3 - <<'PY'
from pathlib import Path
import importlib
import re

p = Path('/usr/local/lib/python3.14/site-packages/deebot_client/hardware/cqyi87.py')
s = p.read_text()

def replace_kw(src, kw, replacement):
    m = re.search(r'(?m)^(\s*)' + re.escape(kw) + r'\s*=', src)
    if not m:
        return src, False
    start = m.start(1)
    eq = src.find('=', start)
    i = eq + 1
    while i < len(src) and src[i].isspace():
        i += 1
    expr_start = i
    depth = 0
    quote = None
    triple = False
    while i < len(src):
        c = src[i]
        if quote:
            if triple:
                if src.startswith(quote * 3, i):
                    i += 3; quote = None; triple = False; continue
            elif c == '\\':
                i += 2; continue
            elif c == quote:
                quote = None
        else:
            if c in "'\"":
                if src.startswith(c * 3, i):
                    quote = c; triple = True; i += 3; continue
                quote = c
            elif c in '([{': depth += 1
            elif c in ')]}':
                if depth == 0: break
                depth -= 1
            elif c == ',' and depth == 0: break
        i += 1
    return src[:expr_start] + replacement + src[i:], True

# Y1 Pro returns data=null for getBattery. Do not expose any profile capability
# that causes the library to poll/parse getBattery.
s = re.sub(r'GetBattery\(is_available_check=True\)', 'GetBattery_DISABLED()', s)
s = re.sub(r'\bGetBattery\(\)', 'GetBattery_DISABLED()', s)
s, found = replace_kw(s, 'availability', 'None')
print('AVAILABILITY_DISABLED:', found)

# Y1 Pro has also proven incompatible with the N20 water/map polling format.
for kw in ('water', 'map'):
    s, found = replace_kw(s, kw, 'None')
    print(f'{kw.upper()}_DISABLED:', found)

p.write_text(s)
compile(s, str(p), 'exec')
importlib.invalidate_caches()
m = importlib.import_module('deebot_client.hardware.cqyi87')
info = m.get_device_info()
print('CQYI87 IMPORT OK')
print('GETBATTERY_REFERENCES:', s.count('GetBattery('))
print('CAPABILITIES:', info.capabilities)
PY

echo
echo "Y1 Pro profile updated: battery, water and map polling disabled."
echo "Restart Home Assistant Core to load the updated profile."
echo "Backup: $BACKUP"
