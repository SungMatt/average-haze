"""Command-line report: PSI over 24h, 48h, 7d, 30d and 365d windows."""

import argparse
import json
from datetime import date

from .fetch import REGIONS, fetch_range
from .psi import psi_band
from .rolling import WINDOWS, analyse, parse_rows


# WHO 2021 Global Air Quality Guidelines, PM2.5 annual mean (ug/m3):
# the Air Quality Guideline level plus the four interim targets.
WHO_ANNUAL = [
    (5.0, "WHO annual guideline"),
    (10.0, "WHO interim target 4"),
    (15.0, "WHO interim target 3"),
    (25.0, "WHO interim target 2"),
    (35.0, "WHO interim target 1"),
]


def benchmark_annual(mean_pm25):
    """Compare a long-window mean against the WHO annual PM2.5 ladder."""
    lines = []
    guideline = WHO_ANNUAL[0][0]
    lines.append("    annual mean PM2.5       : %.1f ug/m3" % mean_pm25)
    lines.append("    vs WHO annual guideline : %.1fx over (%.0f ug/m3)"
                 % (mean_pm25 / guideline, guideline))
    met = [name for level, name in WHO_ANNUAL if mean_pm25 <= level]
    lines.append("    strictest level met     : %s"
                 % (met[0] if met else "none - above every WHO interim target"))
    return lines


def _fmt(summary):
    cf = summary["psi_concentration_first"]
    idx = summary["psi_index_first"]
    return {
        "mean_pm25": "%.1f" % summary["mean_pm25"],
        "cf": "%d (%s)" % (round(cf), psi_band(cf)),
        "idx": "%d (%s)" % (round(idx), psi_band(idx)) if idx is not None else "n/a",
        "cov": "%.0f%%" % (100 * summary["coverage"]),
    }


def render(results, region):
    who = region or "worst region"
    lines = []
    lines.append("PM2.5 -> PSI, rolling windows (%s)" % who)
    lines.append("=" * 78)
    lines.append("")
    lines.append("%-24s %10s %20s %20s" % ("Window", "mean PM2.5", "PSI (conc-first)", "PSI (index-first)"))
    lines.append("-" * 78)
    for label, summary in results:
        if summary is None:
            lines.append("%-24s %10s %20s %20s" % (label, "-", "no data", "no data"))
            continue
        f = _fmt(summary)
        lines.append("%-24s %10s %20s %20s" % (label, f["mean_pm25"], f["cf"], f["idx"]))
    lines.append("")

    lines.append("What each window conceals")
    lines.append("-" * 78)
    for label, summary in results:
        if summary is None:
            continue
        lines.append("%s  (%s to %s, %.0f%% coverage)"
                     % (label, summary["start"].strftime("%Y-%m-%d %H:%M"),
                        summary["end"].strftime("%Y-%m-%d %H:%M"),
                        100 * summary["coverage"]))
        if summary["worst_24h_psi"] is not None:
            lines.append("    worst 24h PSI in window : %d (%s) on %s"
                         % (round(summary["worst_24h_psi"]),
                            psi_band(summary["worst_24h_psi"]),
                            summary["worst_24h_at"].strftime("%Y-%m-%d %H:%M")))
        lines.append("    peak 1-hour PM2.5       : %.0f ug/m3 on %s"
                     % (summary["peak_1h_pm25"],
                        summary["peak_1h_at"].strftime("%Y-%m-%d %H:%M")))
        if summary["unhealthy_share"] is not None:
            lines.append("    hours at PSI > 100      : %d (%.1f%% of window)"
                         % (summary["unhealthy_hours"], 100 * summary["unhealthy_share"]))
        if summary["hours"] >= 24 * 365:
            lines.extend(benchmark_annual(summary["mean_pm25"]))
        lines.append("")

    lines.append("Note: PSI bands are defined for 24-hour exposure. Reading a 30- or")
    lines.append("365-day mean against them is a category error -- a long-window mean")
    lines.append("belongs against an annual guideline, which is why the 365-day block")
    lines.append("above carries the WHO comparison instead.")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--region", choices=REGIONS,
                    help="single region; default is the worst region each hour")
    ap.add_argument("--days", type=int, default=370,
                    help="days of history to fetch (default 370)")
    ap.add_argument("--json", action="store_true", help="emit JSON instead of a table")
    args = ap.parse_args()

    rows = fetch_range(date.today(), args.days)
    series = parse_rows(rows, args.region)
    if not series:
        raise SystemExit("no readings fetched")
    results = analyse(series)

    if args.json:
        payload = []
        for label, summary in results:
            if summary is None:
                continue
            item = {k: (v.isoformat() if hasattr(v, "isoformat") else v)
                    for k, v in summary.items()}
            item["window"] = label
            item["band_concentration_first"] = psi_band(summary["psi_concentration_first"])
            item["band_index_first"] = psi_band(summary["psi_index_first"])
            payload.append(item)
        print(json.dumps(payload, indent=2))
    else:
        print(render(results, args.region))


if __name__ == "__main__":
    main()
