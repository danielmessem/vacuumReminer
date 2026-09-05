"""Tests for DEEBOT Y1 PRO (cqyi87) support candidate."""

from __future__ import annotations

import asyncio
from unittest.mock import Mock

from deebot_client.events import BatteryEvent, StateEvent
from deebot_client.hardware import get_static_device_info
from deebot_client.models import CleanAction, State

from deebot_client.hardware.cqyi87 import (
    Y1ProCharge,
    Y1ProClean,
    Y1ProCleanArea,
    Y1ProFieldCommand,
    Y1ProStateMessage,
)


def test_device_profile_loads() -> None:
    """cqyi87 must be discoverable through the normal hardware loader."""
    assert asyncio.run(get_static_device_info("cqyi87")) is not None


def test_numeric_clean_commands() -> None:
    """Use the observed numeric Y1 control protocol."""
    start = Y1ProClean(CleanAction.START)
    pause = Y1ProClean(CleanAction.PAUSE)
    resume = Y1ProClean(CleanAction.RESUME)
    charge = Y1ProCharge()

    assert start.NAME in ("40001", "40011")
    assert pause.NAME == "40009"
    assert resume.NAME == "40011"
    assert charge.NAME == "40013"


def test_area_clean_command() -> None:
    """Area cleaning carries integer room identifiers."""
    command = Y1ProCleanArea(Mock(), [2, 7])
    assert command.NAME == "40007"
    assert command._args["cleanMode"] == "area"
    assert command._args["cleanValues"] == [2, 7]


def test_battery_field_query() -> None:
    """Battery is requested with command 10001 and a fields array."""
    command = Y1ProFieldCommand(["battery"])
    assert command.NAME == "10001"
    assert command._args == {"fields": ["battery"]}


def test_partial_state_messages() -> None:
    """10000 updates are partial and must not require unrelated fields."""
    event_bus = Mock()

    result = Y1ProStateMessage._handle_body_data_dict(
        event_bus, {"battery": 83}
    )
    assert result is not None
    event_bus.notify.assert_called_with(BatteryEvent(83))

    event_bus.reset_mock()
    Y1ProStateMessage._handle_body_data_dict(
        event_bus, {"status": "smartClean", "pauseSwitch": False}
    )
    event_bus.notify.assert_called_with(StateEvent(State.CLEANING))

    event_bus.reset_mock()
    Y1ProStateMessage._handle_body_data_dict(
        event_bus, {"status": "goCharge"}
    )
    event_bus.notify.assert_called_with(StateEvent(State.RETURNING))


def test_charge_status_sets_docked() -> None:
    """A true chargeStatus update means the robot is docked."""
    event_bus = Mock()
    Y1ProStateMessage._handle_body_data_dict(
        event_bus, {"chargeStatus": True}
    )
    event_bus.notify.assert_called_with(StateEvent(State.DOCKED))
