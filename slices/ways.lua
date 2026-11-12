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

-- route=ferry and aerialway: foot crossings that aren't highway=* ways (see
-- way_function_crossing).
way_keys = {'highway', 'route=road', 'route=ferry', 'aerialway'}

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
	if highway ~= '' then way_function_highway(highway); return end
	way_function_crossing()
end

-- Crossings hikers make that OSM doesn't map as highway=* ways: ferries and
-- hand-operated cable cars, e.g. on the West Coast Trail the Nitinat Narrows
-- and Gordon River ferries (route=ferry, foot=yes) and the Klanawa River or
-- Cullite Creek cable cars (aerialway=yes / zip_line, foot=yes). Without
-- them the trail is cut into pieces, and hikeratlas/routes can't walk it end
-- to end. Only walk-on (foot=yes/designated), short ones in parks, so the
-- path layer doesn't fill up with car ferries and ski lifts.
local crossing_aerialways = { yes = true, zip_line = true, cable_car = true }

-- Lifts that carry people up and down the mountain all year, e.g. Grouse
-- Mountain's Skyride (aerialway=cable_car), which hikers ride down after the
-- Grouse Grind, a trail that is up only. hikeratlas/routes reads them for a
-- way back to the trailhead, never as a way to walk. Chair lifts are left
-- out: most only run for skiers. Kept in or out of parks: a resort's lifts
-- often run just outside the park beside them (the Red Skyride, ~35 m
-- outside Grouse Mountain Regional Park, was dropped while the Blue Grouse
-- Gondola beside it, just inside, was kept: #295), and there are few of them.
local passenger_lifts = { gondola = true, cable_car = true, mixed_lift = true }

function way_function_lift()
	if not passenger_lifts[Find('aerialway')] then return false end
	local access = Find('access')
	if access == 'no' or access == 'private' then return true end
	if Find('disused') == 'yes' or Find('abandoned') == 'yes' then return true end
	Layer('path', false)
	MinZoom(12)
	Attr('name', Find('name'))
	Attr('kind', 'lift')
	return true
end

function way_function_crossing()
	local foot = Find('foot')
	-- A walk-on cable car across a river stays a crossing (below).
	if foot ~= 'yes' and foot ~= 'designated' and way_function_lift() then return end
	if foot ~= 'yes' and foot ~= 'designated' then return end
	local kind
	if Find('route') == 'ferry' then
		kind = 'ferry'
	elseif crossing_aerialways[Find('aerialway')] then
		kind = 'cable_car'
	else
		return
	end
	if Length() > 2000 then return end
	if not Intersects('parks') then return end
	Layer('path', false)
	MinZoom(12)
	Attr('name', Find('name'))
	Attr('kind', kind)
	Attr('foot', foot)
	AttributeBoolean('in_park', true)
	AttributeBoolean('in_city_park', false)
end

-- Whether private motor vehicles may not use a road, e.g. the Lake O'Hara
-- Fire Road (motor_vehicle=private: Parks Canada's bus only). The most
-- specific tag that's set wins, so motor_vehicle=yes on an access=no road
-- leaves it open.
-- The SAC hiking scale (https://wiki.openstreetmap.org/wiki/Key:sac_scale).
local sac_grades = {
	hiking = 1,
	mountain_hiking = 2,
	demanding_mountain_hiking = 3,
	alpine_hiking = 4,
	demanding_alpine_hiking = 5,
	difficult_alpine_hiking = 6,
}

local function closed_to_cars()
	for _, k in ipairs({ 'motorcar', 'motor_vehicle', 'vehicle', 'access' }) do
		local v = Find(k)
		if v ~= '' then return v == 'no' or v == 'private' end
	end
	return false
end

function way_function_highway(highway)
	local in_park = Intersects('parks')
	local in_city_park = Intersects('city_parks')

	-- If a road is part of a national road route, bump its importance to
	-- motorway. This avoids gaps at low zooms.
	-- A path in a hiking or foot route relation is part of a trail even when
	-- the way itself has no name (e.g. most of the climb to Upper Yosemite
	-- Fall): the style keeps those at full weight at low zooms.
	local on_route = false
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
		if route == 'hiking' or route == 'foot' then on_route = true end
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
		-- hikeratlas/routes walks these like tracks, and doesn't treat
		-- campsites near them as drive-in.
		if closed_to_cars() then AttributeBoolean('closed_to_cars', true) end
		-- A lot's driving aisles: hikeratlas/routes starts hikes from a
		-- lot mapped only by its aisles, with no amenity=parking area
		-- (Killarney's Granite Ridge trailhead, routes#102).
		if highway == 'service' and Find('service') == 'parking_aisle' then
			AttributeBoolean('parking_aisle', true)
		end
		-- What a service road is for (OSM's service=*: driveway,
		-- parking_aisle, alley, drive-through, emergency_access...).
		-- hikeratlas/routes treats a lodge's or visitor centre's driveways
		-- like a lot: a trail leaving them is a trailhead (Mt Norquay's day
		-- lodge, routes#156).
		if highway == 'service' then Attr('service', Find('service')) end
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
		-- A closed trail, which hikeratlas/routes mustn't use: access=no with
		-- no permission for walkers, or a mapper's 'Trail Closed' name (Gros
		-- Morne's way/168941774 and way/420891009). It's still drawn.
		local closed = false
		if Find('access') == 'no' and foot ~= 'yes' and foot ~= 'designated' and foot ~= 'permissive' then closed = true end
		local lname = string.lower(Find('name'))
		if lname == 'trail closed' or lname == 'closed trail' or lname == 'closed' or string.find(lname, '%(closed%)') then closed = true end
		local segregated = Find('segregated')
		local surface = Find('surface')
		local bridge = Find('bridge')
		-- For portages, e.g. Algonquin PP
		local canoe = Find('canoe')

		-- Ignore private paths, and cycleways whose pedestrians must use a
		-- sidewalk alongside (foot=use_sidepath). Bike-only trails (foot=no)
		-- stay, so the map can show them in their own style; walking routes
		-- skip them (hikeratlas/routes, and the website's route planner).
		if foot == 'private' or foot == 'use_sidepath' then return end

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
		if on_route then AttributeBoolean('on_route', true) end
		if closed then AttributeBoolean('closed', true) end
		-- One-way trails: walk the way only as drawn (yes), or only against it
		-- (-1). hikeratlas/routes won't walk them backwards: the Grouse Grind is
		-- up only, so its hike comes down another trail (routes#163).
		local oneway = Find('oneway')
		if oneway == 'yes' or oneway == '-1' then Attr('oneway', oneway) end
		-- Mountain bike trails, which hikeratlas/routes avoids when the trail
		-- isn't also designated for walking (foot). Whistler's are graded with
		-- mtb:scale:imba rather than mtb:scale (e.g. way/1411691966).
		if Find('mtb:scale') ~= '' or Find('mtb:scale:imba') ~= '' or Find('mtb') == 'designated' then
			AttributeBoolean('mtb', true)
		end
		-- Hiking difficulty, the SAC scale's T1-T6 as 1-6 (sac_scale=hiking is
		-- 1, difficult_alpine_hiking 6). hikeratlas/routes never uses T5-T6
		-- (climbing, glaciers: routes#45), e.g. Jasper's Mount Edith Cavell
		-- Route (way/264994422), which took the Tonquin Valley hike over the
		-- mountain (routes#54); T4 is a scramble.
		local sac = sac_grades[Find('sac_scale')]
		if sac ~= nil then AttributeNumeric('sac', sac) end
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
		if on_route then AttributeBoolean('on_route', true) end
		if closed then AttributeBoolean('closed', true) end
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
	
	if route == 'road' or route == 'hiking' or route == 'foot' then
		Accept()
	end
end
