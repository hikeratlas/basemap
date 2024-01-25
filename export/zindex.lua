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
	'natural=peak',
	'tourism=camp_site',
	'waterway=waterfall',
}
way_keys = {
	'boundary=national_park',
	'boundary=protected_area',
	'landuse=recreation_ground',
	'leisure=nature_reserve',
	'leisure=park',
	'tourism=camp_site',
	'water=lake',
}

function sanitize_park(x)
	x = string.gsub(x, 'National Park', 'NP')
	x = string.gsub(x, 'State Park', 'SP')
	x = string.gsub(x, 'Provincial Park', 'PP')
	x = string.gsub(x, 'National Forest', 'NF')
	return x
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

	local state = FindIntersecting('states')[1]
	if state then sanitized_properties['state'] = state end

	local country = FindIntersecting('countries')[1]
	if country then sanitized_properties['country'] = country end

	if sanitized_properties['kind'] ~= 'park' then
		local park = FindIntersecting('parks')[1]
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

function node_function()
  local natural = Find('natural')
  local tourism = Find('tourism')
	local waterway = Find('waterway')

	if waterway == 'waterfall' then
		return emit({kind='waterfall'})
	end
	if natural == 'peak' then
		return emit({kind='peak'})
	end

	if tourism == 'camp_site' then
		return emit({kind='camp_site'})
	end
end

function way_function()
  local boundary = Find('boundary')
  local leisure = Find('leisure')
  local landuse = Find('landuse')
  local tourism = Find('tourism')
  local water = Find('water')

	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' then
		return emit({kind='park'}, true)
	end

	if water == 'lake' then
		return emit({kind='lake'}, true)
	end

	if tourism == 'camp_site' then
		return emit({kind='camp_site'}, true)
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
		water == 'lake' then
		Accept()
	end
end

function relation_function()
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
		return emit({kind='lake'}, true)
	end
end
