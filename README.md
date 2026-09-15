# average-haze

Reports Singapore PSI over 24-hour, 48-hour, 7-day, 30-day and 365-day rolling
windows, using NEA's own PM2.5 -> PSI conversion.

**Live report: <https://sungmatt.github.io/average-haze/>** — rebuilt hourly.
**Region by region: <https://sungmatt.github.io/average-haze/regions.html>**

## The conversion

From NEA, [*Computation of the Pollutant Standards Index
(PSI)*](https://www.haze.gov.sg/docs/default-source/faq/computation-of-the-pollutant-standards-index-(psi).pdf)
(last updated March 2014). Each pollutant sub-index is a segmented linear
function of concentration. For PM2.5 the published bands are:

| PSI band  | 24-hr PM2.5 (µg/m³) |
|-----------|---------------------|
| 0 – 50    | 0 – 12    |
| 51 – 100  | 13 – 55   |
| 101 – 200 | 56 – 150  |
| 201 – 300 | 151 – 250 |
| 301 – 400 | 251 – 350 |
| 401 – 500 | 351 – 500 |

Within a segment, NEA Equation 1 interpolates linearly:

```
Ii = (Ii,j+1 - Ii,j) / (Xi,j+1 - Xi,j) × (Xi - Xi,j) + Ii,j
```

The overall PSI is the maximum of the six pollutant sub-indices. This tool
computes the PM2.5 sub-index only, which is the binding one during haze.

Verified against NEA's worked example: 40 µg/m³ → 83.

## Running it

```
python3 -m haze.report                 # worst region each hour
python3 -m haze.report --region north  # a single region
python3 -m haze.report --json
python3 -m unittest test_haze          # 27 tests
```

Hourly PM2.5 comes from the data.gov.sg real-time API, one day per request,
cached under `data/cache/`. The cache is committed, so a refresh only fetches
the two days that can still change.

## Hourly refresh

`.github/workflows/refresh.yml` runs hourly:

```
python -m unittest test_haze     # conversion still matches NEA's example
python -m haze.refresh           # refetch recent days, rebuild haze-report.html
```

then commits any changed readings and deploys the page to GitHub Pages.

`haze.refresh` drops the last two cached days before fetching (today's entry is
written while the day is still incomplete), rebuilds `haze-report.html` from
`template.html` and `regions.html` from `map-template.html`, and prunes cache
files older than 375 days so a long-running
schedule doesn't grow the repo without bound. Every figure in the page's prose
is filled in from the data at load time, so the text can't drift out of step
with the charts.

Two caveats worth knowing. GitHub queues scheduled runs on a best-effort basis,
so an hourly run can land late. And GitHub disables scheduled workflows after 60
days without repository activity — bot commits don't reliably reset that clock,
so the schedule may occasionally need a manual re-enable.

## The region map

`regions.html` puts the same conversion on a map of Singapore, one card per NEA
reporting region, each showing 365-day, 30-day, 7-day, 24-hour and 1-hour
levels on a shared scale. Selecting a window recolours the map; the choice is
kept in the URL hash (`regions.html#365d`) so a view is a shareable link.

Two things about it are worth stating plainly.

**The 1-hour number is a PSI-equivalent, not a PSI.** NEA's PM2.5 band table is
defined for a 24-hour average. Pushing a single hourly reading through it
answers "how bad is the air right now" and must not be quoted against a
published PSI.

**The region shapes are a reconstruction.** NEA publishes no boundary file for
its five reporting regions — the API gives one label point each. `tools/build_map.py`
takes those five points, builds their Voronoi partition (every place belongs to
the reporting point nearest it), and clips it to an OpenStreetMap-derived
coastline. That reproduces the cross-shaped arrangement NEA's own map uses
without inventing borders, but the borders are approximate and the page says so.
`test_region_areas_sum_to_the_coastline` checks the cells tile the island with
no gaps or overlaps.

The script runs once and its output is committed as `data/map.json`, so the
hourly refresh never touches the network for geometry:

```
python3 tools/build_map.py
```

## Two averaging orders

Averaging and the PSI transform do not commute, so both are reported:

- **concentration-first** — mean the PM2.5 over the window, then convert once.
  The direct generalisation of NEA's method to a longer window.
- **index-first** — mean the 24-hour PSI values NEA would have published at
  each hour. "The average of what was reported."

The transform is concave: its first segment runs at 4.17 index points per
µg/m³, the 55–150 segment at 1.05, the 350–500 segment at 0.67. By Jensen's
inequality `f(mean(x)) ≥ mean(f(x))`, so index-first always reads at or below
concentration-first, and the gap grows with the spread inside the window.

## What the long windows actually do

They do not measure current air quality, and nothing here should be published
as though they do.

A rolling mean is a low-pass filter. Haze in Singapore arrives as episodes
lasting days to weeks against a clean baseline, which is exactly the signal a
long window removes. Widening the window from 24 hours to 365 days divides a
one-week episode's contribution by roughly 52 — an episode can sit at
Hazardous throughout while the annual mean stays in the Good band. The number
gets lower because the averaging discarded the event, not because the air was
clean. `test_long_window_hides_a_spike` pins that behaviour down: 30 clean days
plus a 3-day Hazardous episode reports "Moderate".

The 365-day mean is a real and useful statistic for chronic exposure, which is
what long-term PM2.5 health effects track, and it is worth reporting for that.
It is the wrong instrument for "should I go outside today", and the 24-hour
window is already criticised for the same reason on a smaller scale.

So the report prints, next to every window: the worst 24-hour PSI inside it,
the peak 1-hour PM2.5, and the number of hours above PSI 100. A window average
is only honest when shown with the peaks it smoothed away.
