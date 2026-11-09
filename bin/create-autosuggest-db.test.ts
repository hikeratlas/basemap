import { expect, test } from 'bun:test';
import { mergePieces } from './create-autosuggest-db.ts';

// A trail piece: a box around (lon, lat), ~0.5 km across.
const piece = (name: string, park: string | null, lon: number, lat: number, extra: object = {}) => ({
	kind: 'trail', name, park, state: 'X', country: 'Y', lon, lat, km: 1,
	box: { min_lon: lon - 0.003, min_lat: lat - 0.002, max_lon: lon + 0.003, max_lat: lat + 0.002 }, ...extra,
});
const names = (rows: any[]) => rows.map((r) => r.name).sort();

test('a trail\'s pieces in one park merge at any distance (#140: West Coast Trail Beach Option)', () => {
	const p = 'Pacific Rim NP Reserve';
	const out = mergePieces([piece('Beach Option', p, -124.78, 48.63), piece('Beach Option', p, -124.49, 48.55), piece('Beach Option', p, -125.11, 48.79)]);
	expect(out.length).toBe(1);
	expect(out[0].km).toBe(3);
});

test('a trail\'s nearby pieces merge across parks (#140: Tonquin Trail)', () => {
	const out = mergePieces([piece('Tonquin Trail', 'Graham Oaks Nature Park', -122.797, 45.299), piece('Tonquin Trail', null, -122.798, 45.309),
		piece('Tonquin Trail', null, -122.835, 45.35), piece('Tonquin Trail', 'Hedges Creek Greenway', -122.78, 45.364)]);
	expect(out.length).toBe(1);
});

test('generic names merge as before: not across parks', () => {
	const out = mergePieces([piece('Blue Trail', 'Park A', -74.0, 41.0), piece('Blue Trail', 'Park B', -74.01, 41.0)]);
	expect(names(out)).toEqual(['Blue Trail', 'Blue Trail']);
});

test('generic names merge as before: not far apart in one park', () => {
	const out = mergePieces([piece('Nature Trail', 'Big Park', -74.0, 41.0), piece('Nature Trail', 'Big Park', -74.2, 41.0)]);
	expect(out.length).toBe(2);
});
