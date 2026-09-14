"""Rolling-window PM2.5 averaging and PSI reporting.

NEA reports PSI from a 24-hour average PM2.5 concentration. This module
generalises that to longer windows (48h, 7d, 30d, 365d) and computes the
sub-index two different ways, because averaging and the PSI transform do not
commute:

  concentration-first : mean the PM2.5 concentrations over the whole window,
                        then apply the PSI transform once. This is the direct
                        generalisation of NEA's method to a longer window.
  index-first         : take the 24-hour PSI as NEA would have reported it at
                        each hour, then mean those reported values over the
                        window. This is "the average of what was published".

The PSI transform is piecewise linear and concave over the reporting range:
its first segment is steep (0-12 ug/m3 covers 50 index points, ~4.17
index/ug) and every later segment is flatter (55-150 ug/m3 covers 100 points,
~1.05 index/ug; 350-500 covers 100 points, ~0.67 index/ug). For a concave f,
Jensen's inequality gives f(mean(x)) >= mean(f(x)), so the index-first average
is <= the concentration-first average whenever the window contains any
variation. Averaging the published index therefore yields the lower headline
number of the two, and the gap widens the more the window mixes clean air
with haze peaks.

Both are reported, alongside the peak and exceedance statistics that a long
window necessarily conceals.
"""

from datetime import datetime, timedelta
from statistics import mean

from .psi import pm25_to_psi, psi_band

# (label, window length in hours)
WINDOWS = [
    ("24-hour (NEA standard)", 24),
    ("48-hour", 48),
    ("7-day", 24 * 7),
    ("30-day", 24 * 30),
    ("365-day", 24 * 365),
]

MIN_HOURS_FOR_24H_PSI = 18  # require most of a day present before reporting one


def parse_rows(rows, region=None):
    """Convert raw (timestamp, {region: value}) rows into (datetime, ug/m3).

    If `region` is None the all-region maximum is used, matching how NEA
    headlines the worst-affected region. Otherwise that single region is used.
    """
    series = []
    for ts, values in rows:
        if not values:
            continue
        when = datetime.fromisoformat(ts)
        if region is None:
            series.append((when, float(max(values.values()))))
        elif region in values:
            series.append((when, float(values[region])))
    series.sort()
    return series


def rolling_24h_psi(series):
    """The 24-hour PSI as NEA would have reported it at each hour.

    Linear two-pointer sweep: a year of hourly data is ~8,800 points, so the
    naive nested scan would be ~77M comparisons.
    """
    out = []
    lo = 0
    running = 0.0
    for hi, (when, value) in enumerate(series):
        running += value
        cutoff = when - timedelta(hours=24)
        while series[lo][0] <= cutoff:
            running -= series[lo][1]
            lo += 1
        count = hi - lo + 1
        if count >= MIN_HOURS_FOR_24H_PSI:
            out.append((when, pm25_to_psi(running / count)))
    return out


def window_slice(points, hours, end):
    """Return the points falling in the `hours` ending at `end`."""
    start = end - timedelta(hours=hours)
    return [(t, v) for t, v in points if start < t <= end]


def summarise(series, reported, hours, end=None):
    """Compute both averaging orders plus the statistics they hide."""
    if not series:
        return None
    end = end or series[-1][0]

    raw = window_slice(series, hours, end)
    if not raw:
        return None
    values = [v for _, v in raw]
    conc_mean = mean(values)

    # The 24h PSI values NEA published during this window.
    published = window_slice(reported, hours, end)
    published_psi = [p for _, p in published]

    worst = max(published, key=lambda p: p[1]) if published else (None, None)
    unhealthy = sum(1 for p in published_psi if round(p) > 100)
    peak_hour = max(raw, key=lambda p: p[1])

    return {
        "hours": hours,
        "readings": len(values),
        "coverage": len(values) / hours,
        "start": raw[0][0],
        "end": raw[-1][0],
        "mean_pm25": conc_mean,
        "psi_concentration_first": pm25_to_psi(conc_mean),
        "psi_index_first": mean(published_psi) if published_psi else None,
        "peak_1h_pm25": peak_hour[1],
        "peak_1h_at": peak_hour[0],
        "worst_24h_psi": worst[1],
        "worst_24h_at": worst[0],
        "unhealthy_hours": unhealthy,
        "unhealthy_share": unhealthy / len(published_psi) if published_psi else None,
    }


def analyse(series, windows=WINDOWS, end=None):
    """Summarise every window. Returns [(label, summary_or_None)]."""
    reported = rolling_24h_psi(series)
    return [(label, summarise(series, reported, hours, end)) for label, hours in windows]
