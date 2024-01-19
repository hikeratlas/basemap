# basemap

This repo has tools to generate the "basemap" that Hiker Atlas uses.

> What's a basemap?
>
> Basemaps are the map canvas on which everything else is built. They show
> the roads, cities, mountains, etc. You can pay someone like Google to provide
> basemaps, but they're expensive. We'd also like to style them to emphasize
> hiking-specific things.

This repo is useful for two tasks:

1. Building a [PMTiles](https://docs.protomaps.com/pmtiles/) database with vector tiles suitable for Hiker Atlas

2. Tweaking the [MapLibre Style Spec](https://maplibre.org/maplibre-style-spec/) file

The two tasks depend on each other.

We use [`tilemaker`](https://github.com/systemed/tilemaker) to convert a [PBF extract](https://download.geofabrik.de/) from [OpenStreetMap](https://www.openstreetmap.org/) into a `.pmtiles` file. This act translates from OSM's `relation`, `way`, and `node` entries into layers of content that the styles will render.

The styles can only render the layers that we emit: so we need to ensure we emit things we care about. (And, of course, it means there's no sense in emitting things we know we don't want to render.)

Our schema and style is entirely custom. We have separate scripts for each individual layer, and the ability to merge them in a post-processing step. This makes it slightly faster to iterate on a given layer, while still being able to see the final result.

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
