#!/bin/sh
set -eu

CORE=homeassistant
PKG=/usr/local/lib/python3.14/site-packages/deebot_client
HW="$PKG/hardware"
STAMP=$(date +%Y%m%d-%H%M%S)
BACKUP="/config/deebot-y1pro-backup-$STAMP"

echo "Backing up deebot-client to $BACKUP"
docker exec "$CORE" sh -c "mkdir -p '$BACKUP' && cp -a '$PKG' '$BACKUP/'"

echo "Finding N20 hardware profile"
SRC=$(docker exec "$CORE" sh -c "grep -l 'Deebot N20 Capabilities' '$HW'/*.py | head -1")
[ -n "$SRC" ]

echo "Using: $SRC"

docker exec "$CORE" sh -c "cp '$SRC' '$HW/cqyi87.py'"

docker exec "$CORE" python3 - <<'PY'
from pathlib import Path
import re
p = Path('/usr/local/lib/python3.14/site-packages/deebot_client/hardware/cqyi87.py')
s = p.read_text()
s = re.sub(r'^\"\"\".*?\"\"\"', '\"\"\"DEEBOT Y1 PRO Capabilities.\"\"\"', s, count=1, flags=re.S)
s, n = re.subn(r'availability=CapabilityEvent\(\s*AvailabilityEvent,\s*\[GetBattery\(is_available_check=True\)\]\s*\),', 'availability=None,', s)
p.write_text(s)
print('PROFILE:', p)
print('AVAILABILITY_PATCHED:', n)
PY

echo "Testing import"
docker exec "$CORE" python3 - <<'PY'
import importlib
m=importlib.import_module('deebot_client.hardware.cqyi87')
info=m.get_device_info()
print('CQYI87 IMPORT OK')
print('CAPABILITIES:', info.capabilities)
PY

echo
echo "Y1 Pro profile installed. Restart Home Assistant Core, then run the DEEBOT deep capture."
echo "Backup: $BACKUP"
