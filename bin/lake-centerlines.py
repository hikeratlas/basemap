#!/usr/bin/env python3
# Centerlines for lake, bay and strait name labels (issue #7), following
# acalcutt/osm-lakelines' recipe: named water areas over 2 km² (in Web
# Mercator, as there), simplified to 25 m, then the label_centerlines
# algorithm: a Voronoi skeleton of the outline, the least curved of its 5
# longest paths, smoothed. label_centerlines itself runs Dijkstra between
# every pair of the skeleton's end nodes, which takes hours on a big lake;
# this finds the long paths from two sweeps instead (see longest_paths).
#
#   lake-centerlines.py IN.geojsonseq OUT.geojsonl
#
# IN is `osmium export -f geojsonseq --add-unique-id=type_id` of the water
# areas (ids "a<n>": a way's area is 2 * id, a relation's 2 * id + 1). OUT has
# one feature per area: {osm_type, osm_id, name} and a (Multi)LineString.
import json, math, multiprocessing, sys, time

import numpy as np
import shapely
from scipy.ndimage import gaussian_filter1d
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import Voronoi
from shapely.geometry import LineString, mapping, shape

R = 6378137.0
MIN_AREA = 2_000_000  # m², in Web Mercator
LAKE_WATER = {'lake', 'reservoir', 'lagoon', 'stream_pool', 'pond', 'oxbow'}


def is_lake(tags):
    if tags.get('natural') in ('bay', 'strait'):
        return True
    w = tags.get('water')
    if w is not None:
        return w in LAKE_WATER
    return tags.get('natural') == 'water'


def merc(c):
    return np.column_stack((R * np.radians(c[:, 0]), R * np.log(np.tan(np.pi / 4 + np.radians(c[:, 1]) / 2))))


def lonlat(c):
    return np.round(np.column_stack((np.degrees(c[:, 0] / R), np.degrees(2 * np.arctan(np.exp(c[:, 1] / R)) - np.pi / 2))), 6)


def path_to(pred, end):
    path = [end]
    while pred[path[-1]] >= 0:
        path.append(pred[path[-1]])
    return path


def farthest_ends(graph, src, ends, n):
    # The n end nodes farthest from src (reachable ones only), with paths.
    dist, pred = dijkstra(graph, directed=False, indices=src, return_predecessors=True)
    d = np.where(np.isinf(dist[ends]), -1, dist[ends])
    return [(d[i], path_to(pred, ends[i])) for i in np.argsort(-d)[:n] if d[i] > 0]


def longest_paths(graph, ends, n):
    # The longest path runs from the end node farthest from any node (a) to
    # the end node farthest from a (b); that's exact for a tree, and the
    # skeleton is one except around islands. The other candidates are the
    # next farthest end nodes from a and from b.
    a = farthest_ends(graph, ends[0], ends, 1)[0][1][0]
    from_a = farthest_ends(graph, a, ends, n)
    b = from_a[0][1][0]
    cands = sorted(from_a + farthest_ends(graph, b, ends, n), key=lambda c: -c[0])
    return [p for _, p in cands[:n]]


def angles_sum(pts):
    v = np.diff(pts, axis=0)
    a = np.arctan2(v[:, 1], v[:, 0])
    return np.abs((np.diff(a) + np.pi) % (2 * np.pi) - np.pi).sum()


def skeleton_line(poly, seg, max_points=10000, max_paths=5, sigma=3):
    outline = shapely.segmentize(poly.exterior, seg)
    while len(outline.coords) > max_points:
        seg *= 1.5
        outline = shapely.segmentize(poly.exterior.simplify(seg / 4), seg)
    pts = np.asarray(outline.coords)[:-1]
    vor = Voronoi(pts)
    rv = np.asarray(vor.ridge_vertices)
    rv = rv[(rv >= 0).all(axis=1)]
    shapely.prepare(poly)
    inside = shapely.contains_xy(poly, vor.vertices[:, 0], vor.vertices[:, 1])
    rv = rv[inside[rv[:, 0]] & inside[rv[:, 1]]]
    if len(rv) < 2:
        return None
    w = np.linalg.norm(vor.vertices[rv[:, 0]] - vor.vertices[rv[:, 1]], axis=1)
    nv = len(vor.vertices)
    graph = coo_matrix((w, (rv[:, 0], rv[:, 1])), shape=(nv, nv)).tocsr()
    graph = graph + graph.T
    # Only the largest connected piece of the skeleton.
    _, comp = connected_components(graph, directed=False)
    used = np.unique(rv)
    main = np.bincount(comp[used]).argmax()
    deg = np.diff(graph.indptr)
    ends = np.flatnonzero((deg == 1) & (comp == main))
    if len(ends) < 2:
        return None
    paths = longest_paths(graph, ends, max_paths)
    if not paths:
        return None
    best = min((vor.vertices[p] for p in paths), key=angles_sum)
    if len(best) > 2 * sigma:
        best = np.column_stack((gaussian_filter1d(best[:, 0], sigma), gaussian_filter1d(best[:, 1], sigma)))
    return LineString(best)


def centerline(line):
    feat = json.loads(line.lstrip('\x1e'))
    tags = feat['properties']
    if not tags.get('name') or not is_lake(tags):
        return None
    g = shape(feat['geometry'])
    gm = shapely.transform(g, merc)
    # Label the largest part: one label per lake.
    if gm.geom_type == 'MultiPolygon':
        gm = max(gm.geoms, key=lambda p: p.area)
    if gm.area < MIN_AREA:
        return None
    gm = gm.simplify(25, preserve_topology=True)
    if gm.is_empty:
        return None
    # osm-lakelines segmentizes at 100 m, simplifying to under 10,000 points.
    oid = int(feat['id'][1:])
    t = time.time()
    try:
        cl = skeleton_line(gm, 100)
    except Exception as e:
        print(f'{feat["id"]} {tags["name"]}: {type(e).__name__}: {e}', file=sys.stderr)
        return None
    if cl is None:
        return None
    if time.time() - t > 10:
        print(f'{feat["id"]} {tags["name"]}: {time.time() - t:.0f}s', file=sys.stderr)
    geom = mapping(shapely.transform(cl, lonlat))
    props = {'osm_type': 'relation' if oid % 2 else 'way', 'osm_id': oid // 2, 'name': tags['name']}
    return json.dumps({'type': 'Feature', 'properties': props, 'geometry': geom}, separators=(',', ':'), ensure_ascii=False)


def main(src, out):
    n = 0
    with open(src) as f, open(out, 'w') as w, multiprocessing.Pool() as pool:
        for r in pool.imap_unordered(centerline, f, chunksize=16):
            if r:
                w.write(r + '\n')
                n += 1
    print(f'{n} centerlines', file=sys.stderr)


if __name__ == '__main__':
    main(*sys.argv[1:])
