# Notes for Claude

Traps hit before, across the Hiker Atlas repos (basemap, routes, website, nl-dem).

- Ask before committing images (screenshots, renders), even on a side branch.
- Read remote PMTiles with `pmtiles extract --bbox=W,S,E,N URL out.pmtiles`
  (go-pmtiles), or read directories once and fetch tiles in coalesced ranges.
  Never one call per tile: the Python reader's `get` re-reads the header and
  directories each time. Reuse existing readers: routes' `src/pmtiles.rs`,
  the website's pmtiles.js.
- After a routes merge, bump `ROUTES_REF` in `.github/workflows/routes.yml`.
- `no-exports` builds re-run `bin/search-add-hikes.py` on the previous search
  DB: keep its changes idempotent and reversible.
- Keep the style generic; site-only behaviour belongs in the website.

## Cloud sandbox testing

- `public.hikeratlas.com` allows only `https://www.hikeratlas.com` by CORS:
  proxy it (e.g. a Playwright route adding `access-control-allow-origin`).
- Playwright sends localhost through the proxy (405s): serve test pages with
  `context.route` on a made-up host.
- routes' `fixtures/run.sh` drops option values from `ROUTES_ARGS`; run the
  binary directly for those.
- While a build rewrites the layers, get tiles from the fixtures snapshot
  (`fixtures/latest.json`).

## Posting images in GitHub comments

The sandbox's AWS key is a placeholder, so put images in R2 with a workflow:

- Make an orphan branch (`git switch --orphan`; empty index, so no other
  push workflow comes along) holding only `images/` and a one-off
  `.github/workflows/upload.yml`: on push to that branch, with the R2 env of
  `lake-centerlines.yml`, run `aws s3 cp --recursive --content-type image/png
  images/ s3://hikes-public/claude-images/<topic>/`. Never open a PR from it.
- Link `https://public.hikeratlas.com/claude-images/<topic>/<file>.png`.
- The sandbox can't delete branches: ask the user to delete it afterwards, or
  full clones keep the images. Still ask before committing images (above).
