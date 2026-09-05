"""DEEBOT Y1 PRO capabilities.

Candidate upstream implementation for device class cqyi87.
This first slice intentionally contains only the protocol needed for discovery,
core vacuum controls, battery and state. Map support is kept for a follow-up
change so the upstream review stays small.
"""

from __future__ import annotations

from typing import Any

import orjson

from deebot_client.capabilities import (
    Capabilities,
    CapabilityClean,
    CapabilityCleanAction,
    CapabilityCustomCommand,
    CapabilityEvent,
    CapabilityExecute,
    DeviceType,
)
from deebot_client.commands import COMMANDS_WITH_MQTT_P2P_HANDLING
from deebot_client.commands.json.common import JsonCommandMqttP2P
from deebot_client.commands.json.custom import CustomCommand
from deebot_client.const import DataType
from deebot_client.events import (
    AvailabilityEvent,
    BatteryEvent,
    CustomCommandEvent,
    StateEvent,
)
from deebot_client.message import HandlingResult, HandlingState, MessageBodyDataDict
from deebot_client.messages.json import MESSAGES
from deebot_client.models import CleanAction, CleanMode, State, StaticDeviceInfo

_paused = False
_charge_status: bool | None = None


class Y1ProClean(CustomCommand):
    """Control cleaning with the numeric protocol used by cqyi87."""

    def __init__(self, action: CleanAction) -> None:
        if action == CleanAction.START:
            if _paused:
                super().__init__("40011", {"pauseSwitch": False})
            else:
                super().__init__(
                    "40001", {"cleanSwitch": True, "cleanMode": "smart"}
                )
        elif action == CleanAction.PAUSE:
            super().__init__("40009", {"pauseSwitch": True})
        elif action == CleanAction.RESUME:
            super().__init__("40011", {"pauseSwitch": False})
        else:
            super().__init__("clean", {"act": action.value})


class Y1ProCleanArea(CustomCommand):
    """Start an area clean using Y1 room identifiers."""

    def __init__(
        self,
        mode: CleanMode,
        values: list[int | float],
        cleanings: int = 1,
    ) -> None:
        del mode, cleanings
        super().__init__(
            "40007",
            {
                "cleanSwitch": True,
                "cleanMode": "area",
                "cleanValues": [int(value) for value in values],
            },
        )


class Y1ProCharge(CustomCommand):
    """Return the Y1 PRO to its charging station."""

    def __init__(self) -> None:
        super().__init__("40013", {"chargeSwitch": True})


class Y1ProStateMessage(MessageBodyDataDict):
    """Handle multiplexed, partial cqyi87 state updates."""

    NAME = "10000"

    @classmethod
    def _handle_body_data_dict(
        cls, event_bus, data: dict[str, Any]
    ) -> HandlingResult:
        global _paused, _charge_status

        handled = False
        battery = data.get("battery")
        if (
            isinstance(battery, (int, float))
            and not isinstance(battery, bool)
            and 0 <= int(battery) <= 100
        ):
            event_bus.notify(BatteryEvent(int(battery)))
            handled = True

        charge_status = data.get("chargeStatus")
        if isinstance(charge_status, bool):
            _charge_status = charge_status
            handled = True
            if charge_status:
                _paused = False
                event_bus.notify(StateEvent(State.DOCKED))
                return HandlingResult.success()

        pause_switch = data.get("pauseSwitch")
        if pause_switch is True:
            _paused = True
            event_bus.notify(StateEvent(State.PAUSED))
            return HandlingResult.success()
        if pause_switch is False:
            _paused = False
            handled = True

        status = data.get("status")
        if isinstance(status, str):
            status = status.lower()
            if status in ("smartclean", "areaclean"):
                _paused = False
                _charge_status = False
                event_bus.notify(StateEvent(State.CLEANING))
                return HandlingResult.success()
            if status == "gocharge":
                _paused = False
                _charge_status = False
                event_bus.notify(StateEvent(State.RETURNING))
                return HandlingResult.success()
            if status == "idle":
                _paused = False
                event_bus.notify(
                    StateEvent(
                        State.DOCKED if _charge_status is True else State.IDLE
                    )
                )
                return HandlingResult.success()

        return HandlingResult.success() if handled else HandlingResult.analyse()


class Y1ProFieldCommand(JsonCommandMqttP2P):
    """Query cqyi87 fields using numeric command 10001."""

    NAME = "10001"

    def __init__(self, fields: list[str] | tuple[str, ...]) -> None:
        self.fields = tuple(str(field) for field in fields)
        super().__init__({"fields": list(self.fields)})

    @classmethod
    def create_from_mqtt(cls, payload: str | bytes | bytearray):
        obj = orjson.loads(payload)
        data = obj.get("body", {}).get("data", {})
        fields = data.get("fields", []) if isinstance(data, dict) else []
        return cls(fields if isinstance(fields, list) else [])

    def _handle_field_data(self, event_bus, data: Any) -> HandlingResult:
        if isinstance(data, (str, bytes, bytearray)):
            try:
                data = orjson.loads(data)
            except Exception:
                return HandlingResult.analyse()

        if isinstance(data, dict) and "body" in data:
            body = data.get("body", {})
            if isinstance(body, dict) and body.get("code", 0) not in (0, None):
                return HandlingResult(HandlingState.FAILED)
            data = body.get("data", {}) if isinstance(body, dict) else {}
        elif (
            isinstance(data, dict)
            and "data" in data
            and not any(
                key in data
                for key in ("battery", "chargeStatus", "status", "pauseSwitch")
            )
        ):
            data = data.get("data", {})

        if not isinstance(data, dict):
            return HandlingResult.analyse()
        return Y1ProStateMessage._handle_body_data_dict(event_bus, data)

    def _handle_response(self, event_bus, response: dict[str, Any]) -> HandlingResult:
        data: Any = response.get("resp", response)
        return self._handle_field_data(event_bus, data)

    def _handle_mqtt_p2p(self, event_bus, response: dict[str, Any]) -> None:
        self._handle_field_data(event_bus, response)


# cqyi87 publishes state with numeric names instead of the legacy JSON names.
MESSAGES["10000"] = Y1ProStateMessage
COMMANDS_WITH_MQTT_P2P_HANDLING.setdefault(DataType.JSON, {})[
    "10001"
] = Y1ProFieldCommand


def get_device_info() -> StaticDeviceInfo:
    """Get static device information for the DEEBOT Y1 PRO (cqyi87)."""
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            # Incoming MQTT traffic proves reachability. An empty refresh list is
            # intentional because cqyi87 does not implement legacy getBattery.
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=CapabilityEvent(
                BatteryEvent, [Y1ProFieldCommand(["battery"])]
            ),
            charge=CapabilityExecute(Y1ProCharge),
            clean=CapabilityClean(
                action=CapabilityCleanAction(
                    command=Y1ProClean,
                    area=Y1ProCleanArea,
                )
            ),
            custom=CapabilityCustomCommand(
                event=CustomCommandEvent,
                get=[],
                set=CustomCommand,
            ),
            state=CapabilityEvent(StateEvent, []),
        ),
    )
