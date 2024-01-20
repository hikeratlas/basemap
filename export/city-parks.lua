-- A script to export city parks as GeoJSONL.

local file_append = require 'file_append'
local json = require 'json'

local dump_filename = os.getenv('DUMP_FILENAME')

way_keys = {'leisure=park', 'landuse=recreation_ground'}

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

function node_function()
end

function dump()
	-- If you don't have a name, you're probably not well-enough detailed
	-- to be included, eg https://www.openstreetmap.org/way/989294968
	-- is a broken item.
	local name = Find('name')

	if name == '' then return end

	leisure = Find('leisure')
	landuse = Find('landuse')
	if leisure ~= 'park' and landuse ~= 'recreation_ground' then return end

	local geojson = GeoJSON(true)
	if not geojson then return end
	local geometry = json.decode(geojson)

	feature = build_feature(
		geometry,
		{
			name=name,
			leisure=Find('leisure'),
			landuse=Find('landuse'),
			wikidata=Find('wikidata'),
			osm_id=Id()
		}
	)
	file_append.write(dump_filename, json.encode(feature) .. '\n')
end

function way_function()
	local landuse
	local leisure

	-- If the way is only being included due to a relation, do nothing.
	while true do
		local rel = NextRelation()
		if not rel then break end

		leisure = FindInRelation('leisure')
		landuse = FindInRelation('landuse')
		if leisure == 'park' or landuse == 'recreation_ground' then
			return
		end
	end

	dump()
end

function relation_scan_function()
  local leisure = Find('leisure')
  local landuse = Find('landuse')

	if leisure == 'park' or landuse == 'recreation_ground' then
		Accept()
	end
end

function relation_function()
	dump()
end
