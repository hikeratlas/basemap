"""How many of a park's published hikes exist as route=hiking relations?

    python3 -I published_hikes.py EXPECT_DIR OUTDIR > hikes.csv

EXPECT_DIR is hikeratlas/routes' fixtures/expect/ (hikes parks list on their
websites, each with a trace drawn along it); OUTDIR is extract.py's output
for the area. For each traced hike, with routes' own thresholds (a hike's
line within 50 m of at least 70% of the trace's points):
- relation: one route=hiking relation follows the hike;
- relations: several together do (the hike is stitched from pieces);
- any_trail: the hike is mapped at all, as trail ways or route ways;
- name: a relation near the hike has the hike's name (or an aka).
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely

WITHIN_M, COVER = 50, 0.7
CRS = "EPSG:3978"  # Canada Lambert: metres


def norm(s):
    s = re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())
    s = re.sub(r"\b(trail|loop|the|hike|route|path|sentier)\b", " ", s)
    return " ".join(s.split())


def main(expect_dir, outdir):
    import geopandas as gpd
    entries = [json.loads(l) for f in sorted(Path(expect_dir).glob("*.jsonl")) for l in open(f) if l.strip()]
    entries = [e for e in entries if e.get("kind") == "trail" and (e.get("trace") or e.get("traces"))]

    ways = pd.read_parquet(Path(outdir) / "ways.parquet", columns=["id", "trail", "route_member", "geom"])
    ways = gpd.GeoDataFrame(ways.drop(columns="geom"), geometry=shapely.from_wkb(ways.geom.values), crs=4326)
    # Only the ways near the hikes.
    pts = np.array([p for e in entries for p in (e.get("trace") or e["traces"][0])])
    lo, hi = pts.min(axis=0) - 0.2, pts.max(axis=0) + 0.2
    ways = ways.cx[lo[0]:hi[0], lo[1]:hi[1]].to_crs(CRS)

    routes = pd.read_parquet(Path(outdir) / "routes.parquet")
    route_of = {}
    for rid, tags, wids in zip(routes.id, routes.tags, routes.way_ids):
        for w in wids:
            route_of.setdefault(w, []).append(rid)
    names = {rid: json.loads(t).get("name", "") for rid, t in zip(routes.id, routes.tags)}

    rows = []
    for e in entries:
        trace = e.get("trace") or e["traces"][0]
        p = gpd.GeoSeries(shapely.points(trace), crs=4326).to_crs(CRS).values
        near = ways.sindex.query(p, predicate="dwithin", distance=WITHIN_M)
        hits = pd.DataFrame({"pt": near[0], "way": ways.id.values[near[1]],
                             "member": ways.route_member.values[near[1]]})
        n = len(p)
        any_trail = hits.pt.nunique() / n
        in_routes = hits[hits.member].pt.nunique() / n
        best, best_name, name_hit = 0.0, "", False
        per_route = {}
        for pt, w in zip(hits.pt[hits.member], hits.way[hits.member]):
            for rid in route_of.get(w, []):
                per_route.setdefault(rid, set()).add(pt)
        for rid, s in per_route.items():
            if len(s) / n > best:
                best, best_name = len(s) / n, names.get(rid, "")
        wanted = {norm(e["name"])} | {norm(a) for a in e.get("aka", [])} | ({norm(e["trail"])} if e.get("trail") else set())
        name_hit = any(norm(names.get(rid, "")) in wanted for rid in per_route) if per_route else False
        rows.append({
            "park": e["park"], "hike": e["name"], "km": e.get("km"), "source": e.get("source", ""),
            "any_trail": round(any_trail, 2), "best_relation": round(best, 2), "best_relation_name": best_name,
            "all_relations": round(in_routes, 2), "name_match": name_hit,
            "relation": best >= COVER, "relations": in_routes >= COVER, "mapped": any_trail >= COVER,
        })
    df = pd.DataFrame(rows)
    df.to_csv(sys.stdout, index=False)
    s = df[df.mapped]
    print(f"{len(df)} hikes in {df.park.nunique()} parks; {len(s)} mapped as trail", file=sys.stderr)
    for k in ["relation", "relations", "name_match"]:
        print(f"  {k}: {s[k].sum()} of {len(s)} ({100 * s[k].mean():.0f}%)", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
