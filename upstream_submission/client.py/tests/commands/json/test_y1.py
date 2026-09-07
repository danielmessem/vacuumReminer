from __future__ import annotations

import pytest

from deebot_client.commands.json.y1 import Y1Charge, Y1Clean, Y1CleanArea, Y1FieldQuery
from deebot_client.models import CleanAction, CleanMode


def _body_data(command):
    payload = command._get_payload()
    assert payload["header"]["channel"] == "Android"
    assert payload["header"]["m"] == "request"
    assert payload["header"]["pri"] == 2
    assert payload["header"]["ver"] == "0.0.22"
    return payload["body"]["data"]


def test_y1_start_payload() -> None:
    command = Y1Clean(CleanAction.START)
    assert command.NAME == "40001"
    assert _body_data(command) == {"cleanSwitch": True, "cleanMode": "smart"}


def test_y1_pause_payload() -> None:
    command = Y1Clean(CleanAction.PAUSE)
    assert command.NAME == "40009"
    assert _body_data(command) == {"pauseSwitch": True}


def test_y1_resume_payload() -> None:
    command = Y1Clean(CleanAction.RESUME)
    assert command.NAME == "40011"
    assert _body_data(command) == {"pauseSwitch": False}


def test_y1_stop_not_invented() -> None:
    with pytest.raises(NotImplementedError):
        Y1Clean(CleanAction.STOP)


def test_y1_area_payload() -> None:
    command = Y1CleanArea(CleanMode.SPOT_AREA, [9, 12])
    assert command.NAME == "40007"
    assert _body_data(command) == {
        "cleanSwitch": True,
        "cleanMode": "area",
        "cleanValues": [9, 12],
    }


def test_y1_charge_payload() -> None:
    command = Y1Charge()
    assert command.NAME == "40013"
    assert _body_data(command) == {"chargeSwitch": True}


def test_y1_battery_query_payload() -> None:
    command = Y1FieldQuery(["battery"])
    assert command.NAME == "10001"
    assert _body_data(command) == {"fields": ["battery"]}
