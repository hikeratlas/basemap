#!/usr/bin/env python3
# urban-lots.py TRAILS.geojsonl OUT.geojsonl [--bbox MINLON,MINLAT,MAXLON,MAXLAT]
#
# Where parking lots are urban, so the map can hide them: a city has a lot on
# every block, and a hiking map needs none of them. Reads export/trails.lua's
# output (its parking lots and trailheads) and writes CELL_M grid cells, merged
# into runs along each row, that hold an urban lot: one with URBAN_LOTS or more
# lots within 1 km, as hikeratlas/routes' urban_lots (remote trailheads have a
# handful nearby, cities dozens). slices/pois.lua marks parking in these cells
# urban=true and the style leaves those out; the lots stay in the tiles, so
# hikeratlas/routes still sees them.
#
# Distances are approximate: longitude is scaled by the cosine of each lot's
# latitude.
import json, math, sys
from collections import defaultdict
import numpy as np

URBAN_LOTS = 12
RADIUS_M = 1000.0
CELL_M = 500.0
M_PER_DEG = 111_320.0

args = sys.argv[1:]
bbox = None
if '--bbox' in args:
    i = args.index('--bbox')
    bbox = [float(x) for x in args[i + 1].split(',')]
    del args[i:i + 2]
trails_path, out_path = args


def centroid(g):
    """A rough centre: the mean of a point's or polygon's outer ring."""
    if g['type'] == 'Point':
        return g['coordinates'][:2]
    ring = g['coordinates'][0] if g['type'] == 'Polygon' else g['coordinates'][0][0]
    xs = [c[0] for c in ring]
    ys = [c[1] for c in ring]
    return sum(xs) / len(xs), sum(ys) / len(ys)


pts = []
with open(trails_path) as f:
    for line in f:
        line = line.strip().lstrip('\x1e')
        if not line or '"parking"' not in line and '"trailhead"' not in line:
            continue
        try:
            ft = json.loads(line)
        except ValueError:
            continue
        if ft['properties'].get('kind') not in ('parking', 'trailhead'):
            continue
        lon, lat = centroid(ft['geometry'])
        # The box plus a margin, so lots near its edge count their neighbours.
        if bbox and not (bbox[0] - 0.05 <= lon <= bbox[2] + 0.05 and bbox[1] - 0.05 <= lat <= bbox[3] + 0.05):
            continue
        pts.append((lon, lat))

xy = np.array([(lon * M_PER_DEG * math.cos(math.radians(lat)), lat * M_PER_DEG) for lon, lat in pts]).reshape(-1, 2)
ll = np.array(pts).reshape(-1, 2)

# Count each lot's neighbours within RADIUS_M, a RADIUS_M grid at a time.
grid = defaultdict(list)
for i, (x, y) in enumerate(xy):
    grid[(int(x // RADIUS_M), int(y // RADIUS_M))].append(i)
grid = {k: np.array(v) for k, v in grid.items()}
urban = np.zeros(len(xy), dtype=bool)
r2 = RADIUS_M * RADIUS_M
for (cx, cy), idx in grid.items():
    near = np.concatenate([grid[(cx + dx, cy + dy)] for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (cx + dx, cy + dy) in grid])
    if len(near) <= URBAN_LOTS:
        continue  # the lot itself counts, so it needs URBAN_LOTS others
    d = ((xy[idx, None, :] - xy[None, near, :]) ** 2).sum(axis=2)
    urban[idx] = (d <= r2).sum(axis=1) > URBAN_LOTS

# Cells in degrees: CELL_M of latitude per row, and CELL_M of longitude at the
# row's latitude.
dlat = CELL_M / M_PER_DEG
rows = defaultdict(set)
for lon, lat in ll[urban]:
    r = int(math.floor(lat / dlat))
    dlon = CELL_M / (M_PER_DEG * math.cos(math.radians((r + 0.5) * dlat)))
    rows[r].add(int(math.floor(lon / dlon)))

n_cells = n_runs = 0
with open(out_path, 'w') as out:
    for r, cols in rows.items():
        dlon = CELL_M / (M_PER_DEG * math.cos(math.radians((r + 0.5) * dlat)))
        y0, y1 = r * dlat, (r + 1) * dlat
        cols = sorted(cols)
        n_cells += len(cols)
        start = prev = cols[0]
        for c in cols[1:] + [None]:
            if c is not None and c == prev + 1:
                prev = c
                continue
            x0, x1 = start * dlon, (prev + 1) * dlon
            ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
            out.write(json.dumps({'type': 'Feature', 'properties': {}, 'geometry': {'type': 'Polygon', 'coordinates': [ring]}}) + '\n')
            n_runs += 1
            if c is not None:
                start = prev = c

print(f'{len(pts)} parking lots/trailheads, {int(urban.sum())} urban, in {n_cells} cells ({n_runs} runs)', file=sys.stderr)
