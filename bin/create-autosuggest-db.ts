#!/usr/bin/env bun
import { Database } from "bun:sqlite";
import fs from 'node:fs';

const DB_FILE = 'autosuggest.db';

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
lat NUMERIC NOT NULL
)`).run();


	const rows = (await Bun.file('zindex.geojsonl').text()).split('\n').filter(x => x).map(x => JSON.parse(x));

	db.query('PRAGMA synchronous = OFF').run();

	const ins = db.query(`INSERT INTO items (qrank, wikidata, osm_id, kind, park, country, state, name, lon, lat) VALUES ($qrank, $wikidata, $osm_id, $kind, $park, $country, $state, $name, $lon, $lat)`);
	for (const row of rows) {
		let { wikidata, park, qrank, country, lon, lat, kind, state, osm_id, name } = row;
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
			$lat: lat
		});
	}

	db.query(`INSERT INTO fts(rowid, name, qrank) SELECT rowid, name, qrank FROM items`).run();
	db.query(`INSERT INTO fts_popular(rowid, name, qrank) SELECT rowid, name, qrank FROM items WHERE qrank > 1`).run();
	db.close();
}

main();
