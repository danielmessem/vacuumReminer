# DEEBOT Y1 PRO compatibility package

This directory is the clean production home for support for Ecovacs DEEBOT Y1 PRO class `cqyi87`.

## Baseline

The behavioural baseline is Diagnostics 2.0.41 / generated profile 1.8.18. The existing `main` implementation remains the known-good rollback while this package is developed and validated.

## Proven protocol

- Start smart clean: `40001` with `cleanSwitch=true`, `cleanMode=smart`
- Pause: `40009` with `pauseSwitch=true`
- Resume: `40011` with `pauseSwitch=false`
- Area clean: `40007` with `cleanSwitch=true`, `cleanMode=area`, `cleanValues=[...]`
- Return to charger: `40013` with `chargeSwitch=true`
- Live state/event: `10000` (partial updates)
- Field query: `10001` with `fields=[...]`
- Map query/telemetry: `30001` / `30000`

Only behaviour captured from the Y1 PRO or physically validated should be promoted to production support. Generic Ecovacs commands must not be used as substitutes where the Y1 protocol is unproven.

## Architecture

The production package will contain the Y1 device profile, protocol translation, state handling and map translation. Diagnostics/reverse-engineering and repair tooling stays outside this directory.

The package should remain compatible with the existing Home Assistant Ecovacs integration by supplying the missing `deebot-client` hardware profile rather than replacing Home Assistant's `ecovacs` integration.

## Stability rules

1. Do not change the working map geometry, vertical orientation, border-connected outside-background removal or room palette without a regression test.
2. Do not add an availability workaround while the current profile remains stable for long periods.
3. Treat `10000` as partial state updates; retain prior state for fields omitted from an event.
4. Consumable resets remain unsupported until their Y1 protocol is captured and physically verified.
5. Keep the old 2.0.41 / 1.8.18 path available until the clean package passes equivalent tests.

## Migration plan

1. Materialize the effective 1.8.18 profile into this directory instead of generating it through the historical hotfix chain.
2. Split commands, state and map helpers into reviewable modules where doing so does not conflict with `deebot-client` hardware-profile conventions.
3. Add offline tests for state transitions and map transforms.
4. Point Diagnostics at the clean package on the development branch and verify it on the physical Y1 PRO.
5. Promote it to `main` only after parity with the known-good baseline.
6. Prepare the resulting hardware support for an upstream `deebot-client` contribution.
