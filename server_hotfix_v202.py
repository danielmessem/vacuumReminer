#!/usr/bin/env python3
"""Hotfix wrapper for DEEBOT Y1 PRO Diagnostics 2.0.2 / profile 1.7.3."""
from pathlib import Path

import server_wrapper_v181 as w

VERSION = "2.0.2"
PROFILE_VERSION = "1.7.3"


def build_profile_173():
    """Correct the 1.7.2 availability event constructor for deebot-client 18.5.1."""
    src = Path("/app/cqyi87_profile_172.py")
    if not src.exists():
        # Re-run the existing generator if import-time generation did not leave the file behind.
        src = w.build_profile_172()
    dst = Path("/app/cqyi87_profile_173.py")
    text = src.read_text()

    old = "event_bus.notify(AvailabilityEvent(True))"
    new = "event_bus.notify(AvailabilityEvent())"
    if old not in text:
        raise RuntimeError("Could not locate AvailabilityEvent bootstrap call")
    text = text.replace(old, new, 1)
    text = text.replace('Y1PRO_PATCH_VERSION = "1.7.2"', 'Y1PRO_PATCH_VERSION = "1.7.3"', 1)
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_173()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.1", "v2.0.2")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
