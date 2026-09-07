# DEEBOT Y1 PRO Diagnostic Toolkit

Home Assistant add-on for collecting and testing DEEBOT Y1 PRO diagnostics.

## Initial scope

- Home Assistant and host environment diagnostics
- DEEBOT client/integration version discovery
- Python package inspection
- Y1 PRO capability and API probing
- Map-related method tests
- Recent log collection
- Structured diagnostic bundle export
- Web UI for running tests

This project is intentionally diagnostic-first: it should not modify the existing Home Assistant DEEBOT integration unless explicitly enabled in a future version.

## Whole-house Clean ETA

The optional `y1_pro_eta` companion integration learns from the five most recent
completed whole-house cleans. At five samples it removes the longest and
shortest runs, applies a median-absolute-deviation outlier check, and averages
the remaining durations. It exposes elapsed time, estimated total time, time
left, expected finish time, and sample count as Home Assistant sensors.

Install it from the add-on's **Install Whole-house ETA** button, restart Home
Assistant Core, then add **Y1 PRO Whole-house Clean ETA** from Settings > Devices
& services and select `vacuum.beepbop`.
