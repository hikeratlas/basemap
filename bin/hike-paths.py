#!/usr/bin/env python3
# hike-paths.py AUTOSUGGEST_DB PARKS_DIR INDEX_JSON REGIONS_JSON [BUNDLE]
#
# The website's /hikes/<country>/<state>/<park> URLs (hikeratlas/website#55
# and #56): a slug for every park and trail area with curated hikes, and the
# regions above them. Run by routes.yml after the routes are merged.
#
# Writes REGIONS_JSON, everything the /hikes pages list, in one file (one
# upload a build, not one per state):
#   {"countries": [{"slug", "name", "hikes", "parks", "bbox", "states": [
#       {"slug", "name", "hikes", "parks", "bbox", "areas": [
#           {"slug", "id", "ids", "name", "hikes", "bbox"}, ...]}, ...]}, ...]}
# sorted by name, areas by hikes (most first). bbox is [w, s, e, n].
# And adds to INDEX_JSON (the routes index the website already loads) "paths",
# park id -> "<country>/<state>/<park>", and "regions", country and state
# path -> name, so it can build a URL and breadcrumbs for a park opened on
# the map without loading REGIONS_JSON.
#
# A park's state and country come from its item in the search DB; a trail
# area (no park item) takes the nearest place's that has one. Parks whose
# routes are one document under two ids (Cape Breton Highlands' two OSM
# relations) get one slug, for both ids. Two parks in a state with the same
# name are told apart by the nearest town to their hikes, "Pacific Crest
# Trail (near Wrightwood)" (basemap#296: pieces of one park, or of one trail,
# are one area already, so these are different places); any still alike get
# -2, -3, ... in OSM-id order. Hike slugs aren't here: the website
# derives them from each park's routes, which it loads anyway.
#
# With BUNDLE (the routes' bundle, routes.bin), each state's park cards
# (hikeratlas/website#110) are added to its end, one gzipped JSON a state,
# {<area id>: {"top", "tags", "outline"}}, and INDEX_JSON gains "cards",
# "<country>/<state>" -> [offset, length], as for a park's routes: the state
# page loads its own, not every park's in regions.json (which every map
# page loads). "top" is its best hike's name, "tags" what its hikes pass
# most ("Lakes", "Lookouts"... and "Backcountry" for camps or multi-day
# trips), "outline" its shape (hikeratlas/routes' park outline) as an SVG
# path in a 100 x 100 box, filled nonzero.
import gzip, json, math, os, re, sqlite3, sys, unicodedata
from collections import defaultdict

# The countries with hike pages, as the search DB names them (#158).
COUNTRIES = {'Canada', 'United States'}


def slugify(s):
    s = unicodedata.normalize('NFKD', s)
    s = ''.join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def routes(doc):
    """Every curated hike's route: day hikes, base camps' walk-ins and their
    day hikes, and multi-day routes."""
    for h in doc.get('day_hikes', []):
        yield h['route']
    for b in doc.get('base_camps', []):
        yield b['approach']
        for h in b.get('hikes', []):
            yield h['route']
    for t in doc.get('point_to_points', []):
        yield t['route']


def union(boxes):
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


# What a hike passes (hikeratlas/routes' route "passes" kinds), as a tag.
TAGS = {'peak': 'Peaks', 'viewpoint': 'Lookouts', 'lake': 'Lakes', 'waterfall': 'Waterfalls',
        'hut': 'Huts', 'spring': 'Springs'}


def card(doc, rs):
    """A park's card: its best hike's name, its tags and its outline."""
    top = None
    if doc.get('day_hikes'):
        h = doc['day_hikes'][0]
        top = h.get('name') or h.get('dest')
    elif doc.get('point_to_points'):
        t = doc['point_to_points'][0]
        top = t.get('name') or f"{t.get('from')} to {t.get('to')}"
    elif doc.get('base_camps'):
        top = doc['base_camps'][0].get('camp')
    # Each kind by the places of it passed (not the hikes passing them), at
    # least 2; the 3 most.
    seen = defaultdict(set)
    for r in rs:
        for kind, names in r.get('passes') or []:
            if kind in TAGS:
                seen[kind].update(names)
    tags = [TAGS[k] for k, v in sorted(seen.items(), key=lambda kv: -len(kv[1])) if len(v) >= 2][:3]
    if doc.get('base_camps') or doc.get('point_to_points'):
        tags = tags[:2] + ['Backcountry']
    c = {'top': top, 'tags': tags}
    path = outline_path(doc.get('park', {}).get('outline'))
    if path:
        c['outline'] = path
    return c


def outline_path(rings):
    """An outline's rings ([lon, lat]) as an SVG path in a 100 x 100 box, in
    Web Mercator, centred."""
    rings = [r for r in rings or [] if len(r) >= 3]
    if not rings:
        return None
    merc = lambda p: (p[0], math.degrees(math.log(math.tan(math.pi / 4 + math.radians(p[1]) / 2))))
    rings = [[merc(p) for p in r] for r in rings]
    xs = [p[0] for r in rings for p in r]
    ys = [p[1] for r in rings for p in r]
    w, e, s, n = min(xs), max(xs), min(ys), max(ys)
    size = max(e - w, n - s)
    if not size > 0:
        return None
    k = 100 / size
    ox, oy = (100 - (e - w) * k) / 2, (100 - (n - s) * k) / 2
    out = []
    for r in rings:
        pts = []
        for x, y in r:
            q = (round(ox + (x - w) * k), round(oy + (n - y) * k))
            if not pts or q != pts[-1]:
                pts.append(q)
        if len(pts) >= 3:
            out.append('M' + 'L'.join(f'{x} {y}' for x, y in pts) + 'Z')
    return ''.join(out) or None


def r5(b):
    return [round(x, 5) for x in b] if b else None


class Nearest:
    """The state and country of the nearest search item that has them, from a
    0.1-degree grid of them."""
    def __init__(self, db):
        self.grid = defaultdict(list)
        for lat, lon, state, country in db.execute(
                'select lat, lon, state, country from items where state is not null and country is not null'):
            self.grid[(int(lat * 10), int(lon * 10))].append((lat, lon, state, country))

    def __call__(self, lat, lon):
        gy, gx = int(lat * 10), int(lon * 10)
        for r in range(0, 6):  # up to ~50 km
            best = None
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dy), abs(dx)) != r:
                        continue
                    for p in self.grid.get((gy + dy, gx + dx), ()):
                        d = (p[0] - lat) ** 2 + ((p[1] - lon) * math.cos(math.radians(lat))) ** 2
                        if best is None or d < best[0]:
                            best = (d, p[2], p[3])
            if best:
                return best[1], best[2]
        return None, None


class Towns:
    """The nearest city, town or village to a point, from a 0.1-degree grid of
    them, up to ~50 km away."""
    def __init__(self, db):
        self.grid = defaultdict(list)
        for lat, lon, name in db.execute(
                "select lat, lon, name from items where kind in ('city', 'town', 'village') and name is not null"):
            self.grid[(int(lat * 10), int(lon * 10))].append((lat, lon, name))

    def __call__(self, lat, lon):
        gy, gx = int(lat * 10), int(lon * 10)
        for r in range(0, 6):
            best = None
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if max(abs(dy), abs(dx)) != r:
                        continue
                    for p in self.grid.get((gy + dy, gx + dx), ()):
                        d = (p[0] - lat) ** 2 + ((p[1] - lon) * math.cos(math.radians(lat))) ** 2
                        if best is None or d < best[0]:
                            best = (d, p[2])
            if best:
                return best[1]
        return None


def tell_apart(xs, towns):
    """Areas of a state with the same name: each named for the town nearest
    its hikes' middle, "<name> (near <town>)", where that tells them apart."""
    by_name = defaultdict(list)
    for a in xs:
        by_name[a['name']].append(a)
    for name, same in by_name.items():
        if len(same) < 2:
            continue
        near = [towns((a['bbox'][1] + a['bbox'][3]) / 2, (a['bbox'][0] + a['bbox'][2]) / 2) if a['bbox'] else None
                for a in same]
        for a, t in zip(same, near):
            if t and near.count(t) == 1 and t.lower() not in name.lower():
                a['name'] = f'{name} (near {t})'


def main(db_path, parks_dir, index_path, regions_path, bundle_path=None):
    db = sqlite3.connect(db_path)
    index = json.load(open(index_path))
    place = {}  # park osm_id -> (name, state, country, box)
    for osm_id, name, state, country, qrank, w, s, e, n in db.execute(
            "select osm_id, name, state, country, qrank, min_lon, min_lat, max_lon, max_lat"
            " from items where kind = 'park'"):
        if osm_id not in place or (qrank or 0) > place[osm_id][4]:
            place[osm_id] = (name, state, country, [w, s, e, n] if w is not None else None, qrank or 0)
    nearest = Nearest(db)
    towns = Towns(db)

    # Park ids by routes document: twins share a slice of the bundle.
    by_slice = defaultdict(list)
    for pid, at in index['parks'].items():
        by_slice[tuple(at)].append(pid)

    areas = defaultdict(list)  # (country, state) -> areas
    skipped = 0
    elsewhere = 0
    for ids in by_slice.values():
        ids.sort(key=lambda i: (not i.isdigit(), int(i) if i.isdigit() else 0, i))
        doc = None
        for pid in ids:
            fn = os.path.join(parks_dir, f'{pid}.json')
            if os.path.exists(fn):
                doc = json.load(open(fn))
                break
        if doc is None:
            skipped += 1
            continue
        rs = list(routes(doc))
        if not rs:
            continue
        lines = [r.get('line') or [] for r in rs]
        route_box = union([[min(p[0] for p in l), min(p[1] for p in l), max(p[0] for p in l), max(p[1] for p in l)]
                           for l in lines if l])
        known = next((place[i] for i in ids if i in place), None)
        name = (known and known[0]) or doc.get('park', {}).get('name') or ''
        state, country = (known[1], known[2]) if known else (None, None)
        if not (state and country):
            start = next(l[0] for l in lines if l)
            state, country = nearest(start[1], start[0])
        if not (state and country and name):
            skipped += 1
            continue
        # Hike pages are for Canada and the US only (#158). The PBF is cut to
        # them, but Geofabrik's outlines run past the borders, so a few areas
        # across them still get hikes: Cañón de Santa Elena and Maderas del
        # Carmen (Mexico, across the Rio Grande from Big Bend), and a trail on
        # Saint-Pierre-et-Miquelon (France).
        if country not in COUNTRIES:
            elsewhere += 1
            continue
        areas[(country, state)].append({
            'name': name, 'ids': ids, 'hikes': len(rs),
            # Fit to the hikes, not the whole park: Jasper's hikes, not the
            # empty north of it.
            'bbox': r5(route_box),
            'card': card(doc, rs),
        })

    paths = {}
    countries = defaultdict(list)
    for (country, state), xs in areas.items():
        tell_apart(xs, towns)
        # Slugs, -2, -3, ... for repeats in OSM-id order.
        xs.sort(key=lambda a: (slugify(a['name']), int(a['ids'][0]) if a['ids'][0].isdigit() else 10 ** 12))
        used = defaultdict(int)
        for a in xs:
            base = slugify(a['name']) or 'area'
            used[base] += 1
            a['slug'] = base if used[base] == 1 else f'{base}-{used[base]}'
            a['id'] = a['ids'][0]
        cs, ss = slugify(country), slugify(state)
        for a in xs:
            for i in a['ids']:
                paths[i] = f"{cs}/{ss}/{a['slug']}"
        xs.sort(key=lambda a: (-a['hikes'], a['name']))
        countries[country].append({
            'slug': ss, 'name': state, 'hikes': sum(a['hikes'] for a in xs), 'parks': len(xs),
            'bbox': r5(union([a['bbox'] for a in xs])),
            'areas': [{k: a[k] for k in ('slug', 'id', 'ids', 'name', 'hikes', 'bbox')} for a in xs],
        })
    out = []
    for country, states in sorted(countries.items()):
        states.sort(key=lambda s: s['name'])
        out.append({'slug': slugify(country), 'name': country,
                    'hikes': sum(s['hikes'] for s in states), 'parks': sum(s['parks'] for s in states),
                    'bbox': r5(union([s['bbox'] for s in states])), 'states': states})
    json.dump({'countries': out}, open(regions_path, 'w'), separators=(',', ':'), ensure_ascii=False)
    # Each state's cards at the end of the bundle.
    if bundle_path:
        cards = {}
        with open(bundle_path, "ab") as f:
            f.seek(0, os.SEEK_END)
            for (country, state), xs in sorted(areas.items()):
                blob = gzip.compress(json.dumps({a['id']: a['card'] for a in xs}, separators=(',', ':'),
                                                ensure_ascii=False).encode(), mtime=0)
                cards[f'{slugify(country)}/{slugify(state)}'] = [f.tell(), len(blob)]
                f.write(blob)
        index['cards'] = cards
    index['paths'] = paths
    # Country and state names by path, for the website's breadcrumbs.
    index['regions'] = {c['slug']: c['name'] for c in out}
    index['regions'].update({f"{c['slug']}/{st['slug']}": st['name'] for c in out for st in c['states']})
    json.dump(index, open(index_path, 'w'), separators=(',', ':'))
    n_areas = sum(len(x) for x in areas.values())
    print(f'{n_areas} parks and trail areas in {sum(len(s) for s in countries.values())} states of '
          f'{len(out)} countries; {len(paths)} park ids with paths; {skipped} skipped (no document or place); '
          f'{elsewhere} outside {" and ".join(sorted(COUNTRIES))}')


if __name__ == '__main__':
    main(*sys.argv[1:])
