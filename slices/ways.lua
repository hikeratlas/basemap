local debug = false

qrank = nil

function init_function()
	qrank = require 'qrank' 
	qrank.init()
end

function exit_function()
	qrank.close()
end

way_keys = {'highway', 'route=road'}

-- These zooms are for roads, i.e. where cars go
local road_zooms = {
	motorway = 5,
	motorway_link = 5,

	trunk = 6,
	trunk_link = 6,

	primary = 7,
	primary_link = 7,

	secondary = 8,
	secondary_link = 8,

	tertiary = 9,
	tertiary_link = 9,

	unclassified = 11,
	residential = 11,

	living_street = 11,
	service = 11,
	pedestrian = 10,
	track = 10,
	escape = 10,
	road = 10,
	busway = 10,
	raceway = 10
}

-- These zooms are for paths, i.e. where creatures with two or more feet go
local path_zooms = {
	footway = 8,
	bridleway = 8,
	cycleway = 8,
	steps = 8,
	path = 8,
	via_ferrata = 8
}

function node_function()
end

function way_function()
	local highway = Find('highway')
	if highway ~= '' then way_function_highway(highway) end
end

function way_function_highway(highway)
	local in_park = Intersects('parks')
	local in_city_park = Intersects('city_parks')

	-- If a road is part of a national road route, bump its importance to
	-- motorway. This avoids gaps at low zooms.
	while true do
		local rel = NextRelation()
		if not rel then break end
		local route = FindInRelation('route')
		local network = FindInRelation('network')

		local wikidata = FindInRelation('wikidata')
		local rank = qrank.get(wikidata)

		if route == 'road' and rank > 1000 then
			highway = 'motorway'
		end
	end

	-- See https://wiki.openstreetmap.org/wiki/Key:highway#Highway
	road_zoom = road_zooms[highway]
	local name = Find('name')

	if road_zoom ~= nil then
		if in_park or in_city_park then
			road_zoom = math.min(10, road_zoom)
		end
		Layer('road', false)
		MinZoom(road_zoom)
		Attribute('kind', highway)
		Attribute('name', name)
		AttributeBoolean('in_park', in_park)
		AttributeBoolean('in_city_park', in_city_park)
		if name == '' then return end
		Layer('road_name', false)
		MinZoom(road_zoom)
		Attribute('name', name)
		Attribute('kind', highway)
		AttributeBoolean('in_park', in_park)
		AttributeBoolean('in_city_park', in_city_park)
		return
	end

	path_zoom = path_zooms[highway]
	if path_zoom ~= nil and (highway ~= 'cycleway' or Find('foot') == 'yes' or Find('foot') == 'designated') then
		local footway = Find('footway')

		-- In urban areas, sidewalks dominate.
		if not in_park and not in_city_park and (footway == 'sidewalk' or footway == 'crossing') then return end

		local bicycle = Find('bicycle')
		local foot = Find('foot')
		local segregated = Find('segregated')
		local surface = Find('surface')
		local bridge = Find('bridge')
		-- For portages, e.g. Algonquin PP
		local canoe = Find('canoe')

		-- Ignore dedicated bike paths, downhill bike trails, etc.
		if foot == 'no' then return end

		if not in_park then path_zoom = path_zoom + 2 end

		-- If the path is not in a park, we'd like to only show it if:
		-- - it has a name
		-- - it's in a city park
		Layer('path', false)
		MinZoom(path_zoom)
		Attribute('name', name)
		Attribute('kind', highway)
		Attribute('bicycle', bicycle)
		Attribute('bridge', bridge)
		Attribute('foot', foot)
		Attribute('segregated', segregated)
		Attribute('surface', surface)
		Attribute('canoe', canoe)
		AttributeBoolean('in_park', in_park)
		AttributeBoolean('in_city_park', in_city_park)
		if debug then
			Attribute('osm_id', Id())
		end
		if name == '' then return end
		Layer('path_name', false)
		MinZoom(path_zoom)
		Attribute('name', name)
		Attribute('kind', highway)
		Attribute('bicycle', bicycle)
		Attribute('bridge', bridge)
		Attribute('foot', foot)
		Attribute('segregated', segregated)
		Attribute('surface', surface)
		Attribute('canoe', canoe)
		AttributeBoolean('in_park', in_park)
		AttributeBoolean('in_city_park', in_city_park)
		return
	end
end

function relation_scan_function()
	local route = Find('route')
	
	if route == 'road' then
		Accept()
	end
end
