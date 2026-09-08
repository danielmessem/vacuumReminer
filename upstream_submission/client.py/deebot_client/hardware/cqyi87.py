"""DEEBOT Y1 PRO (cqyi87) capabilities."""

from __future__ import annotations

from typing import NoReturn

from deebot_client.capabilities import (
    Capabilities,
    CapabilityClean,
    CapabilityCleanAction,
    CapabilityCustomCommand,
    CapabilityEvent,
    CapabilityExecute,
    CapabilityLifeSpan,
    CapabilitySettings,
    CapabilityStats,
    DeviceType,
)
from deebot_client.commands.json.custom import CustomCommand
from deebot_client.commands.json.y1 import Y1Charge, Y1CleanArea, Y1FieldQuery, y1_clean
from deebot_client.const import DataType
from deebot_client.events import (
    AvailabilityEvent,
    BatteryEvent,
    CustomCommandEvent,
    ErrorEvent,
    LifeSpan,
    LifeSpanEvent,
    NetworkInfoEvent,
    ReportStatsEvent,
    StateEvent,
    StatsEvent,
    TotalStatsEvent,
)
from deebot_client.models import StaticDeviceInfo


def _unsupported_life_span_reset(component: LifeSpan) -> NoReturn:
    """Refuse to send a consumable reset until its Y1 protocol is verified."""
    message = f"Y1 PRO consumable reset is not mapped: {component}"
    raise NotImplementedError(message)


def _unsupported_play_sound() -> NoReturn:
    """Refuse to send an unverified Y1 sound command."""
    raise NotImplementedError("Y1 PRO play-sound command is not mapped")


def get_device_info() -> StaticDeviceInfo:
    """Get PR1 capabilities for DEEBOT Y1 PRO class cqyi87.

    This first upstream slice intentionally covers device discovery, core clean
    and dock controls, battery/state and current-clean statistics only. Map,
    consumables and optional settings are separate follow-up changes.
    """
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=CapabilityEvent(BatteryEvent, [Y1FieldQuery(["battery"])]),
            charge=CapabilityExecute(Y1Charge),
            clean=CapabilityClean(
                action=CapabilityCleanAction(command=y1_clean, area=Y1CleanArea),
            ),
            custom=CapabilityCustomCommand(
                event=CustomCommandEvent, get=[], set=CustomCommand
            ),
            error=CapabilityEvent(ErrorEvent, []),
            fan_speed=None,
            life_span=CapabilityLifeSpan(
                event=LifeSpanEvent,
                get=[],
                reset=_unsupported_life_span_reset,
                types=(),
            ),
            map=None,
            network=CapabilityEvent(NetworkInfoEvent, []),
            play_sound=CapabilityExecute(_unsupported_play_sound),
            settings=CapabilitySettings(),
            state=CapabilityEvent(
                StateEvent, [Y1FieldQuery(["status", "chargeStatus"])]
            ),
            stats=CapabilityStats(
                clean=CapabilityEvent(
                    StatsEvent, [Y1FieldQuery(["cleanArea", "cleanTime"])]
                ),
                report=CapabilityEvent(ReportStatsEvent, []),
                total=CapabilityEvent(TotalStatsEvent, []),
            ),
            water=None,
        ),
    )
