-- A script to export OSM hiking route relations (route=hiking or route=foot)
-- as GeoJSONL: one line per relation, its member ways as a (Multi)LineString,
-- with name, network (iwn, nwn, rwn, lwn), distance, roundtrip, wikidata,
-- osm_id and km (the whole relation's length). hikeratlas/routes checks its curated routes against them (how many
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

	-- The whole relation's length, so hikeratlas/routes can tell a hike in
	-- a park from a section of a long trail passing through it: routes only
	-- sees the tiles around each park.
	local km = 0
	local parts = geometry.type == 'LineString' and { geometry.coordinates } or geometry.coordinates
	for _, line in ipairs(parts) do
		for i = 2, #line do
			local a, b = line[i - 1], line[i]
			local dx = (b[1] - a[1]) * math.cos(math.rad((a[2] + b[2]) / 2))
			km = km + math.sqrt(dx * dx + (b[2] - a[2]) ^ 2) * 111.32
		end
	end

	local properties = { osm_id = Id(), name = name, km = math.floor(km * 10 + 0.5) / 10 }
	for _, k in ipairs({ 'network', 'distance', 'roundtrip', 'wikidata', 'ref' }) do
		local v = Find(k)
		if v ~= '' then properties[k] = v end
	end
	file_append.write(dump_filename, json.encode({ type = "Feature", geometry = geometry, properties = properties }) .. '\n')
end
