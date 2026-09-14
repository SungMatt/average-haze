"""Fetch historical hourly PM2.5 readings from Singapore's data.gov.sg API.

The NEA real-time PM2.5 endpoint returns one-hourly PM2.5 (ug/m3) for the five
reporting regions. Queried one calendar day at a time and cached locally, since
a 365-day window needs a year of requests.
"""

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

API = "https://api-open.data.gov.sg/v2/real-time/api/pm25"
# data.gov.sg rejects requests without a browser-style User-Agent.
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
REGIONS = ("north", "south", "east", "west", "central")
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "cache")


def _fetch_day(day, retries=5):
    """Return {iso_timestamp: {region: ug/m3}} for one calendar day."""
    cache_path = os.path.join(CACHE_DIR, "%s.json" % day.isoformat())
    if os.path.exists(cache_path):
        with open(cache_path) as fh:
            return json.load(fh)

    url = "%s?date=%s" % (API, day.isoformat())
    last_error = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code == 429:
                # The API rate-limits a year-long backfill; back off hard and
                # respect Retry-After when it is supplied.
                wait = float(exc.headers.get("Retry-After") or 0) or 20.0 * (attempt + 1)
                time.sleep(wait)
            else:
                time.sleep(1.5 * (attempt + 1))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(1.5 * (attempt + 1))
    else:
        print("  ! %s: %s" % (day, last_error))
        return {}

    readings = {}
    for item in payload.get("data", {}).get("items", []):
        values = item.get("readings", {}).get("pm25_one_hourly", {})
        if not values:
            continue
        # Regions occasionally report null during instrument downtime.
        clean = {r: values[r] for r in REGIONS if values.get(r) is not None}
        if clean:
            readings[item["timestamp"]] = clean

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(cache_path, "w") as fh:
        json.dump(readings, fh)
    return readings


def fetch_range(end_day, days, workers=4, progress=True):
    """Fetch `days` calendar days ending on `end_day` inclusive.

    Returns a list of (timestamp_str, {region: value}) sorted ascending.
    """
    wanted = [end_day - timedelta(days=n) for n in range(days)]
    uncached = [d for d in wanted
                if not os.path.exists(os.path.join(CACHE_DIR, "%s.json" % d.isoformat()))]
    if progress and uncached:
        print("Fetching %d days from data.gov.sg (%d already cached)..."
              % (len(uncached), len(wanted) - len(uncached)))

    merged = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for i, day_readings in enumerate(pool.map(_fetch_day, wanted), 1):
            merged.update(day_readings)
            if progress and uncached and i % 50 == 0:
                print("  ...%d/%d days" % (i, len(wanted)))

    return sorted(merged.items())


if __name__ == "__main__":
    rows = fetch_range(date.today(), 3)
    print("%d hourly records" % len(rows))
    for ts, vals in rows[-3:]:
        print(" ", ts, vals)
