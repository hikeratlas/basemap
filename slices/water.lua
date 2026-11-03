local debug = false

way_keys = {'natural=water', 'water', 'waterway'}
node_keys = {'waterway=weir', 'waterway=dam'}

local function Attr(k, v) if v ~= '' then Attribute(k, v) end end

function init_function()
end

function exit_function()
end

-- Weirs and dams, e.g. the Kitchener Weir (https://www.openstreetmap.org/way/105587319)
-- and the Glen Canyon Dam (https://www.openstreetmap.org/way/108060498): an area,
-- a line across the river, or a node on it. Dams are usually much bigger, so
-- they show from a zoom earlier.
local barrier_zooms = { dam = 12, weir = 13 }

function emit_barrier(kind, is_node)
	local mz = barrier_zooms[kind]
	local is_area = not is_node and IsClosed()
	Layer('water_barrier', is_area)
	MinZoom(mz)
	Attr('kind', kind)
	if debug then
		Attr('osm_id', Id())
	end

	-- The name goes on a point (an area's or line's centroid), a zoom later.
	local name = Find('name')
	if name == '' then return end
	if is_node then
		Layer('water_barrier_name', false)
	else
		LayerAsCentroid('water_barrier_name')
	end
	MinZoom(mz + 1)
	Attr('kind', kind)
	Attr('name', name)
end

function node_function()
	local waterway = Find('waterway')
	if barrier_zooms[waterway] then emit_barrier(waterway, true) end
end

-- water=* values for areas that are long and thin, like rivers.
river_areas = { river = true, canal = true, stream = true, ditch = true, drain = true, tidal_channel = true }

function maybe_emit()
	local name = Find('name')
  local natural = Find('natural')
  local water = Find('water')
  local waterway = Find('waterway')

	local id = Id()

	if barrier_zooms[waterway] then
		emit_barrier(waterway, false)
		return
	end

	if not (natural == 'water' or water == 'lake' or waterway == 'river' or waterway == 'stream') then return end

	local isClosed = IsClosed()
	local area = 0
	if isClosed then
		area = math.ceil(Area())
	end

	mz = 6

	if not isClosed then
		mz = 10
		if name == '' then
			mz = 11
		end
	end

	if isClosed then
		if area < 10000000 then
			mz = 7
		end

		if area < 3000000 then
			mz = 8
		end

		if area < 1000000 then
			mz = 9
		end
		if area < 500000 then
			mz = 10
		end
	end

	-- List of honkin' big lakes in North America, from
	-- https://en.wikipedia.org/wiki/List_of_lakes_by_area#Geological_list
	if id == '1206310' -- Lake Ontario
		or id == '1205151' -- Lake Huron
		or id == '1205149' -- Lake Michigan
		or id == '4039486' -- Lake Superior
		or id == '4039900' -- Lake Erie
		or id == '2791372' -- Great Bear Lake
		or id == '1834172' -- Great Slave Lake
		or id == '1259563' -- Lake Winnipeg
	then
		mz = 2
	end


	local layer = 'water_line'
	if isClosed then
		layer = 'water_poly'
		-- River areas are long and thin. Visvalingam (water_poly's simplifier)
		-- breaks them into fragments at low zooms, so they keep the default
		-- simplifier, in a layer that writes into water_poly.
		if river_areas[water] or waterway == 'riverbank' then layer = 'water_poly_river' end
	end

	local name_layer = 'water_line_name'
	if isClosed then name_layer = 'water_poly_name' end

	kind = 'lake'
	if waterway == 'river' or waterway == 'stream' then kind = waterway end

	Layer(layer, isClosed)
	MinZoom(mz)
	Attr('name', name)
	Attr('kind', kind)
	Attr('wikidata', Find('wikidata'))
	Attr('intermittent', Find('intermittent'))
	Attr('seasonal', Find('seasonal'))
	if isClosed then
		Attr('area', area)
	end
	if debug then
		Attr('osm_id', Id())
	end

	if name == '' then return end

	if isClosed then
		LayerAsCentroid(name_layer)
	else
		Layer(name_layer, false)
	end
	MinZoom(mz)
	Attr('name', name)
	Attr('kind', kind)
	Attr('wikidata', Find('wikidata'))
	if debug then
		Attr('osm_id', Id())
	end
end

function way_function()
	local boundary

	-- If the way is only being included due to a relation, do nothing.
	-- The great lakes are part of the Great Lakes relation -- so
	-- only do these checks if we think the current object is not itself
	-- a multipolygon relation
	while Find('type') ~= 'multipolygon' do
		local rel = NextRelation()
		if not rel then break end

		local water = FindInRelation('water')
		local waterway = FindInRelation('waterway')
		local natural = FindInRelation('natural')
		if natural == 'water' or water == 'lake' or waterway == 'river' or waterway == 'stream' then
			return
		end
	end

	maybe_emit()
end
