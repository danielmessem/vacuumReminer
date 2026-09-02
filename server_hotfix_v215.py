#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.15 / profile 1.8.5.

Stats-only hotfix. Ensures Home Assistant's TotalStatsEvent subscriber receives
an immediate value by attaching the proven Y1 10001 clean-stats query to the
total-stats refresh path. No map/control changes.
"""
from pathlib import Path

import server_hotfix_v214 as h

w = h.w
VERSION = "2.0.15"
PROFILE_VERSION = "1.8.5"


def build_profile_185():
    src = h.build_profile_184()
    dst = Path("/app/cqyi87_profile_185.py")
    text = src.read_text()

    text = text.replace('Y1PRO_PATCH_VERSION = "1.8.4"', 'Y1PRO_PATCH_VERSION = "1.8.5"', 1)

    # In 1.8.4 the local totals were emitted while HA was refreshing the live
    # StatsEvent sensor. Home Assistant subscribes to TotalStatsEvent separately,
    # so that initial event can be missed and all three total sensors stay
    # Unknown. Give the total capability its own safe 10001 refresh. The field
    # handler already emits the persisted local TotalStatsEvent values.
    old_stats = '            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, [Y1ProFieldCommand(["cleanArea", "cleanTime", "cleanCount", "cleanLogReport"])]), report=CapabilityEvent(ReportStatsEvent, [Y1ProCleanInfoV2Command()]), total=CapabilityEvent(TotalStatsEvent, [])),\n'
    new_stats = '            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, [Y1ProFieldCommand(["cleanArea", "cleanTime", "cleanCount", "cleanLogReport"])]), report=CapabilityEvent(ReportStatsEvent, [Y1ProCleanInfoV2Command()]), total=CapabilityEvent(TotalStatsEvent, [Y1ProFieldCommand(["cleanArea", "cleanTime", "cleanCount", "cleanLogReport"])])),\n'
    if old_stats not in text:
        raise RuntimeError("Could not locate 1.8.4 stats capability")
    text = text.replace(old_stats, new_stats, 1)

    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_185()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.14", "v2.0.15")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
