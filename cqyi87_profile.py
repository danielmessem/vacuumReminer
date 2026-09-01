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
    CustomCommandEvent,
    FanSpeedEvent,
    FanSpeedLevel,
    LifeSpanEvent,
    ReportStatsEvent,
    StateEvent,
    StatsEvent,
    TotalStatsEvent,
)
from deebot_client.messages import HandlingResult
from deebot_client.messages.json import MESSAGES
from deebot_client.messages.json.common import MessageBodyDataDict
from deebot_client.models import CleanAction, CleanMode, State, StaticDeviceInfo

Y1PRO_PATCH_VERSION = "1.5.8"


class Y1ProClean(CustomCommand):
    """Y1 PRO cleaning action.

    The official Android app for cqyi87 was observed starting cleaning with
    numeric command 40001 and body data:
        {"cleanSwitch": true, "cleanMode": "smart"}

    Only START uses that proven protocol. Other actions remain on the legacy
    path until their actual Y1 PRO app payloads are captured.
    """

    def __init__(self, action: CleanAction) -> None:
        if action == CleanAction.START:
            super().__init__(
                "40001",
                {"cleanSwitch": True, "cleanMode": "smart"},
            )
            return

        args: dict[str, Any] = {"act": action.value}
        if action == CleanAction.RESUME:
            args = {"act": action.value}
        super().__init__("clean", args)


class Y1ProCharge(CustomCommand):
    """Return Y1 PRO to its charger using the observed app protocol."""

    def __init__(self) -> None:
        super().__init__("40013", {"chargeSwitch": True})


class Y1ProStateMessage(MessageBodyDataDict):
    """Passively map observed Y1 PRO 10000 status updates to HA state."""

    NAME = "10000"

    @classmethod
    async def _handle_body_data_dict(cls, event_bus, data: dict[str, Any]) -> HandlingResult:
        status = data.get("status")
        pause_switch = data.get("pauseSwitch")

        if pause_switch is True:
            event_bus.notify(StateEvent(State.PAUSED))
            return HandlingResult.SUCCESS

        if isinstance(status, str):
            normalized = status.lower()
            if normalized == "smartclean":
                event_bus.notify(StateEvent(State.CLEANING))
                return HandlingResult.SUCCESS
            if normalized == "gocharge":
                event_bus.notify(StateEvent(State.RETURNING))
                return HandlingResult.SUCCESS

        return HandlingResult.ANALYSE


# Passive registration only: no polling/get commands are added.
MESSAGES["10000"] = Y1ProStateMessage


def get_device_info() -> StaticDeviceInfo:
    """Return the known-working conservative Y1 PRO profile."""
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=None,
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
                event=LifeSpanEvent,
                get=[],
                reset=ResetLifeSpan,
                types=(),
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
