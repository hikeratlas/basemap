#!/usr/bin/env python3
# parks-near.py PARKS.geojsonl OUT.geojsonl [METRES] [--bbox MINLON,MINLAT,MAXLON,MAXLAT]
#
# Grows each park (from export/parks.lua) by METRES (default 2000), for
# slices/pois.lua: parking lots and trailheads just outside a park, where many
# hikes start, are kept in the poi layer (hikeratlas/routes uses them).
#
# Only the shapes matter, so they're simplified and written without
# properties. Distances are approximate: each park is buffered in degrees,
# with longitude scaled by the cosine of its latitude.
#
# --bbox skips parks that can't reach the box once grown, i.e. the build's box
# (a preview's, or its area's from areas.json). The exports a build reads may
# cover more than it builds, e.g. an Ontario preview reads north-america's.
#
# Buffering dominates (~80 of ~110 s for north-america's ~58k parks), so parks
# are grown on every CPU. Output order matches input order.
import json, math, os, sys
from multiprocessing import Pool
import shapely
from shapely.geometry import shape, mapping

args = sys.argv[1:]
bbox = None
if '--bbox' in args:
    i = args.index('--bbox')
    bbox = [float(x) for x in args[i + 1].split(',')]
    del args[i:i + 2]
src, dst = args[0], args[1]
metres = float(args[2]) if len(args) > 2 else 2000
deg = metres / 111_320

if bbox:
    # Widen the box by the growth: a park outside it can still reach in.
    # Longitude degrees shrink toward the poles, so widen by the most it
    # could need anywhere in the box.
    k = math.cos(math.radians(min(max(abs(bbox[1]), abs(bbox[3])), 89)))
    bbox = (bbox[0] - deg / k, bbox[1] - deg, bbox[2] + deg / k, bbox[3] + deg)


def grow(line):
    line = line.strip().lstrip('\x1e')
    if not line:
        return None
    try:
        g = shape(json.loads(line)['geometry'])
    except Exception:
        return None
    if g.is_empty or 'Polygon' not in g.geom_type:
        return None
    if bbox:
        x0, y0, x1, y1 = g.bounds
        if x1 < bbox[0] or x0 > bbox[2] or y1 < bbox[1] or y0 > bbox[3]:
            return None
    k = math.cos(math.radians(g.centroid.y)) or 1e-6
    # Scale longitude so a degree is the same distance both ways, buffer,
    # and scale back.
    g = shapely.transform(g.simplify(deg / 10), lambda c: c * [k, 1])
    g = g.buffer(deg, quad_segs=4).simplify(deg / 10)
    g = shapely.transform(g, lambda c: c / [k, 1])
    return json.dumps({'type': 'Feature', 'properties': {}, 'geometry': mapping(g)})


if __name__ == '__main__':
    n = 0
    with open(src) as f, open(dst, 'w') as out, Pool(os.cpu_count()) as pool:
        # imap streams the file, so memory stays flat however many parks.
        for feature in pool.imap(grow, f, chunksize=64):
            if feature is not None:
                out.write(feature + '\n')
                n += 1
    where = f' near {",".join(f"{x:g}" for x in bbox)}' if bbox else ''
    print(f'{n} parks grown by {metres:.0f} m{where} on {os.cpu_count()} CPUs', file=sys.stderr)
