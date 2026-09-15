"""Refresh the published report: refetch recent days, rebuild the page.

Run this before republishing the artifact. Everything older than a couple of
days is already cached, so a refresh costs only a handful of API calls.
"""

import json
import os
from datetime import date, timedelta

from .fetch import CACHE_DIR, fetch_range
from .psi import psi_band
from .regions import CARD_WINDOWS, summarise_all
from .rolling import analyse, parse_rows, rolling_24h_psi

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE = os.path.join(ROOT, "template.html")
PAGE = os.path.join(ROOT, "haze-report.html")
DATA = os.path.join(ROOT, "data", "chart.json")

MAP_TEMPLATE = os.path.join(ROOT, "map-template.html")
MAP_PAGE = os.path.join(ROOT, "regions.html")
MAP_GEOMETRY = os.path.join(ROOT, "data", "map.json")

# Today's cache entry is written while the day is still incomplete, and
# yesterday's can be missing its final hours, so both are always refetched.
STALE_DAYS = 2

# Days of history to keep on disk. The report needs 365 plus a few days of
# lead-in for the first rolling window; anything older is dropped so a
# long-running scheduled refresh does not grow the cache without bound.
KEEP_DAYS = 375


def drop_stale_cache(today):
    for n in range(STALE_DAYS):
        path = os.path.join(CACHE_DIR, "%s.json" % (today - timedelta(days=n)).isoformat())
        if os.path.exists(path):
            os.remove(path)


def prune_cache(today):
    """Drop cache files older than the window the report actually uses."""
    cutoff = (today - timedelta(days=KEEP_DAYS)).isoformat()
    dropped = 0
    for name in os.listdir(CACHE_DIR):
        if name.endswith(".json") and name[:-5] < cutoff:
            os.remove(os.path.join(CACHE_DIR, name))
            dropped += 1
    return dropped


def build_payload(series):
    rolled = rolling_24h_psi(series)
    end = rolled[-1][0]
    year = [(t, p) for t, p in rolled if t >= end - timedelta(days=365)]
    # The series is already a 24-hour mean, so it holds no sub-daily detail;
    # sampling every 6th hour is lossless at chart resolution.
    sampled = year[::6]
    recent = [(t, p) for t, p in rolled if t >= end - timedelta(days=14)]

    windows = []
    for label, s in analyse(series):
        windows.append({
            "label": label.replace(" (NEA standard)", ""),
            "isStandard": "NEA" in label,
            "hours": s["hours"],
            "meanPm25": round(s["mean_pm25"], 1),
            "psi": round(s["psi_concentration_first"]),
            "psiIndexFirst": round(s["psi_index_first"]),
            "band": psi_band(s["psi_concentration_first"]),
            "worst24h": round(s["worst_24h_psi"]),
            "worstAt": s["worst_24h_at"].strftime("%d %b %Y"),
            "unhealthyHours": s["unhealthy_hours"],
            "unhealthyShare": round(100 * s["unhealthy_share"], 1),
        })

    return {
        "generated": end.strftime("%d %b %Y, %H:%M"),
        "yearStart": sampled[0][0].strftime("%d %b %Y"),
        "yearEnd": end.strftime("%d %b %Y"),
        "t0": sampled[0][0].isoformat(),
        "stepHours": 6,
        "psi": [round(p, 1) for _, p in sampled],
        "months": [{"i": i, "label": t.strftime("%b")} for i, (t, _) in enumerate(sampled)
                   if t.day == 1 and t.hour < 6],
        "recentT0": recent[0][0].isoformat(),
        "recent": [round(p, 1) for _, p in recent],
        "recentDays": [{"i": i, "label": t.strftime("%-d %b")} for i, (t, _) in enumerate(recent)
                       if t.hour == 0],
        "windows": windows,
        "annualMeanPm25": round([w for w in windows if w["label"] == "365-day"][0]["meanPm25"], 1),
        "totalReadings": len(series),
        "peakRolled": round(max(p for _, p in year), 1),
        "minRolled": round(min(p for _, p in year), 1),
    }


def build_map_payload(rows, end):
    """Per-region card ladders plus the committed region geometry."""
    regions = summarise_all(rows)
    if not regions:
        raise SystemExit("no regional readings")

    with open(MAP_GEOMETRY) as fh:
        geometry = json.load(fh)

    ranked = sorted(regions, key=lambda r: r["windows"]["24h"]["psi"], reverse=True)
    return {
        "generated": end.strftime("%d %b %Y, %H:%M"),
        "map": geometry,
        "regions": regions,
        "windows": [{"key": key, "label": label, "hours": hours, "big": big}
                    for key, label, hours, big in CARD_WINDOWS],
        "worst": ranked[0]["name"],
        "cleanest": ranked[-1]["name"],
        "spread24h": ranked[0]["windows"]["24h"]["psi"] - ranked[-1]["windows"]["24h"]["psi"],
    }


def render(template_path, out_path, payload):
    template = open(template_path).read()
    if "__DATA__" not in template:
        raise SystemExit("%s is missing its __DATA__ placeholder" % template_path)
    with open(out_path, "w") as fh:
        fh.write(template.replace("__DATA__", json.dumps(payload)))


def main():
    today = date.today()
    drop_stale_cache(today)
    pruned = prune_cache(today)
    rows = fetch_range(today, 370, progress=False)
    series = parse_rows(rows)
    if not series:
        raise SystemExit("no readings fetched")

    payload = build_payload(series)
    with open(DATA, "w") as fh:
        json.dump(payload, fh)
    render(TEMPLATE, PAGE, payload)

    map_payload = build_map_payload(rows, series[-1][0])
    render(MAP_TEMPLATE, MAP_PAGE, map_payload)

    current = payload["windows"][0]
    print("latest reading   : %s" % payload["generated"])
    print("24-hour PSI      : %d (%s)" % (current["psi"], current["band"]))
    print("365-day PSI      : %d" % payload["windows"][-1]["psi"])
    print("cache            : %d days (%d pruned)"
          % (len(os.listdir(CACHE_DIR)), pruned))
    print("worst region     : %s (24h PSI %d)"
          % (map_payload["worst"],
             max(r["windows"]["24h"]["psi"] for r in map_payload["regions"])))
    print("rebuilt          : %s" % PAGE)
    print("                 : %s" % MAP_PAGE)


if __name__ == "__main__":
    main()
