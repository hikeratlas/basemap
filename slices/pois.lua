node_keys = {'amenity', 'tourism', 'waterway=waterfall', 'ford', 'historic', 'natural', 'highway=trailhead'}
way_keys = node_keys

qrank = nil

local function Attr(k, v) if v ~= '' then Attribute(k, v) end end

function init_function()
	qrank = require 'qrank' 
	qrank.init()
end

function exit_function()
	qrank.close()
end

function maybe_emit(is_area)
	local in_park = Intersects('parks')
	local in_city_park = Intersects('city_parks')

	if not in_park and not in_city_park then return end

	local amenity = Find('amenity')
	local tourism = Find('tourism')
	local historic = Find('historic')
	local waterway = Find('waterway')
	local natural = Find('natural')
	local ford = Find('ford')
	local highway = Find('highway')

	local locker = Find('locker')
	local shelter_type = Find('shelter_type')
	local toilets_disposal = Find('toilets:disposal')

	-- POIs are opt-out
	if tourism == 'camp_pitch' then tourism = '' end -- not sure I want to show these; Taylor Meadows Campground has them haphazardly included

	-- Garbage cans are really interesting in the backcountry. In the city,
	-- less so.
	if (amenity == 'waste_basket' or amenity == 'recycling') and in_city_park then amenity = '' end

	-- General-purpose buildings aren't that interesting.
	if amenity == 'arts_centre' then amenity = '' end
	if amenity == 'atm' then amenity = '' end
	if amenity == 'childcare' then amenity = '' end
	if amenity == 'college' then amenity = '' end
	if amenity == 'community_centre' then amenity = '' end
	if amenity == 'conference_centre' then amenity = '' end
	if amenity == 'kindergarten' then amenity = '' end
	if amenity == 'letter_box' then amenity = '' end
	if amenity == 'library' then amenity = '' end
	if amenity == 'parking_entrance' then amenity = '' end
	if amenity == 'parking_space' then amenity = '' end
	if amenity == 'polling_station' then amenity = '' end
	if amenity == 'post_box' then amenity = '' end
	if amenity == 'public_bookcase' then amenity = '' end
	if amenity == 'school' then amenity = '' end
	if amenity == 'social_centre' then amenity = '' end
	if amenity == 'telephone' then amenity = '' end
	if amenity == 'townhall' then amenity = '' end
	if amenity == 'university' then amenity = '' end


	if amenity == '' and tourism == '' and waterway ~= 'waterfall' and natural ~= 'spring' and ford == '' and historic == '' and highway ~= 'trailhead' then return end

	local wikidata = Find('wikidata')
	local name = Find('name')

	if name == 'Trail Sign' then return end

	if tourism == 'camp_site' then
		name = string.gsub(name, ' Camp$', '')
		name = string.gsub(name, ' Campsite$', '')
		name = string.gsub(name, ' Campground$', '')
	end

	if is_area then
		LayerAsCentroid('poi')
	else
		Layer('poi')
	end

	Attr('ford', ford)
	Attr('waterway', waterway)
	Attr('amenity', amenity)
	Attr('natural', natural)
	Attr('historic', historic)
	Attr('highway', highway)
	Attr('locker', locker)
	Attr('tourism', tourism)
	Attr('wikidata', wikidata)
	Attr('shelter_type', shelter_type)
	Attr('toilets:disposal', toilets_disposal)
	Attr('name', name)
	Attr('osm_id', Id())
end

function node_function()
	maybe_emit(false)
end

function way_function()
	maybe_emit(true)
end
