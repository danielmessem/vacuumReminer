#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.14 / profile 1.8.4.

Cleans up cqyi87 map rendering by collapsing transient room/coverage raster
classes to one floor colour, preserving wall/unknown gaps, and fixing Y1
position units. Also fixes cleanTime minute->second conversion and adds a
persistent local total-stats tracker for completed clean jobs.
"""
from pathlib import Path

import server_hotfix_v213 as h

w = h.w
VERSION = "2.0.14"
PROFILE_VERSION = "1.8.4"


def build_profile_184():
    src = h.build_profile_183()
    dst = Path("/app/cqyi87_profile_184.py")
    text = src.read_text()

    text = text.replace('Y1PRO_PATCH_VERSION = "1.8.3"', 'Y1PRO_PATCH_VERSION = "1.8.4"', 1)

    # The raw Y1 raster contains semantic/coverage classes 1..9. Drawing every
    # class with a different native colour creates the large diagonal wedges
    # seen in HA. 127 is the outside/background class; 0 is the structural gap
    # / wall outline. Render all traversable classes as one floor colour and
    # leave 0/255 transparent so the structural outline stays crisp.
    old_pixel = '''def _pixel_index(value: int) -> int:\n    if value <= 0:\n        return 0\n    if value <= 5:\n        return value\n    return 6 + ((value - 6) % 6)\n'''
    new_pixel = '''def _pixel_index(value: int) -> int:\n    if value in (0, 255):\n        return 0\n    if value == 127:\n        return 7\n    if 1 <= value <= 9:\n        return 2\n    return 0\n'''
    if old_pixel not in text:
        raise RuntimeError("Could not locate Y1 pixel mapping")
    text = text.replace(old_pixel, new_pixel, 1)

    # Y1 pos/chargePos are centimetres; deebot-client map positions use mm.
    text = text.replace(
        'Position(PositionType.DEEBOT, int(pos.get("x", 0)), int(pos.get("y", 0)), int(pos.get("a", 0)))',
        'Position(PositionType.DEEBOT, int(pos.get("x", 0)) * 10, int(pos.get("y", 0)) * 10, int(pos.get("a", 0)))',
    )
    text = text.replace(
        'Position(PositionType.CHARGER, int(charge.get("x", 0)), int(charge.get("y", 0)), int(charge.get("a", 0)))',
        'Position(PositionType.CHARGER, int(charge.get("x", 0)) * 10, int(charge.get("y", 0)) * 10, int(charge.get("a", 0)))',
    )

    # Insert persistent local totals before the state handler. The firmware's
    # getTotalStats and getCleanInfo_V2 both return data:null, so the only safe
    # way to populate HA's total sensors is to track completed jobs locally.
    state_marker = '\n\nclass Y1ProStateMessage(MessageBodyDataDict):\n'
    totals = r'''

from pathlib import Path as _Y1Path

_Y1_TOTALS_PATH = _Y1Path("/config/deebot_y1pro_totals.json")
_Y1PRO_CURRENT_AREA = 0
_Y1PRO_CURRENT_TIME_S = 0
_Y1PRO_TOTAL_AREA = 0
_Y1PRO_TOTAL_TIME_S = 0
_Y1PRO_TOTAL_COUNT = 0
_Y1PRO_LAST_CID = None


def _y1_load_totals() -> None:
    global _Y1PRO_TOTAL_AREA, _Y1PRO_TOTAL_TIME_S, _Y1PRO_TOTAL_COUNT, _Y1PRO_LAST_CID
    try:
        if _Y1_TOTALS_PATH.exists():
            data = orjson.loads(_Y1_TOTALS_PATH.read_bytes())
            if isinstance(data, dict):
                _Y1PRO_TOTAL_AREA = max(0, int(data.get("area", 0) or 0))
                _Y1PRO_TOTAL_TIME_S = max(0, int(data.get("time", 0) or 0))
                _Y1PRO_TOTAL_COUNT = max(0, int(data.get("count", 0) or 0))
                _Y1PRO_LAST_CID = data.get("last_cid")
    except Exception:
        _LOGGER.debug("Y1 totals load failed", exc_info=True)


def _y1_save_totals() -> None:
    try:
        _Y1_TOTALS_PATH.write_bytes(orjson.dumps({
            "area": _Y1PRO_TOTAL_AREA,
            "time": _Y1PRO_TOTAL_TIME_S,
            "count": _Y1PRO_TOTAL_COUNT,
            "last_cid": _Y1PRO_LAST_CID,
        }))
    except Exception:
        _LOGGER.debug("Y1 totals save failed", exc_info=True)


def _y1_emit_totals(event_bus) -> None:
    event_bus.notify(TotalStatsEvent(_Y1PRO_TOTAL_AREA, _Y1PRO_TOTAL_TIME_S, _Y1PRO_TOTAL_COUNT))


def _y1_commit_clean(event_bus, cid) -> None:
    global _Y1PRO_TOTAL_AREA, _Y1PRO_TOTAL_TIME_S, _Y1PRO_TOTAL_COUNT, _Y1PRO_LAST_CID
    cid = str(cid or "").strip()
    if cid and cid != str(_Y1PRO_LAST_CID or "") and (_Y1PRO_CURRENT_AREA > 0 or _Y1PRO_CURRENT_TIME_S > 0):
        _Y1PRO_TOTAL_AREA += max(0, int(_Y1PRO_CURRENT_AREA))
        _Y1PRO_TOTAL_TIME_S += max(0, int(_Y1PRO_CURRENT_TIME_S))
        _Y1PRO_TOTAL_COUNT += 1
        _Y1PRO_LAST_CID = cid
        _y1_save_totals()
        _LOGGER.warning(
            "Y1PRO_TOTALS committed clean area=%s time_s=%s count=%s",
            _Y1PRO_TOTAL_AREA, _Y1PRO_TOTAL_TIME_S, _Y1PRO_TOTAL_COUNT,
        )
    _y1_emit_totals(event_bus)


_y1_load_totals()
'''
    if state_marker not in text:
        raise RuntimeError("Could not locate Y1 state handler insertion point")
    text = text.replace(state_marker, totals + state_marker, 1)

    text = text.replace(
        'global _Y1PRO_PAUSED, _Y1PRO_CHARGE_STATUS\n        handled = False',
        'global _Y1PRO_PAUSED, _Y1PRO_CHARGE_STATUS, _Y1PRO_CURRENT_AREA, _Y1PRO_CURRENT_TIME_S\n        handled = False',
        1,
    )

    # 10000/10001 cleanTime is minutes; HA StatsEvent time is seconds.
    old_stats = '''        if ((isinstance(clean_area, (int, float)) and not isinstance(clean_area, bool)) or\n                (isinstance(clean_time, (int, float)) and not isinstance(clean_time, bool))):\n            event_bus.notify(StatsEvent(\n                area=int(clean_area) if isinstance(clean_area, (int, float)) and not isinstance(clean_area, bool) else None,\n                time=int(clean_time) if isinstance(clean_time, (int, float)) and not isinstance(clean_time, bool) else None,\n                type=None,\n            ))\n            handled = True\n'''
    new_stats = '''        if ((isinstance(clean_area, (int, float)) and not isinstance(clean_area, bool)) or\n                (isinstance(clean_time, (int, float)) and not isinstance(clean_time, bool))):\n            if isinstance(clean_area, (int, float)) and not isinstance(clean_area, bool):\n                _Y1PRO_CURRENT_AREA = max(0, int(clean_area))\n            if isinstance(clean_time, (int, float)) and not isinstance(clean_time, bool):\n                _Y1PRO_CURRENT_TIME_S = max(0, int(round(float(clean_time) * 60)))\n            event_bus.notify(StatsEvent(\n                area=_Y1PRO_CURRENT_AREA,\n                time=_Y1PRO_CURRENT_TIME_S,\n                type=None,\n            ))\n            _y1_emit_totals(event_bus)\n            handled = True\n'''
    if old_stats not in text:
        raise RuntimeError("Could not locate Y1 clean stats block")
    text = text.replace(old_stats, new_stats, 1)

    # A cleanLogReport cid is emitted at the end of a completed job. Commit it
    # once only, then persist the aggregate across HA/Core restarts.
    old_log = '''        if clean_count is not None or clean_log is not None:\n            safe_log = None\n            if isinstance(clean_log, dict):\n                safe_log = {"cid": clean_log.get("cid"), "has_resource": bool(clean_log.get("resource"))}\n            _LOGGER.warning("Y1PRO_CLEAN_HISTORY cleanCount=%r cleanLogReport=%r", clean_count, safe_log)\n'''
    new_log = '''        if clean_count is not None or clean_log is not None:\n            safe_log = None\n            if isinstance(clean_log, dict):\n                safe_log = {"cid": clean_log.get("cid"), "has_resource": bool(clean_log.get("resource"))}\n                _y1_commit_clean(event_bus, clean_log.get("cid"))\n            else:\n                _y1_emit_totals(event_bus)\n            _LOGGER.warning("Y1PRO_CLEAN_HISTORY cleanCount=%r cleanLogReport=%r", clean_count, safe_log)\n'''
    if old_log not in text:
        raise RuntimeError("Could not locate Y1 clean history block")
    text = text.replace(old_log, new_log, 1)

    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_184()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.13", "v2.0.14")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
