-- Ways whose tags read the same are replayed rather than run again (tilemaker's
-- way_memo): way_function must only depend on what it reads, so keep state out of it.
way_memo = true

local debug = false
way_keys = {'landuse', 'leisure', 'natural', 'wetland', 'tourism=camp_site', 'aeroway'}
-- Only beaches mapped as a point, for their names (#352).
node_keys = {'natural=beach'}

local function Attr(k, v) if v ~= '' then Attribute(k, v) end end

function init_function()
end

function exit_function()
end

local landuse_filter = {
	forest = true,
	grass = true,
	meadow = true,
	orchard = true,
	vineyard = true,
	allotments = true,
	cemetery = true,
	village_green = true,
	recreation_ground = true,
	farmyard = true,
	farmland = true
}

local natural_filter = {
	wood = true,
	sand = true,
	beach = true,
	glacier = true,
	cliff=true,
	heath = true,
	scrub = true,
	grassland = true,
	bare_rock = true,
	scree = true,
	shingle = true
}

local wetland_filter = {
	swamp = true,
	bog = true,
	string_bog = true,
	wet_meadow = true,
	marsh = true
}

function emit(key, value)
	local wikidata = Find('wikidata')
	if IsClosed() then
		Layer('land', true)
		Attr(key, value)
		Attr('wikidata', wikidata)
	else
		Layer('land_line', false)
		Attr(key, value)
		Attr('wikidata', wikidata)
	end

end

-- Canyons, gorges and valleys get their name along the line. They're
-- usually mapped as a line down the valley floor (natural=valley, sometimes
-- gorge or canyon), but some, like Barron Canyon in Algonquin
-- (way/628304812), only as named cliffs along the rim.
local valley_naturals = { valley = true, gorge = true, canyon = true }

local function is_canyon_cliff(name)
	local n = string.lower(name)
	return string.find(n, 'canyon', 1, true) ~= nil
		or string.find(n, 'gorge', 1, true) ~= nil
		or string.find(n, 'chasm', 1, true) ~= nil
end

function emit_landform_name(natural)
	if IsClosed() then return end
	local name = Find('name')
	if name == '' then return end
	if not (valley_naturals[natural] or (natural == 'cliff' and is_canyon_cliff(name))) then return end
	Layer('landform_name', false)
	Attr('name', name)
	Attr('natural', natural)
	Attr('wikidata', Find('wikidata'))
end

-- A named golf course, airport, beach or dunes' name, at its centre, with
-- its kind for the label's icon (land_label in land.json).
local function emit_label(kind, minzoom)
	local name = Find('name')
	if name == '' or not IsClosed() then return end
	LayerAsCentroid('land_label')
	MinZoom(minzoom)
	Attr('name', name)
	Attr('kind', kind)
end

-- Beach and dune names (#352): a named natural=beach, area or point, and a
-- named natural=sand that's called a beach or dunes. Some beaches are mapped
-- only as sand: Sandbanks's Dunes Beach is natural=sand (way/80312440), the
-- beach beside it unnamed natural=beach. From z13, like golf courses.
local function sand_kind(name)
	local n = string.lower(name)
	if string.find(n, 'beach', 1, true) then return 'beach' end
	if string.find(n, 'dune', 1, true) then return 'dune' end
end

local function beach_kind(natural)
	local name = Find('name')
	if name == '' then return nil end
	if natural == 'beach' then return 'beach' end
	if natural == 'sand' then return sand_kind(name) end
end

function node_function()
	local kind = beach_kind(Find('natural'))
	if not kind then return end
	Layer('land_label', false)
	MinZoom(13)
	Attr('name', Find('name'))
	Attr('kind', kind)
end

-- Airports (#153): the aerodrome and its aprons are areas, runways and
-- taxiways lines (as they're nearly always mapped; their width comes from
-- the style). None of it was drawn, so Dawson Creek's airport didn't show.
local aeroway_areas = { aerodrome = true, apron = true }
local aeroway_lines = { runway = true, taxiway = true }

function way_function()
	-- Golf courses (#152): the course itself, under its fairways, greens and
	-- bunkers (mapped as grass and sand), so the rough between them isn't
	-- blank.
	if Find('leisure') == 'golf_course' and IsClosed() then
		emit('leisure', 'golf_course')
		emit_label('golf_course', 13)
		return
	end

	local aeroway = Find('aeroway')
	if aeroway_areas[aeroway] and IsClosed() then
		emit('aeroway', aeroway)
		if aeroway == 'aerodrome' then emit_label('aerodrome', 11) end
		return
	end
	if aeroway_lines[aeroway] then
		Layer('land_line', false)
		Attr('aeroway', aeroway)
		return
	end

	local natural = Find('natural')
	emit_landform_name(natural)
	if natural_filter[natural] == true then
		emit('natural', natural)
		local kind = beach_kind(natural)
		if kind then emit_label(kind, 13) end
		return
	end

	if natural == 'wetland' then emit('wetland', 'natural=wetland'); return end

	local landuse = Find('landuse')
	if landuse_filter[landuse] == true then emit('landuse', landuse); return end

	local wetland = Find('wetland')
	if wetland_filter[wetland] == true then emit('wetland', wetland); return end

	local tourism = Find('tourism')
	if tourism == 'camp_site' then emit('tourism', 'camp_site'); return end
end
