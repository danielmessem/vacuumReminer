from __future__ import annotations

from deebot_client.hardware.cqyi87 import get_device_info
from deebot_client.models import CleanAction


def test_cqyi87_core_capabilities() -> None:
    info = get_device_info()
    capabilities = info.capabilities

    assert capabilities.battery.get[0].NAME == "10001"
    assert capabilities.state.get[0].NAME == "10001"
    assert capabilities.clean.action.command(CleanAction.START).NAME == "40001"
    assert capabilities.clean.action.command(CleanAction.PAUSE).NAME == "40009"
    assert capabilities.clean.action.command(CleanAction.RESUME).NAME == "40011"
    assert capabilities.charge.execute().NAME == "40013"
    assert capabilities.map is None
