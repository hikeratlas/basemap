-- A script to export hiking trails as GeoJSONL.
-- The exported file is intended to be consumed by the hiking route
-- inferencer at https://github.com/hikeratlas/routes
local file_append = require 'file_append'
local json = require 'json'

local dump_filename = os.getenv('DUMP_FILENAME')

node_keys = {'natural=peak', 'amenity=parking'}
way_keys = {'highway=path', 'highway=footway', 'route=hiking', 'amenity=parking', 'water=lake', 'natural=water'}

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

function dump(is_way_or_relation)
	is_area = false
	if is_way_or_relation then
		if Find('natural') == 'water' or Find('amenity') == 'parking' then
			is_area = true
		end
	end
	-- Require a name for now; eventually we'll want to loosen this, I think.
	local name = Find('name')
	if name == '' then return end

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
	dump(false)
end

function way_function()
	dump(true)
end

function relation_scan_function()
  local route = Find('route')

	if route == 'hiking' then
		Accept()
	end
end

function relation_function()
	local route = Find('route')
	if route == 'hiking' then dump(true) end
end
