local geometry = {}
local json = require 'json'

function geometry.box(geom)
	local min_lon = 999
	local min_lat = 999
	local max_lon = -999
	local max_lat = -999

	if not geom or not geom['type'] then return nil end
	if geom['type'] == 'MultiPolygon' then
		for _, polygon in ipairs(geom['coordinates']) do
			for _, coord in ipairs(polygon[1]) do
				local lon = coord[1]
				local lat = coord[2]
				min_lon = math.min(min_lon, lon)
				min_lat = math.min(min_lat, lat)
				max_lon = math.max(max_lon, lon)
				max_lat = math.max(max_lat, lat)
			end
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

return geometry
