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

## Build all layers

This builds each layer, emitting `buildings.pmtiles`, `water.pmtiles`, `ways.pmtiles`, etc.

This is useful the first time you run the repo, or when switching to a new area of focus.

```bash
./build-all rockies.osm.pbf
```

## Build a single layer

You can also focus on a single layer at a time:

```bash
LAYER=ways ./create-tiles rockies.pbf
```

## View the results

The repo includes a small webserver written in [Bun](https://bun.sh/).

Start it like so:

```bash
bun index.ts
```

Then navigate to http://localhost:8081/ - you should see your map.

The server will stitch together any styles in `/styles/`. If you edit any
of them, the page will reload.

The server also serves your pmtiles archives, so you can use [the PMTiles Viewer](https://protomaps.github.io/PMTiles/?url=http%3A%2F%2Flocalhost%3A8081%2Fparks.pmtiles#map=8.9/35.528/-83.2195)
to look at raw contents, ignoring styles.
## Licensing and Attributions

This repository is licensed under Apache 2.0. The artifacts it produces depend on things that may be licensed under other licenses. Your usage of the code in this repository is also subject to those licenses.

- The data in the basemap is copyright OpenStreetMap contributors, and licensed under ODbL.
- We use [Tailwind CSS](https://tailwindcss.com/)'s color palette, licensed under MIT.
- We use [Wikidata QRank](https://qrank.wmcloud.org/) to prioritize which features to show, licensed under CC0.
- We use [Mapzen's Joerd terrain dataset](https://github.com/tilezen/joerd/blob/master/docs/attribution.md) for hillshading.
	- See Mapzen's page for all copyrights for that data.
	- We use [Protomap's hosted version of the terrain dataset](https://protomaps.com/blog/serverless-maps-now-open-source), which I believe is not guaranteed to be stable.

# Miscellaneous resources

- https://osmlanduse.org/ helps identify the landuse OSM object in a given range. (I found OSM's Query Features action often omitted landcover polygons.)
