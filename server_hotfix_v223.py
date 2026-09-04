#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.23 / profile 1.8.7.

Adds the two Y1-specific setting controls proven from Ecovacs Android traffic:
  * suction: MQTT/P2P command 50011 with fanMode quiet/auto/strong/max
  * water:   MQTT/P2P command 50013 with waterMode low/mid/high
Also translates the robot's 10000 fanMode/waterMode/mopState events into the
native deebot-client events Home Assistant already consumes.

All existing map, cleaning, docking, battery and stats behaviour is inherited
unchanged from profile 1.8.6.
"""
from pathlib import Path

import server_hotfix_v222 as h
import server_hotfix_v216 as installer

w = h.w
VERSION = "2.0.23"
PROFILE_VERSION = "1.8.7"
_PROFILE_BUILD_ERROR = None


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise RuntimeError(f"Could not locate {label}")
    return text.replace(old, new, 1)


def build_profile_187() -> Path:
    src = installer.build_profile_186()
    dst = Path("/app/cqyi87_profile_187.py")
    text = src.read_text()

    text = _replace_once(
        text,
        'Y1PRO_PATCH_VERSION = "1.8.6"',
        'Y1PRO_PATCH_VERSION = "1.8.7"',
        "1.8.6 profile marker",
    )

    text = _replace_once(
        text,
        'import lzma\nfrom typing import Any\n',
        'import lzma\nfrom enum import IntEnum\nfrom typing import Any\n',
        "enum import insertion point",
    )

    text = _replace_once(
        text,
        '    CapabilitySetTypes, CapabilitySettings, CapabilityStats, DeviceType,\n',
        '    CapabilitySetTypes, CapabilitySettings, CapabilityStats, CapabilityWater, DeviceType,\n',
        "CapabilityWater import",
    )

    text = _replace_once(
        text,
        'from deebot_client.events.map import Map as MapDefinition\n',
        'from deebot_client.events.map import Map as MapDefinition\nfrom deebot_client.events.water_info import MopAttachedEvent, WaterAmountEvent\n',
        "water event imports",
    )

    marker = '\n\nclass Y1ProClean(CustomCommand):\n'
    additions = '''\n\nclass Y1ProFanMode(IntEnum):
    """Y1 PRO suction modes, ordered from lowest to highest."""
    QUIET = 1
    AUTO = 2
    STRONG = 3
    MAX = 4


class Y1ProWaterMode(IntEnum):
    """Y1 PRO water flow modes, ordered from lowest to highest."""
    LOW = 1
    MID = 2
    HIGH = 3


class Y1ProFanSpeedCommand(CustomCommand):
    """Set Y1 suction using the numeric protocol observed from the Ecovacs app."""
    def __init__(self, speed) -> None:
        raw = speed.name.lower() if hasattr(speed, "name") else str(speed).lower()
        aliases = {"normal": "auto", "max_plus": "max"}
        value = aliases.get(raw, raw)
        if value not in {"quiet", "auto", "strong", "max"}:
            raise ValueError(f"Unsupported Y1 PRO suction mode: {speed}")
        super().__init__("50011", {"fanMode": value})


class Y1ProWaterCommand(CustomCommand):
    """Set Y1 water flow using the numeric protocol observed from the Ecovacs app."""
    def __init__(self, amount) -> None:
        raw = amount.name.lower() if hasattr(amount, "name") else str(amount).lower()
        aliases = {"medium": "mid"}
        value = aliases.get(raw, raw)
        if value not in {"low", "mid", "high"}:
            raise ValueError(f"Unsupported Y1 PRO water mode: {amount}")
        super().__init__("50013", {"waterMode": value})
'''
    text = _replace_once(text, marker, additions + marker, "Y1 command insertion point")

    state_anchor = '''        pause = data.get("pauseSwitch")
'''
    state_additions = '''        fan_mode = data.get("fanMode")
        if isinstance(fan_mode, str):
            fan_map = {
                "quiet": Y1ProFanMode.QUIET,
                "auto": Y1ProFanMode.AUTO,
                "strong": Y1ProFanMode.STRONG,
                "max": Y1ProFanMode.MAX,
            }
            if fan_mode.lower() in fan_map:
                event_bus.notify(FanSpeedEvent(fan_map[fan_mode.lower()]))
                handled = True

        water_mode = data.get("waterMode")
        if isinstance(water_mode, str):
            water_map = {
                "low": Y1ProWaterMode.LOW,
                "mid": Y1ProWaterMode.MID,
                "high": Y1ProWaterMode.HIGH,
            }
            if water_mode.lower() in water_map:
                event_bus.notify(WaterAmountEvent(water_map[water_mode.lower()]))
                handled = True

        mop_state = data.get("mopState")
        if isinstance(mop_state, str):
            event_bus.notify(MopAttachedEvent(mop_state.lower() == "installed"))
            handled = True

'''
    text = _replace_once(text, state_anchor, state_additions + state_anchor, "10000 setting event handler")

    old_fan = '            fan_speed=CapabilitySetTypes(event=FanSpeedEvent, get=[], set=SetFanSpeed, types=(FanSpeedLevel.QUIET, FanSpeedLevel.NORMAL, FanSpeedLevel.MAX, FanSpeedLevel.MAX_PLUS)),\n'
    new_fan = '            fan_speed=CapabilitySetTypes(event=FanSpeedEvent, get=[Y1ProFieldCommand(["fanMode"])], set=Y1ProFanSpeedCommand, types=(Y1ProFanMode.QUIET, Y1ProFanMode.AUTO, Y1ProFanMode.STRONG, Y1ProFanMode.MAX)),\n'
    text = _replace_once(text, old_fan, new_fan, "fan speed capability")

    old_water = '            water=None,\n'
    new_water = '''            water=CapabilityWater(
                amount=CapabilitySetTypes(
                    event=WaterAmountEvent,
                    get=[Y1ProFieldCommand(["waterMode"])],
                    set=Y1ProWaterCommand,
                    types=(Y1ProWaterMode.LOW, Y1ProWaterMode.MID, Y1ProWaterMode.HIGH),
                ),
                mop_attached=CapabilityEvent(MopAttachedEvent, [Y1ProFieldCommand(["mopState"])]),
            ),
'''
    text = _replace_once(text, old_water, new_water, "water capability")

    # Fail before installation if the generated Python itself is malformed.
    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_187()
    # Reuse the strict, byte-for-byte installer from 2.0.16 with the new source.
    installer.PROFILE_VERSION = PROFILE_VERSION
    installer._PROFILE_BUILD_ERROR = None
except Exception as exc:
    _PROFILE_BUILD_ERROR = str(exc)
    installer.PROFILE_VERSION = PROFILE_VERSION
    installer._PROFILE_BUILD_ERROR = _PROFILE_BUILD_ERROR
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

# The strict functions reference installer module globals at call time, so after
# the version/path switch above they validate and install 1.8.7 exactly.
w.s.patch_status = installer.patch_status_strict
w.s.install_patch = installer.install_patch_strict

_base_diagnose = w.s.diagnose

def diagnose_223():
    result = _base_diagnose()
    result["version"] = VERSION
    result["y1pro_controls"] = {
        "profile": PROFILE_VERSION,
        "suction": {"command": "50011", "values": ["quiet", "auto", "strong", "max"]},
        "water": {"command": "50013", "values": ["low", "mid", "high"]},
        "event_channel": "10000",
        "build_error": _PROFILE_BUILD_ERROR,
    }
    return result

w.s.diagnose = diagnose_223
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.22", "v2.0.23")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
