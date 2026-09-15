"""Tests for the PSI conversion and rolling-window logic."""

import unittest
from datetime import datetime, timedelta

from haze.psi import PM25_BREAKPOINTS, pm25_to_psi, psi_band, psi_to_pm25
from haze.regions import CARD_WINDOWS, summarise_all, summarise_region
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


class TestRegions(unittest.TestCase):
    """The per-region ladder, on a synthetic year with one region hazed."""

    def setUp(self):
        start = datetime(2026, 1, 1, 0, 0)
        # 400 days of hourly rows. Every region sits at 20 ug/m3 except
        # central, which spends the final 48 hours at 120.
        self.rows = []
        total = 24 * 400
        for i in range(total):
            when = start + timedelta(hours=i)
            values = {r: 20 for r in ("north", "south", "east", "west", "central")}
            if i >= total - 48:
                values["central"] = 120
            self.rows.append((when.isoformat(), values))
        self.end = start + timedelta(hours=total - 1)

    def test_every_card_window_is_present(self):
        card = summarise_region(self.rows, "north", self.end)
        self.assertEqual(sorted(card["windows"]), sorted(k for k, _, _, _ in CARD_WINDOWS))

    def test_one_hour_window_is_the_latest_reading(self):
        card = summarise_region(self.rows, "central", self.end)
        one = card["windows"]["1h"]
        self.assertEqual(one["readings"], 1)
        self.assertAlmostEqual(one["pm25"], 120.0)
        self.assertEqual(one["psi"], round(pm25_to_psi(120)))

    def test_quiet_region_reads_the_same_on_every_window(self):
        card = summarise_region(self.rows, "west", self.end)
        psis = {w["psi"] for w in card["windows"].values()}
        self.assertEqual(psis, {round(pm25_to_psi(20))})

    def test_the_ladder_falls_as_the_window_widens(self):
        """The point of the page: a 48-hour episode shrinks with the window."""
        card = summarise_region(self.rows, "central", self.end)
        order = [card["windows"][key]["psi"] for key, _, _, _ in CARD_WINDOWS]
        # CARD_WINDOWS runs 365d -> 1h, so the numbers must rise along it.
        self.assertEqual(order, sorted(order))
        self.assertGreater(card["windows"]["1h"]["psi"], card["windows"]["365d"]["psi"])

    def test_regions_are_independent(self):
        cards = {c["key"]: c for c in summarise_all(self.rows)}
        self.assertEqual(len(cards), 5)
        self.assertGreater(cards["central"]["windows"]["24h"]["psi"],
                           cards["east"]["windows"]["24h"]["psi"])

    def test_all_regions_share_one_end_instant(self):
        cards = summarise_all(self.rows)
        self.assertEqual({c["windows"]["365d"]["readings"] for c in cards}, {24 * 365})


class TestMapGeometry(unittest.TestCase):
    """The committed Voronoi partition must actually partition the island."""

    @classmethod
    def setUpClass(cls):
        import json
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "data", "map.json")) as fh:
            cls.geo = json.load(fh)

    def test_every_region_has_geometry(self):
        for region in ("north", "south", "east", "west", "central"):
            self.assertIn(region, self.geo["regions"])
            self.assertTrue(self.geo["regions"][region]["d"].startswith("M"))

    def test_labels_sit_inside_the_viewbox(self):
        for region, shape in self.geo["regions"].items():
            x, y = shape["label"]
            self.assertTrue(0 <= x <= self.geo["width"], region)
            self.assertTrue(0 <= y <= self.geo["height"], region)

    def test_region_areas_sum_to_the_coastline(self):
        """Voronoi cells tile the island: no gaps, no double-counting."""
        import re

        def area(path):
            total = 0.0
            for sub in path.split("Z"):
                pts = [tuple(map(float, p.split()))
                       for p in re.findall(r"(-?\d+\.?\d* -?\d+\.?\d*)", sub)]
                if len(pts) < 3:
                    continue
                acc = 0.0
                for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
                    acc += x1 * y2 - x2 * y1
                total += abs(acc) / 2
            return total

        whole = area(self.geo["outline"])
        parts = sum(area(s["d"]) for s in self.geo["regions"].values())
        self.assertAlmostEqual(parts / whole, 1.0, places=2)


if __name__ == "__main__":
    unittest.main()
