-- Emit JSON lines data suitable for building an autosuggest index.
--
-- The `zindex` name is chosen because it sorts last, so running `export-all` will
-- first build the GeoJSON outputs that this script depends on for finding states
-- and countries.

local file_append = require 'file_append'
local json = require 'json'
local qrank = nil
local geometry = require 'geometry'

local dump_filename = os.getenv('DUMP_FILENAME')

node_keys = {
	'place=city',
	'place=town',
	'place=village',
	'boundary=national_park',
	'boundary=protected_area',
	'leisure=nature_reserve',
	'natural=peak',
	'natural=volcano',
	'tourism=camp_site',
	'waterway=waterfall',
}
way_keys = {
	'boundary=national_park',
	'boundary=protected_area',
	'landuse=recreation_ground',
	'leisure=nature_reserve',
	'leisure=park',
	'natural=cliff',
	'tourism=camp_site',
	'water=lake',
	'highway=path',
	'highway=footway',
}

function sanitize_park(x)
	x = string.gsub(x, 'National Park', 'NP')
	x = string.gsub(x, 'State Park', 'SP')
	x = string.gsub(x, 'Provincial Park', 'PP')
	x = string.gsub(x, 'National Forest', 'NF')
	return x
end

-- The feature of `layer` that the current object is in, for the context
-- shown with a search result ("Lake X, Y Park, Z State"), or nil: the one
-- covering more than half of the object's area (a point: the one it's in).
--
-- Taking the first intersecting feature gave nonsense for big objects, e.g.
-- "Lake Huron, Pinery PP, Michigan" (hikeratlas/website#10): a lake touches
-- many shoreline parks, and more than one state. Requiring the feature to
-- cover the object entirely was too strict instead: a campground poking out
-- of its park, or a park whose edge strays a few metres over a provincial
-- border, lost its context.
--
-- States and countries cover all the land and water, so an object that
-- touches only one is in it: skip measuring overlaps, which is slow against
-- a whole province. Parks don't: Lake Huron touches just one, and isn't in it.
function containing(layer, one_is_enough)
	if one_is_enough then
		local hits = FindIntersecting(layer)
		if #hits <= 1 then return hits[1] end
	end
	return LargestIntersecting(layer, 0.5)
end

-- Metres from an ele tag: "2830", "2830 m", "2,830", "9285 ft"; nil if not
-- a number.
function elevation(v)
	if v == nil or v == '' then return nil end
	local n, unit = string.match(string.gsub(v, ',', ''), '^%s*(-?[%d%.]+)%s*(%a*)')
	n = tonumber(n)
	if not n then return nil end
	if unit == 'ft' or unit == 'feet' then n = n * 0.3048 end
	return math.floor(n + 0.5)
end

function emit(properties, area)
	local sanitized_properties = {name=Find('name')}
	local wikidata = Find('wikidata')

	for k, v in pairs(properties) do
		if v ~= "" then
			sanitized_properties[k] = v
		end
	end

	local encoded = json.encode(sanitized_properties)
	if encoded == '[]' then return end
	if sanitized_properties['name'] == nil or sanitized_properties['name'] == '' then return end

	local centroid = Centroid('polylabel')
	if not centroid then return end

	local state = containing('states', true)
	if state then sanitized_properties['state'] = state end

	local country = containing('countries', true)
	if country then sanitized_properties['country'] = country end

	if sanitized_properties['kind'] ~= 'park' then
		local park = containing('parks')
		if park then sanitized_properties['park'] = sanitize_park(park) end
	end

	sanitized_properties['lat'] = centroid[1]
	sanitized_properties['lon'] = centroid[2]
	local rank = qrank.get(wikidata)
	sanitized_properties['qrank'] = rank

	if wikidata ~= '' then
		sanitized_properties['wikidata'] = wikidata
	end
	sanitized_properties['osm_id'] = Id()

	local geom = GeoJSON(area or false)
	if geom then geom = json.decode(geom) end
	local box = geometry.box(geom)
	sanitized_properties['box'] = box
	-- A trail's length, for its search result (website#44).
	if sanitized_properties['kind'] == 'trail' then
		local km = geometry.line_km(geom)
		if km and km > 0 then sanitized_properties['km'] = math.floor(km * 10 + 0.5) / 10 end
	end

	encoded = json.encode(sanitized_properties)
	file_append.write(dump_filename, encoded .. '\n')
end


function init_function()
	qrank = require 'qrank' 
	qrank.init()
end

function exit_function()
	qrank.close()
end

-- Places people search for by name, e.g. to find hiking near a town.
-- Mapped as nodes in North America; smaller places (hamlets etc.) are left out.
local searchable_places = { city=true, town=true, village=true }

function node_function()
	local place = Find('place')
	if searchable_places[place] then
		return emit({kind=place})
	end

  local natural = Find('natural')
  local tourism = Find('tourism')
	local waterway = Find('waterway')
	local boundary = Find('boundary')
	local leisure = Find('leisure')

	-- Some parks are mapped as a single node, e.g. Ivanhoe Lake Provincial Park:
	-- https://www.openstreetmap.org/node/3046004352
	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
		return emit({kind='park'})
	end

	if waterway == 'waterfall' then
		return emit({kind='waterfall'})
	end
	-- Volcanoes are peaks too (#150): Mount Price is natural=volcano.
	if natural == 'peak' or natural == 'volcano' then
		-- Elevation for the search result's second line (website#44):
		-- "2830", "2830 m" or "9285 ft" are all mapped.
		local ele = elevation(Find('ele'))
		return emit({kind='peak', ele=ele})
	end

	if tourism == 'camp_site' then
		return emit({kind='camp_site'})
	end
end

-- Trails people search for by name (website#11): the West Coast Trail is a
-- hiking route relation, the Skerwink Trail only named ways. Only in parks:
-- named footways are mostly city sidewalks and plazas. A trail's ways are
-- merged into one result by bin/create-autosuggest-db.ts.
local trail_highways = { path=true, footway=true }

function is_trail_way()
	return trail_highways[Find('highway')] and Find('name') ~= ''
		and (Intersects('parks') or Intersects('city_parks'))
end

function way_function()
	if is_trail_way() then
		return emit({kind='trail'})
	end

  local boundary = Find('boundary')
  local leisure = Find('leisure')
  local landuse = Find('landuse')
  local tourism = Find('tourism')
  local water = Find('water')

	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
		return emit({kind='park'}, true)
	end

	if water == 'lake' then
		return emit({kind='lake', area=math.floor(Area())}, true)
	end

	if tourism == 'camp_site' then
		return emit({kind='camp_site'}, true)
	end

	-- Usually a line along the top of the cliff, e.g. Barron Canyon:
	-- https://www.openstreetmap.org/way/1190940447
	-- Not cliff nodes: many are points and peninsulas (e.g. node/1402749898,
	-- "Long Point"), or scattered markers along an escarpment.
	if Find('natural') == 'cliff' then
		return emit({kind='cliff'}, IsClosed())
	end
end

function relation_scan_function()
  local boundary = Find('boundary')
  local leisure = Find('leisure')
  local landuse = Find('landuse')
  local water = Find('water')
  local tourism = Find('tourism')

	if boundary == 'national_park' or
		boundary == 'protected_area' or
		leisure == 'nature_reserve' or
		tourism == 'camp_site' or
		water == 'lake' or
		is_trail_relation() then
		Accept()
	end
end

-- Hiking route relations (not superroutes, which only group them: the
-- Appalachian Trail's are per state).
local trail_routes = { hiking=true, foot=true }

function is_trail_relation()
	return Find('type') == 'route' and trail_routes[Find('route')] and Find('name') ~= ''
end

function relation_function()
	-- Tongass National Forest: polylabel, FindIntersecting and GeoJSON on its
	-- huge geometry took ~23 minutes. Skip it until tilemaker handles it faster.
	if Id() == '6535292' then return end

  local boundary = Find('boundary')
  local leisure = Find('leisure')
  local landuse = Find('landuse')
  local tourism = Find('tourism')
  local water = Find('water')

	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
		return emit({kind='park'}, true)
	end

	if tourism == 'camp_site' then
		return emit({kind='camp_site'}, true)
	end

	if water == 'lake' then
		return emit({kind='lake', area=math.floor(Area())}, true)
	end

	if is_trail_relation() then
		return emit({kind='trail', relation=true})
	end
end
