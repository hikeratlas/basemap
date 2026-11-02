// Works out what a PR build should preview, from a "Preview:" line in the PR
// description (or the build's `preview` input):
//
//   Preview: https://www.openstreetmap.org/node/3046004352
//   Preview: way/123456 radius=25km
//   Preview: ontario
//
// For an OSM node, way or relation, it fetches the element from the OSM API,
// takes its bounding box, widens it to at least `radius` (default 10 km) around
// its centre, and picks the smallest area in areas.json whose Geofabrik extract
// contains that box. The build then uses that area's PBF but only that box.
//
//   bun bin/preview-target.ts    (reads PREVIEW and DEFAULT_AREA from the env)
//
// Writes area=, bbox= (empty unless an element was given), view= (a map hash,
// zoom/lat/lon, empty if unknown) and target= to $GITHUB_OUTPUT if set, and
// always to stdout.

import { appendFileSync } from 'node:fs';

const DEFAULT_RADIUS_KM = 10;
const USER_AGENT = 'hikeratlas-basemap-ci (https://github.com/hikeratlas/basemap)';

type Box = { minLon: number; minLat: number; maxLon: number; maxLat: number };
type Area = { geofabrik: string; bbox: string };

const areas: Record<string, Area> = await Bun.file(new URL('../areas.json', import.meta.url)).json();

function fail(msg: string): never {
  console.log(`::error::${msg}`);
  process.exit(1);
}

function parseBox(s: string): Box {
  const [minLon, minLat, maxLon, maxLat] = s.split(',').map(Number);
  return { minLon, minLat, maxLon, maxLat };
}

const boxString = (b: Box) => [b.minLon, b.minLat, b.maxLon, b.maxLat].map((n) => n.toFixed(5)).join(',');

// A map hash (zoom/lat/lon) that fits the box in a ~1200x800 viewport of
// 512 px tiles, as MapLibre uses.
function view(b: Box): string {
  const mercY = (lat: number) => Math.log(Math.tan(Math.PI / 4 + (lat * Math.PI) / 360));
  const zx = Math.log2((1200 * 360) / (512 * Math.max(b.maxLon - b.minLon, 1e-6)));
  const zy = Math.log2((800 * 2 * Math.PI) / (512 * Math.max(mercY(b.maxLat) - mercY(b.minLat), 1e-9)));
  const zoom = Math.min(14, Math.max(2, Math.min(zx, zy)));
  const lat = (b.minLat + b.maxLat) / 2;
  const lon = (b.minLon + b.maxLon) / 2;
  return `${zoom.toFixed(1)}/${lat.toFixed(5)}/${lon.toFixed(5)}`;
}

async function fetchOk(url: string): Promise<Response> {
  const res = await fetch(url, { headers: { 'user-agent': USER_AGENT } });
  if (!res.ok) fail(`${url}: ${res.status} ${res.statusText}`);
  return res;
}

// The bounding box of an OSM element's nodes (for a relation: its member
// nodes and the nodes of its member ways).
async function elementBox(type: string, id: string): Promise<Box> {
  const url = `https://api.openstreetmap.org/api/0.6/${type}/${id}${type === 'node' ? '' : '/full'}.json`;
  const { elements } = await (await fetchOk(url)).json();
  const nodes = elements.filter((e: any) => e.type === 'node' && e.lat !== undefined);
  if (!nodes.length) fail(`${type}/${id} has no nodes with coordinates`);
  const lats = nodes.map((n: any) => n.lat), lons = nodes.map((n: any) => n.lon);
  return { minLon: Math.min(...lons), minLat: Math.min(...lats), maxLon: Math.max(...lons), maxLat: Math.max(...lats) };
}

// Widens the box so it reaches at least radiusKm from its centre in each direction.
function widen(b: Box, radiusKm: number): Box {
  const lat = (b.minLat + b.maxLat) / 2, lon = (b.minLon + b.maxLon) / 2;
  const dLat = radiusKm / 111.32;
  const dLon = radiusKm / (111.32 * Math.cos((lat * Math.PI) / 180));
  return {
    minLon: Math.min(b.minLon, lon - dLon), minLat: Math.max(-85, Math.min(b.minLat, lat - dLat)),
    maxLon: Math.max(b.maxLon, lon + dLon), maxLat: Math.min(85, Math.max(b.maxLat, lat + dLat)),
  };
}

// Geofabrik's .poly boundary of an extract: outer rings, and holes (sections
// whose names start with "!").
type Ring = [number, number][];
async function boundary(geofabrik: string): Promise<{ outer: Ring[]; holes: Ring[] }> {
  const text = await (await fetchOk(`https://download.geofabrik.de/${geofabrik}.poly`)).text();
  const outer: Ring[] = [], holes: Ring[] = [];
  let ring: Ring | null = null, hole = false;
  for (const line of text.split('\n').slice(1).map((l) => l.trim()).filter(Boolean)) {
    if (line === 'END') {
      if (ring) (hole ? holes : outer).push(ring);
      ring = null;
    } else if (!ring) {
      // a section name, e.g. "1"
      ring = [];
      hole = line.startsWith('!');
    } else if (ring) {
      const [x, y] = line.split(/\s+/).map(Number);
      ring.push([x, y]);
    }
  }
  return { outer, holes };
}

function inRing(x: number, y: number, ring: Ring): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i], [xj, yj] = ring[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

// Whether the box's corners, edge midpoints and centre are all inside the extract.
async function contains(area: Area, b: Box): Promise<boolean> {
  const a = parseBox(area.bbox);
  if (b.minLon < a.minLon || b.minLat < a.minLat || b.maxLon > a.maxLon || b.maxLat > a.maxLat) return false;
  const { outer, holes } = await boundary(area.geofabrik);
  const midLon = (b.minLon + b.maxLon) / 2, midLat = (b.minLat + b.maxLat) / 2;
  const points = [b.minLon, midLon, b.maxLon].flatMap((x) => [b.minLat, midLat, b.maxLat].map((y) => [x, y]));
  return points.every(([x, y]) => outer.some((r) => inRing(x, y, r)) && !holes.some((r) => inRing(x, y, r)));
}

const boxArea = (s: string) => {
  const b = parseBox(s);
  return (b.maxLon - b.minLon) * (b.maxLat - b.minLat);
};

async function main() {
  const text = process.env.PREVIEW ?? '';
  const defaultArea = process.env.DEFAULT_AREA || 'nova-scotia';
  const m = /^\s*(?:preview:\s*)?(\S.*?)\s*$/im.exec(
    // A PR description: just the "Preview:" line. A build input: the whole thing.
    /^\s*preview:/im.test(text) ? /^\s*preview:.*$/im.exec(text)![0] : text,
  );
  const spec = m ? m[1] : '';

  let area = defaultArea, bbox = '', target = defaultArea;
  let v = areas[defaultArea] ? view(parseBox(areas[defaultArea].bbox)) : '';

  if (spec) {
    const radius = Number((/\bradius=(\d+(?:\.\d+)?)\s*km\b/i.exec(spec) || [])[1] || DEFAULT_RADIUS_KM);
    const el = /(?:openstreetmap\.org\/)?\b(node|way|relation)\/(\d+)\b/i.exec(spec);
    const name = spec.split(/\s+/)[0];
    if (el) {
      const [type, id] = [el[1].toLowerCase(), el[2]];
      const box = widen(await elementBox(type, id), radius);
      const candidates = Object.entries(areas).sort(([, a], [, b]) => boxArea(a.bbox) - boxArea(b.bbox));
      let found: string | null = null;
      for (const [key, a] of candidates) {
        if (await contains(a, box)) { found = key; break; }
      }
      if (!found) fail(`${type}/${id} (with a ${radius} km radius) isn't inside any area in areas.json`);
      area = found;
      bbox = boxString(box);
      v = view(box);
      target = `${type}/${id} (${radius} km radius) from ${area}`;
    } else if (areas[name]) {
      area = name;
      v = view(parseBox(areas[name].bbox));
      target = area;
    } else {
      fail(`Don't know how to preview "${spec}": use an OSM node/way/relation (or its openstreetmap.org URL), or one of: ${Object.keys(areas).join(', ')}`);
    }
  }

  const out = `area=${area}\nbbox=${bbox}\nview=${v}\ntarget=${target}\n`;
  process.stdout.write(out);
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, out);
}

await main();
