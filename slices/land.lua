local debug = false
way_keys = {'landuse', 'leisure', 'natural', 'wetland', 'tourism=camp_site'}

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

function node_function()
end

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

function way_function()
	local natural = Find('natural')
	if natural_filter[natural] == true then emit('natural', natural); return end

	if natural == 'wetland' then emit('wetland', 'natural=wetland'); return end

	local landuse = Find('landuse')
	if landuse_filter[landuse] == true then emit('landuse', landuse); return end

	local wetland = Find('wetland')
	if wetland_filter[wetland] == true then emit('wetland', wetland); return end

	local tourism = Find('tourism')
	if tourism == 'camp_site' then emit('tourism', 'camp_site'); return end
end
