"""DEEBOT Y1 PRO (cqyi87) state messages."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from deebot_client.events import BatteryEvent, StateEvent, StatsEvent
from deebot_client.message import HandlingResult, MessageBodyDataDict
from deebot_client.models import State

if TYPE_CHECKING:
    from deebot_client.event_bus import EventBus


def handle_y1_state_data(event_bus: EventBus, data: dict[str, Any]) -> HandlingResult:
    """Translate a partial Y1 10000/10001 payload into native events.

    10000 is multiplexed and often carries only a subset of fields, so every
    field is handled independently and missing fields are never treated as a
    state reset.
    """
    handled = False

    battery = data.get("battery")
    if isinstance(battery, (int, float)) and not isinstance(battery, bool):
        value = int(battery)
        if 0 <= value <= 100:
            event_bus.notify(BatteryEvent(value))
            handled = True

    clean_area = data.get("cleanArea")
    clean_time = data.get("cleanTime")
    if (
        isinstance(clean_area, (int, float))
        and not isinstance(clean_area, bool)
    ) or (
        isinstance(clean_time, (int, float))
        and not isinstance(clean_time, bool)
    ):
        event_bus.notify(
            StatsEvent(
                area=int(clean_area)
                if isinstance(clean_area, (int, float))
                and not isinstance(clean_area, bool)
                else None,
                # Captured Y1 cleanTime is minutes; deebot-client/HA expects sec.
                time=round(float(clean_time) * 60)
                if isinstance(clean_time, (int, float))
                and not isinstance(clean_time, bool)
                else None,
                type=None,
            )
        )
        handled = True

    charge_status = data.get("chargeStatus")
    if charge_status is True:
        event_bus.notify(StateEvent(State.DOCKED))
        handled = True

    pause_switch = data.get("pauseSwitch")
    if pause_switch is True:
        event_bus.notify(StateEvent(State.PAUSED))
        handled = True

    status = data.get("status")
    if isinstance(status, str):
        state = {
            "smartclean": State.CLEANING,
            "areaclean": State.CLEANING,
            "gocharge": State.RETURNING,
            # Do not infer DOCKED from idle without per-device cached charge
            # context. A separate chargeStatus=true event is authoritative.
            "idle": State.IDLE,
        }.get(status.lower())
        if state is not None:
            event_bus.notify(StateEvent(state))
            handled = True

    return HandlingResult.success() if handled else HandlingResult.analyse()


class OnY1State(MessageBodyDataDict):
    """Handle Y1 PRO live state/event message 10000."""

    NAME = "10000"

    @classmethod
    def _handle_body_data_dict(
        cls, event_bus: EventBus, data: dict[str, Any]
    ) -> HandlingResult:
        return handle_y1_state_data(event_bus, data)
