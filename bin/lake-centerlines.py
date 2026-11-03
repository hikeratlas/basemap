#!/usr/bin/env python3
# Lake centerlines for lake name labels, from acalcutt/osm-lakelines
# (https://github.com/acalcutt/osm-lakelines/releases), which has no names.
#
#   lake-centerlines.py convert IN.geojson OUT.geojsonl IDS.txt minlon,minlat,maxlon,maxlat
#     Converts its lake_centerline.geojson (EPSG:3857, one feature per line,
#     properties {"OSM_ID": n}; n < 0 is a relation, else a way) to GeoJSONL in
#     WGS84, keeping lines that overlap the box, and lists their OSM ids
#     (w123 / r456) for `osmium getid -i`.
#
#   lake-centerlines.py name IN.geojsonl LAKES.opl OUT.geojsonl
#     Adds each lake's current name from an `osmium getid -f opl` dump of those
#     ids, dropping lines whose lake is gone, no longer water, or unnamed. Bays
#     (natural=bay) are kept: osm-lakelines has centerlines for many inlets and
#     fjords, e.g. Bute Inlet (relation/8350798).
import json, math, re, sys

R = 6378137.0


def lonlat(x, y):
    return [round(x / R * 180 / math.pi, 6), round((2 * math.atan(math.exp(y / R)) - math.pi / 2) * 180 / math.pi, 6)]


def convert(src, out, ids_out, bbox):
    minx, miny, maxx, maxy = (float(v) for v in bbox.split(','))
    kept = total = 0
    ids = set()
    with open(src) as f, open(out, 'w') as w:
        for line in f:
            line = line.strip().rstrip(',')
            if not line.startswith('{ "type": "Feature"'):
                continue
            total += 1
            feat = json.loads(line)
            g = feat['geometry']
            if g['type'] == 'LineString':
                lines = [g['coordinates']]
            elif g['type'] == 'MultiLineString':
                lines = g['coordinates']
            else:
                continue
            lines = [[lonlat(*p) for p in l] for l in lines]
            xs = [p[0] for l in lines for p in l]
            ys = [p[1] for l in lines for p in l]
            if max(xs) < minx or min(xs) > maxx or max(ys) < miny or min(ys) > maxy:
                continue
            osm_id = int(round(feat['properties']['OSM_ID']))
            props = {'osm_type': 'relation' if osm_id < 0 else 'way', 'osm_id': abs(osm_id)}
            ids.add(('r' if osm_id < 0 else 'w') + str(abs(osm_id)))
            geom = {'type': 'LineString', 'coordinates': lines[0]} if len(lines) == 1 else {'type': 'MultiLineString', 'coordinates': lines}
            w.write(json.dumps({'type': 'Feature', 'properties': props, 'geometry': geom}, separators=(',', ':')) + '\n')
            kept += 1
    with open(ids_out, 'w') as w:
        w.write('\n'.join(sorted(ids)) + '\n')
    print(f'{total} centerlines, {kept} in {bbox}, {len(ids)} lakes', file=sys.stderr)


# OPL escapes characters as %<hex code point>%
def unescape(s):
    return re.sub(r'%([0-9a-fA-F]+)%', lambda m: chr(int(m.group(1), 16)), s)


def opl_tags(field):
    tags = {}
    for kv in field.split(','):
        if '=' in kv:
            k, v = kv.split('=', 1)
            tags[unescape(k)] = unescape(v)
    return tags


def name(src, opl, out):
    lakes = {}
    with open(opl) as f:
        for line in f:
            parts = line.split(' ')
            t = next((p[1:] for p in parts if p.startswith('T')), '')
            lakes[(parts[0][0], int(parts[0][1:]))] = opl_tags(t.rstrip('\n'))
    kept = gone = notwater = unnamed = 0
    with open(src) as f, open(out, 'w') as w:
        for line in f:
            feat = json.loads(line)
            p = feat['properties']
            tags = lakes.get(('r' if p['osm_type'] == 'relation' else 'w', p['osm_id']))
            if tags is None:
                gone += 1
                continue
            if tags.get('natural') not in ('water', 'bay') and 'water' not in tags:
                notwater += 1
                continue
            if not tags.get('name'):
                unnamed += 1
                continue
            p['name'] = tags['name']
            w.write(json.dumps(feat, separators=(',', ':'), ensure_ascii=False) + '\n')
            kept += 1
    print(f'{kept} named lake centerlines; dropped {gone} gone, {notwater} no longer water, {unnamed} unnamed', file=sys.stderr)


if __name__ == '__main__':
    cmd, *args = sys.argv[1:]
    {'convert': convert, 'name': name}[cmd](*args)
