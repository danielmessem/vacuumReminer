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
from deebot_client.commands.json.charge import Charge
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
from deebot_client.models import CleanAction, CleanMode, StaticDeviceInfo

Y1PRO_PATCH_VERSION = "1.5.4"


class Y1ProClean(CustomCommand):
    """Y1 PRO cleaning action.

    The official Android app for cqyi87 was observed starting cleaning with
    numeric command 40001 and body data:
        {"cleanSwitch": true, "cleanMode": "smart"}

    Only START is changed to that proven protocol. Other actions retain the
    legacy clean command shape until their actual app payloads are captured.
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
            # Keep the current deebot-client legacy action value unchanged.
            args = {"act": action.value}
        super().__init__("clean", args)


def get_device_info() -> StaticDeviceInfo:
    """Return a conservative Y1 PRO profile using only proven-safe capabilities."""
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=None,
            charge=CapabilityExecute(Charge),
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
