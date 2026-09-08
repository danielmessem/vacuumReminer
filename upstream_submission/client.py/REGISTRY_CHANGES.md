# Required registry changes for PR1

The current `client.py` `dev` branch builds MQTT P2P routing from the normal JSON command registry. The upstream Y1 implementation therefore registers fixed-name command classes normally instead of mutating global dictionaries from `hardware/cqyi87.py`.

## `deebot_client/commands/json/__init__.py`

Import the fixed numeric command classes:

```python
from .y1 import (
    Y1Charge,
    Y1CleanArea,
    Y1FieldQuery,
    Y1PauseClean,
    Y1ResumeClean,
    Y1StartClean,
)
```

Add all six to `_COMMANDS`:

```python
    Y1StartClean,
    Y1CleanArea,
    Y1PauseClean,
    Y1ResumeClean,
    Y1Charge,
    Y1FieldQuery,
```

This produces normal registry entries for `40001`, `40007`, `40009`, `40011`, `40013`, and `10001`. Because each class subclasses `CommandMqttP2P`, `deebot_client.commands.COMMANDS_WITH_MQTT_P2P_HANDLING` is populated automatically by the existing library code.

`Y1Clean(action)` is intentionally a factory used only by the hardware capability. It dispatches a `CleanAction` to one of the fixed-name command classes, so the command registry never depends on an instance mutating its `NAME`.

## `deebot_client/messages/json/__init__.py`

Add:

```python
from .y1 import OnY1State
```

Add `OnY1State` to `_MESSAGES`. This registers message `10000` through the normal message registry.

## `deebot_client/hardware/cqyi87.py`

No global registry mutation is required. The hardware profile only wires capabilities to the Y1 command/message/event implementation.

## Why this differs from the local runtime patch

The working Home Assistant patch directly modifies `MESSAGES` and `COMMANDS_WITH_MQTT_P2P_HANDLING` because it is injected into an already-installed `deebot-client`. That mechanism should not be submitted upstream. In package source, normal registries are cleaner, typed, testable, and automatically participate in MQTT P2P routing.
