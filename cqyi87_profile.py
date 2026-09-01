"""DEEBOT Y1 PRO compatibility profile."""
from __future__ import annotations

from typing import Any

from deebot_client.capabilities import (
    Capabilities,
    CapabilityClean,
    CapabilityCleanAction,
    CapabilityCustomCommand,
    CapabilityEvent,
    CapabilityExecute,
    CapabilityLifeSpan,
    CapabilitySetTypes,
    CapabilitySettings,
    CapabilityStats,
    DeviceType,
)
from deebot_client.commands.json.clean import CleanArea
from deebot_client.commands.json.custom import CustomCommand
from deebot_client.commands.json.fan_speed import SetFanSpeed
from deebot_client.commands.json.life_span import ResetLifeSpan
from deebot_client.const import DataType
from deebot_client.events import (
    AvailabilityEvent,
    BatteryEvent,
    CustomCommandEvent,
    FanSpeedEvent,
    FanSpeedLevel,
    LifeSpanEvent,
    ReportStatsEvent,
    StateEvent,
    StatsEvent,
    TotalStatsEvent,
)
from deebot_client.message import HandlingResult, MessageBodyDataDict
from deebot_client.messages.json import MESSAGES
from deebot_client.models import CleanAction, CleanMode, State, StaticDeviceInfo

Y1PRO_PATCH_VERSION = "1.5.13"

_Y1PRO_PAUSED = False
_Y1PRO_CHARGE_STATUS: bool | None = None


class Y1ProClean(CustomCommand):
    def __init__(self, action: CleanAction) -> None:
        if action == CleanAction.START:
            if _Y1PRO_PAUSED:
                super().__init__("40011", {"pauseSwitch": False})
            else:
                super().__init__("40001", {"cleanSwitch": True, "cleanMode": "smart"})
            return
        if action == CleanAction.PAUSE:
            super().__init__("40009", {"pauseSwitch": True})
            return
        if action == CleanAction.RESUME:
            super().__init__("40011", {"pauseSwitch": False})
            return
        super().__init__("clean", {"act": action.value})


class Y1ProCharge(CustomCommand):
    def __init__(self) -> None:
        super().__init__("40013", {"chargeSwitch": True})


class Y1ProStateMessage(MessageBodyDataDict):
    """Passively map observed Y1 PRO 10000 updates to HA events."""

    NAME = "10000"

    @classmethod
    def _handle_body_data_dict(cls, event_bus, data: dict[str, Any]) -> HandlingResult:
        global _Y1PRO_PAUSED, _Y1PRO_CHARGE_STATUS

        handled = False
        battery = data.get("battery")
        pause_switch = data.get("pauseSwitch")
        status = data.get("status")
        charge_status = data.get("chargeStatus")

        # Y1 PRO publishes battery percentage directly in message 10000.
        # Keep this passive: do not add the unsupported 10001 polling path.
        if isinstance(battery, (int, float)) and not isinstance(battery, bool):
            battery_value = int(battery)
            if 0 <= battery_value <= 100:
                event_bus.notify(BatteryEvent(battery_value))
                handled = True

        if isinstance(charge_status, bool):
            _Y1PRO_CHARGE_STATUS = charge_status
            handled = True
            if charge_status:
                _Y1PRO_PAUSED = False
                event_bus.notify(StateEvent(State.DOCKED))
                return HandlingResult.success()

        if pause_switch is True:
            _Y1PRO_PAUSED = True
            event_bus.notify(StateEvent(State.PAUSED))
            return HandlingResult.success()

        if pause_switch is False:
            _Y1PRO_PAUSED = False
            handled = True

        if isinstance(status, str):
            normalized = status.lower()
            if normalized == "smartclean":
                _Y1PRO_PAUSED = False
                _Y1PRO_CHARGE_STATUS = False
                event_bus.notify(StateEvent(State.CLEANING))
                return HandlingResult.success()
            if normalized == "gocharge":
                _Y1PRO_PAUSED = False
                _Y1PRO_CHARGE_STATUS = False
                event_bus.notify(StateEvent(State.RETURNING))
                return HandlingResult.success()
            if normalized == "idle":
                _Y1PRO_PAUSED = False
                state = State.DOCKED if _Y1PRO_CHARGE_STATUS is True else State.IDLE
                event_bus.notify(StateEvent(state))
                return HandlingResult.success()

        return HandlingResult.success() if handled else HandlingResult.analyse()


MESSAGES["10000"] = Y1ProStateMessage


def get_device_info() -> StaticDeviceInfo:
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=CapabilityEvent(BatteryEvent, []),
            charge=CapabilityExecute(Y1ProCharge),
            clean=CapabilityClean(
                action=CapabilityCleanAction(command=Y1ProClean, area=CleanArea)
            ),
            custom=CapabilityCustomCommand(
                event=CustomCommandEvent, get=[], set=CustomCommand
            ),
            error=None,
            fan_speed=CapabilitySetTypes(
                event=FanSpeedEvent,
                get=[],
                set=SetFanSpeed,
                types=(
                    FanSpeedLevel.QUIET,
                    FanSpeedLevel.NORMAL,
                    FanSpeedLevel.MAX,
                    FanSpeedLevel.MAX_PLUS,
                ),
            ),
            life_span=CapabilityLifeSpan(
                event=LifeSpanEvent, get=[], reset=ResetLifeSpan, types=()
            ),
            map=None,
            network=None,
            play_sound=None,
            settings=CapabilitySettings(),
            state=CapabilityEvent(StateEvent, []),
            station=None,
            stats=CapabilityStats(
                clean=CapabilityEvent(StatsEvent, []),
                report=CapabilityEvent(ReportStatsEvent, []),
                total=CapabilityEvent(TotalStatsEvent, []),
            ),
            water=None,
        ),
    )
