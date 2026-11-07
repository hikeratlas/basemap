# Notes for Claude

Hiker Atlas spans several repos: hikeratlas/basemap (this one: tiles, style,
search DB, builds), hikeratlas/routes (curated hikes, Rust), hikeratlas/website
(Remix + MapLibre), hikeratlas/nl-dem (Newfoundland's DEM as tiles),
hikeratlas/sprites and hikeratlas/lake-centrelines. These notes are traps hit
before; they apply across the repos.

## Ask first

- **Don't commit images** (screenshots, comparison renders) without asking,
  not even on a side branch. The GitHub API can't attach images to comments;
  hand the files to the user to drag in.

## Reading remote PMTiles efficiently

- **Never fetch tiles one call at a time** through a reader that re-reads the
  header and directories per tile (the Python `pmtiles` reader's `get` does
  this: ~4 requests per tile).
- For an area, use `pmtiles extract --bbox=W,S,E,N URL out.pmtiles`
  ([go-pmtiles](https://github.com/protomaps/go-pmtiles), one binary). It reads
  the directories once and fetches tile data in a few merged range requests.
- In code: read the header and directories once, look up the wanted tiles,
  sort them by offset (tile ids follow a Hilbert curve, so nearby tiles are
  nearby in the file), and coalesce neighbouring ranges into a few large
  requests.
- **Check for an existing reader first**: hikeratlas/routes has
  `src/pmtiles.rs` (local file or URL, with a tile cache); the website uses
  pmtiles.js (`PMTILES_JS` in `app/components/nlDem.ts`).

## Testing in the cloud sandbox

- `public.hikeratlas.com` (R2) only allows `https://www.hikeratlas.com` by
  CORS. A local page (dev server, test harness) must proxy it, e.g. with a
  Playwright route that adds `access-control-allow-origin`.
- Playwright through the sandbox proxy sends localhost through it too
  (405s). Serve test pages with `context.route` on a made-up host rather
  than a localhost server.
- hikeratlas/routes' HTTP client (ureq) doesn't trust the sandbox proxy's CA:
  pre-fill its `--dem-cache` with curl, and pass local files (e.g. a
  `pmtiles extract` of nl-dem) where it reads URLs.
- routes' `fixtures/run.sh` checks each word of `ROUTES_ARGS` against the
  binary's usage and drops the rest, including option values: run the binary
  directly for options that take one.
- The frozen fixtures snapshot (`fixtures/latest.json`, ~230 MB) is the way to
  get tiles while a north-america build is rewriting the layers.

## Builds and data flow

- After merging into hikeratlas/routes, bump `ROUTES_REF` in
  `.github/workflows/routes.yml` here; builds use only the pinned commit.
- `build-area.yml` modes: `full`; `no-exports` (reuses the previous search DB
  and exports; `bin/search-add-hikes.py` re-runs on that reused DB, so its
  changes must be idempotent and reversible); `style-only` (publishes the style
  only, both `north-america.style.json` and the default `style.json`).
- Any non-Markdown PR here runs a PR build of `build-area.yml`.
- The style points hillshade at Mapterhorn; the website reroutes those tiles
  (and contours, and elevation profiles) through nl-dem over Newfoundland.
  Keep the style generic: site-only behaviour lives in the website.

## Git

- Work on `claude/*` branches; merge only with the user's go-ahead (often
  "merge when green").
- Force pushes and branch deletion are blocked in the sandbox: use a new
  branch name instead, and ask the user to delete leftovers.
