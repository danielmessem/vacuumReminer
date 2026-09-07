"""DEEBOT Y1 PRO (cqyi87) capabilities."""

from __future__ import annotations

from deebot_client.capabilities import (
    Capabilities,
    CapabilityClean,
    CapabilityCleanAction,
    CapabilityCustomCommand,
    CapabilityEvent,
    CapabilityExecute,
    CapabilityLifeSpan,
    CapabilityMap,
    CapabilitySettings,
    CapabilityStats,
    DeviceType,
)
from deebot_client.commands.json.custom import CustomCommand
from deebot_client.commands.json.y1 import Y1Charge, Y1Clean, Y1CleanArea, Y1FieldQuery
from deebot_client.const import DataType
from deebot_client.events import (
    AvailabilityEvent,
    BatteryEvent,
    CachedMapInfoEvent,
    CustomCommandEvent,
    LifeSpanEvent,
    MapChangedEvent,
    MapTraceEvent,
    PositionsEvent,
    ReportStatsEvent,
    RoomsEvent,
    StateEvent,
    StatsEvent,
    TotalStatsEvent,
)
from deebot_client.models import StaticDeviceInfo


def get_device_info() -> StaticDeviceInfo:
    """Get capabilities for DEEBOT Y1 PRO class cqyi87.

    PR1 intentionally limits itself to discovery, core clean/dock controls,
    battery/state and current-clean stats. Map translation and consumables are
    follow-up work so this initial change remains reviewable.
    """
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            # Keep the library's existing empty availability behavior. The local
            # working profile has remained available for hours with this setup.
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=CapabilityEvent(BatteryEvent, [Y1FieldQuery(["battery"])]),
            charge=CapabilityExecute(Y1Charge),
            clean=CapabilityClean(
                action=CapabilityCleanAction(command=Y1Clean, area=Y1CleanArea),
            ),
            custom=CapabilityCustomCommand(
                event=CustomCommandEvent, get=[], set=CustomCommand
            ),
            error=None,
            fan_speed=None,
            life_span=CapabilityLifeSpan(
                event=LifeSpanEvent,
                get=[],
                reset=lambda component: (_ for _ in ()).throw(
                    NotImplementedError(
                        f"Y1 PRO consumable reset is not mapped: {component}"
                    )
                ),
                types=(),
            ),
            map=CapabilityMap(
                cached_info=CapabilityEvent(CachedMapInfoEvent, []),
                changed=CapabilityEvent(MapChangedEvent, []),
                major=None,
                minor=None,
                multi_state=None,
                position=CapabilityEvent(PositionsEvent, []),
                relocation=None,
                rooms=CapabilityEvent(RoomsEvent, []),
                set=None,
                trace=CapabilityEvent(MapTraceEvent, []),
            ),
            network=None,
            play_sound=None,
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
