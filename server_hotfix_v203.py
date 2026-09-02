#!/usr/bin/env python3
"""Hotfix wrapper for DEEBOT Y1 PRO Diagnostics 2.0.7 / profile 1.7.7."""
from pathlib import Path

import server_wrapper_v181 as w

VERSION = "2.0.7"
PROFILE_VERSION = "1.7.7"


def build_profile_177():
    """Keep Y1 available and refresh state/battery over direct MQTT P2P."""
    src = Path("/app/cqyi87_profile_172.py")
    if not src.exists():
        src = w.build_profile_172()
    dst = Path("/app/cqyi87_profile_177.py")
    text = src.read_text()

    # Correct the kw-only AvailabilityEvent constructor.
    text = text.replace(
        "event_bus.notify(AvailabilityEvent(True))",
        "event_bus.notify(AvailabilityEvent(available=True))",
    )

    # Never use Y1 10001 field queries as availability probes. A sleeping Y1 can
    # return cloud errno 500 while remaining connected to MQTT.
    old_cap = '            availability=CapabilityEvent(AvailabilityEvent, [Y1ProFieldCommand(["battery"], is_available_check=True), Y1ProFieldCommand(["chargeStatus"], is_available_check=True, bootstrap_state=True)]),\n'
    new_cap = '            availability=CapabilityEvent(AvailabilityEvent, []),\n'
    if old_cap not in text:
        raise RuntimeError("Could not locate Y1 availability capability")
    text = text.replace(old_cap, new_cap, 1)

    # Official app capture proves these exact 10001 fields are the native Y1
    # state/battery queries. They are transported directly over MQTT below.
    old_state = '            state=CapabilityEvent(StateEvent, []),\n'
    new_state = '            state=CapabilityEvent(StateEvent, [Y1ProFieldCommand(["status"])]),\n'
    if old_state not in text:
        raise RuntimeError("Could not locate Y1 state capability")
    text = text.replace(old_state, new_state, 1)

    # A real state-bearing response is explicit proof the robot is online.
    old_block = '''        if isinstance(data, dict):\n            if self.is_available_check:\n                event_bus.notify(AvailabilityEvent(available=True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n'''
    new_block = '''        if isinstance(data, dict):\n            if any(key in data for key in ("battery", "chargeStatus", "status", "pauseSwitch", "workMode")):\n                event_bus.notify(AvailabilityEvent(available=True))\n            result = Y1ProStateMessage._handle_body_data_dict(event_bus, data)\n'''
    if old_block not in text:
        raise RuntimeError("Could not locate Y1 field response availability block")
    text = text.replace(old_block, new_block, 1)

    # JsonCommandMqttP2P passes the complete MQTT response object. Unwrap the
    # Ecovacs body.data envelope before feeding it to the Y1 field parser.
    old_p2p = '''    def _handle_mqtt_p2p(self, event_bus, response: dict[str, Any]) -> None:\n        self._handle_field_data(event_bus, response)\n'''
    new_p2p = '''    def _handle_mqtt_p2p(self, event_bus, response: dict[str, Any]) -> None:\n        data: Any = response\n        if isinstance(response, dict):\n            body = response.get("body")\n            if isinstance(body, dict):\n                data = body.get("data", body)\n            else:\n                data = response.get("data", response)\n        self._handle_field_data(event_bus, data)\n'''
    if old_p2p not in text:
        raise RuntimeError("Could not locate Y1 P2P response handler")
    text = text.replace(old_p2p, new_p2p, 1)

    text = text.replace('Y1PRO_PATCH_VERSION = "1.7.2"', 'Y1PRO_PATCH_VERSION = "1.7.7"', 1)

    # deebot-client can decode MQTT P2P responses, but Command.execute always
    # sends via the cloud devmanager endpoint. For cqyi87 field reads, retain the
    # live MQTT client used by Device.initialize and publish the request on that
    # same connection instead. This avoids a second broker login and the cloud
    # errno 500 path entirely.
    text += r'''

# --- Y1 PRO direct MQTT P2P field-query transport (profile 1.7.7) ---
import secrets as _y1_secrets
import time as _y1_time
from deebot_client.command import DeviceCommandResult as _Y1DeviceCommandResult
from deebot_client.device import Device as _Y1Device
from deebot_client.mqtt_client import MqttClient as _Y1MqttClient

if not getattr(_Y1MqttClient, "_y1pro_active_client_patch", False):
    _y1_orig_pending_worker = _Y1MqttClient._pending_subscriptions_worker

    async def _y1_pending_worker(self, client):
        self._y1pro_active_client = client
        try:
            await _y1_orig_pending_worker(self, client)
        finally:
            self._y1pro_active_client = None

    _Y1MqttClient._pending_subscriptions_worker = _y1_pending_worker
    _Y1MqttClient._y1pro_active_client_patch = True

if not getattr(_Y1Device, "_y1pro_direct_field_patch", False):
    _y1_orig_initialize = _Y1Device.initialize
    _y1_orig_execute_command = _Y1Device._execute_command

    async def _y1_initialize(self, client):
        if self.device_info.get("class") == "cqyi87":
            self._y1pro_mqtt_client = client
        await _y1_orig_initialize(self, client)

    async def _y1_execute_command(self, command):
        if self.device_info.get("class") == "cqyi87" and isinstance(command, Y1ProFieldCommand):
            mqtt = getattr(self, "_y1pro_mqtt_client", None)
            active = getattr(mqtt, "_y1pro_active_client", None) if mqtt is not None else None
            if active is None:
                _LOGGER.warning("Y1PRO_P2P no active MQTT client for fields=%s", list(command.fields))
                return _Y1DeviceCommandResult(device_reached=False)

            reqid = _y1_secrets.token_hex(4)
            api = self.device_info
            topic = (
                f"iot/p2p/{command.NAME}/HomeAssistant/ecosys/1234/"
                f"{api['did']}/{api['class']}/{api['resource']}/q/{reqid}/{command.DATA_TYPE.value}"
            )
            payload = orjson.dumps({
                "body": {"data": {"fields": list(command.fields)}},
                "header": {
                    "channel": "HomeAssistant",
                    "m": "request",
                    "pri": 2,
                    "reqid": reqid,
                    "ts": str(int(_y1_time.time() * 1000)),
                    "tzc": "Africa/Johannesburg",
                    "tzm": 120,
                    "ver": "0.0.22",
                },
            })

            # Register before publish so the normal mqtt_client P2P response path
            # can correlate and dispatch the robot response even if the broker does
            # not echo our own request back to this client.
            mqtt._received_p2p_commands[reqid] = command
            try:
                await active.publish(topic, payload)
                _LOGGER.debug("Y1PRO_P2P sent fields=%s reqid=%s", list(command.fields), reqid)
                return _Y1DeviceCommandResult(
                    device_reached=False,
                    raw_response={"transport": "mqtt_p2p", "request_id": reqid},
                )
            except Exception:
                mqtt._received_p2p_commands.pop(reqid, None)
                _LOGGER.warning("Y1PRO_P2P publish failed for fields=%s", list(command.fields), exc_info=True)
                return _Y1DeviceCommandResult(device_reached=False)

        return await _y1_orig_execute_command(self, command)

    _Y1Device.initialize = _y1_initialize
    _Y1Device._execute_command = _y1_execute_command
    _Y1Device._y1pro_direct_field_patch = True
'''

    dst.write_text(text)
    return dst


try:
    w.s.PROFILE_PATH = build_profile_177()
except Exception as exc:
    print(f"WARNING: could not build Y1 PRO {PROFILE_VERSION} profile: {exc}", flush=True)

w.VERSION = VERSION
w.s.VERSION = VERSION
w.s.HTML = w.s.HTML.replace("v2.0.1", "v2.0.7")

if __name__ == "__main__":
    w.s.SHARE.mkdir(parents=True, exist_ok=True)
    token_state = "available" if w.supervisor_token() else "missing"
    print(f"DEEBOT Y1 PRO Diagnostics {VERSION} on :{w.s.PORT}; HA API token: {token_state}", flush=True)
    w.s.ThreadingHTTPServer(("0.0.0.0", w.s.PORT), w.s.Handler).serve_forever()
