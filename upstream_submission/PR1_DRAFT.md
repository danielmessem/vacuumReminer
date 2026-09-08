# Draft PR: Add DEEBOT Y1 PRO (`cqyi87`) core support

## Summary

Adds initial support for the DEEBOT Y1 PRO hardware class `cqyi87` using protocol captured from the official Ecovacs app and validated against a physical device.

This deliberately limits scope to core discovery, cleaning control, battery, state, and current-clean statistics. Map support will follow separately to keep review size manageable.

## Why

`cqyi87` currently has no hardware profile, so `get_static_device_info("cqyi87")` cannot return a supported device profile and Home Assistant's Ecovacs integration cannot initialize it normally.

The Y1 PRO also does not use several legacy Ecovacs commands expected by similar profiles. Battery/state and cleaning control use numeric commands/messages.

## Captured protocol included in this PR

| Function | Y1 command/message | Body / observed fields |
| --- | --- | --- |
| Start smart clean | `40001` | `{"cleanSwitch": true, "cleanMode": "smart"}` |
| Pause | `40009` | `{"pauseSwitch": true}` |
| Resume | `40011` | `{"pauseSwitch": false}` |
| Return to charger | `40013` | `{"chargeSwitch": true}` |
| Area clean | `40007` | `{"cleanSwitch": true, "cleanMode": "area", "cleanValues": [...]}` |
| Query fields | `10001` | `{"fields": ["battery"]}` etc. |
| Live state | `10000` | partial updates including `status`, `pauseSwitch`, `chargeStatus`, `battery`, `cleanArea`, `cleanTime` |

The numeric request envelope observed with the verified start command uses `channel=rop`, `m=cloudctl`, `pri=3`, and `ver=0.0.1`.

## State mapping

- `status=smartClean` / `areaClean` -> cleaning
- `pauseSwitch=true` -> paused
- `status=goCharge` -> returning
- `chargeStatus=true` -> docked
- `status=idle` -> idle

`10000` messages are partial updates; omitted fields must not be treated as false/default values. The first upstream version deliberately avoids process-global cached pause/charge state so multiple devices cannot interfere with one another. `chargeStatus=true` remains the authoritative docked event.

`cleanTime` is reported by this Y1 in minutes and is converted to seconds before emitting `StatsEvent`, matching the existing client.py/Home Assistant duration contract.

## Architecture

The upstream implementation uses normal package registration:

- fixed command classes for `40001`, `40007`, `40009`, `40011`, `40013`, and `10001`;
- `Y1Clean(action)` only as a capability factory that dispatches to those fixed classes;
- `OnY1State` registered normally as message `10000`;
- `hardware/cqyi87.py` only wires capabilities and does not mutate global command/message registries.

This differs intentionally from the local runtime patch, which had to mutate already-imported registries because it was injected into an installed package.

## Validation

The start command has been physically verified to start the Y1 PRO. Battery query and live state payloads were captured from device/app traffic. Other numeric controls are included only where captured and should not be described as physically verified unless a corresponding physical test record exists.

The STOP command is not invented in this PR. `CleanAction.STOP` currently raises `NotImplementedError` until the Y1 stop payload is captured or physically verified.

## Follow-up

A separate PR will add the Y1 map/rooms/positions protocol (`30000` / `30001`) and raster conversion, based on the already-working local implementation. Consumables and optional settings can follow after core support is accepted.

Related: #1752
