#!/usr/bin/env python3
"""Hotfix wrapper for DEEBOT Y1 PRO Diagnostics 2.0.6 / profile 1.7.6."""
from pathlib import Path

import server_wrapper_v181 as w

VERSION = "2.0.6"
PROFILE_VERSION = "1.7.6"


def build_profile_176():
    """Keep Y1 available and bootstrap state without false offline probes."""
    src = Path("/app/cqyi87_profile_172.py")
    if not src.exists():
        src = w.build_profile_172()
    dst = Path("/app/cqyi87_profile_176.py")
    text = src.read_text()

    # Correct the kw-only AvailabilityEvent constructor.
    text = text.replace(
        "event_bus.notify(AvailabilityEvent(True))",
        "event_bus.notify(AvailabilityEvent(available=True))",
    )

    # Y1 PRO cqyi87 often returns errno 500 to cloud 10001 battery/chargeStatus
    # probes while it is otherwise online on MQTT. Do not use those probes for
    # availability. Incoming MQTT traffic and successful commands already mark
    # Device available.
    old_cap = '            availability=CapabilityEvent(AvailabilityEvent, [Y1ProFieldCommand(["battery"], is_available_check=True), Y1ProFieldCommand(["chargeStatus"], is_available_check=True, bootstrap_state=True)]),\n'
    new_cap = '            availability=CapabilityEvent(AvailabilityEvent, []),\n'
    if old_cap not in text:
        raise RuntimeError("Could not locate Y1 availability capability")
    text = text.replace(old_cap, new_cap, 1)

    # The official Ecovacs app queries 10001 fields:[status] and receives values
    # such as status:idle. Use that proven field as the HA state bootstrap, but do
    # not attach availability semantics to it. Failure leaves state unknown rather
    # than falsely marking the robot offline.
    old_state = '            state=CapabilityEvent(StateEvent, []),\n'
    new_state = '            state=CapabilityEvent(StateEvent, [Y1ProFieldCommand(["status"])]),\n'
    if old_state not in text:
        raise RuntimeError("Could not locate Y1 state capability")
    text = text.replace(old_state, new_state, 1)

    # A real state-bearing response is explicit proof the robot is online.
    # Ignore MQTT request echoes that contain only {fields:[...]}.
    old_block = '''        if isinstance(data, dict):\n            if self.is_available_check:\n                event_bus.notify(AvailabilityEvent(available=True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n'''
    new_block = '''        if isinstance(data, dict):\n            if any(key in data for key in ("battery", "chargeStatus", "status", "pauseSwitch", "workMode")):\n                event_bus.notify(AvailabilityEvent(available=True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n'''
    if old_block not in text:
        raise RuntimeError("Could not locate Y1 field response availability block")
    text = text.replace(old_block, new_block, 1)

    text = text.replace('Y1PRO_PATCH_VERSION = "1.7.2"', 'Y1PRO_PATCH_VERSION = "1.7.6"', 1)
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_176()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.1", "v2.0.6")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
