"""Per-region rolling PSI for the five NEA reporting regions.

`haze.rolling` headlines the worst region each hour, which is what NEA does.
This module keeps the regions apart, so each one can be read on its own ladder:
1 hour, 24 hours, 7 days, 30 days, 365 days.

The 1-hour figure needs a caveat the others do not. NEA's PM2.5 band table is
defined for a 24-hour average; pushing a single hourly reading through it gives
a *PSI-equivalent*, not a PSI. It is the right number for "how bad is the air
outside right now" and the wrong number to compare against a published PSI.
"""

from datetime import timedelta

from .fetch import REGIONS
from .psi import psi_band
from .rolling import analyse, parse_rows, rolling_24h_psi

# (payload key, label, window hours, emphasised on the card)
CARD_WINDOWS = [
    ("365d", "365-day", 24 * 365, True),
    ("30d", "30-day", 24 * 30, False),
    ("7d", "7-day", 24 * 7, False),
    ("24h", "24-hour", 24, True),
    ("1h", "1-hour", 1, True),
]

REGION_NAMES = {
    "north": "North",
    "south": "South",
    "east": "East",
    "west": "West",
    "central": "Central",
}

SPARK_DAYS = 14


def common_end(rows):
    """The latest hour any region reported, so every card ends at one instant."""
    series = parse_rows(rows)
    if not series:
        return None
    return series[-1][0]


def summarise_region(rows, region, end):
    """Every card window for one region, plus a fortnight sparkline."""
    series = parse_rows(rows, region)
    if not series:
        return None

    windows = [(label, hours) for _, label, hours, _ in CARD_WINDOWS]
    results = dict(analyse(series, windows=windows, end=end))

    out = {}
    for key, label, hours, big in CARD_WINDOWS:
        s = results.get(label)
        if s is None:
            out[key] = None
            continue
        psi = s["psi_concentration_first"]
        out[key] = {
            "label": label,
            "big": big,
            "psi": round(psi),
            "band": psi_band(psi),
            "pm25": round(s["mean_pm25"], 1),
            "coverage": round(100 * s["coverage"]),
            "readings": s["readings"],
        }

    rolled = rolling_24h_psi(series)
    cutoff = end - timedelta(days=SPARK_DAYS)
    spark = [p for t, p in rolled if t > cutoff]

    year = results.get("365-day")
    return {
        "key": region,
        "name": REGION_NAMES[region],
        "windows": out,
        "spark": [round(p, 1) for p in spark[::3]],
        "peak1h": round(year["peak_1h_pm25"]) if year else None,
        "peak1hAt": year["peak_1h_at"].strftime("%-d %b %Y") if year else None,
        "worst24h": round(year["worst_24h_psi"]) if year else None,
        "worst24hAt": year["worst_24h_at"].strftime("%-d %b %Y") if year else None,
        "unhealthyHours": year["unhealthy_hours"] if year else None,
    }


def summarise_all(rows):
    """[{region payload}] in a fixed order, all ending at the same instant."""
    end = common_end(rows)
    if end is None:
        return []
    out = [summarise_region(rows, r, end) for r in REGIONS]
    return [r for r in out if r is not None]
