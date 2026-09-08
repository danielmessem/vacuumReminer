from __future__ import annotations

from typing import Any, Protocol

import pytest

from deebot_client.commands.json.y1 import Y1Charge, Y1CleanArea, Y1FieldQuery, y1_clean
from deebot_client.models import CleanAction, CleanMode


class PayloadCommand(Protocol):
    """Command exposing the JSON payload builder used by these tests."""

    def _get_payload(self) -> dict[str, Any]: ...


def _body_data(command: PayloadCommand) -> dict[str, Any]:
    payload = command._get_payload()
    assert payload["header"]["channel"] == "rop"
    assert payload["header"]["m"] == "cloudctl"
    assert payload["header"]["pri"] == 3
    assert payload["header"]["ver"] == "0.0.1"
    assert isinstance(payload["header"]["reqid"], str)
    assert isinstance(payload["header"]["ts"], str)
    return payload["body"]["data"]


def test_y1_start_payload() -> None:
    command = y1_clean(CleanAction.START)
    assert command.NAME == "40001"
    assert _body_data(command) == {"cleanSwitch": True, "cleanMode": "smart"}


def test_y1_pause_payload() -> None:
    command = y1_clean(CleanAction.PAUSE)
    assert command.NAME == "40009"
    assert _body_data(command) == {"pauseSwitch": True}


def test_y1_resume_payload() -> None:
    command = y1_clean(CleanAction.RESUME)
    assert command.NAME == "40011"
    assert _body_data(command) == {"pauseSwitch": False}


def test_y1_stop_not_invented() -> None:
    with pytest.raises(NotImplementedError):
        y1_clean(CleanAction.STOP)


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
