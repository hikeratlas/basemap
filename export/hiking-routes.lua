-- A script to export OSM hiking route relations (route=hiking or route=foot)
-- as GeoJSONL: one line per relation, its member ways as a (Multi)LineString,
-- with name, network (iwn, nwn, rwn, lwn), distance, roundtrip, wikidata and
-- osm_id. hikeratlas/routes checks its curated routes against them (how many
-- of these known hikes it finds); they aren't drawn on the map. A relation of
-- relations (a long-distance trail's sections) has no ways of its own, so no
-- geometry, and is left out: its sections are exported themselves.

local file_append = require 'file_append'
local json = require 'json'

local dump_filename = os.getenv('DUMP_FILENAME')

node_keys = {}
way_keys = {}

function node_function()
end

function way_function()
end

function relation_scan_function()
	local route = Find('route')
	if route == 'hiking' or route == 'foot' then
		Accept()
	end
end

function relation_function()
	local name = Find('name')
	if name == '' then return end
	local geojson = GeoJSON(false)
	if not geojson then return end
	local geometry = json.decode(geojson)
	if not geometry or not geometry.coordinates or #geometry.coordinates == 0 then return end

	local properties = { osm_id = Id(), name = name }
	for _, k in ipairs({ 'network', 'distance', 'roundtrip', 'wikidata', 'ref' }) do
		local v = Find(k)
		if v ~= '' then properties[k] = v end
	end
	file_append.write(dump_filename, json.encode({ type = "Feature", geometry = geometry, properties = properties }) .. '\n')
end
