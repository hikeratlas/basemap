-- A script to export protected areas as GeoJSONL.
local file_append = require 'file_append'
local json = require 'json'

local dump_filename = os.getenv('DUMP_FILENAME')

way_keys = {'boundary=protected_area', 'boundary=national_park', 'leisure=nature_reserve'}

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

function dump()
	-- Require a name
	local name = Find('name')
	if name == '' then return end

	local boundary = Find('boundary')
	local leisure = Find('leisure')
	if boundary ~= 'national_park' and boundary ~= 'protected_area' and leisure ~= 'nature_reserve' then return end

	local geojson = GeoJSON(true)
	if not geojson then return end
	local geometry = json.decode(geojson)

	feature = build_feature(
		geometry,
		{
			name=name,
			leisure=leisure,
			boundary=boundary,
			wikidata=Find('wikidata'),
			osm_id=Id()
		}
	)
	file_append.write(dump_filename, json.encode(feature) .. '\n')
end

function node_function()
end

function way_function()
	-- If the way is only being included due to a relation, do nothing.
	while true do
		local rel = NextRelation()
		if not rel then break end

		local boundary = FindInRelation('boundary')
		local leisure = FindInRelation('leisure')
		if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
			return
		end
	end

	dump()
end

function relation_scan_function()
  local boundary = Find('boundary')
  local leisure = Find('leisure')

	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
		Accept()
	end
end

function relation_function()
  local id = Id()

	-- Ignore some broken relations.
	if id == '11538224' then return end
	if id == '12180623' then return end
	if id == '6495680' then return end
	if id == '6535292' then return end -- Tongass National Park

	dump()
end
