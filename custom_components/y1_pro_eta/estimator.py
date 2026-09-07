"""Pure ETA calculation helpers."""

from __future__ import annotations

from statistics import median


def filtered_average(durations: list[float]) -> float | None:
    """Return a robust average in seconds from up to five recent runs.

    With five samples the fastest and slowest are removed. A MAD check is then
    applied to the remaining values. For fewer samples, all available samples
    are used so the feature can learn immediately.
    """
    values = sorted(float(value) for value in durations[-5:] if value > 0)
    if not values:
        return None
    if len(values) >= 5:
        values = values[1:-1]
    if len(values) >= 3:
        centre = median(values)
        deviations = [abs(value - centre) for value in values]
        mad = median(deviations)
        if mad > 0:
            # Modified z-score threshold 3.5; 0.6745 scales MAD to sigma.
            kept = [
                value
                for value in values
                if 0.6745 * abs(value - centre) / mad <= 3.5
            ]
            if kept:
                values = kept
        elif values.count(centre) > len(values) / 2:
            # When most runs are identical MAD is zero; differing values are
            # still clear outliers rather than evidence of zero variability.
            values = [value for value in values if value == centre]
    return sum(values) / len(values)
