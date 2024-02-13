-- A script to export hiking trails as GeoJSONL.
-- The exported file is intended to be consumed by the hiking route
-- inferencer at https://github.com/hikeratlas/routes
local file_append = require 'file_append'
local json = require 'json'

local dump_filename = os.getenv('DUMP_FILENAME')

node_keys = {
	'natural=peak',
	'amenity=parking'
}
way_keys = {
	'highway=path',
	'highway=footway',
	'highway=motorway',
	'highway=trunk',
	'highway=primary',
	'highway=secondary',
	'highway=tertiary',
	'highway=unclassified',
	'highway=residential',
	'highway=service',
	'route=hiking',
	'amenity=parking',
--	'water=lake',
--	'natural=water'
}

function build_feature(geometry, properties)
	sanitized_properties = {}

	for k, v in pairs(properties) do
		if v ~= "" then
			sanitized_properties[k] = v
		end
	end

	return {
		type="Feature",
		geometry=geometry,
		properties=sanitized_properties
	}
end

function dump(kind)
	local is_way_or_relation = kind == 'way' or kind == 'relation'
	local is_area = false
	if is_way_or_relation then
		if Find('natural') == 'water' or Find('amenity') == 'parking' then
			is_area = true
		end
	end

	local name_required = true
	if Find('amenity') == 'parking' then name_required = false end

	local name = Find('name')
	if name_required and name == '' then return end

	print(name)

	local geojson = GeoJSON(is_area)
	if not geojson then return end
	local geometry = json.decode(geojson)

	feature = build_feature(
		geometry,
		{
			name=name,
			access=Find('access'),
			ascent=Find('ascent'),
			amenity=Find('amenity'),
			bicycle=Find('bicycle'),
			descent=Find('descent'),
			description=Find('description'),
			distance=Find('distance'),
			fee=Find('fee'),
			highway=Find('highway'),
			historic=Find('historic'),
			kind=kind,
			natural=Find('natural'),
			network=Find('network'),
			osm_id=Id(),
			operator=Find('operator'),
			ref=Find('ref'),
			roundtrip=Find('roundtrip'),
			route=Find('route'),
			sac_scale=Find('sac_scale'),
			segregated=Find('segregated'),
			signed_direction=Find('signed_direction'),
			surface=Find('surface'),
			trail_visibility=Find('trail_visibility'),
			type=Find('type'),
			water=Find('water'),
			website=Find('website'),
			wikidata=Find('wikidata'),
			wikipedia=Find('wikipedia'),
		}
	)
	file_append.write(dump_filename, json.encode(feature) .. '\n')
end

function node_function()
	dump('node')
end

function way_function()
	dump('way')
end

function relation_scan_function()
  local route = Find('route')

	if route == 'hiking' then
		Accept()
	end
end

function relation_function()
	local route = Find('route')
	if route == 'hiking' then dump('relation') end
end
