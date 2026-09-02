#!/usr/bin/env python3
"""Hotfix wrapper for DEEBOT Y1 PRO Diagnostics 2.0.8 / profile 1.7.8."""
from pathlib import Path

import server_wrapper_v181 as w

VERSION = "2.0.8"
PROFILE_VERSION = "1.7.8"


def build_profile_178():
    """Use passive Y1 telemetry for state/battery and avoid broken 10001 polling."""
    src = Path("/app/cqyi87_profile_172.py")
    if not src.exists():
        src = w.build_profile_172()
    dst = Path("/app/cqyi87_profile_178.py")
    text = src.read_text()

    # Correct the kw-only AvailabilityEvent constructor in the generated base.
    text = text.replace(
        "event_bus.notify(AvailabilityEvent(True))",
        "event_bus.notify(AvailabilityEvent(available=True))",
    )

    # Do not use cloud 10001 field reads as an availability test. The Y1 can be
    # online on MQTT while devmanager returns errno 500 for these requests.
    old_avail = '            availability=CapabilityEvent(AvailabilityEvent, [Y1ProFieldCommand(["battery"], is_available_check=True), Y1ProFieldCommand(["chargeStatus"], is_available_check=True, bootstrap_state=True)]),\n'
    new_avail = '            availability=CapabilityEvent(AvailabilityEvent, []),\n'
    if old_avail not in text:
        raise RuntimeError("Could not locate Y1 availability capability")
    text = text.replace(old_avail, new_avail, 1)

    # State and battery are populated from unsolicited 10000 / buried telemetry.
    # Active 10001 refreshes are deliberately disabled because this firmware often
    # returns errno 500 even while the robot is reachable and publishing MQTT.
    old_battery = '            battery=CapabilityEvent(BatteryEvent, [Y1ProFieldCommand(["battery"])]),\n'
    new_battery = '            battery=CapabilityEvent(BatteryEvent, []),\n'
    if old_battery not in text:
        raise RuntimeError("Could not locate Y1 battery capability")
    text = text.replace(old_battery, new_battery, 1)

    old_state = '            state=CapabilityEvent(StateEvent, []),\n'
    new_state = '            state=CapabilityEvent(StateEvent, []),\n'
    if old_state not in text:
        raise RuntimeError("Could not locate Y1 state capability")
    text = text.replace(old_state, new_state, 1)

    # A real state-bearing field response is still explicit proof of reachability
    # if one arrives from the Ecovacs helper/app path.
    old_block = '''        if isinstance(data, dict):\n            if self.is_available_check:\n                event_bus.notify(AvailabilityEvent(available=True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n'''
    new_block = '''        if isinstance(data, dict):\n            if any(key in data for key in ("battery", "chargeStatus", "status", "pauseSwitch", "workMode")):\n                event_bus.notify(AvailabilityEvent(available=True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n'''
    if old_block not in text:
        raise RuntimeError("Could not locate Y1 field response block")
    text = text.replace(old_block, new_block, 1)

    text = text.replace('Y1PRO_PATCH_VERSION = "1.7.2"', 'Y1PRO_PATCH_VERSION = "1.7.8"', 1)

    # The Y1 broadcasts useful state outside the normal 10000 message too.
    # Consume the two observed buried-point events before deebot-client logs them
    # as unknown. This is passive only: no cloud request and no extra MQTT session.
    text += r'''

# --- Y1 PRO passive telemetry bridge (profile 1.7.8) ---
from deebot_client.device import Device as _Y1Device

if not getattr(_Y1Device, "_y1pro_passive_telemetry_patch", False):
    _y1_orig_handle_message = _Y1Device._handle_message

    def _y1_handle_message(self, message_name, message_data):
        if self.device_info.get("class") == "cqyi87":
            try:
                obj = orjson.loads(message_data) if isinstance(message_data, (str, bytes, bytearray)) else message_data
                body = obj.get("body", {}) if isinstance(obj, dict) else {}
                if isinstance(body, dict):
                    if message_name == "onFwBuryPoint-bd_task-chargeState-evt":
                        battery = body.get("battery")
                        if isinstance(battery, (int, float)) and not isinstance(battery, bool) and 0 <= int(battery) <= 100:
                            self.events.notify(BatteryEvent(int(battery)))
                        charge = body.get("chargeStatus")
                        if charge in (1, True):
                            self.events.notify(StateEvent(State.DOCKED))
                        self.events.notify(AvailabilityEvent(available=True))
                    elif message_name == "onFwBuryPoint-task-evt":
                        act = str(body.get("act", "")).lower()
                        task_type = str(body.get("taskType", "")).lower()
                        if task_type == "clean":
                            if act in ("start", "resume"):
                                self.events.notify(StateEvent(State.CLEANING))
                            elif act in ("pause",):
                                self.events.notify(StateEvent(State.PAUSED))
                            elif act in ("stop", "finish", "end"):
                                self.events.notify(StateEvent(State.IDLE))
                            self.events.notify(AvailabilityEvent(available=True))
            except Exception:
                _LOGGER.debug("Y1 passive telemetry parse failed for %s", message_name, exc_info=True)
        return _y1_orig_handle_message(self, message_name, message_data)

    _Y1Device._handle_message = _y1_handle_message
    _Y1Device._y1pro_passive_telemetry_patch = True
'''

    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_178()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.1", "v2.0.8")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
