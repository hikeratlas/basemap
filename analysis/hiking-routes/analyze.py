"""Per-country stats on route=hiking relations, from extract.py's Parquet.

    python3 -I analyze.py OUTDIR ISO      (ISO: CA, US or FR)

Writes OUTDIR/{summary.json,states.csv,parks.csv,routes.csv}.

Definitions:
- A route is a route=hiking relation with at least one member way; a
  relation of relations (a long trail's sections) is counted separately as
  a "super-route". A route belongs to the state/province/region holding the
  midpoint of its longest member way.
- Lengths are of distinct ways: a way in two routes counts once in totals.
- The trail network is highway=path/footway/bridleway/steps, less sidewalks,
  crossings and private ways. A trail way is "covered" if it's a member of
  any hiking route. Ways are placed by their midpoint.
- Parks are named protected areas, classed by name (national park,
  provincial/state park, French parc naturel régional), merged by name. A
  park "has a route" if a hiking route has a member way with its midpoint
  inside.
"""
import json
import re
import sqlite3
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely

EQUAL_AREA = "EPSG:6933"
NOT_TRAIL_FOOTWAY = {"sidewalk", "crossing", "traffic_island", "access_aisle"}
QRANK_DB = "/home/user/data/qrank.db"


def subdivide(geom, max_vertices=256):
    """Pieces of geom, each with at most max_vertices (like ST_Subdivide)."""
    if shapely.get_num_coordinates(geom) <= max_vertices:
        return [geom]
    x0, y0, x1, y1 = geom.bounds
    if x1 - x0 > y1 - y0:
        xm = (x0 + x1) / 2
        halves = [(x0, y0, xm, y1), (xm, y0, x1, y1)]
    else:
        ym = (y0 + y1) / 2
        halves = [(x0, y0, x1, ym), (x0, ym, x1, y1)]
    out = []
    for box in halves:
        part = shapely.clip_by_rect(geom, *box)
        if not part.is_empty:
            out.extend(subdivide(part, max_vertices))
    return out


class PolygonIndex:
    """Point-in-polygon lookups on polygons subdivided into small pieces."""

    def __init__(self, polys):
        pieces, owner = [], []
        for i, g in enumerate(polys):
            for part in subdivide(shapely.make_valid(g)):
                pieces.append(part)
                owner.append(i)
        self.tree, self.owner = shapely.STRtree(pieces), np.asarray(owner)

    def first(self, points):
        """For each point, the index of a polygon holding it, or -1."""
        pi, si = self.tree.query(points, predicate="within")
        out = np.full(len(points), -1)
        out[pi] = self.owner[si]
        return out

    def pairs(self, points):
        """(point index, polygon index) for every polygon holding a point."""
        pi, si = self.tree.query(points, predicate="within")
        df = pd.DataFrame({"way": pi, "park": self.owner[si]})
        return df.drop_duplicates()


# Parks Canada's parks in Québec and New Brunswick named in French, without an
# operator tag. Québec's own provincial parks are also "parcs nationaux".
CA_FEDERAL_FRENCH = ("Parc national de Forillon", "Parc national de Kouchibouguac",
                     "Parc national de la Mauricie")


def park_class(t, iso):
    name = t.get("name", "")
    name_en = t.get("name:en", "")
    title = (t.get("protection_title") or "").lower()
    op = (t.get("operator") or "").lower()
    if iso == "FR":
        if re.match(r"(?i)parc national\b", name) or t.get("boundary") == "national_park":
            return "national"
        if re.match(r"(?i)parc naturel régional\b", name) or title == "parc naturel régional":
            return "regional"
        # Réserves naturelles nationales, régionales and de Corse: smaller
        # protected sites, nearer in kind to state/provincial parks than the
        # parcs naturels régionaux, which are inhabited countryside.
        if re.match(r"(?i)réserve naturelle\b", name):
            return "reserve"
        return None
    if iso == "CA" and re.search(r"(?i)\bparc national\b", name):
        federal = ("parks canada" in op or "parcs canada" in op or name.startswith(CA_FEDERAL_FRENCH)
                   or name.startswith("Réserve de parc national"))
        return "national" if federal else "regional"
    if re.search(r"\bNational Park\b", name) or re.search(r"\bNational Park\b", name_en):
        return "national"
    if iso == "CA" and (re.search(r"\bProvincial Park\b", name) or title == "provincial park"):
        return "regional"
    if iso == "US" and (re.search(r"\bState Park\b", name) or title == "state park"):
        return "regional"
    return None


def park_key(name):
    """A park's name less any unit: "Grasslands National Park (East Block)",
    "Pacific Rim National Park Reserve - Long Beach Unit" -> "... National Park"."""
    m = re.match(r"(.*?\b(National|Provincial|State) Park)\b", name)
    if m:
        return m.group(1)
    # French parks are mapped as a core and a buffer zone: "Parc national
    # des Écrins (cœur)", "... (aire d'adhésion)". One park.
    return re.sub(r"\s*\((cœur|coeur|aire)[^)]*\)\s*$", "", name, flags=re.I)


def main(outdir, iso):
    outdir = Path(outdir)
    print("loading", file=sys.stderr)
    areas = pd.read_parquet(outdir / "areas.parquet")
    if (outdir / "extra_states.parquet").exists():  # fix_alaska.py
        areas = pd.concat([areas, pd.read_parquet(outdir / "extra_states.parquet")], ignore_index=True)
    areas["t"] = areas.tags.map(json.loads)
    areas = gpd.GeoDataFrame(areas, geometry=shapely.from_wkb(areas.geom.values), crs=4326).drop(columns="geom")

    # States: admin_level 4 relations with this country's ISO3166-2 code.
    states = areas[(areas.kind == "admin4") & areas.t.map(lambda t: t.get("ISO3166-2", "").startswith(iso + "-"))].copy()
    states["code"] = states.t.map(lambda t: t["ISO3166-2"])
    states["name"] = states.t.map(lambda t: t.get("name:en") or t.get("name"))
    states = states.dissolve(by="code", aggfunc={"name": "first"}).reset_index()
    if iso == "FR":  # Metropolitan regions only: the extract has no overseas ones anyway.
        states = states[~states.code.isin(["FR-GUA", "FR-MQ", "FR-GF", "FR-LRE", "FR-MAY", "FR-971", "FR-972", "FR-973", "FR-974", "FR-976"])]
    states["area_km2"] = states.to_crs(EQUAL_AREA).area / 1e6
    states = states[["code", "name", "area_km2", "geometry"]]
    print(f"{len(states)} states", file=sys.stderr)

    state_index = PolygonIndex(states.geometry.values)
    locate = state_index.first

    # Ways, a chunk at a time: just their midpoint, length and a few flags.
    print("ways", file=sys.stderr)
    chunks = []
    for batch in pq.ParquetFile(outdir / "ways.parquet").iter_batches(batch_size=500_000):
        df = batch.to_pandas()
        mid = shapely.line_interpolate_point(shapely.from_wkb(df.geom.values), 0.5, normalized=True)
        t = df.tags.map(json.loads)
        out = pd.DataFrame({
            "id": df.id.values, "length_m": df.length_m.values, "route_member": df.route_member.values,
            "network_trail": (df.trail & ~t.map(
                lambda x: x.get("footway") in NOT_TRAIL_FOOTWAY
                or x.get("access") in ("private", "no") and x.get("foot") not in ("yes", "designated", "permissive"))).values,
            "x": shapely.get_x(mid), "y": shapely.get_y(mid), "state": locate(mid),
        })
        chunks.append(out[out.state >= 0])
        del df, mid, t
    ways = pd.concat(chunks, ignore_index=True)
    del chunks
    members = ways[ways.route_member]
    way_len = dict(zip(members.id, members.length_m))
    way_state = dict(zip(members.id, members.state))

    # Routes.
    print("routes", file=sys.stderr)
    routes = pd.read_parquet(outdir / "routes.parquet")
    routes["t"] = routes.tags.map(json.loads)
    routes["ways_in"] = routes.way_ids.map(lambda ids: [i for i in ids if i in way_len])
    routes["km"] = routes.ways_in.map(lambda ids: sum(way_len[i] for i in set(ids)) / 1000)
    routes["super"] = (routes.way_ids.str.len() == 0) & (routes.relation_ids.str.len() > 0)
    routes["state"] = routes.ways_in.map(lambda ids: way_state[max(ids, key=way_len.get)] if ids else -1)
    super_routes = routes[routes.super]
    routes = routes[~routes.super & (routes.state >= 0)].copy()
    for k in ["name", "network", "operator", "wikidata", "ref", "osmc:symbol"]:
        routes[k] = routes.t.map(lambda x: x.get(k))

    route_ways = set(i for ids in routes.ways_in for i in ids)
    ways["in_route"] = ways.id.isin(route_ways)
    nt = ways[ways.network_trail]

    # Per state.
    g = lambda df, col: df.groupby("state")[col]
    st = states.drop(columns="geometry").copy()
    st["routes"] = routes.groupby("state").size().reindex(range(len(st)), fill_value=0).values
    st["route_km"] = (g(ways[ways.in_route], "length_m").sum() / 1000).reindex(range(len(st)), fill_value=0).values
    st["trail_km"] = (g(nt, "length_m").sum() / 1000).reindex(range(len(st)), fill_value=0).values
    st["trail_km_in_routes"] = (g(nt[nt.in_route], "length_m").sum() / 1000).reindex(range(len(st)), fill_value=0).values
    st["trail_coverage"] = st.trail_km_in_routes / st.trail_km
    st["routes_per_10k_km2"] = st.routes / st.area_km2 * 1e4
    st["route_km_per_1k_km2"] = st.route_km / st.area_km2 * 1e3
    st.to_csv(outdir / "states.csv", index=False)

    # Parks.
    print("parks", file=sys.stderr)
    parks = areas[areas.kind == "park"].copy()
    parks["class"] = parks.t.map(lambda t: park_class(t, iso))
    parks = parks[parks["class"].notna()]
    parks["name"] = parks.t.map(lambda t: t.get("name"))
    parks["wikidata"] = parks.t.map(lambda t: t.get("wikidata"))
    parks["operator"] = parks.t.map(lambda t: t.get("operator"))
    parks["name"] = parks.name.map(park_key)
    parks = parks.dissolve(by=["class", "name"], aggfunc={"wikidata": "first", "operator": "first"}).reset_index()
    parks["state"] = locate(parks.geometry.representative_point().values)
    # A park whose point falls outside every region (e.g. the Calanques'
    # mostly marine core): the region it overlaps most.
    for i in parks.index[parks.state < 0]:
        g = shapely.make_valid(parks.geometry[i])
        overlaps = [(shapely.intersection(g, shapely.make_valid(sg)).area, j)
                    for j, sg in enumerate(states.geometry.values) if g.intersects(sg)]
        if overlaps:
            parks.loc[i, "state"] = max(overlaps)[1]
    parks = parks[parks.state >= 0].reset_index(drop=True)
    parks["area_km2"] = parks.to_crs(EQUAL_AREA).area / 1e6

    # Ways whose midpoint is in each park.
    # Parks overlap (e.g. a park inside a larger reserve), so all pairs.
    park_index = PolygonIndex(parks.geometry.values)
    pairs = []
    for start in range(0, len(ways), 1_000_000):
        part = ways.iloc[start:start + 1_000_000]
        pr = park_index.pairs(shapely.points(part.x.values, part.y.values))
        pr["way"] += start
        pairs.append(pr)
    pairs = pd.concat(pairs, ignore_index=True)
    pairs = pairs.join(ways[["id", "length_m", "network_trail", "in_route"]], on="way")
    way_routes = routes[["id", "ways_in"]].explode("ways_in").dropna()
    way_routes = way_routes.groupby("ways_in").id.apply(list).to_dict()
    def park_stats(df):
        r = set(x for i in df.id[df.in_route] for x in way_routes.get(i, []))
        nt_ = df[df.network_trail]
        return pd.Series({
            "routes": len(r),
            "route_ids": " ".join(map(str, sorted(r))),
            "route_km": df.length_m[df.in_route].sum() / 1000,
            "trail_km": nt_.length_m.sum() / 1000,
            "trail_km_in_routes": nt_.length_m[nt_.in_route].sum() / 1000,
        })
    ps = pairs.groupby("park").apply(park_stats, include_groups=False)
    parks = parks.join(ps)
    for c in ["routes", "route_km", "trail_km", "trail_km_in_routes"]:
        parks[c] = parks[c].fillna(0)
    parks["route_ids"] = parks.route_ids.fillna("")
    parks["state_code"] = states.code.values[parks.state]

    # QRank (Wikipedia/Wikidata pageviews) as a measure of fame.
    qdb = sqlite3.connect(QRANK_DB)
    def qrank(q):
        if not isinstance(q, str) or not re.fullmatch(r"Q\d+", q):
            return None
        row = qdb.execute("select qrank from qrank where id = ?", (int(q[1:]),)).fetchone()
        return row[0] if row else None
    parks["qrank"] = parks.wikidata.map(qrank)
    parks.drop(columns=["geometry", "state"]).to_csv(outdir / "parks.csv", index=False)

    routes["state_code"] = states.code.values[routes.state]
    routes["qrank"] = routes.wikidata.map(qrank)
    routes[["id", "name", "ref", "network", "operator", "wikidata", "qrank", "km", "state_code"]].to_csv(outdir / "routes.csv", index=False)

    summary = {
        "iso": iso,
        "area_km2": float(st.area_km2.sum()),
        "routes": int(len(routes)),
        "super_routes": int(len(super_routes)),
        "route_km": float(ways.length_m[ways.in_route].sum() / 1000),
        "route_km_sum_of_routes": float(routes.km.sum()),
        "trail_km": float(nt.length_m.sum() / 1000),
        "trail_km_in_routes": float(nt.length_m[nt.in_route].sum() / 1000),
        "route_km_on_trails": float(ways.length_m[ways.in_route & ways.network_trail].sum() / 1000),
        "routes_by_network": routes.network.fillna("(none)").value_counts().to_dict(),
        "routes_named": float(routes.name.notna().mean()),
        "routes_with_wikidata": float(routes.wikidata.notna().mean()),
        "parks": {c: {
            "count": int((parks["class"] == c).sum()),
            "with_route": int(((parks["class"] == c) & (parks.routes > 0)).sum()),
            "trail_km": float(parks.trail_km[parks["class"] == c].sum()),
            "trail_km_in_routes": float(parks.trail_km_in_routes[parks["class"] == c].sum()),
        } for c in ["national", "regional", "reserve"] if (parks["class"] == c).any()},
    }
    summary["trail_coverage"] = summary["trail_km_in_routes"] / summary["trail_km"]
    (outdir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
