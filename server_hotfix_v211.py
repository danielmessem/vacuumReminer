#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.11 / profile 1.8.1.

Builds on 2.0.10. Removes the unsupported legacy getTotalStats poll and
captures the Y1 cleanCount / cleanLogReport fields for clean-history reverse
engineering, without changing the working live stats, map, state or battery.
"""
from pathlib import Path

import server_hotfix_v210 as h

w = h.w
VERSION = "2.0.11"
PROFILE_VERSION = "1.8.1"


def build_profile_181():
    src = h.build_profile_180()
    dst = Path("/app/cqyi87_profile_181.py")
    text = src.read_text()

    text = text.replace('Y1PRO_PATCH_VERSION = "1.8.0"', 'Y1PRO_PATCH_VERSION = "1.8.1"', 1)

    # getTotalStats is acknowledged by cqyi87 but returns data:null, so do not
    # poll it. Keeping it active only creates parser warnings and cannot populate
    # HA's lifetime sensors.
    old_stats = '            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, [Y1ProFieldCommand(["cleanArea", "cleanTime"])]), report=CapabilityEvent(ReportStatsEvent, []), total=CapabilityEvent(TotalStatsEvent, [Y1ProTotalStatsCommand()])),\n'
    new_stats = '            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, [Y1ProFieldCommand(["cleanArea", "cleanTime", "cleanCount", "cleanLogReport"])]), report=CapabilityEvent(ReportStatsEvent, []), total=CapabilityEvent(TotalStatsEvent, [])),\n'
    if old_stats not in text:
        raise RuntimeError("Could not locate 1.8.0 stats capability")
    text = text.replace(old_stats, new_stats, 1)

    # Log only non-sensitive clean-history metadata. cleanCount on this firmware
    # has not yet been proven to mean lifetime-clean count, so deliberately do
    # not map it to TotalStatsEvent until an app/history capture confirms it.
    marker = '''        clean_area = data.get("cleanArea")\n        clean_time = data.get("cleanTime")\n'''
    replacement = '''        clean_area = data.get("cleanArea")\n        clean_time = data.get("cleanTime")\n        clean_count = data.get("cleanCount")\n        clean_log = data.get("cleanLogReport")\n        if clean_count is not None or clean_log is not None:\n            safe_log = None\n            if isinstance(clean_log, dict):\n                safe_log = {"cid": clean_log.get("cid"), "has_resource": bool(clean_log.get("resource"))}\n            _LOGGER.warning("Y1PRO_CLEAN_HISTORY cleanCount=%r cleanLogReport=%r", clean_count, safe_log)\n'''
    if marker not in text:
        raise RuntimeError("Could not locate clean stats parser")
    text = text.replace(marker, replacement, 1)

    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_181()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.10", "v2.0.11")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
