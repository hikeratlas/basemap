local debug = false
logger = nil

way_keys = {'building', 'amenity=parking'}

function init_function()
	logger = require 'logger'
	logger.init()
end

function exit_function()
	logger.close()
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
	Attribute('amenity', amenity)
	Attribute('building', building)
end
