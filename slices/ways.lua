local debug = false

qrank = nil

local function Attr(k, v) if v ~= '' then Attribute(k, v) end end

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
		Attr('kind', highway)
		Attr('name', name)
		AttributeBoolean('in_park', in_park)
		AttributeBoolean('in_city_park', in_city_park)
		if name == '' then return end
		Layer('road_name', false)
		MinZoom(road_zoom)
		Attr('name', name)
		Attr('kind', highway)
		AttributeBoolean('in_park', in_park)
		AttributeBoolean('in_city_park', in_city_park)
		return
	end

	path_zoom = path_zooms[highway]
	-- Cycleways count as paths, unless walking on them is ruled out: in the US,
	-- highway=cycleway allows pedestrians by default (see the defaults table at
	-- https://wiki.openstreetmap.org/wiki/OSM_tags_for_routing/Access_restrictions).
	-- Until 2026 a cycleway needed foot=yes/designated, so e.g. the Bike and Hike
	-- Trail (way/168254737) was hidden until a mapper added foot=designated.
	if path_zoom ~= nil then
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

		-- Ignore paths pedestrians may not use: dedicated bike paths, downhill
		-- bike trails, and cycleways whose pedestrians must use a sidewalk
		-- alongside (foot=use_sidepath).
		if foot == 'no' or foot == 'private' or foot == 'use_sidepath' then return end

		if not in_park then path_zoom = path_zoom + 2 end

		-- If the path is not in a park, we'd like to only show it if:
		-- - it has a name
		-- - it's in a city park
		Layer('path', false)
		MinZoom(path_zoom)
		Attr('name', name)
		Attr('kind', highway)
		Attr('bicycle', bicycle)
		Attr('bridge', bridge)
		Attr('foot', foot)
		Attr('segregated', segregated)
		Attr('surface', surface)
		Attr('canoe', canoe)
		AttributeBoolean('in_park', in_park)
		AttributeBoolean('in_city_park', in_city_park)
		-- Mountain bike trails (e.g. Whistler's), which hikeratlas/routes
		-- avoids when the trail isn't also designated for walking (foot).
		if Find('mtb:scale') ~= '' then AttributeBoolean('mtb', true) end
		if debug then
			Attr('osm_id', Id())
		end
		if name == '' then return end
		Layer('path_name', false)
		MinZoom(path_zoom)
		Attr('name', name)
		Attr('kind', highway)
		Attr('bicycle', bicycle)
		Attr('bridge', bridge)
		Attr('foot', foot)
		Attr('segregated', segregated)
		Attr('surface', surface)
		Attr('canoe', canoe)
		AttributeBoolean('in_park', in_park)
		AttributeBoolean('in_city_park', in_city_park)
		-- The tiles stop at z14, so z15 and z16 labels follow copies in the
		-- z14 tiles simplified for those zooms (see path_name in ways.json).
		if in_park and canoe ~= 'portage' then
			Layer('path_name_15', false)
			Attr('name', name)
			Layer('path_name_16', false)
			Attr('name', name)
		end
		return
	end
end

function relation_scan_function()
	local route = Find('route')
	
	if route == 'road' then
		Accept()
	end
end
