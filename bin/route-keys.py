#!/usr/bin/env python3
# route-keys.py OUT_DIR
#
# Gives every curated route in the parks' documents its route key
# (hikeratlas/route-keys, recipe v1; basemap#325), "route_key", the name
# faves, tracks and reviews know a hike by: made once here, by route-keys'
# own Python implementation, rather than by each client. Run by routes.yml
# right after the routes are merged, before anything else reads them.
#
# Each route's line and shape are the website's (app/atproto/findRoutes.ts
# parkRoutes, routeKey.ts shapeFor), so the keys agree with the ones it makes:
#   day_hikes[].route               shape from its kind
#   stops[].route                   b
#   base_camps[].approach           w
#   base_camps[].hikes[].route      shape from its kind
#   point_to_points[].route         shape from its kind
# where a kind's shape is p for a loop, b for an out-and-back and w for
# anything else. A line too short for a key (route-keys raises) gets none.
# Not "key": that's routes' own name-based key, which trip reports use.
#
# OUT_DIR is routes' output: parks/<id>.json, and routes.bin, each park's
# JSON gzipped end to end, located by index.json ({"bundle", "parks": {id:
# [offset, length]}}; one park under two ids shares a slice). Each document
# gets its keys in both, and the bundle is rewritten with the index's
# offsets. Any other [offset, length] map in the index (hike-paths.py's
# "cards") is carried over as it is, to its new place. Keys are computed
# afresh each run and overwrite what's there, so running it again (a reused
# output) changes nothing.
import gzip, json, os, sys

from route_keys import route_key, shape_for


def keyed_routes(doc):
    """(route, shape) for every route the website keys."""
    for h in doc.get('day_hikes') or []:
        yield h.get('route'), shape_for(h.get('kind') or '')
    for h in doc.get('stops') or []:
        yield h.get('route'), 'b'
    for b in doc.get('base_camps') or []:
        yield b.get('approach'), 'w'
        for h in b.get('hikes') or []:
            yield h.get('route'), shape_for(h.get('kind') or '')
    for t in doc.get('point_to_points') or []:
        yield t.get('route'), shape_for(t.get('kind') or '')


def add_keys(doc):
    """Sets each route's route_key (or drops it, for a line too short).
    Returns (keyed, too short)."""
    keyed = short = 0
    for r, shape in keyed_routes(doc):
        if not isinstance(r, dict):
            continue
        try:
            r['route_key'] = route_key(r.get('line') or [], shape)
            keyed += 1
        except ValueError:
            r.pop('route_key', None)
            short += 1
    return keyed, short


def dumps(doc):
    # As routes writes them (serde_json): compact, UTF-8.
    return json.dumps(doc, separators=(',', ':'), ensure_ascii=False).encode()


def write_atomic(path, data):
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        f.write(data)
    os.replace(tmp, path)


def is_slices(v):
    return isinstance(v, dict) and v and all(
        isinstance(x, list) and len(x) == 2 and all(isinstance(n, int) for n in x) for x in v.values())


def main(out_dir):
    index_path = os.path.join(out_dir, 'index.json')
    parks_dir = os.path.join(out_dir, 'parks')
    index = json.load(open(index_path))
    bundle_path = os.path.join(out_dir, index.get('bundle') or 'routes.bin')
    # Park ids by document: one park under two ids shares a slice.
    by_slice = {}
    for pid, at in index['parks'].items():
        by_slice.setdefault(tuple(at), []).append(pid)
    others = {k: v for k, v in index.items() if k != 'parks' and is_slices(v)}

    docs = keyed = short = 0
    parks = {}
    tmp = bundle_path + '.tmp'
    with open(bundle_path, 'rb') as src, open(tmp, 'wb') as dst:
        for (offset, length), ids in sorted(by_slice.items()):
            src.seek(offset)
            doc = json.loads(gzip.decompress(src.read(length)))
            k, s = add_keys(doc)
            docs += 1
            keyed += k
            short += s
            body = dumps(doc)
            for pid in ids:
                fn = os.path.join(parks_dir, f'{pid}.json')
                if os.path.exists(fn):
                    write_atomic(fn, body)
            blob = gzip.compress(body, compresslevel=9, mtime=0)
            at = [dst.tell(), len(blob)]
            dst.write(blob)
            for pid in ids:
                parks[pid] = at
        # The rest (cards), byte for byte, after the parks.
        copied = {}  # old (offset, length) -> new [offset, length]
        for name, slices in others.items():
            for k, (offset, length) in slices.items():
                if (offset, length) not in copied:
                    src.seek(offset)
                    copied[(offset, length)] = [dst.tell(), length]
                    dst.write(src.read(length))
            index[name] = {k: copied[tuple(at)] for k, at in slices.items()}
    index['parks'] = {pid: parks[pid] for pid in index['parks']}
    os.replace(tmp, bundle_path)
    write_atomic(index_path, json.dumps(index, separators=(',', ':')).encode())
    print(f'Route keys: {keyed} routes keyed in {docs} parks; {short} lines too short for a key')
    return keyed, short


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit('usage: route-keys.py OUT_DIR')
    main(sys.argv[1])
