#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.43 / profile 1.8.18.

Makes the ETA installer visible and groups ETA entities with the Ecovacs device.
The known-good Y1 hardware profile and map pipeline are unchanged.
"""

import server_hotfix_v242 as release

w = release.w
VERSION = "2.0.43"
PROFILE_VERSION = release.PROFILE_VERSION

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.42", "v2.0.43")

if "Install Whole-house ETA" not in w.s.HTML:
    anchor = "<button onclick=call('install')>Install / Repair Patch</button>"
    button = (
        anchor
        + "<button class=good onclick=call('install-eta')>"
        "Install Whole-house ETA</button>"
    )
    if anchor not in w.s.HTML:
        raise RuntimeError("Could not locate diagnostics install button")
    w.s.HTML = w.s.HTML.replace(anchor, button, 1)


if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}; "
        "ETA integration 0.1.1",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
