# basemap

This repo has tools to generate the "basemap" that [Hiker Atlas](https://www.hikeratlas.com/map) uses.

> What's a basemap?
>
> Basemaps are the map canvas on which everything else is built. They show
> the roads, cities, mountains, etc. You can pay someone like Google to provide
> basemaps, but they're expensive. We'd also like to style them to emphasize
> hiking-specific things.

This repo is useful for two tasks:

1. Building a [PMTiles](https://docs.protomaps.com/pmtiles/) database with vector tiles suitable for Hiker Atlas

2. Tweaking the [MapLibre Style Spec](https://maplibre.org/maplibre-style-spec/) file

The two tasks are closely related.

We use [`tilemaker`](https://github.com/systemed/tilemaker) to convert a [PBF extract](https://download.geofabrik.de/) from [OpenStreetMap](https://www.openstreetmap.org/) into a `.pmtiles` file. This act translates from OSM's `relation`, `way`, and `node` entries into layers of content that the styles will render.

The styles can only render the layers that we emit: so we need to ensure we emit things we care about. (And, of course, it means there's no sense in emitting things we know we don't want to render.)

Our schema and style is entirely custom. We have separate scripts for each individual layer, and the ability to merge them in a post-processing step. This makes it slightly faster to iterate on a given layer, while still being able to see the final result.

# Setup

The basemap requires certain GeoJSON files that define boundaries of countries, states and parks. These are created from OSM itself:

```bash
./export/export-all planet.osm.pbf
```

# Usage

We use [mapt](https://github.com/cldellow/mapt) to develop the basemap. `bun install` will install it.

The scripts require some third-party Lua modules:

```bash
apt install lua-sql-sqlite3
luarocks install luaflock
```

## Build all layers

This builds each layer, emitting `buildings.pmtiles`, `water.pmtiles`, `ways.pmtiles`, etc.

This is useful the first time you run the repo, or when switching to a new area of focus.

```bash
bun mapt build rockies.osm.pbf
```

## Build a single layer

You can also focus on a subset of layers at a time:

```bash
bun mapt build rockies.osm.pbf boundaries ways
```

## View the results

Start the webserver with:

```bash
bun mapt serve
```

Then navigate to http://localhost:8081/ - you can inspect individual pmtiles files, or view the `development` map.

The server will stitch together any styles in `/styles/`. If you edit any
of them, the page will reload.

## Licensing and Attributions

Unless otherwise noted, this repository is licensed under Apache 2.0. The artifacts it produces depend on things that may be licensed under other licenses. Your usage of the code in this repository is also subject to those licenses.

- The data in the basemap is copyright OpenStreetMap contributors, and licensed under ODbL.
- [Tailwind CSS](https://tailwindcss.com/)'s color palette is licensed under MIT.
- [Wikidata QRank](https://qrank.wmcloud.org/) is licensed under CC0.
- [Mapzen's Joerd terrain dataset](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) is complicated; see the link for details.
- [json.lua](https://github.com/rxi/json.lua) is licensed under MIT.

# Miscellaneous resources

- https://osmlanduse.org/ helps identify the landuse OSM object in a given range. (I found OSM's Query Features action often omitted landcover polygons.)

# Forked tools

The build uses forks of two tools, published as Docker images that the scripts
pull: [cldellow/tilemaker](https://github.com/cldellow/tilemaker), branch
`relslow-patched` (`ghcr.io/cldellow/tilemaker:relslow-patched`, see
`bin/docker-tilemaker`), and [cldellow/go-pmtiles](https://github.com/cldellow/go-pmtiles)
(pinned by commit in `bin/docker-pmtiles`). Both images are built for amd64 and
arm64, since the GitHub Actions jobs run on arm64 runners.

Upstream versions won't build this repo as it is. Its config and Lua rely on
these features of the forks:

**tilemaker**
- `"compress": "zstd"` for vector tiles (every slice), and reading `.osm.pbf`
  files whose blobs are zstd-compressed (the mirrored `<area>.zstd.pbf`).
- `outline_of` in a layer's config: the boundaries of another layer's polygons
  as lines, without the edges that clipping to the tile added. `park_outline`
  in `slices/parks.json` uses it for park outlines.
- The `GeoJSON(area)` Lua function, which `export/zindex.lua` uses for each
  search result's bounding box.
- The `LargestIntersecting(layer, min_share)` Lua function: the park, state
  or country a search result is mostly in (`export/zindex.lua`, from #90).

The rest of the fork's patches only make it faster, mostly on huge polygons
(e.g. national forests). Some of them are proposed upstream. It also logs
relations that take more than half a second to process (`RELSLOW`), to help
find the slow ones.

**go-pmtiles**
- `merge`, as `tile-join.yml` uses it to combine the layers into one tileset:
  - it accepts archives whose tiles overlap, as long as their layers don't,
    and concatenates the layers of overlapping tiles;
  - it reads and writes zstd tiles, and recompresses to the compression given
    by `--tile-compression`;
  - for zstd output, it joins the zstd frames of the tiles it combines rather
    than recompressing them, so a tile may be several frames. libzstd decodes
    them all; the website's zstd-wasm needs to be handed one frame at a time;
  - it skips layer archives that have no tiles;
  - `--no-progress` hides its progress bars in CI logs.
