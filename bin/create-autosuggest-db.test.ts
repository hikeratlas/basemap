import { expect, test } from 'bun:test';
import { mergePieces } from './create-autosuggest-db.ts';

// A trail piece: a box around (lon, lat), ~0.5 km across.
const piece = (name: string, park: string | null, lon: number, lat: number, extra: object = {}) => ({
	kind: 'trail', name, park, state: 'X', country: 'Y', lon, lat, km: 1,
	box: { min_lon: lon - 0.003, min_lat: lat - 0.002, max_lon: lon + 0.003, max_lat: lat + 0.002 }, ...extra,
});

test('a trail\'s pieces in one park merge within 15 km of each other (#140: Beach Option)', () => {
	const p = 'Pacific Rim NP Reserve';
	// ~8 km apart, then ~12 km on.
	const out = mergePieces([piece('Beach Option', p, -124.70, 48.60), piece('Beach Option', p, -124.60, 48.60), piece('Beach Option', p, -124.45, 48.60)]);
	expect(out.length).toBe(1);
	expect(out[0].km).toBe(3);
});

test('but not farther apart, even in one park (a big national forest\'s two Bear Creek Trails)', () => {
	const out = mergePieces([piece('Bear Creek Trail', 'Big NF', -107.0, 38.0), piece('Bear Creek Trail', 'Big NF', -107.4, 38.0)]);
	expect(out.length).toBe(2);
});

test('pieces in different parks stay apart without a route relation (#140: Tonquin Trail)', () => {
	const out = mergePieces([piece('Tonquin Trail', 'Graham Oaks Nature Park', -122.797, 45.299), piece('Tonquin Trail', 'Hedges Creek Greenway', -122.798, 45.309)]);
	expect(out.length).toBe(2);
});

test('pieces within a same-named route relation\'s extent join it, across parks', () => {
	const route = { ...piece('Bay Circuit Trail', 'Park A', -71.2, 42.5), relation: true, km: 370,
		box: { min_lon: -71.6, min_lat: 42.1, max_lon: -70.8, max_lat: 42.9 } };
	const out = mergePieces([route, piece('Bay Circuit Trail', 'Park B', -71.0, 42.3), piece('Bay Circuit Trail', null, -71.5, 42.8)]);
	expect(out.length).toBe(1);
});

test('outside parks, pieces merge within 1 km as before', () => {
	const out = mergePieces([piece('Rail Trail', null, -74.0, 41.0), piece('Rail Trail', null, -74.05, 41.0)]);
	expect(out.length).toBe(2);
});
