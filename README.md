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
  in `slices/parks.json` uses it for park outlines, from z5 (where the
  biggest parks start), though the style draws them from z9: the website
  outlines a park whose panel is open at any zoom (hikeratlas/website#193).
- The `GeoJSON(area)` Lua function, which `export/zindex.lua` uses for each
  search result's bounding box.
- The `LargestIntersecting(layer, min_share)` Lua function: the park, state
  or country a search result is mostly in (`export/zindex.lua`, from #90).
- The `LayerInside(layer, shapeLayer)`, `LayerOutside(layer, shapeLayer)` and
  `LengthInside(shapeLayer)` Lua functions: `slices/ways.lua` splits a path
  that crosses a park's edge there, so only the part inside gets the park's
  treatment (#368).
- `--skip-outside-bbox ZOOM`, which a preview build's slices pass to skip OSM
  objects outside the preview's box (`tilemaker-layers.yml`).

The rest of the fork's patches only make it faster, mostly on huge polygons
(e.g. national forests). Some of them are proposed upstream. It also logs
relations that take more than half a second to process (`RELSLOW`), to help
find the slow ones.

## How the tilemaker fork is put together

`relslow-patched` is upstream's [systemed/tilemaker](https://github.com/systemed/tilemaker)
`master` at 2789651 (#929, 2026-11-03), plus merges. Every push to it builds
and publishes the image (`.github/workflows/publish-relslow-patched.yml` in
the fork, tags `:relslow-patched` and `:sha-<commit>`). `bin/docker-tilemaker`
uses `:relslow-patched`, not a commit, so merging into that branch changes
the tilemaker every following build here uses. Test a fork change with this
repo's slices before merging it (the fork's PRs show how: Nova Scotia's
layers, old image against new).

**Upstream PRs**, open upstream when applied (systemed/tilemaker numbers; #980
has since been merged there), applied as merges:
- dktue's performance PRs: #944, #946–#948, #950, #952, #954, #955, #957–#959,
  #962, #965–#968, #970–#976, #978, #983, #986, #987 (most via fork #18), and
  his 3-minute planet series, #993–#1000 on #1001 (his `perf/planet-3min`,
  fork #27), which needs Lua 5.3/5.4.
- Others' fixes: #928, #933, #941, #942, #971, #980, #981, #984, #985, and
  ports of #989 and #990 (fork #21).

**Hikeratlas patches**, as [fork PRs](https://github.com/cldellow/tilemaker/pulls?q=base%3Arelslow-patched):

| Fork PR | What |
|---|---|
| (commit) | `GeoJSON(area)` Lua function (also proposed upstream as fork #4) |
| (commit) | `RELSLOW`: log relations that take 0.5 s or more |
| (commit) | No margin around a tile's clipping box; `rect_clip` skips segments beyond one edge |
| (commit) | `mayIntersect` checks a large query box once; a polygon's outer ring indexed for holes only when it has some |
| (commit) | `outline_of` layers |
| (commit) | `LargestIntersecting(layer, minShare)` |
| #12 | zstd vector tiles and `.osm.pbf` input |
| #13 | `GeoJSON(false)` for a relation: its ways in member order |
| #16 | Index a sparse multipolygon by clusters of its outers (fork #15, for upstream) |
| #18 | `Intersects()` against large polygons with an edge index (fork #17, for upstream); upstream `master`; 24 open upstream PRs |
| #20 | The `Intersects` index built lazily; query-index boxes (fork #19) |
| #21 | Ports of upstream #989 and #990 |
| #22–#25 | Precheck, hole repair, clipping and batching speed-ups, since replaced by dktue's versions in #27 |
| #26 | `--skip-outside-bbox ZOOM` |
| #27 | dktue's planet series; Lua 5.4 and jemalloc in the image |
| #28 | `outline_of` reuses the source layer's clips of the tile |
| #29 | `LayerInside`, `LayerOutside`, `LengthInside` |

Each fork PR's description says what it changes, where it meets the other
patches, and how it was checked. To list exactly what's in the branch:

    git clone https://github.com/cldellow/tilemaker && cd tilemaker
    git remote add upstream https://github.com/systemed/tilemaker
    git fetch upstream master
    # every merge and commit on top of upstream, newest first
    git log --first-parent --oneline upstream/master..origin/relslow-patched
    # and the whole difference
    git diff upstream/master...origin/relslow-patched --stat

To take a newer upstream, merge upstream `master` into a branch off
`relslow-patched` in a PR to it (as fork #18 did), resolve conflicts with the
patches above, and compare this repo's layers on Nova Scotia, old image
against new, before merging.

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
