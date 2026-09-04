#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.33 / profile 1.8.10.

Release wrapper for the robust 1.8.10 map-cleanup generator in v231.
"""
import server_hotfix_v231 as h

w = h.w
VERSION = "2.0.33"
PROFILE_VERSION = "1.8.10"

_base_diagnose = w.s.diagnose

def diagnose_233():
    result = _base_diagnose()
    result["version"] = VERSION
    result["profile"] = PROFILE_VERSION
    result["release_note"] = "Robust raster decode anchor for 1.8.10 map cleanup"
    return result

w.s.diagnose = diagnose_233
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.32", "v2.0.33")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
