#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.42 / profile 1.8.18.

Adds an installer for the separate Whole-house Clean ETA companion integration.
The known-good Y1 hardware profile and map pipeline are unchanged.
"""

from datetime import datetime
from pathlib import Path
import json
import shutil

import server_hotfix_v241 as release

w = release.w
VERSION = "2.0.42"
PROFILE_VERSION = release.PROFILE_VERSION
ETA_SOURCE = Path("/app/y1_pro_eta")
ETA_TARGET = Path("/homeassistant/custom_components/y1_pro_eta")
ETA_BACKUPS = Path("/homeassistant/y1_pro_eta_backups")


def install_eta():
    """Install the companion integration, retaining a timestamped backup."""
    if not ETA_SOURCE.is_dir():
        return {"ok": False, "message": "Bundled ETA integration is missing"}
    try:
        backup = None
        if ETA_TARGET.exists():
            ETA_BACKUPS.mkdir(parents=True, exist_ok=True)
            backup = ETA_BACKUPS / f"y1_pro_eta-{datetime.now():%Y%m%d-%H%M%S}"
            shutil.copytree(ETA_TARGET, backup)
            shutil.rmtree(ETA_TARGET)
        ETA_TARGET.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ETA_SOURCE, ETA_TARGET)
        manifest = json.loads((ETA_TARGET / "manifest.json").read_text())
        return {
            "ok": True,
            "message": (
                "Whole-house Clean ETA installed. Restart Home Assistant Core, "
                "then add the integration in Settings > Devices & services."
            ),
            "version": manifest.get("version"),
            "target": str(ETA_TARGET),
            "backup": str(backup) if backup else None,
        }
    except Exception as exc:
        return {
            "ok": False,
            "message": "ETA installation failed",
            "error": w.s.redact(exc),
        }


_base_post = w.s.Handler.do_POST


def _do_post(self):
    if self.path.rstrip("/").endswith("/api/install-eta"):
        return self.sendj(install_eta())
    return _base_post(self)


w.s.Handler.do_POST = _do_post
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.41", "v2.0.42")
w.s.HTML = w.s.HTML.replace(
    '<button onclick="call(\'install\')">Install / Repair Patch</button>',
    '<button onclick="call(\'install\')">Install / Repair Patch</button>'
    '<button class="good" onclick="call(\'install-eta\')">Install Whole-house ETA</button>',
)


if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}; "
        "ETA integration 0.1.0",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
