-- A script to export campground areas (tourism=camp_site) as GeoJSONL.
--
-- The pois and buildings slices show things inside a campground, as they do
-- inside a park: e.g. the taps, toilets and buildings of Ivanhoe Lake
-- Provincial Park's campgrounds, whose park is only mapped as a node:
-- https://www.openstreetmap.org/way/851820475

local file_append = require 'file_append'
local json = require 'json'
local geometry_lib = require 'geometry'

local dump_filename = os.getenv('DUMP_FILENAME')

way_keys = {'tourism=camp_site'}

function node_function()
end

function dump()
	if Find('tourism') ~= 'camp_site' then return end

	local geojson = GeoJSON(true)
	if not geojson then return end
	local geometry = json.decode(geojson)

	local properties = {}
	for k, v in pairs({ name=Find('name'), osm_id=Id() }) do
		if v ~= '' then properties[k] = v end
	end
	local feature = { type="Feature", geometry=geometry, properties=properties }

	-- One feature per side of the antimeridian; see geometry.split_antimeridian.
	for _, part in ipairs(geometry_lib.split_antimeridian(feature.geometry)) do
		feature.geometry = part
		file_append.write(dump_filename, json.encode(feature) .. '\n')
	end
end

function way_function()
	-- Only areas: a campground mapped as a line has nothing to be inside.
	if not IsClosed() then return end

	-- If the way is only being included due to a relation, do nothing.
	while true do
		local rel = NextRelation()
		if not rel then break end
		if FindInRelation('tourism') == 'camp_site' then return end
	end

	dump()
end

function relation_scan_function()
	if Find('tourism') == 'camp_site' then
		Accept()
	end
end

function relation_function()
	dump()
end
