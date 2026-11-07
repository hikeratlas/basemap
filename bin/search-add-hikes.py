#!/usr/bin/env python3
# search-add-hikes.py AUTOSUGGEST_DB PARKS_DIR
#
# Adds the curated hikes (hikeratlas/routes' per-park JSON in PARKS_DIR) to a
# search DB built by bin/create-autosuggest-db.ts, so search finds hikes, not
# just places (hikeratlas/website#44). Run by routes.yml after the routes are
# built: the search DB is built earlier, with the exports.
#
# Each day hike, base camp walk-in, hike from a base camp, multi-day route and
# stop (a short walk to a sight from where the car is, hikeratlas/routes#70)
# becomes an item of kind 'hike':
#   - name: as the website titles it (a route's name, else "<dest> from
#     <start>", "<camp>", "<dest> from <camp>", "<start> to <end>", or for a
#     stop, its sight);
#   - osm_id: the website's route id (<park>/day/i, <park>/base/i,
#     <park>/base/i/j, <park>/multi/i, <park>/stop/i), which it opens when
#     picked;
#   - park, state and country from the park's own item (a trail area, which
#     has none, gives its name only);
#   - lat/lon at the start, and a box around the route;
#   - km and gain, and hike: day, base, multi or stop;
#   - qrank: a share of the park's, as create-autosuggest-db.ts gives unranked
#     items (PARK_SHARE there), so hikes in famous parks come first. A stop
#     counts as a full-length hike: it's there for its sight, not its walk.
# Each park item gets hikes: how many curated hikes it has (not stops).
#
# Hike items from an earlier run (a reused DB) are removed first.
import json, os, sqlite3, sys

PARK_SHARE = 0.01   # as in create-autosuggest-db.ts
FULL_KM = 5         # a hike's share scales with its length up to this
NAMED_X = 2         # and doubles for one named after an OSM hiking route


def sanitize_park(x):
    # As export/zindex.lua's sanitize_park.
    for a, b in (('National Park', 'NP'), ('State Park', 'SP'), ('Provincial Park', 'PP'), ('National Forest', 'NF')):
        x = x.replace(a, b)
    return x


def title(r, default):
    return r.get('name') or default


def routes(doc):
    """(id suffix, title, searched text, named, hike, route) for each of a
    park's curated hikes. A hike is found by its name, else by where it
    goes, not where it starts: "Lake Superior from North Kabeyun Trailhead"
    shouldn't be a match for "Kabeyun" (the Kabeyun Trail is)."""
    for i, h in enumerate(doc.get('day_hikes', [])):
        yield f'day/{i}', title(h, f"{h['dest']} from {h['from']}"), h.get('name') or h['dest'], bool(h.get('name')), 'day', h['route']
    for i, b in enumerate(doc.get('base_camps', [])):
        yield f'base/{i}', b['camp'], b['camp'], False, 'base', b['approach']
        for j, h in enumerate(b.get('hikes', [])):
            yield f'base/{i}/{j}', title(h, f"{h['dest']} from {b['camp']}"), h.get('name') or h['dest'], bool(h.get('name')), 'day', h['route']
    for i, t in enumerate(doc.get('point_to_points', [])):
        both = f"{t['from']} to {t['to']}"
        yield f'multi/{i}', title(t, both), t.get('name') or both, bool(t.get('name')), 'multi', t['route']
    for i, h in enumerate(doc.get('stops', [])):
        yield f'stop/{i}', h['dest'], h['dest'], False, 'stop', h['route']


def main(db_path, parks_dir):
    db = sqlite3.connect(db_path)
    cols = {r[1] for r in db.execute('pragma table_info(items)')}
    for col, typ in (('km', 'NUMERIC'), ('gain', 'INTEGER'), ('hike', 'TEXT'), ('hikes', 'INTEGER')):
        if col not in cols:
            db.execute(f'alter table items add column {col} {typ}')
    old = [r[0] for r in db.execute("select rowid from items where kind = 'hike'")]
    for t in ('fts', 'fts_popular', 'items'):
        db.executemany(f'delete from {t} where rowid = ?', [(r,) for r in old])
    db.execute('update items set hikes = null where hikes is not null')

    parks = {}
    for osm_id, name, state, country, qrank in db.execute(
            "select osm_id, name, state, country, qrank from items where kind = 'park'"):
        if osm_id not in parks or (qrank or 0) > (parks[osm_id][3] or 0):
            parks[osm_id] = (name, state, country, qrank)

    n_hikes, n_parks = 0, 0
    counts = {}
    for fn in sorted(os.listdir(parks_dir)):
        if not fn.endswith('.json'):
            continue
        doc = json.load(open(os.path.join(parks_dir, fn)))
        park_id = str(doc.get('park', {}).get('id') or fn[:-5])
        name, state, country, pq = parks.get(park_id, (doc.get('park', {}).get('name', ''), None, None, 1))
        n_parks += 1
        for suffix, t, searched, named, hike, r in routes(doc):
            line = r.get('line') or []
            if not line or not t:
                continue
            lons, lats = [p[0] for p in line], [p[1] for p in line]
            km = r.get('km') or 0
            # Named for the OSM hiking route it follows: the trail itself.
            w = 1.0 if hike == 'stop' else min(1.0, max(0.2, km / FULL_KM)) * (NAMED_X if named else 1)
            qrank = max(1, round((pq or 1) * PARK_SHARE * w))
            cur = db.execute(
                'insert into items (qrank, osm_id, kind, park, country, state, name, lon, lat,'
                ' min_lon, min_lat, max_lon, max_lat, km, gain, hike)'
                " values (?, ?, 'hike', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (qrank, f'{park_id}/{suffix}', sanitize_park(name) if name else None, country, state, t,
                 line[0][0], line[0][1], min(lons), min(lats), max(lons), max(lats),
                 round(km, 1), round(r.get('gain') or 0), hike))
            db.execute('insert into fts(rowid, name, qrank) values (?, ?, ?)', (cur.lastrowid, searched, qrank))
            if qrank > 1:
                db.execute('insert into fts_popular(rowid, name, qrank) values (?, ?, ?)', (cur.lastrowid, searched, qrank))
            if hike != 'stop':
                counts[park_id] = counts.get(park_id, 0) + 1
            n_hikes += 1
    db.executemany("update items set hikes = ? where kind = 'park' and osm_id = ?",
                   [(n, p) for p, n in counts.items()])
    db.commit()
    db.execute('vacuum')
    db.close()
    print(f'{n_hikes} hikes from {n_parks} parks added to {db_path} (replacing {len(old)})')


if __name__ == '__main__':
    main(*sys.argv[1:])
