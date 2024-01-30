local debug = false

way_keys = {'natural=water', 'water', 'waterway'}

function init_function()
end

function exit_function()
end

function node_function()
end

function maybe_emit()
	local name = Find('name')
  local natural = Find('natural')
  local water = Find('water')
  local waterway = Find('waterway')

	local id = Id()

	if not (natural == 'water' or water == 'lake' or waterway == 'river' or waterway == 'stream') then return end

	local isClosed = IsClosed()
	local area = 0
	if isClosed then
		area = math.ceil(Area())
	end

	mz = 6

	if not isClosed then
		mz = 10
		if name == '' then
			mz = 11
		end
	end

	if isClosed then
		if area < 10000000 then
			mz = 7
		end

		if area < 3000000 then
			mz = 8
		end

		if area < 1000000 then
			mz = 9
		end
		if area < 500000 then
			mz = 10
		end
	end

	-- List of honkin' big lakes in North America, from
	-- https://en.wikipedia.org/wiki/List_of_lakes_by_area#Geological_list
	if id == '1206310' -- Lake Ontario
		or id == '1205151' -- Lake Huron
		or id == '1205149' -- Lake Michigan
		or id == '4039486' -- Lake Superior
		or id == '4039900' -- Lake Erie
		or id == '2791372' -- Great Bear Lake
		or id == '1834172' -- Great Slave Lake
		or id == '1259563' -- Lake Winnipeg
	then
		mz = 4
	end


	local layer = 'water_line'
	if isClosed then layer = 'water_poly' end

	local name_layer = 'water_line_name'
	if isClosed then name_layer = 'water_poly_name' end

	kind = 'lake'
	if waterway == 'river' or waterway == 'stream' then kind = waterway end

	Layer(layer, isClosed)
	MinZoom(mz)
	Attribute('name', name)
	Attribute('kind', kind)
	Attribute('wikidata', Find('wikidata'))
	Attribute('intermittent', Find('intermittent'))
	Attribute('seasonal', Find('seasonal'))
	if isClosed then
		Attribute('area', area)
	end
	if debug then
		Attribute('osm_id', Id())
	end

	if name == '' then return end

	if isClosed then
		LayerAsCentroid(name_layer)
	else
		Layer(name_layer, false)
	end
	MinZoom(mz)
	Attribute('name', name)
	Attribute('kind', kind)
	Attribute('wikidata', Find('wikidata'))
	if debug then
		Attribute('osm_id', Id())
	end
end

function way_function()
	local boundary

	-- If the way is only being included due to a relation, do nothing.
	-- The great lakes are part of the Great Lakes relation -- so
	-- only do these checks if we think the current object is not itself
	-- a multipolygon relation
	while Find('type') ~= 'multipolygon' do
		local rel = NextRelation()
		if not rel then break end

		local water = FindInRelation('water')
		local waterway = FindInRelation('waterway')
		local natural = FindInRelation('natural')
		if natural == 'water' or water == 'lake' or waterway == 'river' or waterway == 'stream' then
			return
		end
	end

	maybe_emit()
end

function relation_scan_function()
  local water = Find('water')
  local waterway = Find('waterway')
  local natural = Find('natural')

	if natural == 'water' or water == 'lake' or waterway == 'river' or waterway == 'stream' then
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
