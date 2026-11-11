#!/usr/bin/env python3
# worldcover.py OUT.pmtiles [--bbox W,S,E,N] [--jobs N] [--workdir DIR]
#
# ESA WorldCover 2021 (10 m land cover, CC BY 4.0) as z12 PNG tiles in a
# PMTiles archive, for hikeratlas/routes to fall back on where OSM maps no land
# cover (issue #167). Each 512 px tile is 8-bit greyscale holding WorldCover's
# own class codes, so the archive stays generic and readers map them:
#
#   0 no data, 10 tree cover, 20 shrubland, 30 grassland, 40 cropland,
#   50 built-up, 60 bare / sparse vegetation, 70 snow and ice,
#   80 permanent water, 90 herbaceous wetland, 95 mangroves, 100 moss and lichen
#
# A z12 pixel is 12-16 m across North America, about WorldCover's 10 m, so
# finer zooms would add size and no detail. Pixels are sampled nearest.
#
# WorldCover is published as 3x3 degree Cloud-Optimized GeoTIFFs on AWS
# (s3://esa-worldcover, public). Each job downloads one whole, writes the
# tiles it owns, and deletes it: a tile is owned by the source its centre is
# in, or, if that source doesn't exist (open ocean), the first that does. A
# tile reaching past its owner reads the neighbours' edges by HTTP range.
# All of North America is ~480 sources, ~29 GB.
#
# Needs: pip install numpy pillow pmtiles rasterio requests
import io, json, math, os, struct, sys, tempfile
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np
import requests

BASE = 'https://esa-worldcover.s3.eu-central-1.amazonaws.com'
GRID = f'{BASE}/v200/2021/esa_worldcover_grid.geojson'
Z = 12
TILE = 512
PX = 12000  # WorldCover pixels per degree
DEFAULT_BBOX = (-170.0, 20.0, -48.0, 75.0)  # areas.json's north-america


def src_name(la, lo):
    return f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"


def src_url(name):
    return f'{BASE}/v200/2021/map/ESA_WorldCover_10m_2021_v200_{name}_Map.tif'


def src_of(lon, lat):
    """The (lat, lon) of the 3-degree source holding a point."""
    return 3 * math.floor(lat / 3), 3 * math.floor(lon / 3)


def tile_lon(x):
    return x / 2 ** Z * 360 - 180


def tile_lat(y):
    return math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / 2 ** Z))))


def tile_x(lon):
    return int((lon + 180) / 360 * 2 ** Z)


def tile_y(lat):
    return int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * 2 ** Z)


def sources_of_tile(x, y):
    """The sources a z12 tile overlaps, as (lat, lon)."""
    w, e, n, s = tile_lon(x), tile_lon(x + 1), tile_lat(y), tile_lat(y + 1)
    las = range(3 * math.floor(s / 3), 3 * math.floor((n - 1e-9) / 3) + 1, 3)
    los = range(3 * math.floor(w / 3), 3 * math.floor((e - 1e-9) / 3) + 1, 3)
    return [(la, lo) for la in las for lo in los]


def owner(x, y, have):
    c = src_of((tile_lon(x) + tile_lon(x + 1)) / 2, (tile_lat(y) + tile_lat(y + 1)) / 2)
    if c in have:
        return c
    return next((s for s in sources_of_tile(x, y) if s in have), None)


def tiles_of_source(la, lo, bbox):
    """The z12 tiles overlapping a source, clipped to bbox."""
    W, S, E, N = max(lo, bbox[0]), max(la, bbox[1]), min(lo + 3, bbox[2]), min(la + 3, bbox[3])
    if W >= E or S >= N:
        return []
    return [(x, y) for x in range(tile_x(W), tile_x(E - 1e-9) + 1)
            for y in range(tile_y(N - 1e-9), tile_y(S) + 1)]


def pixel_index(x, y):
    """Global WorldCover row and column of each pixel centre in a z12 tile."""
    n = 2 ** Z * TILE
    cols = ((np.arange(TILE) + x * TILE + 0.5) / n * 360 - 180 + 180) * PX
    py = np.arange(TILE) + y * TILE + 0.5
    lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * py / n))))
    rows = (90 - lat) * PX
    return np.floor(rows).astype(np.int64), np.floor(cols).astype(np.int64)


class Sources:
    """Reads global WorldCover pixel boxes: the job's own source from disk,
    neighbours by range request."""

    def __init__(self, have, local):
        import rasterio
        self.rasterio, self.have, self.local, self.open = rasterio, have, local, {}

    def ds(self, s):
        if s not in self.open:
            path = self.local.get(s) or '/vsicurl/' + src_url(src_name(*s))
            self.open[s] = self.rasterio.open(path)
        return self.open[s]

    def read(self, r0, r1, c0, c1):
        """Global rows r0..r1 and columns c0..c1 (exclusive); 0 where no source."""
        from rasterio.windows import Window
        out = np.zeros((r1 - r0, c1 - c0), np.uint8)
        for la in range(3 * math.floor((90 - r1 / PX) / 3), 3 * math.floor((90 - r0 / PX) / 3) + 1, 3):
            for lo in range(3 * math.floor((c0 / PX - 180) / 3), 3 * math.floor((c1 / PX - 180) / 3) + 1, 3):
                if (la, lo) not in self.have:
                    continue
                sr0, sc0 = round((90 - la - 3) * PX), round((lo + 180) * PX)  # source's top-left
                a0, a1 = max(r0, sr0), min(r1, sr0 + 3 * PX)
                b0, b1 = max(c0, sc0), min(c1, sc0 + 3 * PX)
                if a0 >= a1 or b0 >= b1:
                    continue
                win = Window(b0 - sc0, a0 - sr0, b1 - b0, a1 - a0)
                out[a0 - r0:a1 - r0, b0 - c0:b1 - c0] = self.ds((la, lo)).read(1, window=win)
        return out


def png(a):
    from PIL import Image
    buf = io.BytesIO()
    Image.fromarray(a, 'L').save(buf, 'PNG', compress_level=6)
    return buf.getvalue()


def download(url, path):
    for attempt in range(5):
        try:
            with requests.get(url, stream=True, timeout=120) as r:
                r.raise_for_status()
                with open(path, 'wb') as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            return
        except requests.RequestException as e:
            print(f'{url}: {e} (attempt {attempt + 1})', file=sys.stderr, flush=True)
    raise SystemExit(f'{url}: download failed')


def job(s, have, bbox, workdir):
    """Writes the tiles source s owns to a run file: (tile id, length, PNG)*."""
    from pmtiles.tile import zxy_to_tileid
    name = src_name(*s)
    tif = os.path.join(workdir, name + '.tif')
    download(src_url(name), tif)
    src = Sources(have, {s: tif})
    out_path = os.path.join(workdir, name + '.run')
    n = 0
    with open(out_path, 'wb') as out:
        for x, y in tiles_of_source(*s, bbox):
            if owner(x, y, have) != s:
                continue
            rows, cols = pixel_index(x, y)
            box = src.read(rows.min(), rows.max() + 1, cols.min(), cols.max() + 1)
            a = box[np.ix_(rows - rows.min(), cols - cols.min())]
            if not a.any():
                continue
            data = png(a)
            out.write(struct.pack('<QI', zxy_to_tileid(Z, x, y), len(data)))
            out.write(data)
            n += 1
    os.remove(tif)
    return s, out_path, n


def main():
    args = sys.argv[1:]
    bbox, jobs, workdir = DEFAULT_BBOX, os.cpu_count() or 1, None
    for flag in ('--bbox', '--jobs', '--workdir'):
        if flag in args:
            i = args.index(flag)
            v = args[i + 1]
            del args[i:i + 2]
            if flag == '--bbox':
                bbox = tuple(float(c) for c in v.split(','))
            elif flag == '--jobs':
                jobs = int(v)
            else:
                workdir = v
    if len(args) != 1:
        raise SystemExit('usage: worldcover.py OUT.pmtiles [--bbox W,S,E,N] [--jobs N] [--workdir DIR]')
    out = args[0]
    workdir = workdir or tempfile.mkdtemp(prefix='worldcover-')
    os.makedirs(workdir, exist_ok=True)

    grid = requests.get(GRID, timeout=120).json()
    have = set()
    for f in grid['features']:
        n = f['properties']['ll_tile']
        have.add((int(n[1:3]) * (1 if n[0] == 'N' else -1), int(n[4:7]) * (1 if n[3] == 'E' else -1)))
    todo = sorted(s for s in have if tiles_of_source(*s, bbox))
    print(f'{len(todo)} WorldCover sources in {bbox}, {jobs} jobs', flush=True)

    runs, total = [], 0
    with ProcessPoolExecutor(jobs) as ex:
        futs = [ex.submit(job, s, have, bbox, workdir) for s in todo]
        for i, f in enumerate(as_completed(futs), 1):
            s, path, n = f.result()
            runs.append(path)
            total += n
            print(f'[{i}/{len(todo)}] {src_name(*s)}: {n} tiles', flush=True)

    # Every tile, in tile id order, for a clustered archive.
    index = []
    for path in runs:
        with open(path, 'rb') as f:
            off = 0
            while head := f.read(12):
                tid, ln = struct.unpack('<QI', head)
                index.append((tid, path, off + 12, ln))
                f.seek(ln, 1)
                off += 12 + ln
    index.sort()
    from pmtiles.tile import Compression, TileType
    from pmtiles.writer import Writer
    files = {p: open(p, 'rb') for p in runs}
    with open(out, 'wb') as f:
        w = Writer(f)
        for tid, path, off, ln in index:
            files[path].seek(off)
            w.write_tile(tid, files[path].read(ln))
        w.finalize({
            'tile_type': TileType.PNG, 'tile_compression': Compression.NONE,
            'min_lon_e7': int(bbox[0] * 1e7), 'min_lat_e7': int(bbox[1] * 1e7),
            'max_lon_e7': int(bbox[2] * 1e7), 'max_lat_e7': int(bbox[3] * 1e7),
            'center_zoom': Z, 'center_lon_e7': int((bbox[0] + bbox[2]) / 2 * 1e7),
            'center_lat_e7': int((bbox[1] + bbox[3]) / 2 * 1e7),
        }, {
            'name': 'ESA WorldCover 2021',
            'attribution': '<a href="https://esa-worldcover.org/">ESA WorldCover 2021</a> (CC BY 4.0)',
            'description': 'WorldCover v200 class codes as 8-bit greyscale: 0 no data, 10 tree cover, '
                           '20 shrubland, 30 grassland, 40 cropland, 50 built-up, 60 bare / sparse '
                           'vegetation, 70 snow and ice, 80 permanent water, 90 herbaceous wetland, '
                           '95 mangroves, 100 moss and lichen',
        })
    for fh in files.values():
        fh.close()
    for p in runs:
        os.remove(p)
    print(f'{out}: {total} tiles, {os.path.getsize(out) / 1e6:.0f} MB', flush=True)


if __name__ == '__main__':
    main()
