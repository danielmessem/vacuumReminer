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
from deebot_client.message import HandlingResult, MessageBodyDataDict
from deebot_client.messages.json import MESSAGES
from deebot_client.models import CleanAction, CleanMode, State, StaticDeviceInfo

Y1PRO_PATCH_VERSION = "1.5.12"

# Home Assistant exposes a single start/resume path for this vacuum. The
# Y1 PRO requires different commands for a fresh start and a resume. These
# flags are updated only from passive robot telemetry.
_Y1PRO_PAUSED = False
_Y1PRO_CHARGE_STATUS: bool | None = None


class Y1ProClean(CustomCommand):
    """Y1 PRO cleaning actions using observed official-app protocols."""

    def __init__(self, action: CleanAction) -> None:
        if action == CleanAction.START:
            if _Y1PRO_PAUSED:
                super().__init__("40011", {"pauseSwitch": False})
            else:
                super().__init__(
                    "40001",
                    {"cleanSwitch": True, "cleanMode": "smart"},
                )
            return
        if action == CleanAction.PAUSE:
            super().__init__("40009", {"pauseSwitch": True})
            return
        if action == CleanAction.RESUME:
            super().__init__("40011", {"pauseSwitch": False})
            return

        args: dict[str, Any] = {"act": action.value}
        super().__init__("clean", args)


class Y1ProCharge(CustomCommand):
    """Return Y1 PRO to its charger using the observed app protocol."""

    def __init__(self) -> None:
        super().__init__("40013", {"chargeSwitch": True})


class Y1ProStateMessage(MessageBodyDataDict):
    """Passively map observed Y1 PRO 10000 updates to HA state."""

    NAME = "10000"

    @classmethod
    def _handle_body_data_dict(
        cls, event_bus, data: dict[str, Any]
    ) -> HandlingResult:
        global _Y1PRO_PAUSED, _Y1PRO_CHARGE_STATUS

        pause_switch = data.get("pauseSwitch")
        status = data.get("status")
        charge_status = data.get("chargeStatus")

        if isinstance(charge_status, bool):
            _Y1PRO_CHARGE_STATUS = charge_status
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

        # These telemetry-only fields are intentionally consumed even if they
        # do not determine a complete HA vacuum state on their own.
        if pause_switch is False or isinstance(charge_status, bool):
            return HandlingResult.success()

        return HandlingResult.analyse()


# Passive registration only: no polling/get commands are added.
MESSAGES["10000"] = Y1ProStateMessage


def get_device_info() -> StaticDeviceInfo:
    """Return the conservative Y1 PRO profile."""
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
