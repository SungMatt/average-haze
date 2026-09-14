"""Tests for the PSI conversion and rolling-window logic."""

import unittest
from datetime import datetime, timedelta

from haze.psi import PM25_BREAKPOINTS, pm25_to_psi, psi_band, psi_to_pm25
from haze.rolling import parse_rows, rolling_24h_psi, summarise


class TestPSIConversion(unittest.TestCase):
    def test_nea_worked_example(self):
        """NEA's own example: 40 ug/m3 -> sub-index 83."""
        self.assertEqual(round(pm25_to_psi(40)), 83)

    def test_breakpoint_nodes_are_exact(self):
        for concentration, index in PM25_BREAKPOINTS:
            self.assertAlmostEqual(pm25_to_psi(concentration), index, places=9)

    def test_monotonic(self):
        previous = -1.0
        for c in range(0, 600):
            current = pm25_to_psi(c)
            self.assertGreaterEqual(current, previous)
            previous = current

    def test_caps_at_500(self):
        self.assertEqual(pm25_to_psi(500), 500.0)
        self.assertEqual(pm25_to_psi(5000), 500.0)

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            pm25_to_psi(-1)

    def test_bands(self):
        self.assertEqual(psi_band(0), "Good")
        self.assertEqual(psi_band(50), "Good")
        self.assertEqual(psi_band(51), "Moderate")
        self.assertEqual(psi_band(100), "Moderate")
        self.assertEqual(psi_band(101), "Unhealthy")
        self.assertEqual(psi_band(200), "Unhealthy")
        self.assertEqual(psi_band(201), "Very Unhealthy")
        self.assertEqual(psi_band(301), "Hazardous")

    def test_round_trip(self):
        for c in [0, 5, 12, 40, 55, 100, 150, 300, 480]:
            self.assertAlmostEqual(psi_to_pm25(pm25_to_psi(c)), c, places=6)

    def test_transform_is_concave(self):
        """First segment is steeper than every later one -- the reason long
        windows understate haze."""
        slopes = [(i2 - i1) / (c2 - c1)
                  for (c1, i1), (c2, i2) in zip(PM25_BREAKPOINTS, PM25_BREAKPOINTS[1:])]
        self.assertAlmostEqual(slopes[0], 50 / 12, places=6)
        for later in slopes[1:]:
            self.assertLess(later, slopes[0])


class TestRolling(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 1, 1, 0, 0)

    def _series(self, values):
        return [(self.t0 + timedelta(hours=i), float(v)) for i, v in enumerate(values)]

    def test_parse_rows_takes_worst_region(self):
        rows = [("2026-01-01T01:00:00+08:00", {"north": 10, "central": 42})]
        self.assertEqual(parse_rows(rows)[0][1], 42.0)

    def test_parse_rows_single_region(self):
        rows = [("2026-01-01T01:00:00+08:00", {"north": 10, "central": 42})]
        self.assertEqual(parse_rows(rows, "north")[0][1], 10.0)

    def test_parse_rows_skips_missing_region(self):
        rows = [("2026-01-01T01:00:00+08:00", {"central": 42})]
        self.assertEqual(parse_rows(rows, "north"), [])

    def test_rolling_24h_needs_enough_hours(self):
        series = self._series([10] * 30)
        rolled = rolling_24h_psi(series)
        # First 17 hours have too few readings to publish a 24h value.
        self.assertEqual(len(rolled), 30 - 17)

    def test_rolling_24h_constant_series(self):
        series = self._series([40] * 48)
        for _, value in rolling_24h_psi(series):
            self.assertAlmostEqual(value, pm25_to_psi(40), places=6)

    def test_jensen_index_first_is_lower(self):
        """PSI is concave, so averaging the published index reads lower than
        averaging concentrations."""
        series = self._series([5] * 336 + [200] * 336)  # 14 clean days, 14 hazy
        reported = rolling_24h_psi(series)
        s = summarise(series, reported, hours=24 * 28)
        self.assertLess(s["psi_index_first"], s["psi_concentration_first"])

    def test_jensen_equality_when_flat(self):
        """With no variation the two averaging orders agree."""
        series = self._series([40] * 720)
        s = summarise(series, rolling_24h_psi(series), hours=24 * 28)
        self.assertAlmostEqual(s["psi_index_first"], s["psi_concentration_first"], places=6)

    def test_long_window_hides_a_spike(self):
        """The headline number goes down while a Hazardous episode is inside."""
        series = self._series([5] * 720 + [320] * 72)  # 30 clean days, then 3 bad
        reported = rolling_24h_psi(series)
        s = summarise(series, reported, hours=len(series))
        self.assertLess(round(s["psi_concentration_first"]), 101)   # reads "Moderate"
        self.assertGreater(round(s["worst_24h_psi"]), 300)          # was "Hazardous"

    def test_coverage_reported(self):
        series = self._series([20] * 12)
        s = summarise(series, rolling_24h_psi(series), hours=24)
        self.assertAlmostEqual(s["coverage"], 0.5, places=6)

    def test_empty_window(self):
        self.assertIsNone(summarise([], [], hours=24))


if __name__ == "__main__":
    unittest.main(verbosity=2)
