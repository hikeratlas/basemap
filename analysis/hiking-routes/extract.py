"""Extract hiking routes, trails, parks and admin areas from a PBF into Parquet.

    python3 -I extract.py INPUT.osm.pbf OUTDIR

Writes OUTDIR/{routes,ways,areas}.parquet:
- routes: every route=hiking relation, with its tags and its member ways and
  relations.
- ways: trail ways (highway=path/footway/bridleway/steps) and every way that
  is a member of a hiking route, with length and geometry (WKB, EPSG:4326).
- areas: protected areas (boundary=protected_area/national_park,
  leisure=nature_reserve) and admin_level 2/4 boundaries, as multipolygons.
"""
import json
import math
import sys
from pathlib import Path

import osmium
import pyarrow as pa
import pyarrow.parquet as pq

TRAIL_HIGHWAYS = {"path", "footway", "bridleway", "steps"}
ROUTE_TAGS = ["name", "ref", "network", "operator", "wikidata", "wikipedia",
              "osmc:symbol", "distance", "roundtrip", "type", "website", "from", "to"]
AREA_TAGS = ["name", "name:en", "boundary", "leisure", "protect_class", "protection_title",
             "operator", "owner", "designation", "admin_level", "wikidata", "wikipedia",
             "ISO3166-1", "ISO3166-2", "park:type", "access"]
WAY_TAGS = ["highway", "footway", "name", "sac_scale", "trail_visibility", "surface", "access", "foot"]


def haversine_m(lon1, lat1, lon2, lat2):
    r = 6371008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def tags_json(tags, keys):
    return json.dumps({k: tags[k] for k in keys if k in tags}, ensure_ascii=False)


class Writer:
    def __init__(self, path, schema, batch=200_000):
        self.w = pq.ParquetWriter(path, schema, compression="zstd")
        self.schema, self.batch, self.rows = schema, batch, []

    def add(self, row):
        self.rows.append(row)
        if len(self.rows) >= self.batch:
            self.flush()

    def flush(self):
        if self.rows:
            cols = {f.name: [r[i] for r in self.rows] for i, f in enumerate(self.schema)}
            self.w.write_table(pa.table(cols, schema=self.schema))
            self.rows = []

    def close(self):
        self.flush()
        self.w.close()


def main(src, outdir):
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    # Pass 1: the hiking routes, and which ways they use.
    routes = Writer(outdir / "routes.parquet", pa.schema([
        ("id", pa.int64()), ("tags", pa.string()),
        ("way_ids", pa.list_(pa.int64())), ("relation_ids", pa.list_(pa.int64())),
    ]))
    member_ways = set()
    for r in osmium.FileProcessor(src, osmium.osm.RELATION):
        if r.tags.get("route") != "hiking":
            continue
        ways = [m.ref for m in r.members if m.type == "w"]
        rels = [m.ref for m in r.members if m.type == "r"]
        member_ways.update(ways)
        routes.add((r.id, tags_json(r.tags, ROUTE_TAGS), ways, rels))
    routes.close()
    print(f"member ways: {len(member_ways)}", file=sys.stderr)

    # Pass 2: ways (with locations) and areas.
    ways = Writer(outdir / "ways.parquet", pa.schema([
        ("id", pa.int64()), ("trail", pa.bool_()), ("route_member", pa.bool_()),
        ("length_m", pa.float64()), ("tags", pa.string()), ("geom", pa.binary()),
    ]))
    areas = Writer(outdir / "areas.parquet", pa.schema([
        ("osm_type", pa.string()), ("osm_id", pa.int64()), ("kind", pa.string()),
        ("tags", pa.string()), ("geom", pa.binary()),
    ]), batch=5_000)
    wkb = osmium.geom.WKBFactory()

    def area_kind(t):
        if t.get("boundary") in ("protected_area", "national_park") or t.get("leisure") == "nature_reserve":
            return "park"
        if t.get("boundary") == "administrative" and t.get("admin_level") in ("2", "4"):
            return "admin" + t.get("admin_level")
        return None

    fp = (osmium.FileProcessor(src)
          .with_locations("flex_mem")
          .with_areas(osmium.filter.KeyFilter("boundary", "leisure")))
    for o in fp:
        if o.is_way():
            is_trail = o.tags.get("highway") in TRAIL_HIGHWAYS
            is_member = o.id in member_ways
            if not (is_trail or is_member):
                continue
            try:
                locs = [(n.lon, n.lat) for n in o.nodes if n.location.valid()]
                if len(locs) < 2:
                    continue
                geom = wkb.create_linestring(o)
            except Exception:
                continue
            length = sum(haversine_m(*locs[i - 1], *locs[i]) for i in range(1, len(locs)))
            ways.add((o.id, is_trail, is_member, length, tags_json(o.tags, WAY_TAGS), geom))
        elif o.is_area():
            kind = area_kind(o.tags)
            if not kind:
                continue
            try:
                geom = wkb.create_multipolygon(o)
            except Exception:
                continue
            areas.add(("way" if o.from_way() else "relation", o.orig_id(), kind,
                       tags_json(o.tags, AREA_TAGS), geom))
    ways.close()
    areas.close()


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
