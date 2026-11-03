#!/usr/bin/env bun
import { Database } from "bun:sqlite";
import fs from 'node:fs';

const DB_FILE = 'autosuggest.db';

// Kinds that are often mapped as several pieces with the same name, e.g. the
// three cliff ways of Barron Canyon (way/1190940447 and its neighbours).
const MERGED_KINDS = new Set(['cliff']);
const MERGE_DISTANCE_KM = 2;

type Box = { min_lon: number; min_lat: number; max_lon: number; max_lat: number };

const boxOf = (row: any): Box => row.box ?? { min_lon: row.lon, min_lat: row.lat, max_lon: row.lon, max_lat: row.lat };

// Whether two boxes are within MERGE_DISTANCE_KM of each other.
function near(a: Box, b: Box): boolean {
	const lat = (a.min_lat + a.max_lat) / 2;
	const dLat = MERGE_DISTANCE_KM / 111.32;
	const dLon = MERGE_DISTANCE_KM / (111.32 * Math.cos((lat * Math.PI) / 180));
	return a.min_lon - dLon <= b.max_lon && b.min_lon - dLon <= a.max_lon
		&& a.min_lat - dLat <= b.max_lat && b.min_lat - dLat <= a.max_lat;
}

// Merges nearby rows of MERGED_KINDS that share a name and place into one
// row: the union of their boxes, centred in it, with the best qrank.
export function mergePieces(rows: any[]): any[] {
	const out: any[] = [];
	const groups = new Map<string, any[]>();
	for (const row of rows) {
		if (!MERGED_KINDS.has(row.kind)) { out.push(row); continue; }
		const key = JSON.stringify([row.kind, row.name, row.park, row.state, row.country]);
		if (!groups.has(key)) groups.set(key, []);
		groups.get(key)!.push(row);
	}
	for (const members of groups.values()) {
		// Single-linkage clusters: keep absorbing rows near the cluster's box.
		const remaining = [...members];
		while (remaining.length) {
			const cluster = [remaining.shift()!];
			let box = { ...boxOf(cluster[0]) };
			for (let grew = true; grew; ) {
				grew = false;
				for (let i = remaining.length - 1; i >= 0; i--) {
					if (near(box, boxOf(remaining[i]))) {
						const r = remaining.splice(i, 1)[0];
						const b = boxOf(r);
						box = {
							min_lon: Math.min(box.min_lon, b.min_lon), min_lat: Math.min(box.min_lat, b.min_lat),
							max_lon: Math.max(box.max_lon, b.max_lon), max_lat: Math.max(box.max_lat, b.max_lat),
						};
						cluster.push(r);
						grew = true;
					}
				}
			}
			if (cluster.length === 1) { out.push(cluster[0]); continue; }
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
max_lat NUMERIC
)`).run();


	const rows = mergePieces((await Bun.file('zindex.geojsonl').text()).split('\n').filter(x => x).map(x => JSON.parse(x)));

	db.query('PRAGMA synchronous = OFF').run();

	const ins = db.query(`INSERT INTO items (qrank, wikidata, osm_id, kind, park, country, state, name, lon, lat, min_lon, min_lat, max_lon, max_lat) VALUES ($qrank, $wikidata, $osm_id, $kind, $park, $country, $state, $name, $lon, $lat, $min_lon, $min_lat, $max_lon, $max_lat)`);
	for (const row of rows) {
		let { wikidata, park, qrank, country, lon, lat, kind, state, osm_id, name, box } = row;
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
		});
	}

	db.query(`INSERT INTO fts(rowid, name, qrank) SELECT rowid, name, qrank FROM items`).run();
	db.query(`INSERT INTO fts_popular(rowid, name, qrank) SELECT rowid, name, qrank FROM items WHERE qrank > 1`).run();
	db.close();
}

if (import.meta.main) main();
