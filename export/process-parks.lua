-- A script to export protected areas -- we'll use this for future
-- spatial queries in our main Lua profile, to give increased prominence
-- to things in parks.

-- Sample command line: tilemaker --input north-america-latest.osm.pbf --output parks.geojson --config config-parks.json --process process-parks.lua

way_keys = {'boundary=protected_area', 'boundary=national_park', 'leisure=nature_reserve'}

function node_function()
end

function way_function()
	local boundary
	local leisure

	-- If the way is only being included due to a relation, do nothing.
	while true do
		local rel = NextRelation()
		if not rel then break end

		boundary = FindInRelation('boundary')
		leisure = FindInRelation('leisure')
		if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
			return
		end
	end

	-- If you don't have a name, you're probably not well-enough detailed
	-- to be included, eg https://www.openstreetmap.org/way/989294968
	-- is a broken item.
	local name = Find('name')

	if name == '' then return end

	boundary = Find('boundary')
	leisure = Find('leisure')
	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
		Layer('polys', true)
		Attribute('name', Find('name'))
		Attribute('boundary', boundary)
		Attribute('leisure', Find('leisure'))
		Attribute('wikidata', Find('wikidata'))
		Attribute('osm_id', Id())
	end
end

function relation_scan_function()
  local boundary = Find('boundary')
  local leisure = Find('leisure')

	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
		Accept()
	end
end

function relation_function()
  local id = Id()

	-- Ignore some broken relations.
	if id == '11538224' then return end
	if id == '12180623' then return end
	if id == '6495680' then return end
	if id == '6535292' then return end -- Tongass National Park

  local boundary = Find('boundary')
  local leisure = Find('leisure')

	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
		Layer('polys', true)
		Attribute('name', Find('name'))
		Attribute('boundary', boundary)
		Attribute('leisure', Find('leisure'))
		Attribute('wikidata', Find('wikidata'))
		Attribute('osm_id', Id())
	end
end
