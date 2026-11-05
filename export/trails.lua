-- A script to export named trails, and the destinations and parking near
-- them, as GeoJSONL, for bin/trail-areas.py: trail networks outside parks
-- (e.g. Newfoundland's Skerwink Trail) become areas that hikeratlas/routes
-- curates, as it does parks.
--
-- Each line is a Feature with properties kind (trail, viewpoint, waterfall,
-- peak, parking, trailhead) and osm_id; trails also have a name.

local file_append = require 'file_append'
local json = require 'json'

local dump_filename = os.getenv('DUMP_FILENAME')

node_keys = {'tourism=viewpoint', 'waterway=waterfall', 'natural=peak', 'amenity=parking', 'highway=trailhead'}
way_keys = {'highway=path', 'highway=footway', 'highway=bridleway', 'highway=track', 'highway=steps', 'amenity=parking'}

local trail_kinds = { path = true, footway = true, bridleway = true, track = true, steps = true }

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
		-- A lot's centroid is enough to count it and to find it.
		local lat, lon = Centroid()
		if lat then write(kind, { type = "Point", coordinates = { lon, lat } }) end
		return
	end

	if not trail_kinds[Find('highway')] then return end
	local name = Find('name')
	if name == '' then return end
	local foot = Find('foot')
	if foot == 'no' or foot == 'private' or foot == 'use_sidepath' then return end
	local access = Find('access')
	if access == 'private' or access == 'no' then return end

	local geojson = GeoJSON(false)
	if geojson then write('trail', json.decode(geojson), { name = name }) end
end
