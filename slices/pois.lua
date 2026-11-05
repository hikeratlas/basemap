node_keys = {'amenity', 'tourism', 'waterway=waterfall', 'ford', 'historic', 'natural=spring', 'highway=trailhead'}
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
	-- Campgrounds count, too: some parks have no area to be in (e.g. Ivanhoe
	-- Lake Provincial Park is a node), but their campgrounds do. A campground
	-- area is inside itself, so it gets its own icon and label.
	local in_campground = Intersects('campgrounds')
	-- Trail networks outside parks that hikeratlas/routes curates (see
	-- bin/trail-areas.py), e.g. the Skerwink Trail: their viewpoints and
	-- parking matter as a park's do.
	local in_trail_area = Intersects('trail_areas')

	-- Outside parks, keep only parking lots and trailheads within 2 km of
	-- one (parks_near, from bin/parks-near.py): many hikes start just
	-- outside a park's boundary, and hikeratlas/routes starts its hikes
	-- from these.
	if not in_park and not in_city_park and not in_campground and not in_trail_area then
		local access = Find('access')
		local trailhead = Find('amenity') == 'parking' or Find('highway') == 'trailhead'
		if not trailhead or access == 'private' or access == 'no' or access == 'customers' then return end
		if not Intersects('parks_near') then return end
	end

	local tourism = Find('tourism')

	local amenity = Find('amenity')
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
	-- In a park proper (not just a city park or near one): the style shows
	-- unstyled POIs there from z12, so nothing in a park goes unnoticed.
	if in_park then AttributeBoolean('in_park', true) end
end

function node_function()
	maybe_emit(false)
end

function way_function()
	maybe_emit(true)
end
