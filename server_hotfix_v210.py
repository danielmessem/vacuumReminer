#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.10 / profile 1.8.0.

Builds on 2.0.9 and adds current-clean stats, an experimental lifetime-stats
probe, and native handling for the Y1's unsolicited 30000 map broadcasts.
"""
from pathlib import Path

import server_hotfix_v203 as h

w = h.w
VERSION = "2.0.10"
PROFILE_VERSION = "1.8.0"


def build_profile_180():
    src = h.build_profile_179()
    dst = Path("/app/cqyi87_profile_180.py")
    text = src.read_text()

    text = text.replace('Y1PRO_PATCH_VERSION = "1.7.9"', 'Y1PRO_PATCH_VERSION = "1.8.0"', 1)

    # Add a handler for the Y1's actual unsolicited map channel. The existing
    # 1.7.x map translator already understands mapInfos, mapData, areas and pos;
    # previously these useful 30000 broadcasts were simply logged as unknown.
    marker = 'MESSAGES["10000"] = Y1ProStateMessage\n'
    insert = '''class Y1ProMapBroadcast(MessageBodyDataDict):\n    NAME = "30000"\n\n    @classmethod\n    def _handle_body_data_dict(cls, event_bus, data: dict[str, Any]) -> HandlingResult:\n        return _map_data(event_bus, data)\n\n\nfrom deebot_client.commands.json.stats import GetTotalStats as _Y1BaseTotalStats\n\n\nclass Y1ProTotalStatsCommand(_Y1BaseTotalStats):\n    \"\"\"Probe the legacy total-stats endpoint using the Y1 Android envelope.\"\"\"\n\n\n'''
    if marker not in text:
        raise RuntimeError("Could not locate Y1 message registration marker")
    text = text.replace(marker, insert + marker, 1)
    text = text.replace(
        'MESSAGES["30001"] = Y1ProMapMessage\n',
        'MESSAGES["30000"] = Y1ProMapBroadcast\nMESSAGES["30001"] = Y1ProMapMessage\n',
        1,
    )

    # Refresh current clean stats using the field query proven by the Android app.
    # Total stats are requested separately; failure does not influence availability.
    old_stats = '            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, []), report=CapabilityEvent(ReportStatsEvent, []), total=CapabilityEvent(TotalStatsEvent, [])),\n'
    new_stats = '            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, [Y1ProFieldCommand(["cleanArea", "cleanTime"])]), report=CapabilityEvent(ReportStatsEvent, []), total=CapabilityEvent(TotalStatsEvent, [Y1ProTotalStatsCommand()])),\n'
    if old_stats not in text:
        raise RuntimeError("Could not locate Y1 stats capability")
    text = text.replace(old_stats, new_stats, 1)

    # Extend the existing 10000/10001 state parser so current cleanArea/cleanTime
    # update Home Assistant's Area cleaned and Cleaning duration sensors.
    old_start = '''        handled = False\n        battery = data.get("battery")\n'''
    new_start = '''        handled = False\n        clean_area = data.get("cleanArea")\n        clean_time = data.get("cleanTime")\n        if ((isinstance(clean_area, (int, float)) and not isinstance(clean_area, bool)) or\n                (isinstance(clean_time, (int, float)) and not isinstance(clean_time, bool))):\n            event_bus.notify(StatsEvent(\n                area=int(clean_area) if isinstance(clean_area, (int, float)) and not isinstance(clean_area, bool) else None,\n                time=int(clean_time) if isinstance(clean_time, (int, float)) and not isinstance(clean_time, bool) else None,\n                type=None,\n            ))\n            handled = True\n        battery = data.get("battery")\n'''
    if old_start not in text:
        raise RuntimeError("Could not locate Y1 state handler")
    text = text.replace(old_start, new_start, 1)

    # The buried clean-info event carries the same fields and often arrives more
    # frequently than 10000, so consume it as a passive stats source too.
    old_branch = '''                    elif message_name == "onFwBuryPoint-task-evt":\n                        act = str(body.get("act", "")).lower()\n'''
    new_branch = '''                    elif message_name == "onFwBuryPoint-bd_task-cleanInfo-evt":\n                        area = body.get("cleanArea")\n                        duration = body.get("cleanTime")\n                        if ((isinstance(area, (int, float)) and not isinstance(area, bool)) or\n                                (isinstance(duration, (int, float)) and not isinstance(duration, bool))):\n                            self.events.notify(StatsEvent(\n                                area=int(area) if isinstance(area, (int, float)) and not isinstance(area, bool) else None,\n                                time=int(duration) if isinstance(duration, (int, float)) and not isinstance(duration, bool) else None,\n                                type=None,\n                            ))\n                        self.events.notify(AvailabilityEvent(available=True))\n                    elif message_name == "onFwBuryPoint-task-evt":\n                        act = str(body.get("act", "")).lower()\n'''
    if old_branch not in text:
        raise RuntimeError("Could not locate passive telemetry task branch")
    text = text.replace(old_branch, new_branch, 1)

    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_180()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.9", "v2.0.10")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
