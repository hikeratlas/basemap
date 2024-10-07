qrank = nil

local function Attr(k, v) if v ~= '' then Attribute(k, v) end end

function init_function()
	qrank = require 'qrank' 
	qrank.init()
end

function exit_function()
	qrank.close()
end

way_keys = {'boundary=protected_area', 'boundary=national_park', 'leisure=nature_reserve', 'leisure=park', 'landuse=recreation_ground'}

function node_function()
end

function get_short_name(x)
	x = string.gsub(x, 'National Park', 'NP')
	x = string.gsub(x, 'State Park', 'SP')
	x = string.gsub(x, 'Provincial Park', 'PP')
	x = string.gsub(x, 'National Forest', 'NF')

	return x
end

function maybe_emit()
	-- If you don't have a name, you're probably not well-enough detailed
	-- to be included, eg https://www.openstreetmap.org/way/989294968
	-- is a broken item.
	local name = Find('name')
	if name == '' then return end

	local protection_title = Find('protection_title')
	-- Highways aren't areas of natural beauty: https://www.openstreetmap.org/relation/166587
	-- (The Blue Ridge Parkway _is_ gorgeous! It's just jarring to see it prominently
	-- highlighted on a hiking-focused map.)
	if protection_title == 'National Parkway' then return end

	local wikidata = Find('wikidata')
	local rank = qrank.get(wikidata)
	local short_name = get_short_name(name)
	local boundary = Find('boundary')
	local leisure = Find('leisure')
	local landuse = Find('landuse')
	if boundary ~= 'national_park' and boundary ~= 'protected_area' and leisure ~= 'nature_reserve' and leisure ~= 'park' and landuse ~= 'recreation_ground' then return end

	local area = math.ceil(Area())

	-- For now, ignore maritime parks. In the future, maybe we just draw a dark
	-- blue border around them, but don't fill them?
	--
	-- Examples:
	-- https://www.openstreetmap.org/relation/9064770
	-- https://www.openstreetmap.org/way/268507821
	--
	if Find('maritime') == 'yes' or
		string.find(name, 'Estuary ', 1, true) ~= nil or
		string.find(name, 'Aquatic ', 1, true) ~= nil or
		string.find(name, 'Marine ', 1, true) ~= nil or
		string.find(name, 'River Delta', 1, true) ~= nil then
		return
	end

	mz = 0

	if area < 200000000 then
		mz = 5
	end
	if area < 160000000 then
		mz = 7
	end
	if area < 36000000 then
		mz = 8
	end
	if area < 450000 then
		mz = 10
	end


	Layer('park', true)
	MinZoom(mz)
	Attr('name', name)
	AttributeNumeric('rank', rank)
	Attr('short_name', short_name)
	Attr('boundary', boundary)
	Attr('leisure', leisure)
	Attr('landuse', landuse)
	Attr('wikidata', wikidata)
	Attr('area', area)
	Attr('osm_id', Id())

	Layer('park_outline', false)
	Attr('name', name)
	AttributeNumeric('rank', rank)
	Attr('boundary', boundary)
	Attr('leisure', leisure)
	Attr('landuse', landuse)
	Attr('wikidata', wikidata)
	Attr('area', area)
	Attr('osm_id', Id())

	if string.find(name, 'Land Use Zone', 1, true) ~= nil then
		mz = 10
	end
	LayerAsCentroid('park_name')
	MinZoom(mz)
	AttributeNumeric('rank', rank)
	Attr('name', name)
	Attr('short_name', short_name)
	Attr('boundary', boundary)
	Attr('leisure', leisure)
	Attr('landuse', landuse)
	Attr('wikidata', wikidata)
	Attr('osm_id', Id())
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
		landuse = FindInRelation('landuse')
		if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' or leisure == 'park' or landuse == 'recreation_ground' then
			return
		end
	end

	maybe_emit()
end

function relation_scan_function()
  local boundary = Find('boundary')
  local leisure = Find('leisure')
  local landuse = Find('landuse')

	if boundary == 'national_park' or boundary == 'protected_area' or leisure == 'nature_reserve' or landuse == 'recreation_ground' then
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

	maybe_emit()
end
