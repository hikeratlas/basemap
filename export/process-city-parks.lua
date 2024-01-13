-- A script to export city parks -- we'll use this for future
-- spatial queries in our main Lua profile, to give increased prominence
-- to things in parks.

-- Sample command line: tilemaker --input north-america-latest.osm.pbf --output city_parks.geojson --config config-city-parks.json --process process-city-parks.lua

way_keys = {'leisure=park', 'landuse=recreation_ground'}

function node_function()
end

function way_function()
	local landuse
	local leisure

	-- If the way is only being included due to a relation, do nothing.
	while true do
		local rel = NextRelation()
		if not rel then break end

		leisure = FindInRelation('leisure')
		landuse = FindInRelation('landuse')
		if leisure == 'park' or landuse == 'recreation_ground' then
			return
		end
	end

	-- If you don't have a name, you're probably not well-enough detailed
	-- to be included, eg https://www.openstreetmap.org/way/989294968
	-- is a broken item.
	local name = Find('name')

	if name == '' then return end

	leisure = Find('leisure')
	landuse = Find('landuse')
	if leisure == 'park' or landuse == 'recreation_ground' then
		Layer('polys', true)
		Attribute('name', name)
		Attribute('leisure', leisure)
		Attribute('landuse', landuse)
		Attribute('wikidata', Find('wikidata'))
		Attribute('osm_id', Id())
	end
end

function relation_scan_function()
  local leisure = Find('leisure')
  local landuse = Find('landuse')

	if leisure == 'park' or landuse == 'recreation_ground' then
		Accept()
	end
end

function relation_function()
  local leisure = Find('leisure')
  local landuse = Find('landuse')

	if leisure == 'park' or landuse == 'recreation_ground' then
		Layer('polys', true)
		Attribute('name', Find('name'))
		Attribute('leisure', leisure)
		Attribute('landuse', landuse)
		Attribute('wikidata', Find('wikidata'))
		Attribute('osm_id', Id())
	end
end
