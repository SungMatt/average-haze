"""Build the SVG geometry for the five NEA reporting regions, once.

NEA publishes PM2.5 for five regions but no boundary file; the API gives only a
label point per region. The regions are therefore reconstructed as the Voronoi
partition of those five points, clipped to Singapore's actual coastline -- i.e.
each place is assigned to the reporting point nearest it. That reproduces the
cross-shaped arrangement NEA's own map uses (north above, south below, west and
east flanking, central in the middle) without inventing boundaries.

Coastline: OpenStreetMap-derived Singapore outline
(github.com/yinshanyang/singapore, maps/0-country.geojson).

Output is committed as data/map.json so the hourly refresh never needs the
network for geometry.
"""

import json
import math
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "map.json")
COASTLINE = ("https://raw.githubusercontent.com/yinshanyang/singapore/master/"
             "maps/0-country.geojson")

# Region label points, verbatim from the data.gov.sg PM2.5 API's regionMetadata.
SITES = {
    "north":   (103.82, 1.41803),
    "south":   (103.82, 1.29587),
    "west":    (103.70, 1.35735),
    "central": (103.82, 1.35735),
    "east":    (103.94, 1.35735),
}

# Drop islets below this area (deg^2). Keeps the main island plus Tekong, Ubin,
# Jurong Island, Sentosa and the larger southern islands; discards the ~30
# specks that would render as single pixels.
MIN_AREA = 2.0e-6

SIMPLIFY_TOL = 0.00022  # degrees, ~24 m -- below one screen pixel at this scale
VIEW_W = 1000.0
PAD = 6.0


def ring_area(ring):
    a = 0.0
    for (x1, y1), (x2, y2) in zip(ring, ring[1:] + ring[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def simplify(points, tol):
    """Douglas-Peucker."""
    if len(points) < 3:
        return points
    ax, ay = points[0]
    bx, by = points[-1]
    dx, dy = bx - ax, by - ay
    span = math.hypot(dx, dy)
    worst, index = -1.0, 0
    for i, (px, py) in enumerate(points[1:-1], 1):
        if span == 0:
            d = math.hypot(px - ax, py - ay)
        else:
            d = abs(dy * px - dx * py + bx * ay - by * ax) / span
        if d > worst:
            worst, index = d, i
    if worst <= tol:
        return [points[0], points[-1]]
    return simplify(points[:index + 1], tol)[:-1] + simplify(points[index:], tol)


def bisector(inside, other):
    """Half-plane (a, b, c) with a*x + b*y <= c holding for points nearer `inside`.

    |p - inside|^2 <= |p - other|^2 expands to a linear constraint.
    """
    ix, iy = inside
    ox, oy = other
    a = 2 * (ox - ix)
    b = 2 * (oy - iy)
    c = (ox * ox + oy * oy) - (ix * ix + iy * iy)
    return a, b, c


def clip_halfplane(ring, plane):
    """Sutherland-Hodgman clip of a ring against a*x + b*y <= c."""
    a, b, c = plane
    out = []
    n = len(ring)
    for i in range(n):
        cur = ring[i]
        prv = ring[i - 1]
        dc = a * cur[0] + b * cur[1] - c
        dp = a * prv[0] + b * prv[1] - c
        if dc <= 0:
            if dp > 0:
                t = dp / (dp - dc)
                out.append((prv[0] + t * (cur[0] - prv[0]), prv[1] + t * (cur[1] - prv[1])))
            out.append(cur)
        elif dp <= 0:
            t = dp / (dp - dc)
            out.append((prv[0] + t * (cur[0] - prv[0]), prv[1] + t * (cur[1] - prv[1])))
    return out


def load_rings():
    with urllib.request.urlopen(COASTLINE, timeout=120) as resp:
        geo = json.load(resp)
    rings = []
    for feature in geo["features"]:
        geom = feature["geometry"]
        polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        for poly in polys:
            outer = [(float(x), float(y)) for x, y in poly[0]]
            if outer[0] == outer[-1]:
                outer = outer[:-1]
            if ring_area(outer) < MIN_AREA:
                continue
            rings.append(simplify(outer, SIMPLIFY_TOL))
    return rings


def main():
    sys.setrecursionlimit(10000)
    rings = load_rings()
    total = sum(len(r) for r in rings)
    print("coastline: %d islands, %d points after simplify" % (len(rings), total))

    xs = [x for r in rings for x, _ in r]
    ys = [y for r in rings for _, y in r]
    lon0, lon1 = min(xs), max(xs)
    lat0, lat1 = min(ys), max(ys)
    # Equirectangular; at 1.3 deg N the cosine correction is 0.9997, so the
    # scale is effectively isotropic, but carry it anyway.
    kx = math.cos(math.radians((lat0 + lat1) / 2))
    scale = (VIEW_W - 2 * PAD) / ((lon1 - lon0) * kx)
    height = (lat1 - lat0) * scale + 2 * PAD

    def project(pt):
        x, y = pt
        return (PAD + (x - lon0) * kx * scale, PAD + (lat1 - y) * scale)

    def path(ring):
        pts = [project(p) for p in ring]
        return "M" + "L".join("%.1f %.1f" % p for p in pts) + "Z"

    regions = {}
    for name, site in SITES.items():
        planes = [bisector(site, SITES[o]) for o in SITES if o != name]
        pieces = []
        for ring in rings:
            clipped = ring
            for plane in planes:
                clipped = clip_halfplane(clipped, plane)
                if len(clipped) < 3:
                    break
            if len(clipped) >= 3 and ring_area(clipped) > 1e-8:
                pieces.append(path(clipped))
        regions[name] = {
            "d": " ".join(pieces),
            "label": project(site),
        }
        print("  %-8s %d piece(s)" % (name, len(pieces)))

    payload = {
        "width": round(VIEW_W, 1),
        "height": round(height, 1),
        "outline": " ".join(path(r) for r in rings),
        "regions": regions,
    }
    with open(OUT, "w") as fh:
        json.dump(payload, fh)
    print("wrote %s (%.1f kB)" % (OUT, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    main()
