local logger = {}
local json = require 'json'
local file_append = require 'file_append'

local dump_filename = os.getenv('DUMP_FILENAME')

local data = {}

function pump()
	local entry = data
	data = {}

	if not entry['name'] then return end

	-- Some layers are duplicates of others; ignore them.
	if entry['_layer'] == 'road_name' then return end
	if entry['_layer'] == 'path_name' then return end
	if entry['_layer'] == 'water_line_name' then return end
	if entry['_layer'] == 'water_poly_name' then return end

	local encoded = json.encode(entry)
	if encoded ~= '[]' then
		file_append.write(dump_filename, encoded .. '\n')
	end
end

function _Layer(name)
	pump()
	data['_layer'] = name
	data['_ll'] = Centroid('polylabel')
	data['_id'] = Id()
end

function _LayerAsCentroid(name)
	pump()
	data['_layer'] = name
	data['_ll'] = Centroid('polylabel')
	data['_id'] = Id()
end

function _Attribute(key, value)
	if value == '' or key == 'osm_id' then return end
	data[key] = value
end

function _AttributeBoolean(key, value)
	data[key] = value
end

function _AttributeNumeric(key, value)
	data[key] = value
end

function logger.init()
	if dump_filename ~= nil then
		local realLayer = Layer
		Layer = function (name, as_area)
			realLayer(name, as_area)
			_Layer(name)
		end

		local realLayerAsCentroid = LayerAsCentroid
		LayerAsCentroid = function (name)
			realLayerAsCentroid(name)
			_LayerAsCentroid(name)
		end

		local realAttribute = Attribute
		Attribute = function (key, value)
			realAttribute(key, value)
			_Attribute(key, value)
		end

		local realAttributeBoolean = AttributeBoolean
		AttributeBoolean = function (key, value)
			realAttributeBoolean(key, value)
			_AttributeBoolean(key, value)
		end

		local realAttributeNumeric = AttributeNumeric
		AttributeNumeric = function (key, value)
			realAttributeNumeric(key, value)
			_AttributeNumeric(key, value)
		end

	end
end

function logger.close()
	pump()
end


return logger
