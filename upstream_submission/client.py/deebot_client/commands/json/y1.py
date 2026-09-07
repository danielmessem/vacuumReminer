"""DEEBOT Y1 PRO (cqyi87) numeric JSON commands.

Drafted for upstream review against DeebotUniverse/client.py dev.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any

from deebot_client.commands.json.common import ExecuteCommand, JsonCommandMqttP2P
from deebot_client.message import HandlingResult, HandlingState
from deebot_client.models import CleanAction, CleanMode

if TYPE_CHECKING:
    from deebot_client.event_bus import EventBus


class _Y1AndroidPayload:
    """Use the request envelope captured from the Ecovacs Android app."""

    def _get_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "header": {
                "channel": "Android",
                "m": "request",
                "pri": 2,
                "reqid": secrets.token_hex(4),
                "ts": str(int(time.time() * 1000)),
                "tzc": "Africa/Johannesburg",
                "tzm": 120,
                "ver": "0.0.22",
            }
        }
        if self._args:
            payload["body"] = {"data": self._args}
        return payload


class _Y1Execute(_Y1AndroidPayload, ExecuteCommand, JsonCommandMqttP2P):
    """Base for Y1 commands which can receive MQTT P2P acknowledgements."""

    @classmethod
    def create_from_mqtt(cls, payload: str | bytes | bytearray):
        # Outbound command instances are normally retained by the MQTT client.
        # This constructor exists so the class satisfies CommandMqttP2P routing.
        return cls._create_from_payload(payload)

    @classmethod
    def _create_from_payload(cls, payload: str | bytes | bytearray):
        raise NotImplementedError

    def _handle_mqtt_p2p(self, event_bus: EventBus, response: dict[str, Any]) -> None:
        # ExecuteCommand already defines the success semantics for body.code == 0.
        body = response.get("body", response)
        self._handle_body(event_bus, body if isinstance(body, dict) else {})


class Y1Clean(_Y1Execute):
    """Start, pause, resume or stop a Y1 PRO cleaning task."""

    # The Y1 uses different numeric commands for each action. NAME is replaced
    # per instance before Command.execute builds the API request.
    NAME = "40001"

    def __init__(self, action: CleanAction) -> None:
        if action == CleanAction.START:
            self.NAME = "40001"
            args = {"cleanSwitch": True, "cleanMode": "smart"}
        elif action == CleanAction.PAUSE:
            self.NAME = "40009"
            args = {"pauseSwitch": True}
        elif action == CleanAction.RESUME:
            self.NAME = "40011"
            args = {"pauseSwitch": False}
        elif action == CleanAction.STOP:
            # STOP has not been independently captured yet. Do not invent a
            # protocol mapping; callers should not expose it until verified.
            raise NotImplementedError("Y1 PRO stop command is not verified")
        else:
            raise ValueError(f"Unsupported Y1 PRO clean action: {action}")
        super().__init__(args)

    @classmethod
    def _create_from_payload(cls, payload: str | bytes | bytearray):
        raise NotImplementedError("Y1 clean commands are created from CleanAction")


class Y1CleanArea(_Y1Execute):
    """Start cleaning one or more room/area IDs."""

    NAME = "40007"

    def __init__(
        self, mode: CleanMode, area: list[int | float], cleanings: int = 1
    ) -> None:
        if mode not in (CleanMode.SPOT_AREA, CleanMode.CUSTOM_AREA, CleanMode.FREE_CLEAN):
            # The wire protocol itself is room-ID based; mode is accepted to match
            # CapabilityCleanAction's area callable signature.
            pass
        if cleanings != 1:
            raise NotImplementedError("Repeated Y1 PRO room cleaning is not verified")
        super().__init__(
            {
                "cleanSwitch": True,
                "cleanMode": "area",
                "cleanValues": [int(value) for value in area],
            }
        )

    @classmethod
    def _create_from_payload(cls, payload: str | bytes | bytearray):
        raise NotImplementedError("Y1 area commands are created from room IDs")


class Y1Charge(_Y1Execute):
    """Return the Y1 PRO to its charging dock."""

    NAME = "40013"

    def __init__(self) -> None:
        super().__init__({"chargeSwitch": True})

    @classmethod
    def _create_from_payload(cls, payload: str | bytes | bytearray):
        return cls()


class Y1FieldQuery(_Y1AndroidPayload, JsonCommandMqttP2P):
    """Read one or more fields through the Y1 10001 query."""

    NAME = "10001"

    def __init__(self, fields: list[str], *, is_available_check: bool = False) -> None:
        super().__init__({"fields": fields})
        self._is_available_check = is_available_check

    @classmethod
    def create_from_mqtt(cls, payload: str | bytes | bytearray):
        import orjson

        data = orjson.loads(payload).get("body", {}).get("data", {})
        fields = data.get("fields", []) if isinstance(data, dict) else []
        return cls(list(fields) if isinstance(fields, list) else [])

    def _handle_response(
        self, event_bus: EventBus, response: dict[str, Any]
    ) -> HandlingResult:
        if response.get("ret") != "ok":
            return HandlingResult(HandlingState.FAILED)
        payload = response.get("resp", response)
        self._handle_mqtt_p2p(event_bus, payload if isinstance(payload, dict) else {})
        return HandlingResult.success()

    def _handle_mqtt_p2p(self, event_bus: EventBus, response: dict[str, Any]) -> None:
        from deebot_client.messages.json.y1 import handle_y1_state_data

        body = response.get("body", response)
        if not isinstance(body, dict) or body.get("code", 0) not in (0, None):
            return
        data = body.get("data", {})
        if isinstance(data, dict):
            handle_y1_state_data(event_bus, data)
