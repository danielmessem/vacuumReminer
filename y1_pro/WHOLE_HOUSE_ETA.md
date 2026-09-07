# Whole-house clean ETA

## Goal

Expose a Home Assistant-friendly estimate for a running whole-house clean:

- elapsed time;
- estimated total duration;
- estimated time remaining;
- expected completion time;
- confidence/sample information.

The estimate is learned from recent completed **whole-house smart cleans only**. Room/area cleans, interrupted cleans and incomplete sessions must not contaminate the history.

## Baseline algorithm

Keep the most recent 5 valid completed whole-house clean durations.

For a new estimate:

1. Start with the last 5 valid whole-house durations.
2. When 5 samples are available, remove the shortest and longest duration.
3. Apply an additional robust outlier check to the remaining samples using MAD (median absolute deviation). A sample is rejected when its modified z-score is greater than 3.5. If MAD is zero, keep the remaining samples.
4. Average the samples that remain.
5. During a running whole-house clean:
   - `elapsed = now - clean_started_at`
   - `estimated_total = robust_average(history)`
   - `remaining = max(estimated_total - elapsed, 0)`
   - `expected_finish = clean_started_at + estimated_total`

With exactly 5 samples this normally averages the middle 3. The MAD pass exists for unusual histories where another sample is still clearly inconsistent after trimming the extremes.

For fewer than 5 historical samples, expose the available sample count but mark the ETA as warming up. Do not present a high-confidence remaining-time estimate until 5 valid whole-house cleans have been collected.

## Valid whole-house session

A session starts when Y1 state enters `smartClean` from a non-cleaning state after a whole-house start (`40001`).

A session counts toward history only when:

- clean mode is whole-house/smart clean;
- it reaches a normal completed/end state;
- it was not an area/room clean (`areaClean` / `40007`);
- it was not manually stopped/cancelled;
- duration is plausible (> 5 minutes);
- the session did not merely pause/resume (pause time remains part of elapsed wall-clock time unless protocol evidence gives a better active-clean-time field).

Returning to the charger after normal completion should finalize the session once, not create a second session.

## Proposed entities

Expose enough raw data for Home Assistant to render this however the user wants:

- `sensor.<vacuum>_clean_elapsed` — duration since this whole-house clean started.
- `sensor.<vacuum>_clean_time_remaining` — estimated duration remaining.
- `sensor.<vacuum>_estimated_clean_duration` — robust historical average.
- `sensor.<vacuum>_estimated_clean_finish` — timestamp.
- `sensor.<vacuum>_clean_eta_samples` — number of valid historical cleans used/available.

Suggested primary display while cleaning:

`Whole house · 47 min elapsed · ~31 min left · finish ~10:53`

When idle, the remaining/finish sensors should be unavailable or null rather than showing stale values. The estimated historical duration can remain available.

## Persistence

The last 5 valid completed durations must survive Home Assistant and integration restarts. Do not store this only in module globals. The clean-history/ETA layer should have per-device state keyed by the device instance and persistent storage supplied by the integration/application layer.

For the upstream `deebot-client` contribution, prefer exposing clean timing/history events or clean-log data rather than adding Home Assistant-specific sensor classes to the protocol library. HA-specific ETA entities can then be implemented in the Home Assistant Ecovacs integration if upstream maintainers consider this outside `deebot-client` scope.

## Future improvement

The Y1 `10000` telemetry has already shown `cleanTime` and `cleanArea`. Once the exact semantics and units of `cleanTime` are verified across start, pause, resume and completion, it can be used to improve session timing and distinguish active cleaning time from wall-clock elapsed time without changing the robust-history estimator.
