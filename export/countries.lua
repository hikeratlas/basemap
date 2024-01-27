-- A script to export protected areas as GeoJSONL.

print('states')
print('states2')
local file_append = require 'file_append'
print('file_append')
local json = require 'json'
print('json')

local dump_filename = os.getenv('DUMP_FILENAME')

print('dump_filename is ' .. DUMP_FILENAME)

way_keys = {'boundary=administrative'}

function build_feature(geometry, properties)
	sanitized_properties = {}

	for k, v in pairs(properties) do
		if v ~= "" then
			sanitized_properties[k] = v
		end
	end

	return {
		type="Feature",
		geometry=geometry,
		properties=sanitized_properties
	}
end

function dump(is_relation)
	print('dump')
	-- Require a name
	local name = Find('name:en')
	if name == '' then name = Find('name') end
	if name == '' then return end

	local admin_level = get_admin_level(true)

	if admin_level > 4 then return end
	local kind = 'country'
	if admin_level > 2 then kind = 'state' end

	if kind == 'country' and string.find(dump_filename, 'state') then return end
	if kind == 'state' and not string.find(dump_filename, 'state') then return end

	local geojson = GeoJSON(true)
	if not geojson then return end
	local geometry = json.decode(geojson)

	feature = build_feature(
		geometry,
		{
			name=name,
			wikidata=Find('wikidata'),
			osm_id=Id()
		}
	)
	file_append.write(dump_filename, json.encode(feature) .. '\n')
end

function get_admin_level(is_relation)
	print('gal')
	local admin_level = 99
	if is_relation then
		admin_level = Find('admin_level')
	else
		admin_level = FindInRelation('admin_level')
	end
	return tonumber(admin_level) or 99
end

function node_function()
	print('node_function')
end

function way_function()
	print('way_function')
end

function relation_scan_function()
	print('rsf')
  if Find('boundary') == 'administrative' then
    local admin_level = get_admin_level(true)
		-- Accept any relation with admin_level - sometimes ways are mistagged,
		-- and we need to check to see if they're part of a relation with a
		-- high admin_level.
    if admin_level >= 2 then
      Accept()
    end
  end
end

function relation_function()
	print('rf')
	dump(true)
end
