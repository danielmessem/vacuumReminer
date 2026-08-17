#!/bin/sh
set -eu
python3 -c 'from pathlib import Path; from installed_client_inspector import core_inspection_script; p=Path("/homeassistant/deebot-y1pro-core-inspection.sh"); p.write_text(core_inspection_script()); p.chmod(0o755)'
exec python3 /app/bootstrap.py
