"""DEEBOT Y1 PRO compatibility profile."""
from __future__ import annotations

import base64
import lzma
from typing import Any

import orjson

from deebot_client.capabilities import (
    Capabilities, CapabilityClean, CapabilityCleanAction, CapabilityCustomCommand,
    CapabilityEvent, CapabilityExecute, CapabilityLifeSpan, CapabilityMap,
    CapabilitySetTypes, CapabilitySettings, CapabilityStats, DeviceType,
)
from deebot_client.commands import COMMANDS_WITH_MQTT_P2P_HANDLING
from deebot_client.commands.json.common import JsonCommandMqttP2P
from deebot_client.commands.json.custom import CustomCommand
from deebot_client.commands.json.fan_speed import SetFanSpeed
from deebot_client.commands.json.life_span import ResetLifeSpan
from deebot_client.const import DataType
from deebot_client.events import (
    AvailabilityEvent, BatteryEvent, CachedMapInfoEvent, CustomCommandEvent,
    FanSpeedEvent, FanSpeedLevel, LifeSpanEvent, MapChangedEvent, MapTraceEvent,
    MinorMapEvent, Position, PositionsEvent, ReportStatsEvent, RoomsEvent,
    StateEvent, StatsEvent, TotalStatsEvent,
)
from deebot_client.events.map import Map as MapDefinition
from deebot_client.message import HandlingResult, HandlingState, MessageBodyDataDict
from deebot_client.messages.json import MESSAGES
from deebot_client.models import CleanAction, CleanMode, Room, State, StaticDeviceInfo
from deebot_client.rs.map import PositionType, RotationAngle

Y1PRO_PATCH_VERSION = "1.6.5"
_Y1PRO_PAUSED = False
_Y1PRO_CHARGE_STATUS: bool | None = None


class Y1ProClean(CustomCommand):
    def __init__(self, action: CleanAction) -> None:
        if action == CleanAction.START:
            super().__init__("40011", {"pauseSwitch": False}) if _Y1PRO_PAUSED else super().__init__("40001", {"cleanSwitch": True, "cleanMode": "smart"})
        elif action == CleanAction.PAUSE:
            super().__init__("40009", {"pauseSwitch": True})
        elif action == CleanAction.RESUME:
            super().__init__("40011", {"pauseSwitch": False})
        else:
            super().__init__("clean", {"act": action.value})


class Y1ProCleanArea(CustomCommand):
    def __init__(self, mode: CleanMode, values: list[int | float], cleanings: int = 1) -> None:
        super().__init__("40007", {"cleanSwitch": True, "cleanMode": "area", "cleanValues": [int(v) for v in values]})


class Y1ProCharge(CustomCommand):
    def __init__(self) -> None:
        super().__init__("40013", {"chargeSwitch": True})


def _b64decode(value: str) -> bytes:
    raw = value.strip()
    raw += "=" * (-len(raw) % 4)
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        return base64.urlsafe_b64decode(raw)


def _lz4_block_decode(src: bytes) -> bytes:
    """Small dependency-free LZ4 block decoder for Y1 mapData."""
    out = bytearray()
    i = 0
    n = len(src)
    while i < n:
        token = src[i]
        i += 1
        literal_len = token >> 4
        if literal_len == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated LZ4 literal length")
                b = src[i]
                i += 1
                literal_len += b
                if b != 255:
                    break
        if i + literal_len > n:
            raise ValueError("truncated LZ4 literals")
        out.extend(src[i:i + literal_len])
        i += literal_len
        if i >= n:
            break
        if i + 2 > n:
            raise ValueError("truncated LZ4 offset")
        offset = src[i] | (src[i + 1] << 8)
        i += 2
        if offset <= 0 or offset > len(out):
            raise ValueError("invalid LZ4 offset")
        match_len = token & 0x0F
        if match_len == 15:
            while True:
                if i >= n:
                    raise ValueError("truncated LZ4 match length")
                b = src[i]
                i += 1
                match_len += b
                if b != 255:
                    break
        match_len += 4
        for _ in range(match_len):
            out.append(out[-offset])
    return bytes(out)


def _lz4_decode(src: bytes) -> bytes:
    """Decode either an LZ4 raw block or a basic LZ4 frame."""
    if not src.startswith(b"\x04\x22\x4d\x18"):
        return _lz4_block_decode(src)

    if len(src) < 7:
        raise ValueError("truncated LZ4 frame")
    flg = src[4]
    p = 6
    if flg & 0x08:
        p += 8
    if flg & 0x01:
        p += 4
    p += 1
    out = bytearray()
    while True:
        if p + 4 > len(src):
            raise ValueError("truncated LZ4 frame block size")
        block_size = int.from_bytes(src[p:p + 4], "little")
        p += 4
        if block_size == 0:
            break
        uncompressed = bool(block_size & 0x80000000)
        block_size &= 0x7FFFFFFF
        if p + block_size > len(src):
            raise ValueError("truncated LZ4 frame block")
        block = src[p:p + block_size]
        p += block_size
        out.extend(block if uncompressed else _lz4_block_decode(block))
        if flg & 0x10:
            p += 4
    return bytes(out)


def _find_map_blob(map_data: dict[str, Any]) -> str | None:
    for key in ("data", "lz4Data", "map", "value", "blob", "raw"):
        value = map_data.get(key)
        if isinstance(value, str) and len(value) > 64:
            return value
    candidates = [
        value for key, value in map_data.items()
        if isinstance(value, str) and len(value) > 64 and key not in ("mapId", "id")
    ]
    return max(candidates, key=len, default=None)


def _compress_native_map_piece(raw: bytes) -> str:
    """Encode a 100x100 piece in the shortened LZMA form deebot-client expects."""
    compressed = bytearray(lzma.compress(raw, format=lzma.FORMAT_ALONE))
    if len(compressed) < 13:
        raise ValueError("unexpected LZMA output")
    # Python writes an unknown-size marker in the LZMA-alone header. Ecovacs'
    # shortened form omits bytes 8..11, which deebot-client restores as zeroes.
    # Write the real little-endian length first so the reconstructed 13-byte
    # header is valid when the Rust renderer expands it again.
    compressed[5:13] = len(raw).to_bytes(8, "little")
    shortened = compressed[:8] + compressed[12:]
    return base64.b64encode(shortened).decode()


def _pixel_index(value: int) -> int:
    if value <= 0:
        return 0
    if value <= 5:
        return value
    return 6 + ((value - 6) % 6)


def _emit_y1_raster(event_bus, map_data: dict[str, Any]) -> bool:
    """Convert Y1 LZ4 raster into deebot-client's native 8x8 map pieces."""
    try:
        width = int(map_data.get("width", 0))
        height = int(map_data.get("height", 0))
        resolution = float(map_data.get("resolution", 50) or 50)
        x_min = float(map_data.get("xMin", 0))
        y_max = float(map_data.get("yMax", 0))
    except Exception:
        return False
    if width <= 0 or height <= 0 or width > 2000 or height > 2000:
        return False
    blob = _find_map_blob(map_data)
    if not blob:
        return False
    try:
        packed = _b64decode(blob)
        raw = _lz4_decode(packed)
    except Exception:
        return False

    expected = width * height
    if len(raw) < expected:
        return False
    if len(raw) > expected:
        raw = raw[-expected:]

    pieces: dict[int, bytearray] = {}
    for row in range(height):
        y_mm = y_max - (row * resolution)
        gy = int(round(400 - (y_mm / 50.0)))
        if gy < 0 or gy >= 800:
            continue
        piece_row_from_top = gy // 100
        piece_row_from_bottom = 7 - piece_row_from_top
        oy = gy % 100
        for col in range(width):
            value = _pixel_index(raw[row * width + col])
            if value == 0:
                continue
            x_mm = x_min + (col * resolution)
            gx = int(round(400 + (x_mm / 50.0)))
            if gx < 0 or gx >= 800:
                continue
            piece_col = gx // 100
            ox = gx % 100
            index = piece_col * 8 + piece_row_from_bottom
            piece = pieces.setdefault(index, bytearray(10000))
            input_x = 99 - oy
            input_y = ox
            piece[input_y * 100 + input_x] = value

    if not pieces:
        return False
    try:
        for index, pixels in pieces.items():
            event_bus.notify(MinorMapEvent(index=index, value=_compress_native_map_piece(bytes(pixels))))
    except Exception:
        return False
    return True


def _map_data(event_bus, data: dict[str, Any]) -> HandlingResult:
    """Translate observed Y1 PRO 30001 data into native deebot-client events."""
    if isinstance(data.get("mapInfos"), list):
        maps: set[MapDefinition] = set()
        selected: str | None = None
        for item in data["mapInfos"]:
            if not isinstance(item, dict):
                continue
            mid = str(item.get("mapId", ""))
            if not mid:
                continue
            try:
                angle = RotationAngle.from_int(int(item.get("angle", 0)))
            except Exception:
                angle = RotationAngle.DEG_0
            using = item.get("status") == 1
            maps.add(MapDefinition(mid, str(item.get("name") or f"Map {mid}").strip(), using, item.get("saved") == 1, angle))
            if selected is None or using:
                selected = mid
        if maps:
            event_bus.notify(CachedMapInfoEvent(maps=maps))
        return HandlingResult(HandlingState.SUCCESS, {"map_id": selected} if selected else None, [Y1ProMapCommand({"mapId": selected, "fields": ["mapData", "areas", "pos"]})] if selected else [])

    handled = False
    mid = str(data.get("mapId", ""))
    if isinstance(data.get("areas"), list) and mid:
        rooms: list[Room] = []
        for area in data["areas"]:
            if not isinstance(area, dict):
                continue
            try:
                rid = int(area["id"])
            except Exception:
                continue
            name = str(area.get("name") or "").strip() or f"Room {rid}"
            rooms.append(Room(name=name, id=rid, coordinates=f"{area.get('centerX', 0)},{area.get('centerY', 0)}"))
        if rooms:
            event_bus.notify(RoomsEvent(map_id=mid, rooms=rooms))
            handled = True

    positions: list[Position] = []
    pos = data.get("pos")
    if isinstance(pos, dict):
        try:
            positions.append(Position(PositionType.DEEBOT, int(pos.get("x", 0)), int(pos.get("y", 0)), int(pos.get("a", 0))))
        except Exception:
            pass
    map_data = data.get("mapData")
    if isinstance(map_data, dict):
        charge = map_data.get("chargePos")
        if isinstance(charge, dict):
            try:
                positions.append(Position(PositionType.CHARGER, int(charge.get("x", 0)), int(charge.get("y", 0)), int(charge.get("a", 0))))
            except Exception:
                pass
        if _emit_y1_raster(event_bus, map_data):
            handled = True
    if positions:
        event_bus.notify(PositionsEvent(positions=positions))
        handled = True

    return HandlingResult.success() if handled else HandlingResult.analyse()


class Y1ProMapCommand(JsonCommandMqttP2P):
    NAME = "30001"

    def __init__(self, args: dict[str, Any] | None = None) -> None:
        super().__init__(args or {})

    @classmethod
    def create_from_mqtt(cls, payload: str | bytes | bytearray):
        obj = orjson.loads(payload)
        return cls(dict(obj.get("body", {}).get("data", {})))

    def _handle_response(self, event_bus, response: dict[str, Any]) -> HandlingResult:
        data: Any = response.get("resp", response)
        if isinstance(data, (str, bytes, bytearray)):
            try:
                data = orjson.loads(data)
            except Exception:
                return HandlingResult.analyse()
        if isinstance(data, dict) and "body" in data:
            data = data.get("body", {}).get("data", {})
        elif isinstance(data, dict) and "data" in data:
            data = data.get("data", {})
        return _map_data(event_bus, data) if isinstance(data, dict) else HandlingResult.analyse()

    def _handle_mqtt_p2p(self, event_bus, response: dict[str, Any]) -> None:
        data = response.get("body", {}).get("data", {}) if isinstance(response, dict) else {}
        if isinstance(data, dict):
            _map_data(event_bus, data)


class Y1ProStateMessage(MessageBodyDataDict):
    NAME = "10000"

    @classmethod
    def _handle_body_data_dict(cls, event_bus, data: dict[str, Any]) -> HandlingResult:
        global _Y1PRO_PAUSED, _Y1PRO_CHARGE_STATUS
        handled = False
        battery = data.get("battery")
        if isinstance(battery, (int, float)) and not isinstance(battery, bool) and 0 <= int(battery) <= 100:
            event_bus.notify(BatteryEvent(int(battery)))
            handled = True
        charge = data.get("chargeStatus")
        if isinstance(charge, bool):
            _Y1PRO_CHARGE_STATUS = charge
            handled = True
            if charge:
                _Y1PRO_PAUSED = False
                event_bus.notify(StateEvent(State.DOCKED))
                return HandlingResult.success()
        pause = data.get("pauseSwitch")
        if pause is True:
            _Y1PRO_PAUSED = True
            event_bus.notify(StateEvent(State.PAUSED))
            return HandlingResult.success()
        if pause is False:
            _Y1PRO_PAUSED = False
            handled = True
        status = data.get("status")
        if isinstance(status, str):
            status = status.lower()
            if status in ("smartclean", "areaclean"):
                _Y1PRO_PAUSED = False
                _Y1PRO_CHARGE_STATUS = False
                event_bus.notify(StateEvent(State.CLEANING))
                return HandlingResult.success()
            if status == "gocharge":
                _Y1PRO_PAUSED = False
                _Y1PRO_CHARGE_STATUS = False
                event_bus.notify(StateEvent(State.RETURNING))
                return HandlingResult.success()
            if status == "idle":
                _Y1PRO_PAUSED = False
                event_bus.notify(StateEvent(State.DOCKED if _Y1PRO_CHARGE_STATUS is True else State.IDLE))
                return HandlingResult.success()
        return HandlingResult.success() if handled else HandlingResult.analyse()


class Y1ProFieldCommand(JsonCommandMqttP2P):
    """Query observed Y1 PRO fields through numeric command 10001."""
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
        elif isinstance(data, dict) and "data" in data and not any(k in data for k in ("battery", "chargeStatus", "status", "pauseSwitch")):
            data = data.get("data", {})
        return Y1ProStateMessage._handle_body_data_dict(event_bus, data) if isinstance(data, dict) else HandlingResult.analyse()

    def _handle_response(self, event_bus, response: dict[str, Any]) -> HandlingResult:
        data: Any = response.get("resp", response) if isinstance(response, dict) else response
        return self._handle_field_data(event_bus, data)

    def _handle_mqtt_p2p(self, event_bus, response: dict[str, Any]) -> None:
        self._handle_field_data(event_bus, response)


class Y1ProMapMessage(MessageBodyDataDict):
    NAME = "30001"

    @classmethod
    def _handle_body_data_dict(cls, event_bus, data: dict[str, Any]) -> HandlingResult:
        return _map_data(event_bus, data)


MESSAGES["10000"] = Y1ProStateMessage
MESSAGES["30001"] = Y1ProMapMessage
COMMANDS_WITH_MQTT_P2P_HANDLING.setdefault(DataType.JSON, {})["10001"] = Y1ProFieldCommand
COMMANDS_WITH_MQTT_P2P_HANDLING.setdefault(DataType.JSON, {})["30001"] = Y1ProMapCommand


def get_device_info() -> StaticDeviceInfo:
    return StaticDeviceInfo(
        DataType.JSON,
        Capabilities(
            device_type=DeviceType.VACUUM,
            availability=CapabilityEvent(AvailabilityEvent, []),
            battery=CapabilityEvent(BatteryEvent, [Y1ProFieldCommand(["battery"])]),
            charge=CapabilityExecute(Y1ProCharge),
            clean=CapabilityClean(action=CapabilityCleanAction(command=Y1ProClean, area=Y1ProCleanArea)),
            custom=CapabilityCustomCommand(event=CustomCommandEvent, get=[], set=CustomCommand),
            error=None,
            fan_speed=CapabilitySetTypes(event=FanSpeedEvent, get=[], set=SetFanSpeed, types=(FanSpeedLevel.QUIET, FanSpeedLevel.NORMAL, FanSpeedLevel.MAX, FanSpeedLevel.MAX_PLUS)),
            life_span=CapabilityLifeSpan(event=LifeSpanEvent, get=[], reset=ResetLifeSpan, types=()),
            map=CapabilityMap(
                cached_info=CapabilityEvent(CachedMapInfoEvent, [Y1ProMapCommand({"fields": ["mapInfos"]})]),
                changed=CapabilityEvent(MapChangedEvent, []),
                major=None,
                minor=CapabilityExecute(lambda index, map_id: Y1ProMapCommand({"mapId": str(map_id), "fields": ["mapData"]})),
                position=CapabilityEvent(PositionsEvent, []),
                rooms=CapabilityEvent(RoomsEvent, []),
                set=CapabilityExecute(lambda map_id, _set_type: Y1ProMapCommand({"mapId": str(map_id), "fields": ["mapData", "areas", "pos"]})),
                trace=CapabilityEvent(MapTraceEvent, []),
            ),
            network=None,
            play_sound=None,
            settings=CapabilitySettings(),
            state=CapabilityEvent(StateEvent, []),
            station=None,
            stats=CapabilityStats(clean=CapabilityEvent(StatsEvent, []), report=CapabilityEvent(ReportStatsEvent, []), total=CapabilityEvent(TotalStatsEvent, [])),
            water=None,
        ),
    )
