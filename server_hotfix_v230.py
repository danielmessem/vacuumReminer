#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.30 / profile 1.8.9.

Expose the Y1 PRO consumables report through deebot-client's native LifeSpan
capability so Home Assistant creates normal diagnostic percentage sensors.

The Y1-specific consumables query is read-only. Reset buttons remain disabled by
default in Home Assistant and this profile deliberately refuses reset commands
until the Y1 reset protocol is proven.
"""
from pathlib import Path

import server_hotfix_v229 as h
import server_hotfix_v224 as profile_base
import server_hotfix_v216 as installer

w = h.w
VERSION = "2.0.30"
PROFILE_VERSION = "1.8.9"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_189() -> Path:
    src = profile_base.build_profile_188()
    dst = Path("/app/cqyi87_profile_189.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.8"',
        'Y1PRO_PATCH_VERSION = "1.8.9"',
        "1.8.8 profile marker",
    )

    # LifeSpan is the native deebot-client component enum used by HA sensors.
    text = _replace_once(
        text,
        '    FanSpeedEvent, FanSpeedLevel, LifeSpanEvent, MapChangedEvent, MapTraceEvent,\n',
        '    FanSpeedEvent, FanSpeedLevel, LifeSpan, LifeSpanEvent, MapChangedEvent, MapTraceEvent,\n',
        "LifeSpan event import",
    )

    # Translate Y1's 10001 consumables array into native LifeSpanEvent values.
    # This is intentionally before chargeStatus handling because a normal 10001
    # status response can contain chargeStatus=true and return early afterward.
    anchor = '        charge = data.get("chargeStatus")\n'
    additions = '''        consumables = data.get("consumables")
        if isinstance(consumables, list):
            life_span_map = {
                "rollBrush": LifeSpan.BRUSH,
                "filter": LifeSpan.FILTER,
                "sideBrush": LifeSpan.SIDE_BRUSH,
                "unitCare": LifeSpan.UNIT_CARE,
            }
            for component in consumables:
                if not isinstance(component, dict):
                    continue
                component_type = life_span_map.get(component.get("type"))
                if component_type is None:
                    continue
                try:
                    left = int(component.get("left"))
                    total = int(component.get("total"))
                except (TypeError, ValueError):
                    continue
                if total <= 0:
                    continue
                percent = round((left / total) * 100, 2)
                event_bus.notify(LifeSpanEvent(component_type, percent, left))
                handled = True

'''
    text = _replace_once(text, anchor, additions + anchor, "consumables event insertion point")

    # CapabilityLifeSpan requires a reset callable. We have not captured the Y1
    # reset protocol, so fail safely instead of sending the generic Ecovacs reset
    # command. HA's reset lifespan buttons are disabled by default.
    marker = '\n\ndef get_device_info() -> StaticDeviceInfo:\n'
    reset_guard = '''\n\ndef Y1ProUnsupportedLifeSpanReset(component):
    """Do not send an unverified Y1 consumable-reset command."""
    raise NotImplementedError(
        f"Y1 PRO consumable reset is not mapped yet: {component}"
    )
'''
    text = _replace_once(text, marker, reset_guard + marker, "lifespan reset guard insertion point")

    old_life = '            life_span=CapabilityLifeSpan(event=LifeSpanEvent, get=[], reset=ResetLifeSpan, types=()),\n'
    new_life = '''            life_span=CapabilityLifeSpan(
                event=LifeSpanEvent,
                get=[Y1ProFieldCommand(["consumables"])],
                reset=Y1ProUnsupportedLifeSpanReset,
                types=(LifeSpan.BRUSH, LifeSpan.FILTER, LifeSpan.SIDE_BRUSH, LifeSpan.UNIT_CARE),
            ),
'''
    text = _replace_once(text, old_life, new_life, "lifespan capability")

    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_189()
    installer.PROFILE_VERSION = PROFILE_VERSION
    installer._PROFILE_BUILD_ERROR = None
except Exception as exc:
    _PROFILE_BUILD_ERROR = str(exc)
    installer.PROFILE_VERSION = PROFILE_VERSION
    installer._PROFILE_BUILD_ERROR = _PROFILE_BUILD_ERROR
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.s.patch_status = installer.patch_status_strict
w.s.install_patch = installer.install_patch_strict

_base_diagnose = w.s.diagnose

def diagnose_230():
    result = _base_diagnose()
    result["version"] = VERSION
    result["y1pro_consumables"] = {
        "profile": PROFILE_VERSION,
        "query": "10001 / consumables",
        "entities": ["brush", "filter", "side_brush", "unit_care"],
        "read_only": True,
        "reset_supported": False,
        "build_error": _PROFILE_BUILD_ERROR,
    }
    return result

w.s.diagnose = diagnose_230
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.29", "v2.0.30")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
