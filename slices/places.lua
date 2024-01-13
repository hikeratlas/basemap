-- Export place names of political entities, e.g. towns, cities, capitals.
--
-- Note that provinces/countries are handled by boundaries.lua.

node_keys = {'place'}
way_keys = node_keys

qrank = nil

function init_function()
	qrank = require 'qrank' 
	qrank.init()
end

function exit_function()
	qrank.close()
end

-- See https://wiki.openstreetmap.org/wiki/Key:place
places = {
	country = -1, -- handled by boundaries
	state = -1, -- handled by boundaries
	region = -1,
	province = -1,
	district = -1,
	county = -1,
	municipality = 3,
	city = 0,
	borough = 3,
	suburb = -1,
	quarter = -1,
	town = 3,
	neighbourhood = -1,
	city_block = -1,
	plot = 3,
	town = 3,
	village = 3,
	hamlet = 7,
	isolated_dwelling = 8,
	farm = 8,
	allotments = 8,
	continent = -1,
	archipelago = -1,
	island = 3,
	islet = 3,
	locality = 8,
	sea = 3,
	ocean = 1
}

function node_function()
	maybe_emit(false)
end

function maybe_emit(is_area)
	local name = Find('name')
	if name == '' then return end

	local place = Find('place')
	mz_place = places[place]
	if mz_place == nil or mz_place < 0 then return end

	local wikidata = Find('wikidata')
	local rank = qrank.get(wikidata)


	-- If we're a node, don't emit if we're also part of a relation that has a place key,
	-- the relation will take precedence.
	while true do
		local rel, role = NextRelation()
		if not rel then break end
		if FindInRelation('place') ~= '' then
			return
		end
	end

	local mz = 99

	if rank > 1000000 then
		mz = 0
	elseif rank > 500000 then
		mz = 3
	elseif rank > 100000 then
		mz = 4
	elseif rank > 50000 then
		mz = 6
	elseif rank > 5000 then
		mz = 7
	elseif rank > 1000 then
		mz = 8
	else
		mz = 10
	end
	if is_area then
		LayerAsCentroid('place_name', 'polylabel', 'label')
	else
		Layer('place_name')
	end

	if mz_place > mz then
		-- Hamlets can never be z0, e.g.
		mz = mz_place
	end

	MinZoom(mz)
	Attribute('name', name)
	AttributeNumeric('rank', rank)
	Attribute('place', place)
	Attribute('wikidata', wikidata)
	Attribute('osm_id', Id())
end

function way_function()
	local place

	-- If the way is only being included due to a relation, do nothing.
	while true do
		local rel = NextRelation()
		if not rel then break end

		place = FindInRelation('place')
		if places[place] ~= nil and places[place] >= 0 then
			return
		end
	end

	maybe_emit(true)
end

function relation_scan_function()
  local place = Find('place')

	if places[place] ~= nil and places[place] >= 0 then
		Accept()
	end
end

function relation_function()
	maybe_emit(true)
end
