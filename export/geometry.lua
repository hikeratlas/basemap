local geometry = {}
local json = require 'json'

function geometry.box(geom)
	local min_lon = 999
	local min_lat = 999
	local max_lon = -999
	local max_lat = -999

	if not geom or not geom['type'] then return nil end

	-- The coordinates that bound the geometry: outer rings of polygons, and
	-- every point of lines (e.g. a cliff).
	local lists = {}
	local t = geom['type']
	local c = geom['coordinates']
	if t == 'MultiPolygon' then
		for _, polygon in ipairs(c) do table.insert(lists, polygon[1]) end
	elseif t == 'Polygon' then
		table.insert(lists, c[1])
	elseif t == 'MultiLineString' then
		for _, line in ipairs(c) do table.insert(lists, line) end
	elseif t == 'LineString' then
		table.insert(lists, c)
	end

	for _, coords in ipairs(lists) do
		for _, coord in ipairs(coords) do
			local lon = coord[1]
			local lat = coord[2]
			min_lon = math.min(min_lon, lon)
			min_lat = math.min(min_lat, lat)
			max_lon = math.max(max_lon, lon)
			max_lat = math.max(max_lat, lat)
		end
	end

	if min_lon == 999 then return nil end

	return {
		min_lon=min_lon,
		min_lat=min_lat,
		max_lon=max_lon,
		max_lat=max_lat,
	}
end

-- Km along a LineString or MultiLineString (haversine), or nil for other
-- geometries: a trail's length for search results (website#44). tilemaker's
-- Length() doesn't measure relations.
function geometry.line_km(geom)
	if not geom then return nil end
	local t, c = geom['type'], geom['coordinates']
	local lines = {}
	if t == 'LineString' then lines = {c}
	elseif t == 'MultiLineString' then lines = c
	else return nil end
	local r = 6371.0088
	local km = 0
	for _, line in ipairs(lines) do
		for i = 2, #line do
			local lon1, lat1 = math.rad(line[i - 1][1]), math.rad(line[i - 1][2])
			local lon2, lat2 = math.rad(line[i][1]), math.rad(line[i][2])
			local h = math.sin((lat2 - lat1) / 2) ^ 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ^ 2
			km = km + 2 * r * math.asin(math.sqrt(h))
		end
	end
	return km
end

-- Splits a MultiPolygon that crosses the antimeridian (e.g. the Aleutian
-- Islands, Alaska, the United States) into its eastern and western parts.
--
-- Otherwise its bounding box spans every longitude. tilemaker indexes each
-- GeoJSON feature by its bounding box, so every FindIntersecting/Intersects
-- query in that latitude band then does an exact test against the whole
-- (often huge) geometry: on north-america, the Alaska Maritime National
-- Wildlife Refuge alone made zindex ~3x slower.
--
-- Returns a list of geometries.
function geometry.split_antimeridian(geom)
	if not geom or geom['type'] ~= 'MultiPolygon' then return {geom} end

	local east = {}
	local west = {}
	for _, polygon in ipairs(geom['coordinates']) do
		if polygon[1][1][1] < 0 then
			table.insert(west, polygon)
		else
			table.insert(east, polygon)
		end
	end

	local box = geometry.box(geom)
	if #east == 0 or #west == 0 or box['max_lon'] - box['min_lon'] <= 180 then return {geom} end

	return {
		{type='MultiPolygon', coordinates=west},
		{type='MultiPolygon', coordinates=east},
	}
end

return geometry
