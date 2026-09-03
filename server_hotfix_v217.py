#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.17 / profile 1.8.6.

Repairs clean profile generation after earlier profiles changed the raster
coordinate transform and pixel mapping. Patch semantics remain profile 1.8.6.
"""
import server_hotfix_v216 as h

w = h.w
VERSION = "2.0.17"

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.16", "v2.0.17")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {h.PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
