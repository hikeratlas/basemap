-- A script to export named trails, and the destinations and parking near
-- them, as GeoJSONL, for bin/trail-areas.py: trail networks outside parks
-- (e.g. Newfoundland's Skerwink Trail) become areas that hikeratlas/routes
-- curates, as it does parks.
--
-- Each line is a Feature with properties kind (trail, viewpoint, waterfall,
-- peak, parking, trailhead) and osm_id; trails also have a name, and bike=yes
-- if graded for mountain bikes or ski=yes if a ski piste. Parking lots
-- mapped as areas are polygons.

local file_append = require 'file_append'
local json = require 'json'

local dump_filename = os.getenv('DUMP_FILENAME')

node_keys = {'tourism=viewpoint', 'waterway=waterfall', 'natural=peak', 'amenity=parking', 'highway=trailhead'}
way_keys = {'highway=path', 'highway=footway', 'highway=bridleway', 'highway=steps', 'amenity=parking'}

-- Not tracks: named ones are mostly roads (County Road 133, Forest Road
-- 8410), and joined networks of them thousands of km long.
local trail_kinds = { path = true, footway = true, bridleway = true, steps = true }

local function write(kind, geometry, extra)
	local properties = { kind = kind, osm_id = Id() }
	for k, v in pairs(extra or {}) do
		if v ~= '' then properties[k] = v end
	end
	file_append.write(dump_filename, json.encode({ type = "Feature", geometry = geometry, properties = properties }) .. '\n')
end

local function point_kind()
	if Find('tourism') == 'viewpoint' then return 'viewpoint' end
	if Find('waterway') == 'waterfall' then return 'waterfall' end
	if Find('natural') == 'peak' then return 'peak' end
	if Find('highway') == 'trailhead' then return 'trailhead' end
	if Find('amenity') == 'parking' then
		local access = Find('access')
		if access == 'private' or access == 'no' or access == 'customers' then return nil end
		return 'parking'
	end
	return nil
end

function node_function()
	local kind = point_kind()
	if not kind then return end
	local geojson = GeoJSON(false)
	if geojson then write(kind, json.decode(geojson)) end
end

function way_function()
	if Find('amenity') == 'parking' then
		local kind = point_kind()
		if not kind or not IsClosed() then return end
		-- The lot's area; bin/trail-areas.py uses its centroid.
		local geojson = GeoJSON(true)
		if geojson then write(kind, json.decode(geojson)) end
		return
	end

	if not trail_kinds[Find('highway')] then return end
	local name = Find('name')
	if name == '' then return end
	local foot = Find('foot')
	if foot == 'no' or foot == 'private' or foot == 'use_sidepath' then return end
	local access = Find('access')
	if access == 'private' or access == 'no' then return end
	-- Snowmobile trails (the 2,800 km Snoman Trail network), unless they're
	-- also for walking.
	local snowmobile = Find('snowmobile')
	if (snowmobile == 'designated' or snowmobile == 'yes') and foot ~= 'designated' and foot ~= 'yes' then return end
	if string.find(name, '[Ss]nowmobile') then return end

	-- Mountain-bike trails and ski pistes, which hikers may share but which
	-- aren't hiking trails: bin/trail-areas.py drops a network that's mostly
	-- these (mountain-bike parks; Nordic ski networks).
	local extra = { name = name }
	if Find('mtb:scale') ~= '' or Find('mtb:scale:imba') ~= '' or Find('mtb') == 'designated' then extra.bike = 'yes' end
	if Find('piste:type') ~= '' then extra.ski = 'yes' end

	local geojson = GeoJSON(false)
	if geojson then write('trail', json.decode(geojson), extra) end
end
