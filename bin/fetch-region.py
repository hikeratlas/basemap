#!/usr/bin/env python3
"""Usage: bin/fetch-region.py URL|FILE REGION.json OUT.pmtiles [--zoom 14] [--gap BYTES] [--threads N]

Fetches the part of a remote PMTiles archive that a region needs (#205):
its header, metadata and directories, and the tiles at --zoom inside the
region (routes --write-region's GeoJSON MultiPolygon of boxes), into a
sparse local file at their original offsets. Readers see the archive as
it is, so long as they only read those tiles; what isn't fetched takes no
disk space.

tilemaker's archives aren't clustered (tiles aren't stored in tile-id
order), so `pmtiles extract` refuses them. Instead, the tiles' byte ranges
are sorted and merged when less than --gap apart. The default, 16 MiB,
keeps the requests below a whole download's (`aws s3 cp` in 64 MB parts):
for north-america's biggest shard, ~90 requests and 13 GB instead of ~290
and 19 GB. Smaller gaps fetch less, in more requests.
"""
import argparse, bisect, gzip, json, math, os, struct, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor


ETAG = None


def get(url, start, length, tries=5):
    if not url.startswith(('http://', 'https://')):  # a local file, for tests
        with open(url, 'rb') as f:
            f.seek(start)
            return f.read(length)
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                'Range': f'bytes={start}-{start + length - 1}', 'User-Agent': 'hikeratlas-fetch-region'})
            with urllib.request.urlopen(req, timeout=120) as r:
                data = r.read()
                etag = r.headers.get('ETag')
            if len(data) != length:
                raise IOError(f'got {len(data)} of {length} bytes')
            # Every range must come from the same version of the archive (it's
            # replaced at the same URL each build): not mixed with an older
            # copy from a cache, or one replaced while this runs.
            global ETAG
            if etag:
                ETAG = ETAG or etag
                if etag != ETAG:
                    sys.exit(f'{url} changed while fetching it (ETag {etag}, not {ETAG})')
            return data
        except Exception as e:
            if i == tries - 1:
                raise
            print(f'{start}+{length}: {e}; retrying', file=sys.stderr)
            time.sleep(2 ** i)


def varints(b):
    out, i = [], 0
    while i < len(b):
        v = s = 0
        while True:
            c = b[i]
            i += 1
            v |= (c & 0x7f) << s
            s += 7
            if c < 0x80:
                break
        out.append(v)
    return out


def parse_dir(b):
    """A PMTiles v3 directory, as (tile_id, offset, length, run_length)."""
    v = varints(b)
    n, p = v[0], 1
    ids, last = [], 0
    for k in range(n):
        last += v[p + k]
        ids.append(last)
    p += n
    runs = v[p:p + n]
    p += n
    lens = v[p:p + n]
    p += n
    offs = []
    for k in range(n):
        o = v[p + k]
        offs.append(offs[-1] + lens[k - 1] if o == 0 and k > 0 else o - 1)
    return list(zip(ids, offs, lens, runs))


def tile_id(z, x, y):
    acc = (4 ** z - 1) // 3
    n, d, s = 1 << z, 0, (1 << z) >> 1
    while s > 0:
        rx, ry = int(x & s > 0), int(y & s > 0)
        d += s * s * ((3 * rx) ^ ry)
        if ry == 0:
            if rx == 1:
                x, y = n - 1 - x, n - 1 - y
            x, y = y, x
        s >>= 1
    return acc + d


def region_tiles(region, z):
    """The tile ids at zoom Z of the region's boxes."""
    n = 1 << z
    tx = lambda lon: min(n - 1, max(0, int((lon + 180) / 360 * n)))
    ty = lambda lat: min(n - 1, max(0, int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)))
    want = set()
    for poly in region['coordinates']:
        xs = [p[0] for p in poly[0]]
        ys = [p[1] for p in poly[0]]
        for x in range(tx(min(xs)), tx(max(xs)) + 1):
            for y in range(ty(max(ys)), ty(min(ys)) + 1):
                want.add(tile_id(z, x, y))
    return want


def coalesce(spans, gap):
    ranges = []
    for off, ln in sorted(spans):
        if ranges and off - ranges[-1][1] <= gap:
            ranges[-1][1] = max(ranges[-1][1], off + ln)
        else:
            ranges.append([off, off + ln])
    return ranges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('url')
    ap.add_argument('region')
    ap.add_argument('out')
    ap.add_argument('--zoom', type=int, default=14)
    ap.add_argument('--gap', type=int, default=16 << 20)
    ap.add_argument('--threads', type=int, default=16)
    a = ap.parse_args()
    t0 = time.time()

    h = get(a.url, 0, 127)
    if h[:7] != b'PMTiles' or h[7] != 3:
        sys.exit(f'{a.url}: not a PMTiles v3 archive')
    u = lambda o: struct.unpack('<Q', h[o:o + 8])[0]
    root_off, root_len, meta_off, meta_len = u(8), u(16), u(24), u(32)
    leaf_off, leaf_len, data_off, data_len = u(40), u(48), u(56), u(64)
    if h[97] not in (1, 2):
        sys.exit(f'{a.url}: internal compression {h[97]} not supported')
    dec = gzip.decompress if h[97] == 2 else (lambda b: b)

    fd = os.open(a.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o644)
    size = max(o + n for o, n in ((root_off, root_len), (meta_off, meta_len),
                                  (leaf_off, leaf_len), (data_off, data_len)))
    os.ftruncate(fd, size)  # sparse: holes take no space
    # The header and the sections other than the tile data, wherever they
    # are (tilemaker puts the leaf directories after the tiles).
    sections = {}
    for name, o, n in (('header', 0, 127), ('root', root_off, root_len),
                       ('meta', meta_off, meta_len), ('leaves', leaf_off, leaf_len)):
        if n:
            sections[name] = get(a.url, o, n)
            os.pwrite(fd, sections[name], o)
    leaves = sections.get('leaves', b'')
    entries = []
    for e in parse_dir(dec(sections['root'])):
        if e[3] == 0:
            entries += parse_dir(dec(leaves[e[1]:e[1] + e[2]]))
        else:
            entries.append(e)
    ids = [e[0] for e in entries]

    want = region_tiles(json.load(open(a.region)), a.zoom)
    spans = {}
    for t in want:
        i = bisect.bisect_right(ids, t) - 1
        if i >= 0 and t < entries[i][0] + max(entries[i][3], 1):
            spans[entries[i][1]] = entries[i][2]
    ranges = coalesce(spans.items(), a.gap)
    total = sum(b - s for s, b in ranges)

    def fetch(r):
        s, e = r
        os.pwrite(fd, get(a.url, data_off + s, e - s), data_off + s)
    with ThreadPoolExecutor(a.threads) as pool:
        list(pool.map(fetch, ranges))
    os.close(fd)
    print(f'{os.path.basename(a.out)}: {len(spans):,} tiles of {len(want):,} in {len(ranges):,} requests, '
          f'{(total + root_len + meta_len + leaf_len) / 1e9:.2f} of {size / 1e9:.2f} GB, {time.time() - t0:.0f}s')


if __name__ == '__main__':
    main()
