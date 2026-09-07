# Required registry changes for PR1

The current `client.py` `dev` branch builds MQTT P2P command routing from the JSON command registry. Therefore the Y1 classes should be registered through the normal package lists, not by mutating global dictionaries from `hardware/cqyi87.py`.

## `deebot_client/commands/json/__init__.py`

Add:

```python
from .y1 import Y1Charge, Y1Clean, Y1CleanArea, Y1FieldQuery
```

Add `Y1FieldQuery` to `_COMMANDS`. `Y1Clean`, `Y1CleanArea` and `Y1Charge` use different numeric names per action/instance, so they should not be used as generic incoming-command factories unless the upstream maintainers want explicit classes for each numeric command. The hardware profile can still instantiate them directly.

The important routing requirement for PR1 is command `10001`: it must appear in `COMMANDS`, which automatically places it in `COMMANDS_WITH_MQTT_P2P_HANDLING` because it subclasses `CommandMqttP2P`.

## `deebot_client/messages/json/__init__.py`

Add:

```python
from .y1 import OnY1State
```

Add `OnY1State` to `_MESSAGES`, which registers message `10000` through the normal message registry.

## Why this differs from the local patch

The working local profile directly modifies `MESSAGES` and `COMMANDS_WITH_MQTT_P2P_HANDLING`. That was appropriate for a runtime patch because no package source files could be changed. It is not the preferred upstream architecture. The upstream submission should use the package registries so the new protocol is imported, typed, tested and discoverable in the same way as existing commands/messages.
