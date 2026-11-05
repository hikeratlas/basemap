#!/usr/bin/env python3
# trail-areas.py TRAILS.geojsonl PARKS.geojsonl OUT.geojsonl [--bbox MINLON,MINLAT,MAXLON,MAXLAT]
#
# Trail networks outside parks, as areas for hikeratlas/routes to curate as it
# does parks (e.g. Newfoundland's Skerwink Trail, which no park contains).
# Reads export/trails.lua's output (named trails, and viewpoints, waterfalls,
# peaks, parking and trailheads) and the parks export, and writes one polygon
# per kept network: its trails grown by BUFFER_M, with name, osm_id
# ("trail-<first way id>"), km and area (m²).
#
# A network is the named trails outside parks that share nodes. It's kept if:
#   - it has at least MIN_KM of trail,
#   - at least MIN_DESTS viewpoints, waterfalls or peaks are within DEST_M,
#   - and it isn't in a city: fewer than half of the points sampled along it
#     have URBAN_LOTS or more parking lots within 1 km (as hikeratlas/routes'
#     urban_lots: remote trailheads have a handful nearby, cities dozens).
#
# Distances are approximate: each network is measured with longitude scaled
# by the cosine of its latitude.
import json, math, sys
from collections import Counter, defaultdict
import numpy as np
import shapely
from shapely.geometry import shape, mapping, LineString, MultiLineString, Point

MIN_KM = 3.0
MIN_DESTS = 2
DEST_M = 300.0
BUFFER_M = 500.0
URBAN_LOTS = 12
SNAP = 1e-6  # nodes shared between ways have identical coordinates
M_PER_DEG = 111_320.0

args = sys.argv[1:]
bbox = None
if '--bbox' in args:
    i = args.index('--bbox')
    bbox = [float(x) for x in args[i + 1].split(',')]
    del args[i:i + 2]
trails_path, parks_path, out_path = args

def read(path):
    with open(path) as f:
        for line in f:
            line = line.strip().lstrip('\x1e')
            if line:
                try:
                    yield json.loads(line)
                except ValueError:
                    pass

def in_bbox(g):
    if not bbox:
        return True
    x0, y0, x1, y1 = g.bounds
    return not (x1 < bbox[0] or x0 > bbox[2] or y1 < bbox[1] or y0 > bbox[3])

# Parks, to drop trails inside them.
parks = []
for f in read(parks_path):
    try:
        g = shape(f['geometry'])
    except Exception:
        continue
    if not g.is_empty and 'Polygon' in g.geom_type and in_bbox(g):
        parks.append(g)
park_tree = shapely.STRtree(parks)

lines, names, ids = [], [], []
dests, lots = [], []
for f in read(trails_path):
    p = f.get('properties', {})
    try:
        g = shape(f['geometry'])
    except Exception:
        continue
    if g.is_empty or not in_bbox(g):
        continue
    kind = p.get('kind')
    if kind == 'trail' and g.geom_type in ('LineString', 'MultiLineString'):
        for part in (g.geoms if g.geom_type == 'MultiLineString' else [g]):
            lines.append(part); names.append(p.get('name', '')); ids.append(int(p.get('osm_id', 0)))
    elif kind in ('viewpoint', 'waterfall', 'peak'):
        dests.append(g.centroid)
    elif kind in ('parking', 'trailhead'):
        lots.append(g.centroid)
print(f'{len(lines)} named trail ways, {len(dests)} destinations, {len(lots)} parking lots/trailheads, {len(parks)} parks', file=sys.stderr)

# Drop trails inside parks (by midpoint).
if lines:
    mids = shapely.line_interpolate_point(np.array(lines, dtype=object), 0.5, normalized=True)
    inside = np.zeros(len(lines), bool)
    if parks:
        inside[np.unique(park_tree.query(mids, predicate='within')[0])] = True
    keep = np.nonzero(~inside)[0]
    lines = [lines[i] for i in keep]; names = [names[i] for i in keep]; ids = [ids[i] for i in keep]

# Networks: union-find over ways that share a node.
parent = list(range(len(lines)))
def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]; a = parent[a]
    return a
first_at = {}
for i, l in enumerate(lines):
    for x, y in l.coords:
        k = (round(x / SNAP), round(y / SNAP))
        j = first_at.setdefault(k, i)
        if j != i:
            a, b = find(i), find(j)
            if a != b:
                parent[a] = b
groups = defaultdict(list)
for i in range(len(lines)):
    groups[find(i)].append(i)

dest_tree = shapely.STRtree(dests) if dests else None
lot_tree = shapely.STRtree(lots) if lots else None
lot_xy = np.array([(p.x, p.y) for p in lots]) if lots else np.zeros((0, 2))

def km_of(ls, k):
    return sum(math.hypot((b[0] - a[0]) * k, b[1] - a[1]) for l in ls for a, b in zip(l.coords, l.coords[1:])) * M_PER_DEG / 1000

out, dropped = [], Counter()
for members in groups.values():
    ls = [lines[i] for i in members]
    lat = sum(l.centroid.y for l in ls) / len(ls)
    k = math.cos(math.radians(lat)) or 1e-6
    km = km_of(ls, k)
    if km < MIN_KM:
        dropped['short'] += 1
        continue
    # Work in degrees with longitude scaled, so buffers are round.
    scaled = shapely.transform(MultiLineString(ls), lambda c: c * [k, 1])
    near = shapely.transform(scaled.buffer(DEST_M / M_PER_DEG, quad_segs=4), lambda c: c / [k, 1])
    n_dests = len(dest_tree.query(near, predicate='contains')) if dest_tree else 0
    if n_dests < MIN_DESTS:
        dropped['few destinations'] += 1
        continue
    # In a city? Sample up to 40 points along the network.
    coords = [c for l in ls for c in l.coords]
    samples = coords[:: max(1, len(coords) // 40)]
    urban = 0
    if lot_tree is not None:
        r_deg = 1000.0 / M_PER_DEG
        for x, y in samples:
            cand = lot_tree.query(Point(x, y).buffer(r_deg / k))  # a superset; filter by metres
            d = np.hypot((lot_xy[cand, 0] - x) * k, lot_xy[cand, 1] - y) * M_PER_DEG
            if (d <= 1000.0).sum() >= URBAN_LOTS:
                urban += 1
    if urban * 2 >= len(samples):
        dropped['urban'] += 1
        continue
    area = scaled.buffer(BUFFER_M / M_PER_DEG, quad_segs=4).simplify(50 / M_PER_DEG)
    area_m2 = area.area * M_PER_DEG ** 2
    poly = shapely.transform(area, lambda c: c / [k, 1])
    by_len = Counter()
    for i in members:
        by_len[names[i]] += lines[i].length
    out.append({'type': 'Feature', 'geometry': mapping(poly), 'properties': {
        'name': by_len.most_common(1)[0][0],
        'osm_id': f'trail-{min(ids[i] for i in members)}',
        'km': round(km, 1),
        'area': round(area_m2),
    }})

with open(out_path, 'w') as f:
    for feat in out:
        f.write(json.dumps(feat) + '\n')
print(f'{len(out)} trail areas from {len(groups)} networks; dropped {dict(dropped)}', file=sys.stderr)
