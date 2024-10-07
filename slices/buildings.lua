local debug = false

way_keys = {'building', 'amenity=parking'}

local function Attr(k, v) if v ~= '' then Attribute(k, v) end end

function init_function()
end

function exit_function()
end

function node_function()
end

function way_function()
	local amenity = Find('amenity')
	local building = Find('building')

	local is_parking = amenity == 'parking'
	local is_building = building ~= '' and building ~= 'no'

	if not is_parking and not is_building then return end

	if not IsClosed() then return end

	local in_park = Intersects('parks')
	local in_city_park = Intersects('city_parks')
	if not in_park and not in_city_park then return end

	Layer('building', true)
	Attr('amenity', amenity)
	Attr('building', building)
end
