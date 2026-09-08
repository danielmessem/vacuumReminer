"""DEEBOT Y1 PRO (cqyi87) numeric JSON commands.

Drafted for upstream review against DeebotUniverse/client.py dev.
"""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any

import orjson

from deebot_client.command import Command
from deebot_client.commands.json.common import ExecuteCommand, JsonCommandMqttP2P
from deebot_client.message import HandlingResult, HandlingState
from deebot_client.models import CleanAction, CleanMode

if TYPE_CHECKING:
    from deebot_client.event_bus import EventBus


class _Y1NumericPayload:
    """Build the cqyi87 numeric request envelope observed from the Ecovacs app."""

    def _get_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "header": {
                "channel": "rop",
                "m": "cloudctl",
                "pri": 3,
                "reqid": secrets.token_hex(4),
                "ts": str(int(time.time() * 1000)),
                "ver": "0.0.1",
            }
        }
        if self._args:
            payload["body"] = {"data": self._args}
        return payload


class _Y1Execute(_Y1NumericPayload, ExecuteCommand, JsonCommandMqttP2P):
    """Base for fixed-name Y1 commands with MQTT P2P acknowledgements."""

    def _handle_mqtt_p2p(self, event_bus: EventBus, response: dict[str, Any]) -> None:
        body = response.get("body", response)
        self._handle_body(event_bus, body if isinstance(body, dict) else {})


class Y1StartClean(_Y1Execute):
    """Start smart cleaning."""

    NAME = "40001"

    def __init__(self) -> None:
        super().__init__({"cleanSwitch": True, "cleanMode": "smart"})

    @classmethod
    def _create_from_mqtt(cls, data: dict[str, Any]) -> Y1StartClean:
        return cls()


class Y1PauseClean(_Y1Execute):
    """Pause the current cleaning task."""

    NAME = "40009"

    def __init__(self) -> None:
        super().__init__({"pauseSwitch": True})

    @classmethod
    def _create_from_mqtt(cls, data: dict[str, Any]) -> Y1PauseClean:
        return cls()


class Y1ResumeClean(_Y1Execute):
    """Resume a paused cleaning task."""

    NAME = "40011"

    def __init__(self) -> None:
        super().__init__({"pauseSwitch": False})

    @classmethod
    def _create_from_mqtt(cls, data: dict[str, Any]) -> Y1ResumeClean:
        return cls()


def Y1Clean(action: CleanAction) -> Command:
    """Create the fixed numeric command for a clean action."""
    if action == CleanAction.START:
        return Y1StartClean()
    if action == CleanAction.PAUSE:
        return Y1PauseClean()
    if action == CleanAction.RESUME:
        return Y1ResumeClean()
    if action == CleanAction.STOP:
        raise NotImplementedError("Y1 PRO stop command is not verified")
    raise ValueError(f"Unsupported Y1 PRO clean action: {action}")


class Y1CleanArea(_Y1Execute):
    """Start cleaning one or more room/area IDs."""

    NAME = "40007"

    def __init__(
        self, mode: CleanMode, area: list[int | float], cleanings: int = 1
    ) -> None:
        # `mode` is accepted to match CapabilityCleanAction.area's callable
        # signature. The observed Y1 wire protocol is room-ID based.
        del mode
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
    def _create_from_mqtt(cls, data: dict[str, Any]) -> Y1CleanArea:
        values = data.get("cleanValues", [])
        return cls(
            CleanMode.SPOT_AREA,
            values if isinstance(values, list) else [],
        )


class Y1Charge(_Y1Execute):
    """Return the Y1 PRO to its charging dock."""

    NAME = "40013"

    def __init__(self) -> None:
        super().__init__({"chargeSwitch": True})

    @classmethod
    def _create_from_mqtt(cls, data: dict[str, Any]) -> Y1Charge:
        return cls()


class Y1FieldQuery(_Y1NumericPayload, JsonCommandMqttP2P):
    """Read fields through the Y1 10001 query."""

    NAME = "10001"

    def __init__(
        self, fields: list[str] | tuple[str, ...], *, is_available_check: bool = False
    ) -> None:
        self.fields = tuple(str(field) for field in fields)
        super().__init__({"fields": list(self.fields)})
        self._is_available_check = is_available_check

    @classmethod
    def _create_from_mqtt(cls, data: dict[str, Any]) -> Y1FieldQuery:
        fields = data.get("fields", [])
        return cls(fields if isinstance(fields, list) else [])

    def _handle_response(
        self, event_bus: EventBus, response: dict[str, Any]
    ) -> HandlingResult:
        data: Any = response.get("resp", response)
        if response.get("ret") not in (None, "ok"):
            return HandlingResult(HandlingState.FAILED)
        return self._handle_field_data(event_bus, data)

    def _handle_field_data(self, event_bus: EventBus, value: Any) -> HandlingResult:
        from deebot_client.messages.json.y1 import handle_y1_state_data  # noqa: PLC0415

        if isinstance(value, (str, bytes, bytearray)):
            try:
                value = orjson.loads(value)
            except Exception:
                return HandlingResult.analyse()

        if isinstance(value, dict) and "body" in value:
            body = value.get("body", {})
            if not isinstance(body, dict) or body.get("code", 0) not in (0, None):
                return HandlingResult(HandlingState.FAILED)
            value = body.get("data", {})
        elif isinstance(value, dict) and "data" in value:
            value = value.get("data", {})

        if not isinstance(value, dict):
            return HandlingResult.analyse()
        return handle_y1_state_data(event_bus, value)

    def _handle_mqtt_p2p(self, event_bus: EventBus, response: dict[str, Any]) -> None:
        self._handle_field_data(event_bus, response)
