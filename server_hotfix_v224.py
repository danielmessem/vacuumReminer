#!/usr/bin/env python3
"""DEEBOT Y1 PRO Diagnostics 2.0.24 / profile 1.8.8.

UI-label correction only for Y1 suction level 2:
  Home Assistant: Standard
  Y1 wire value:  auto

Commands and robot protocol remain unchanged from profile 1.8.7.
"""
from pathlib import Path

import server_hotfix_v223 as h
import server_hotfix_v216 as installer

w = h.w
VERSION = "2.0.24"
PROFILE_VERSION = "1.8.8"
_PROFILE_BUILD_ERROR = None


def build_profile_188() -> Path:
    src = h.build_profile_187()
    dst = Path("/app/cqyi87_profile_188.py")
    text = src.read_text()

    old = 'Y1PRO_PATCH_VERSION = "1.8.7"'
    if old not in text:
        raise RuntimeError("Could not locate 1.8.7 profile marker")
    text = text.replace(old, 'Y1PRO_PATCH_VERSION = "1.8.8"', 1)

    # Keep the robot protocol value `auto`, but expose level 2 through the
    # standard deebot-client enum so Home Assistant labels it Standard.
    old_cap = 'types=(Y1ProFanMode.QUIET, Y1ProFanMode.AUTO, Y1ProFanMode.STRONG, Y1ProFanMode.MAX)'
    new_cap = 'types=(Y1ProFanMode.QUIET, FanSpeedLevel.NORMAL, Y1ProFanMode.STRONG, Y1ProFanMode.MAX)'
    if old_cap not in text:
        raise RuntimeError("Could not locate Y1 suction capability types")
    text = text.replace(old_cap, new_cap, 1)

    # Incoming Y1 `auto` must likewise become NORMAL so HA displays Standard.
    old_event = '"auto": Y1ProFanMode.AUTO,'
    new_event = '"auto": FanSpeedLevel.NORMAL,'
    if old_event not in text:
        raise RuntimeError("Could not locate Y1 auto event mapping")
    text = text.replace(old_event, new_event, 1)

    compile(text, str(dst), "exec")
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_188()
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

def diagnose_224():
    result = _base_diagnose()
    result["version"] = VERSION
    result["y1pro_controls"] = {
        "profile": PROFILE_VERSION,
        "suction": {
            "command": "50011",
            "ha_labels": ["quiet", "standard", "strong", "max"],
            "wire_values": ["quiet", "auto", "strong", "max"],
        },
        "water": {"command": "50013", "values": ["low", "mid", "high"]},
        "event_channel": "10000",
        "build_error": _PROFILE_BUILD_ERROR,
    }
    return result

w.s.diagnose = diagnose_224
w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.23", "v2.0.24")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(
        f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; "
        f"HA API token: {token_state}; expected profile {PROFILE_VERSION}",
        flush=True,
    )
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
