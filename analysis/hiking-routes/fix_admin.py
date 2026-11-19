"""Polygons for admin boundaries osmium can't assemble from an extract.

    python3 -I fix_admin.py INPUT.osm.pbf OUTDIR RELATION_ID [RELATION_ID ...]

- Alaska (1116270): Geofabrik's US extract lacks one of its ways (on the
  maritime border with Russia, outside the extract), so its ring doesn't
  close; and it crosses the antimeridian.
- Grand Est (3792876): every way is in the extract, but the ring doesn't
  assemble as mapped today.

This joins the ways that are there, closes each open ring with a straight
line, polygonizes, and splits the result at the antimeridian. Writes
OUTDIR/extra_states.parquet, in areas.parquet's layout.
"""
import json
import sys
from pathlib import Path

import osmium
import pyarrow as pa
import pyarrow.parquet as pq
import shapely
from shapely import affinity
from shapely.geometry import LineString, box
from shapely.ops import linemerge, polygonize, unary_union

def build(src, rid):
    for r in osmium.FileProcessor(src, osmium.osm.RELATION):
        if r.id == rid:
            tags = dict(r.tags)
            outer = {m.ref for m in r.members if m.type == "w" and m.role != "inner"}
            inner = {m.ref for m in r.members if m.type == "w" and m.role == "inner"}
            break
    lines = {"outer": [], "inner": []}
    for w in osmium.FileProcessor(src, osmium.osm.NODE | osmium.osm.WAY).with_locations("flex_mem"):
        if w.is_way() and (w.id in outer or w.id in inner):
            coords = [(n.lon, n.lat) for n in w.nodes if n.location.valid()]
            if len(coords) >= 2:
                lines["outer" if w.id in outer else "inner"].append(LineString(coords))
    antimeridian = any(c[0] < -170 for l in lines["outer"] for c in l.coords) and \
        any(c[0] > 170 for l in lines["outer"] for c in l.coords)
    if antimeridian:  # Longitudes 0..360, so nothing crosses it.
        lines = {k: [LineString([(x % 360, y) for x, y in l.coords]) for l in v]
                 for k, v in lines.items()}

    def rings(ls):
        merged = linemerge(unary_union(ls))
        parts = list(merged.geoms) if merged.geom_type == "MultiLineString" else [merged]
        closed = []
        for p in parts:
            if not p.is_ring:
                gap = shapely.Point(p.coords[0]).distance(shapely.Point(p.coords[-1]))
                print(f"{rid}: closing a gap of {gap:.4f} degrees", file=sys.stderr)
                p = LineString(list(p.coords) + [p.coords[0]])
            closed.append(p)
        # Rings may touch or nest; even-odd by symmetric difference.
        polys = list(polygonize(unary_union(closed)))
        out = shapely.Polygon()
        for p in polys:
            out = out.symmetric_difference(p)
        return out

    poly = rings(lines["outer"])
    if lines["inner"]:
        poly = poly.difference(rings(lines["inner"]))
    if antimeridian:  # Back to -180..180.
        west = poly.intersection(box(0, -90, 180, 90))
        east = affinity.translate(poly.intersection(box(180, -90, 360, 90)), xoff=-360)
        poly = unary_union([west, east])
    geom = shapely.make_valid(poly)
    if geom.geom_type == "GeometryCollection":  # Drop slivers that are lines.
        geom = unary_union([g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
    print(f"{rid} {tags.get('name')}: {geom.geom_type}, bounds {geom.bounds}", file=sys.stderr)
    keep = {k: tags[k] for k in ("name", "name:en", "boundary", "admin_level", "ISO3166-2", "wikidata") if k in tags}
    return ("relation", rid, "admin" + tags.get("admin_level", "4"), json.dumps(keep), shapely.to_wkb(geom))


def main(src, outdir, ids):
    rows = [build(src, int(i)) for i in ids]
    cols = list(zip(*rows))
    table = pa.table({"osm_type": list(cols[0]), "osm_id": list(cols[1]), "kind": list(cols[2]),
                      "tags": list(cols[3]), "geom": list(cols[4])})
    pq.write_table(table, Path(outdir) / "extra_states.parquet")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
