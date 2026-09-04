# Stable baseline: profile 1.8.18

This package is being reconstructed from the effective behaviour of Diagnostics 2.0.41 / profile 1.8.18.

## Map behaviour that must not regress

Profile 1.8.17 introduced border-connected outside-background removal. It detects the dominant non-zero value on the raster border and flood-fills only border-connected pixels of that value to transparent. Enclosed occurrences of the same raw value are preserved.

Profile 1.8.18 then vertically flips the cleaned raster for Home Assistant presentation while preserving the 1.8.17 cleanup and room palette.

These behaviours have been physically/visually validated on the target Y1 PRO and are frozen as the map baseline.

## Runtime behaviour that must not regress

- Device remains available in Home Assistant for hours without needing the Ecovacs app to revive it.
- Existing Home Assistant Ecovacs integration remains in use; this support supplies the missing cqyi87 deebot-client hardware behaviour.
- Numeric Y1 protocol is used instead of guessed legacy Ecovacs commands.
- State message 10000 is treated as partial telemetry.
- Field query 10001 is used for observed fields such as battery and charge status.
- Consumable resets remain disabled until their protocol is proven.

## Development rule

Do not modify `main` or the currently deployed Diagnostics 2.0.41 path while reconstructing the clean package. Development happens on `y1-pro-clean-package` until parity tests pass.
