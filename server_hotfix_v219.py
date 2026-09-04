#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.19 / profile 1.8.6.

Version bump for the capability-discovery build introduced in 2.0.18.
No vacuum profile or robot-control semantics are changed.
"""
import server_hotfix_v218 as h

w = h.w
VERSION = "2.0.19"

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.18", "v2.0.19")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {h.h.h.PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
