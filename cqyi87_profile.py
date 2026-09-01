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
    CapabilityMap,
    CapabilitySetTypes,
    CapabilitySettings,
    CapabilityStats,
    DeviceType,
)
from deebot_client.commands.json.custom import CustomCommand
from deebot_client.commands.json.fan_speed import SetFanSpeed
from deebot_client.commands.json.life_span import ResetLifeSpan
from deebot_client.const import DataType
from deebot_client.events import (
    AvailabilityEvent,
    BatteryEvent,
    CachedMapInfoEvent,
    CustomCommandEvent,
    FanSpeedEvent,
    FanSpeedLevel,
    LifeSpanEvent,
    MapChangedEvent,
    MapTraceEvent,
    Position,
    PositionsEvent,
    ReportStatsEvent,
    RoomsEvent,
    StateEvent,
    StatsEvent,
    TotalStatsEvent,
)
from deebot_client.events.map import Map as MapDefinition
from deebot_client.message import HandlingResult, HandlingState, MessageBodyDataDict
from deebot_client.messages.json import MESSAGES
from deebot_client.models import CleanAction, CleanMode, Room, State, StaticDeviceInfo
from deebot_client.rs.map import PositionType, RotationAngle

Y1PRO_PATCH_VERSION = "1.6.0"

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


class Y1ProCleanArea(CustomCommand):
    """Native HA room/segment clean using the observed Y1 PRO area protocol."""

    def __init__(self, mode: CleanMode, values: list[int | float], cleanings: int = 1) -> None:
        area_ids = [int(value) for value in values]
        super().__init__(
            "40007",
            {"cleanSwitch": True, "cleanMode": "area", "cleanValues": area_ids},
        )


class Y1ProCharge(CustomCommand):
    def __init__(self) -> None:
        super().__init__("40013", {"chargeSwitch": True})


class Y1ProGetMapInfos(CustomCommand):
    """Request the Y1 PRO's saved-map list."""

    def __init__(self) -> None:
        super().__init__("30001", {"fields": ["mapInfos"]})


class Y1ProGetMapData(CustomCommand):
    """Request rooms and live positions for a selected Y1 PRO map."""

    def __init__(self, map_id: str) -> None:
        super().__init__(
            "30001",
            {"mapId": str(map_id), "fields": ["mapData", "areas", "pos"]},
        )


class Y1ProMapSetRequest(CustomCommand):
    """Read-only compatibility hook required by deebot-client CapabilityMap."""

    def __init__(self, map_id: str, _set_type: Any) -> None:
        super().__init__(
            "30001",
            {"mapId": str(map_id), "fields": ["mapData", "areas", "pos"]},
        )


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
            if normalized in ("smartclean", "areaclean"):
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


class Y1ProMapMessage(MessageBodyDataDict):
    """Translate Y1 PRO 30001 replies into deebot-client native map events."""

    NAME = "30001"

    @classmethod
    def _handle_body_data_dict(cls, event_bus, data: dict[str, Any]) -> HandlingResult:
        if "fields" in data and not any(
            key in data for key in ("mapInfos", "areas", "mapData", "pos", "mapTraceData")
        ):
            return HandlingResult.success()

        if isinstance(data.get("mapInfos"), list):
            maps: set[MapDefinition] = set()
            selected_map_id: str | None = None

            for item in data["mapInfos"]:
                if not isinstance(item, dict):
                    continue
                map_id = str(item.get("mapId", ""))
                if not map_id:
                    continue

                try:
                    angle = RotationAngle.from_int(int(item.get("angle", 0)))
                except Exception:
                    angle = RotationAngle.DEG_0

                using = bool(item.get("status") == 1)
                built = bool(item.get("saved") == 1)
                name = str(item.get("name") or f"Map {map_id}").strip()
                maps.add(MapDefinition(map_id, name, using, built, angle))

                if using and selected_map_id is None:
                    selected_map_id = map_id
                elif selected_map_id is None:
                    selected_map_id = map_id

            if maps:
                event_bus.notify(CachedMapInfoEvent(maps=maps))

            requested = [Y1ProGetMapData(selected_map_id)] if selected_map_id else []
            return HandlingResult(
                HandlingState.SUCCESS,
                {"map_id": selected_map_id} if selected_map_id else None,
                requested,
            )

        handled = False
        map_id = str(data.get("mapId", ""))

        if isinstance(data.get("areas"), list) and map_id:
            rooms: list[Room] = []
            for area in data["areas"]:
                if not isinstance(area, dict):
                    continue
                try:
                    room_id = int(area["id"])
                except Exception:
                    continue

                name = str(area.get("name") or "").strip() or f"Room {room_id}"
                coordinates = f"{area.get('centerX', 0)},{area.get('centerY', 0)}"
                rooms.append(Room(name=name, id=room_id, coordinates=coordinates))

            if rooms:
                event_bus.notify(RoomsEvent(map_id=map_id, rooms=rooms))
                handled = True

        if isinstance(data.get("pos"), dict):
            positions: list[Position] = []
            pos = data["pos"]
            try:
                positions.append(
                    Position(
                        type=PositionType.DEEBOT,
                        x=int(pos.get("x", 0)),
                        y=int(pos.get("y", 0)),
                        a=int(pos.get("a", 0)),
                    )
                )
            except Exception:
                pass

            map_data = data.get("mapData")
            if isinstance(map_data, dict):
                charge_pos = map_data.get("chargePos")
                if isinstance(charge_pos, dict):
                    try:
                        positions.append(
                            Position(
                                type=PositionType.CHARGER,
                                x=int(charge_pos.get("x", 0)),
                                y=int(charge_pos.get("y", 0)),
                                a=int(charge_pos.get("a", 0)),
                            )
                        )
                    except Exception:
                        pass

            if positions:
                event_bus.notify(PositionsEvent(positions=positions))
                handled = True

        # The Y1 PRO raster/trace payload is LZ4 and is not yet compatible with
        # deebot-client's current SVG decoder. Do not feed it into that renderer yet.
        return HandlingResult.success() if handled else HandlingResult.analyse()


MESSAGES["10000"] = Y1ProStateMessage
MESSAGES["30001"] = Y1ProMapMessage


def get_device_info() -> StaticDeviceInfo:
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=CapabilityEvent(BatteryEvent, []),
            charge=CapabilityExecute(Y1ProCharge),
            clean=CapabilityClean(
                action=CapabilityCleanAction(command=Y1ProClean, area=Y1ProCleanArea)
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
            map=CapabilityMap(
                cached_info=CapabilityEvent(CachedMapInfoEvent, [Y1ProGetMapInfos()]),
                changed=CapabilityEvent(MapChangedEvent, []),
                position=CapabilityEvent(PositionsEvent, []),
                rooms=CapabilityEvent(RoomsEvent, []),
                set=CapabilityExecute(Y1ProMapSetRequest),
                trace=CapabilityEvent(MapTraceEvent, []),
            ),
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
