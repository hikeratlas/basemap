#!/usr/bin/env python3
# parks-near.py PARKS.geojsonl OUT.geojsonl [METRES]
#
# Grows each park (from export/parks.lua) by METRES (default 2000), for
# slices/pois.lua: parking lots and trailheads just outside a park, where many
# hikes start, are kept in the poi layer (hikeratlas/routes uses them).
#
# Only the shapes matter, so they're simplified and written without
# properties. Distances are approximate: each park is buffered in degrees,
# with longitude scaled by the cosine of its latitude.
import json, math, sys
import shapely
from shapely.geometry import shape, mapping

src, dst = sys.argv[1], sys.argv[2]
metres = float(sys.argv[3]) if len(sys.argv) > 3 else 2000
deg = metres / 111_320

n = 0
with open(src) as f, open(dst, 'w') as out:
    for line in f:
        line = line.strip().lstrip('\x1e')
        if not line:
            continue
        try:
            g = shape(json.loads(line)['geometry'])
        except Exception:
            continue
        if g.is_empty or 'Polygon' not in g.geom_type:
            continue
        k = math.cos(math.radians(g.centroid.y)) or 1e-6
        # Scale longitude so a degree is the same distance both ways, buffer,
        # and scale back.
        g = shapely.transform(g.simplify(deg / 10), lambda c: c * [k, 1])
        g = g.buffer(deg, quad_segs=4).simplify(deg / 10)
        g = shapely.transform(g, lambda c: c / [k, 1])
        out.write(json.dumps({'type': 'Feature', 'properties': {}, 'geometry': mapping(g)}) + '\n')
        n += 1
print(f'{n} parks grown by {metres:.0f} m', file=sys.stderr)
