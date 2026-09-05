# Upstream PR 1 — DEEBOT Y1 PRO core support

This directory is a staging copy of the first proposed `DeebotUniverse/client.py` contribution for device class `cqyi87` (DEEBOT Y1 PRO).

## Scope

PR1 is intentionally small:

- normal `cqyi87` hardware discovery;
- numeric Y1 smart-clean start (`40001`);
- pause (`40009`) and resume (`40011`);
- area clean (`40007`);
- return to charger (`40013`);
- field query (`10001`) for battery;
- multiplexed/partial live state (`10000`);
- tests for discovery, command construction and partial state handling.

Map rendering, room metadata/names, consumables and additional Y1 fields are deliberately excluded from PR1. They can follow after the core protocol is accepted.

## Evidence status

The `40001` smart-clean command and `10001` battery/chargeStatus query formats were captured from the official app/device protocol. Incoming `10000` state updates were also observed directly.

A successful Ecovacs response (`code: 0`) is not treated as evidence that a command caused physical movement. Commands other than the physically observed start path should receive explicit device validation before the upstream PR is marked ready.

## Upstream target

Target repository: `DeebotUniverse/client.py`, branch `dev`.

Related issue: #1752.

The production Home Assistant integration should continue using its normal `deebot-client` dependency. No replacement `custom_components/ecovacs` integration is required.
