from __future__ import annotations

from deebot_client.commands import COMMANDS_WITH_MQTT_P2P_HANDLING
from deebot_client.const import DataType
from deebot_client.hardware.cqyi87 import get_device_info
from deebot_client.messages.json import MESSAGES
from deebot_client.messages.json.y1 import OnY1State
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


def test_cqyi87_numeric_protocol_is_registered_normally() -> None:
    commands = COMMANDS_WITH_MQTT_P2P_HANDLING[DataType.JSON]
    assert {"40001", "40007", "40009", "40011", "40013", "10001"} <= commands.keys()
    assert MESSAGES["10000"] is OnY1State
