"""Tests for robust whole-house ETA calculation."""

import importlib.util
from pathlib import Path
import unittest

MODULE = Path(__file__).parents[1] / "custom_components/y1_pro_eta/estimator.py"
SPEC = importlib.util.spec_from_file_location("y1_eta_estimator", MODULE)
assert SPEC and SPEC.loader
estimator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(estimator)


class FilteredAverageTests(unittest.TestCase):
    def test_no_history(self):
        self.assertIsNone(estimator.filtered_average([]))

    def test_learns_before_five_runs(self):
        self.assertEqual(estimator.filtered_average([3600, 4200]), 3900)

    def test_uses_latest_five_and_trims_extremes(self):
        self.assertEqual(
            estimator.filtered_average([999, 3000, 3600, 3660, 3720, 9000]),
            3660,
        )

    def test_mad_removes_remaining_outlier(self):
        self.assertEqual(
            estimator.filtered_average([1000, 3600, 3610, 5000, 9000]),
            3605,
        )

    def test_zero_mad_removes_value_different_from_majority(self):
        self.assertEqual(
            estimator.filtered_average([1000, 3600, 3600, 5000, 9000]),
            3600,
        )


if __name__ == "__main__":
    unittest.main()
