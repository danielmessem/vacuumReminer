# Draft PR: Add DEEBOT Y1 PRO (`cqyi87`) core support

## Summary

Adds initial support for the DEEBOT Y1 PRO hardware class `cqyi87` using protocol captured from the official Ecovacs app and validated against a physical device.

This deliberately limits scope to core discovery, cleaning control, battery and state. Map support will follow separately to keep review size manageable.

## Why

`cqyi87` currently has no hardware profile, so `get_static_device_info("cqyi87")` returns no supported device information and Home Assistant's Ecovacs integration cannot initialize it normally.

The Y1 PRO also does not use several legacy Ecovacs commands expected by similar profiles. In particular, battery and state are exposed through numeric commands/messages.

## Captured protocol included in this PR

| Function | Y1 command/message | Body / observed fields |
| --- | --- | --- |
| Start smart clean | `40001` | `{"cleanSwitch": true, "cleanMode": "smart"}` |
| Pause | `40009` | `{"pauseSwitch": true}` |
| Resume | `40011` | `{"pauseSwitch": false}` |
| Return to charger | `40013` | `{"chargeSwitch": true}` |
| Area clean | `40007` | `{"cleanSwitch": true, "cleanMode": "area", "cleanValues": [...]}` |
| Query fields | `10001` | `{"fields": ["battery"]}` etc. |
| Live state | `10000` | partial updates including `status`, `pauseSwitch`, `chargeStatus`, `battery` |

## State mapping

- `status=smartClean` / `areaClean` -> cleaning
- `pauseSwitch=true` -> paused
- `status=goCharge` -> returning
- `chargeStatus=true` -> docked
- `status=idle` -> docked when the most recent `chargeStatus` is true, otherwise idle

`10000` messages are partial updates; omitted fields must not be treated as false/default values.

## Validation

The start command has been physically verified to start the Y1 PRO. Battery query and live state payloads were captured from the device/app traffic. Other numeric controls are included only where captured and should have explicit tests for payload generation before merge.

## Follow-up

A separate PR will add the Y1 map/rooms/positions protocol (`30000` / `30001`) and raster conversion, based on the already-working local implementation.

Related: #1752
