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
- routes' ureq doesn't trust the proxy's CA: pre-fill `--dem-cache` with curl,
  and pass local files for URLs.
- routes' `fixtures/run.sh` drops option values from `ROUTES_ARGS`; run the
  binary directly for those.
- While a build rewrites the layers, get tiles from the fixtures snapshot
  (`fixtures/latest.json`).
