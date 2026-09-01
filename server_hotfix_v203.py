#!/usr/bin/env python3
"""Hotfix wrapper for DEEBOT Y1 PRO Diagnostics 2.0.3 / profile 1.7.4."""
from pathlib import Path

import server_wrapper_v181 as w

VERSION = "2.0.3"
PROFILE_VERSION = "1.7.4"


def build_profile_174():
    """Make Y1 availability recover from passive/app telemetry without false offline probes."""
    src = Path("/app/cqyi87_profile_172.py")
    if not src.exists():
        src = w.build_profile_172()
    dst = Path("/app/cqyi87_profile_174.py")
    text = src.read_text()

    # Correct the kw-only AvailabilityEvent constructor.
    text = text.replace(
        "event_bus.notify(AvailabilityEvent(True))",
        "event_bus.notify(AvailabilityEvent(available=True))",
    )

    # Do not use deebot-client's is_available_check semantics for Y1 startup probes.
    # On this model an asleep robot returns errno 500, which otherwise permanently
    # marks the entity unavailable until another explicit availability check succeeds.
    old_cap = '            availability=CapabilityEvent(AvailabilityEvent, [Y1ProFieldCommand(["battery"], is_available_check=True), Y1ProFieldCommand(["chargeStatus"], is_available_check=True, bootstrap_state=True)]),\n'
    new_cap = '            availability=CapabilityEvent(AvailabilityEvent, [Y1ProFieldCommand(["battery"]), Y1ProFieldCommand(["chargeStatus"], bootstrap_state=True)]),\n'
    if old_cap not in text:
        raise RuntimeError("Could not locate Y1 availability capability")
    text = text.replace(old_cap, new_cap, 1)

    # A successful state response from either HA or the Ecovacs app is proof that
    # the robot is online. Only mark available for real state-bearing payloads,
    # not for MQTT request echoes containing only {fields:[...]}.
    old_block = '''        if isinstance(data, dict):\n            if self.is_available_check:\n                event_bus.notify(AvailabilityEvent(available=True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n'''
    new_block = '''        if isinstance(data, dict):\n            if any(key in data for key in ("battery", "chargeStatus", "status", "pauseSwitch", "workMode")):\n                event_bus.notify(AvailabilityEvent(available=True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n'''
    if old_block not in text:
        raise RuntimeError("Could not locate Y1 field response availability block")
    text = text.replace(old_block, new_block, 1)

    text = text.replace('Y1PRO_PATCH_VERSION = "1.7.2"', 'Y1PRO_PATCH_VERSION = "1.7.4"', 1)
    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_174()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.1", "v2.0.3")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
