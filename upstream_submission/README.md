# Upstream submission: DEEBOT Y1 PRO (`cqyi87`)

The correct first upstream target is **DeebotUniverse/client.py**, not Home Assistant Core.

Home Assistant's Ecovacs integration asks `deebot-client` for the hardware profile. The current failure for `cqyi87` originates there: an unknown device class returns no `StaticDeviceInfo`, so Home Assistant cannot expose the Y1 PRO as a supported Ecovacs vacuum.

Once support is merged and released in `deebot-client`, Home Assistant can consume the release through its normal dependency update process. A Home Assistant PR should only be needed if HA-specific entities/features need adjustment after the library supports the device.

## Proposed upstream series

### PR 1 — device support and core control/state

Keep the first review small and based on captured Y1 protocol:

- add `deebot_client/hardware/cqyi87.py`
- add numeric Y1 commands used by this class
  - `40001` start smart clean
  - `40009` pause
  - `40011` resume
  - `40013` return to charger
  - `40007` room/area clean
  - `10001` field query
- add `10000` partial state message handling
- battery via `10001 {"fields":["battery"]}`
- state from `status`, `pauseSwitch`, and `chargeStatus`
- tests for command payloads and partial state transitions

### PR 2 — map, rooms and positions

After core device support is accepted:

- add Y1 `30001` query support and `30000`/`30001` telemetry handling as required by captured traffic
- translate map metadata into existing `CachedMapInfoEvent`, `RoomsEvent`, `PositionsEvent`, and `MinorMapEvent`
- LZ4 Y1 raster decoding and conversion into deebot-client's native map-piece format
- room names from the Y1 `areas` payload when the device supplies them
- tests using redacted fixture payloads

### PR 3 — consumables / optional capabilities

Add only fields we have captured and validated. Keep consumable reset disabled until a reset command is captured and physically verified.

## What should not be submitted

- the Home Assistant Diagnostics add-on
- runtime patch/install code
- the `server_hotfix_vXXX.py` chain
- global availability overrides
- account/device identifiers or raw unredacted MQTT topics
- guessed legacy Ecovacs commands
- Home Assistant-specific SVG monkey patches

## Current evidence

Working local support proves that `cqyi87` can be represented through the normal `deebot-client` capability/event model. The existing upstream issue is #1752. The issue's early claim that legacy `clean` was functionally working has been superseded by later physical testing: command acknowledgement alone is not evidence of robot motion. The production submission must use the captured numeric Y1 protocol.

## Acceptance baseline

Before submitting PR 1, the candidate must pass offline tests for:

1. exact command name and body for start/pause/resume/charge/area clean;
2. `10001` battery query construction and response parsing;
3. `10000` partial updates without resetting fields omitted from an event;
4. cleaning, paused, returning, docked and idle state transitions;
5. no change to availability semantics outside `cqyi87`.

Before submitting PR 2, map output must match the currently validated 1.8.18 behaviour closely enough that switching from the local patch does not regress orientation, room segmentation, outside-background removal, robot/dock alignment or room metadata.
