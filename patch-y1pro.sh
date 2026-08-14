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

# Remove capabilities that the Y1 Pro has now proven not to support.
# This parser replaces a keyword's balanced Python expression without
# relying on fragile multi-line regexes.
def replace_kw(src, kw, replacement):
    m = re.search(r'(?m)^\s*' + re.escape(kw) + r'\s*=', src)
    if not m:
        return src, False
    start = m.start() + (len(m.group(0)) - len(m.group(0).lstrip()))
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
                    i += 3
                    quote = None
                    triple = False
                    continue
            elif c == '\\':
                i += 2
                continue
            elif c == quote:
                quote = None
        else:
            if c in "'\"":
                if src.startswith(c * 3, i):
                    quote = c
                    triple = True
                    i += 3
                    continue
                quote = c
            elif c in '([{':
                depth += 1
            elif c in ')]}':
                if depth == 0:
                    break
                depth -= 1
            elif c == ',' and depth == 0:
                break
        i += 1
    return src[:expr_start] + replacement + src[i:], True

# The Y1 Pro returns data=null for getBattery and times out for getWaterInfo.
s = re.sub(
    r'availability=CapabilityEvent\(\s*AvailabilityEvent,\s*\[GetBattery\(is_available_check=True\)\]\s*\),',
    'availability=None,', s, count=1, flags=re.S)

for kw in ('water', 'map'):
    s, found = replace_kw(s, kw, 'None')
    print(f'{kw.upper()}_DISABLED:', found)

p.write_text(s)

# Verify syntax and the resulting profile.
compile(s, str(p), 'exec')
m = importlib.import_module('deebot_client.hardware.cqyi87')
info = m.get_device_info()
print('CQYI87 IMPORT OK')
print('CAPABILITIES:', info.capabilities)
PY

echo
echo "Y1 Pro profile updated: water/map disabled because the Y1 Pro rejects those N20 commands."
echo "Restart Home Assistant Core to load the updated profile."
echo "Backup: $BACKUP"
