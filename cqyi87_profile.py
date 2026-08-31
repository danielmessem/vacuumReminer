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
from deebot_client.commands.json.common import JsonCommandWithMessageHandling
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

Y1PRO_PATCH_VERSION = "1.5.5"


class Y1ProClean(CustomCommand):
    """Y1 PRO cleaning action using the proven numeric start protocol."""

    def __init__(self, action: CleanAction) -> None:
        if action == CleanAction.START:
            super().__init__(
                "40001",
                {"cleanSwitch": True, "cleanMode": "smart"},
            )
            return

        # Pause/resume/stop are intentionally left on the prior legacy path
        # until their real Y1 PRO app payloads have been captured.
        super().__init__("clean", {"act": action.value})


class Y1ProInfoMessage(MessageBodyDataDict):
    """Handle the Y1 PRO numeric 10000/10001 telemetry payload shape."""

    NAME = "10000"

    @classmethod
    def _handle_body_data_dict(
        cls, event_bus, data: dict[str, Any]
    ) -> HandlingResult:
        handled = False

        if "battery" in data:
            event_bus.notify(BatteryEvent(int(data["battery"])))
            handled = True

        # 10000 reports current-job statistics incrementally.
        if "cleanArea" in data or "cleanTime" in data:
            area = int(data["cleanArea"]) if "cleanArea" in data else None
            clean_time = int(data["cleanTime"]) if "cleanTime" in data else None
            event_bus.notify(StatsEvent(area, clean_time, data.get("status")))
            handled = True

        pause = data.get("pauseSwitch")
        status = data.get("status")
        charge_status = data.get("chargeStatus")

        # Only map states observed in real cqyi87 traffic so far.
        if pause is True:
            event_bus.notify(StateEvent(State.PAUSED))
            handled = True
        elif status == "smartClean":
            event_bus.notify(StateEvent(State.CLEANING))
            handled = True
        elif charge_status is True:
            event_bus.notify(StateEvent(State.DOCKED))
            handled = True

        return HandlingResult.success() if handled else HandlingResult.analyse()


class Y1ProBasicInfoMessage(MessageBodyDataDict):
    """Use firmware diagnostic basic-info telemetry as a secondary source."""

    NAME = "onFwBuryPoint-bd_basicinfo"

    @classmethod
    def _handle_body_data_dict(
        cls, event_bus, data: dict[str, Any]
    ) -> HandlingResult:
        handled = False

        if "battery" in data:
            event_bus.notify(BatteryEvent(int(data["battery"])))
            handled = True

        if data.get("status") == "smartClean":
            event_bus.notify(StateEvent(State.CLEANING))
            handled = True
        elif data.get("chargeStatus") is True:
            event_bus.notify(StateEvent(State.DOCKED))
            handled = True

        return HandlingResult.success() if handled else HandlingResult.analyse()


class Y1ProInfoQuery(Y1ProInfoMessage, JsonCommandWithMessageHandling):
    """Query selected Y1 PRO fields using numeric command 10001."""

    NAME = "10001"

    def __init__(self, fields: list[str]) -> None:
        super().__init__({"fields": fields})


# Register Y1 PRO-only numeric messages when this hardware profile is imported.
# These names are not used by the older JSON protocol in deebot-client 18.5.1.
MESSAGES["10000"] = Y1ProInfoMessage
MESSAGES["10001"] = Y1ProInfoQuery
MESSAGES["onFwBuryPoint-bd_basicinfo"] = Y1ProBasicInfoMessage


def get_device_info() -> StaticDeviceInfo:
    """Return Y1 PRO capabilities backed by observed cqyi87 traffic."""
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=CapabilityEvent(
                BatteryEvent,
                [Y1ProInfoQuery(["battery"])],
            ),
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
            state=CapabilityEvent(
                StateEvent,
                [Y1ProInfoQuery(["chargeStatus"])],
            ),
            station=None,
            stats=CapabilityStats(
                clean=CapabilityEvent(StatsEvent, []),
                report=CapabilityEvent(ReportStatsEvent, []),
                total=CapabilityEvent(TotalStatsEvent, []),
            ),
            water=None,
        ),
    )
