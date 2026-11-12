#!/usr/bin/env python3
# worldcover-polygons.py WORLDCOVER.pmtiles W,S,E,N OUT.geojsonl
#
# WorldCover land cover (bin/worldcover.py's z12 tiles) as polygons for the
# land slice's "landcover" layer (#167): the style draws it under OSM's land
# fills, so it shows only where OSM maps none. One feature per patch, with
# `class` one of forest, scrub, meadow, rock, glacier, wetland; cropland,
# built-up and water are left out (OSM maps those, and the water layer draws
# water).
#
# Patches under MIN_PIXELS z12 pixels (~12 m across) are merged into their
# neighbours first (a sieve), so the fill isn't speckled; outlines are
# simplified by about a pixel, which also smooths the pixel steps.
#
# WORLDCOVER.pmtiles is a local extract (bin/docker-pmtiles extract ...
# --bbox): this reads every tile in the box.
#
# Needs: pip install numpy pillow pmtiles rasterio shapely
import io, json, math, sys

import numpy as np
from PIL import Image
from pmtiles.reader import MmapSource, Reader
from rasterio.features import shapes, sieve
from rasterio.transform import Affine
import shapely
from shapely.geometry import mapping, shape

Z = 12
TILE = 512
MIN_PIXELS = 25  # ~0.4 ha at 50°N
CLASSES = {1: 'forest', 2: 'scrub', 3: 'meadow', 4: 'rock', 5: 'glacier', 6: 'wetland'}
CODE = {10: 1, 20: 2, 30: 3, 100: 3, 60: 4, 70: 5, 90: 6, 95: 6}  # WorldCover -> CLASSES
HALF = 20037508.342789244
RES = 2 * HALF / (TILE * 2 ** Z)  # metres per z12 pixel, in web mercator


def main():
    src, bbox, out = sys.argv[1], [float(v) for v in sys.argv[2].split(',')], sys.argv[3]
    W, S, E, N = bbox
    n = TILE * 2 ** Z
    px = lambda lon: int((lon + 180) / 360 * n)
    py = lambda lat: int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    x0, y0, x1, y1 = px(W), py(N), px(E), py(S)
    grid = np.zeros((y1 - y0, x1 - x0), np.uint8)
    lut = np.zeros(256, np.uint8)
    for code, c in CODE.items():
        lut[code] = c
    with open(src, 'rb') as f:
        r = Reader(MmapSource(f))
        for tx in range(x0 // TILE, (x1 - 1) // TILE + 1):
            for ty in range(y0 // TILE, (y1 - 1) // TILE + 1):
                d = r.get(Z, tx, ty)
                if not d:
                    continue
                a = lut[np.array(Image.open(io.BytesIO(d)))]
                cx, cy = tx * TILE - x0, ty * TILE - y0
                sx, sy = max(0, -cx), max(0, -cy)
                ex, ey = min(TILE, grid.shape[1] - cx), min(TILE, grid.shape[0] - cy)
                grid[cy + sy:cy + ey, cx + sx:cx + ex] = a[sy:ey, sx:ex]
    grid = sieve(grid, size=MIN_PIXELS, connectivity=8)
    # Pixel (col, row) -> web mercator metres
    aff = Affine(RES, 0, x0 * RES - HALF, 0, -RES, HALF - y0 * RES)
    to_lonlat = lambda a: np.column_stack((np.degrees(a[:, 0] / 6378137.0),
                                           np.degrees(2 * np.arctan(np.exp(a[:, 1] / 6378137.0)) - np.pi / 2)))
    count = 0
    with open(out, 'w') as f:
        for geom, v in shapes(grid, mask=grid > 0, connectivity=8, transform=aff):
            g = shape(geom).simplify(RES, preserve_topology=True)
            if g.is_empty:
                continue
            g = shapely.transform(g, to_lonlat)
            f.write(json.dumps({'type': 'Feature', 'properties': {'class': CLASSES[int(v)]},
                                'geometry': mapping(g)}, separators=(',', ':')) + '\n')
            count += 1
    print(f'{out}: {count} polygons over {grid.shape[1]}x{grid.shape[0]} px; '
          f'{(grid > 0).mean() * 100:.0f}% covered', flush=True)


if __name__ == '__main__':
    main()
