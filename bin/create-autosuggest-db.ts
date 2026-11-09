#!/usr/bin/env bun
import { Database } from "bun:sqlite";
import fs from 'node:fs';

const DB_FILE = 'autosuggest.db';

// Kinds that are often mapped as several pieces with the same name, e.g. the
// three cliff ways of Barron Canyon (way/1190940447 and its neighbours), or
// the many sections of the Niagara Escarpment. Pieces chain together if each
// is within MERGE_DISTANCE_KM of the next; same-named cliffs farther apart
// (e.g. Ontario's two "Black Rock"s, 160 km apart) stay separate.
//
// Parks too: Cape Breton Highlands National Park is a relation, a second
// relation (relation/17879029) and three CanVec nature_reserve nodes, and
// showed up five times (#130). A merged park keeps its best piece's osm_id
// and label point (the relation with the qrank, not a box centre that may be
// in the sea); the box is the union, so the map fits all of it.
//
// Trails too: a trail is many ways (and maybe a hiking route relation over
// them), each with the trail's name. In one park, pieces within
// TRAIL_SAME_PARK_KM of the trail so far are one trail: the West Coast
// Trail's Beach Option is stretches of beach 5-15 km apart (#140). Outside
// parks, as other kinds, within MERGE_DISTANCE_KM. And a piece within its
// same-named hiking route relation's extent is that route, across parks:
// OSM says the Bay Circuit Trail's 58 pieces are one trail.
//
// Ranges too (#194): CanVec imported range names as natural=peak nodes with
// no ele, one every few km along the range, so "La Cloche Mountains" was four
// peaks and the Long Range Mountains 31. A peak with no ele and a range's
// name is a range label; its pieces merge across parks (some labels fall
// just outside the park) and keep the best piece's park and point (a box
// centre may be off the range). Twin Peaks and Twin Buttes have an ele each
// and stay separate.
const MERGED_KINDS = new Set(['cliff', 'park', 'trail', 'range']);
const MERGE_DISTANCE_KM: Record<string, number> = { cliff: 10, park: 1, trail: 1, range: 50 };
const TRAIL_SAME_PARK_KM = 15;
const RANGE_NAME = /\b(mountains|range|hills|ridges|highlands)\b/i;

const mergeKind = (row: any): string =>
	row.kind === 'peak' && !Number.isFinite(row.ele) && RANGE_NAME.test(String(row.name)) ? 'range' : row.kind;

type Box = { min_lon: number; min_lat: number; max_lon: number; max_lat: number };

const boxOf = (row: any): Box => row.box ?? { min_lon: row.lon, min_lat: row.lat, max_lon: row.lon, max_lat: row.lat };

// Whether two boxes are within km of each other.
function near(a: Box, b: Box, km: number): boolean {
	const lat = (a.min_lat + a.max_lat) / 2;
	const dLat = km / 111.32;
	const dLon = km / (111.32 * Math.cos((lat * Math.PI) / 180));
	return a.min_lon - dLon <= b.max_lon && b.min_lon - dLon <= a.max_lon
		&& a.min_lat - dLat <= b.max_lat && b.min_lat - dLat <= a.max_lat;
}

// Merges nearby rows of MERGED_KINDS that share a name and place into one
// row: the union of their boxes, centred in it, with the best qrank.
// A merged trail's length: its ways' lengths added up, or its hiking route
// relation's (export/zindex.lua marks those `relation`), whichever is
// longer. A relation and its ways cover the same ground, and the ways are
// only the ones in parks.
function trailKm(cluster: any[]): number {
	const sum = (rs: any[]) => rs.reduce((t, r) => t + (r.km ?? 0), 0);
	const km = Math.max(sum(cluster.filter((r) => r.relation)), sum(cluster.filter((r) => !r.relation)));
	return Math.round(km * 10) / 10;
}

export function mergePieces(rows: any[]): any[] {
	const out: any[] = [];
	const groups = new Map<string, any[]>();
	for (const row of rows) {
		const kind = mergeKind(row);
		if (!MERGED_KINDS.has(kind)) { out.push(row); continue; }
		// Case aside: "Acadian Trail" and "Acadian trail" are one trail.
		// Ranges and trails can merge across parks (see above).
		const key = JSON.stringify([kind, String(row.name).toLowerCase(), kind === 'range' || kind === 'trail' ? null : row.park, row.state, row.country]);
		if (!groups.has(key)) groups.set(key, []);
		groups.get(key)!.push(row);
	}
	for (const members of groups.values()) {
		// Single-linkage clusters: keep absorbing rows near the cluster's box.
		// Route relations first, so their pieces gather around them.
		const remaining = [...members].sort((x, y) => (y.relation ? 1 : 0) - (x.relation ? 1 : 0));
		while (remaining.length) {
			const cluster = [remaining.shift()!];
			let box = { ...boxOf(cluster[0]) };
			const kind = mergeKind(cluster[0]);
			// A trail's pieces: in the cluster's parks (or outside parks, if
			// it is), or within one of its route relations' extent.
			const parks = new Set<string | null>([cluster[0].park ?? null]);
			const routes: Box[] = cluster[0].relation ? [boxOf(cluster[0])] : [];
			const joins = (r: any) => {
				if (kind !== 'trail') return near(box, boxOf(r), MERGE_DISTANCE_KM[kind]);
				if (routes.some((rb) => near(rb, boxOf(r), 0))) return true;
				const park = r.park ?? null;
				if (!parks.has(park)) return false;
				return near(box, boxOf(r), park === null ? MERGE_DISTANCE_KM.trail : TRAIL_SAME_PARK_KM);
			};
			for (let grew = true; grew; ) {
				grew = false;
				for (let i = remaining.length - 1; i >= 0; i--) {
					if (joins(remaining[i])) {
						const r = remaining.splice(i, 1)[0];
						const b = boxOf(r);
						box = {
							min_lon: Math.min(box.min_lon, b.min_lon), min_lat: Math.min(box.min_lat, b.min_lat),
							max_lon: Math.max(box.max_lon, b.max_lon), max_lat: Math.max(box.max_lat, b.max_lat),
						};
						cluster.push(r);
						parks.add(r.park ?? null);
						if (r.relation) routes.push(b);
						grew = true;
					}
				}
			}
			if (cluster.length === 1) { out.push(cluster[0]); continue; }
			// The best piece: highest qrank, then (for a range) one in a park,
			// then an area over a point, then the biggest area.
			const area = (r: any) => r.box ? (r.box.max_lon - r.box.min_lon) * (r.box.max_lat - r.box.min_lat) : -1;
			const best = cluster.reduce((a, b) =>
				((b.qrank ?? 0) - (a.qrank ?? 0) || (b.park ? 1 : 0) - (a.park ? 1 : 0) || area(b) - area(a)) > 0 ? b : a);
			if (mergeKind(best) === 'range') {
				out.push({ ...best, wikidata: best.wikidata ?? cluster.find((r) => r.wikidata)?.wikidata, box });
				continue;
			}
			if (best.kind === 'park' || best.kind === 'trail') {
				out.push({
					...best,
					wikidata: best.wikidata ?? cluster.find((r) => r.wikidata)?.wikidata,
					box,
					...(best.kind === 'trail' ? { km: trailKm(cluster) || null } : {}),
				});
				continue;
			}
			out.push({
				...cluster[0],
				qrank: Math.max(...cluster.map((r) => r.qrank ?? 0)),
				wikidata: cluster.find((r) => r.wikidata)?.wikidata,
				lon: (box.min_lon + box.max_lon) / 2,
				lat: (box.min_lat + box.max_lat) / 2,
				box,
			});
		}
	}
	return out;
}

// As export/zindex.lua's sanitize_park: a row's park is its park's name
// shortened this way.
function sanitizePark(x: string): string {
	return x.replaceAll('National Park', 'NP').replaceAll('State Park', 'SP')
		.replaceAll('Provincial Park', 'PP').replaceAll('National Forest', 'NF');
}

// Of a park's QRank, the share a row in it with no QRank of its own gets
// (#142): only 590 of 145,522 trails have one, so they all tied at 1 and a
// search for "Tonquin" listed five pieces of Oregon's Tonquin Trail before
// Jasper's Tonquin Valley trail. Jasper NP's QRank is 104,358, so its
// unranked trails get up to ~1,000: above an unranked trail elsewhere, below
// the park itself.
const PARK_SHARE = 0.01;
// A trail's share scales with its length (its box's diagonal) up to this,
// so a park's long trails rank above its short spurs.
const TRAIL_FULL_KM = 5;

function diagKm(box: Box | undefined): number {
	if (!box) return 0;
	const lat = ((box.min_lat + box.max_lat) / 2) * Math.PI / 180;
	const dx = (box.max_lon - box.min_lon) * 111.32 * Math.cos(lat);
	const dy = (box.max_lat - box.min_lat) * 111.32;
	return Math.hypot(dx, dy);
}

// Rows with no QRank of their own (1) take a share of their park's.
export function rankByPark(rows: any[]): any[] {
	const parkRank = new Map<string, number>();
	for (const r of rows) {
		if (r.kind !== 'park' || !(r.qrank > 1)) continue;
		const key = JSON.stringify([sanitizePark(r.name), r.state]);
		parkRank.set(key, Math.max(parkRank.get(key) ?? 0, r.qrank));
	}
	for (const r of rows) {
		if (r.kind === 'park' || (r.qrank ?? 0) > 1 || !r.park) continue;
		const pq = parkRank.get(JSON.stringify([r.park, r.state]));
		if (!pq) continue;
		const w = r.kind === 'trail' ? Math.min(1, Math.max(0.2, diagKm(r.box) / TRAIL_FULL_KM)) : 0.5;
		r.qrank = Math.max(r.qrank ?? 1, Math.round(pq * PARK_SHARE * w));
	}
	return rows;
}

async function main() {
	try {
		fs.unlinkSync(DB_FILE);
	} catch (e) {
		// ignored
	}
	const db = new Database(DB_FILE);

	db.query(`CREATE VIRTUAL TABLE fts USING fts5(name, qrank)`).run();
	db.query(`CREATE VIRTUAL TABLE fts_popular USING fts5(name, qrank)`).run();
	db.query(`CREATE TABLE items(
qrank INTEGER NOT NULL,
wikidata TEXT,
osm_id TEXT NOT NULL,
kind TEXT NOT NULL,
park TEXT,
country TEXT,
state TEXT,
name TEXT NOT NULL,
lon NUMERIC NOT NULL,
lat NUMERIC NOT NULL,
min_lon NUMERIC,
min_lat NUMERIC,
max_lon NUMERIC,
max_lat NUMERIC,
ele INTEGER,
km NUMERIC,
area INTEGER
)`).run();


	const rows = rankByPark(mergePieces((await Bun.file('zindex.geojsonl').text()).split('\n').filter(x => x).map(x => JSON.parse(x))));

	db.query('PRAGMA synchronous = OFF').run();

	const ins = db.query(`INSERT INTO items (qrank, wikidata, osm_id, kind, park, country, state, name, lon, lat, min_lon, min_lat, max_lon, max_lat, ele, km, area) VALUES ($qrank, $wikidata, $osm_id, $kind, $park, $country, $state, $name, $lon, $lat, $min_lon, $min_lat, $max_lon, $max_lat, $ele, $km, $area)`);
	for (const row of rows) {
		let { wikidata, park, qrank, country, lon, lat, kind, state, osm_id, name, box, ele, km, area } = row;
		ins.run({
			$qrank: qrank,
			$wikidata: wikidata,
			$osm_id: osm_id,
			$kind: kind,
			$park: park,
			$country: country,
			$state: state,
			$name: name,
			$lon: lon,
			$lat: lat,
			$min_lon: box?.min_lon || null,
			$min_lat: box?.min_lat || null,
			$max_lon: box?.max_lon || null,
			$max_lat: box?.max_lat || null,
			// For the search result's second line (website#44).
			$ele: Number.isFinite(ele) ? ele : null,
			$km: Number.isFinite(km) ? km : null,
			$area: Number.isFinite(area) ? area : null,
		});
	}

	db.query(`INSERT INTO fts(rowid, name, qrank) SELECT rowid, name, qrank FROM items`).run();
	db.query(`INSERT INTO fts_popular(rowid, name, qrank) SELECT rowid, name, qrank FROM items WHERE qrank > 1`).run();
	db.close();
}

if (import.meta.main) main();
