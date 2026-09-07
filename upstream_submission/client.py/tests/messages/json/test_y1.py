from __future__ import annotations

from unittest.mock import Mock, call

from deebot_client.event_bus import EventBus
from deebot_client.events import BatteryEvent, StateEvent, StatsEvent
from deebot_client.message import HandlingState
from deebot_client.messages.json.y1 import handle_y1_state_data
from deebot_client.models import State


def test_y1_partial_battery_update() -> None:
    event_bus = Mock(spec_set=EventBus)
    result = handle_y1_state_data(event_bus, {"battery": 83})
    assert result.state == HandlingState.SUCCESS
    event_bus.notify.assert_called_once_with(BatteryEvent(83))


def test_y1_cleaning_state() -> None:
    event_bus = Mock(spec_set=EventBus)
    handle_y1_state_data(event_bus, {"status": "smartClean"})
    event_bus.notify.assert_called_once_with(StateEvent(State.CLEANING))


def test_y1_area_cleaning_state() -> None:
    event_bus = Mock(spec_set=EventBus)
    handle_y1_state_data(event_bus, {"status": "areaClean"})
    event_bus.notify.assert_called_once_with(StateEvent(State.CLEANING))


def test_y1_pause_state() -> None:
    event_bus = Mock(spec_set=EventBus)
    handle_y1_state_data(event_bus, {"pauseSwitch": True})
    event_bus.notify.assert_called_once_with(StateEvent(State.PAUSED))


def test_y1_returning_state() -> None:
    event_bus = Mock(spec_set=EventBus)
    handle_y1_state_data(event_bus, {"status": "goCharge"})
    event_bus.notify.assert_called_once_with(StateEvent(State.RETURNING))


def test_y1_docked_state_from_charge_status() -> None:
    event_bus = Mock(spec_set=EventBus)
    handle_y1_state_data(event_bus, {"chargeStatus": True})
    event_bus.notify.assert_called_once_with(StateEvent(State.DOCKED))


def test_y1_idle_does_not_require_global_charge_cache() -> None:
    event_bus = Mock(spec_set=EventBus)
    handle_y1_state_data(event_bus, {"status": "idle"})
    event_bus.notify.assert_called_once_with(StateEvent(State.IDLE))


def test_y1_clean_stats_convert_minutes_to_seconds() -> None:
    event_bus = Mock(spec_set=EventBus)
    handle_y1_state_data(event_bus, {"cleanArea": 12, "cleanTime": 7})
    event_bus.notify.assert_called_once_with(StatsEvent(area=12, time=420, type=None))


def test_y1_multiplexed_partial_payload() -> None:
    event_bus = Mock(spec_set=EventBus)
    handle_y1_state_data(
        event_bus,
        {"battery": 71, "pauseSwitch": False, "status": "smartClean"},
    )
    assert event_bus.notify.call_args_list == [
        call(BatteryEvent(71)),
        call(StateEvent(State.CLEANING)),
    ]
