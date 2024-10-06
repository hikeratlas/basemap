way_keys = {'boundary=administrative'}

function init_function()
end

function exit_function()
end

function node_function()
end

function attribute_function(attr, layer)
	if layer == 'ocean' then
		return { class="ocean" }
	end
end

function get_admin_level(is_relation)
	local admin_level = 99
	if is_relation then
		admin_level = Find('admin_level')
	else
		admin_level = FindInRelation('admin_level')
	end
	return tonumber(admin_level) or 99
end

function way_function()
	-- If the way is only being included due to a relation, do nothing.

	local admin_level = 99
	local name = ''
	local short_name = ''
	while true do
		local rel = NextRelation()
		if not rel then break end

		local boundary = FindInRelation('boundary')
		if boundary == 'administrative' then
			local maybe = get_admin_level(false)
			if maybe < admin_level then
				admin_level = maybe
				name = FindInRelation('name')
				short_name = FindInRelation('short_name')
			end
		end
	end

	if admin_level > 4 then return end
	if name == '' then return end

	local kind = 'country'
	if admin_level > 2 then kind = 'state' end


	Layer('boundary', false)
	if kind == 'state' then
		-- TODO: this should vary for smaller countries
		MinZoom(3)
	end
	if debug then
		Attribute('name', name)
		Attribute('short_name', short_name)
		Attribute('osm_id', Id())
	end
	Attribute('kind', kind)
	AttributeBoolean('maritime', Find('maritime') == 'yes')
end

function relation_scan_function()
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
	local admin_level = get_admin_level(true)

	if admin_level > 4 then return end
	local kind = 'country'
	if admin_level > 2 then kind = 'state' end


	LayerAsCentroid('boundary_name')
	if kind == 'state' then
		MinZoom(3)
	end

	local name = Find('name')
	if name ~= '' then Attribute('name', name) end

	local short_name = Find('short_name')
	if short_name ~= '' then Attribute('short_name', short_name) end
	Attribute('kind', kind)
	Attribute('osm_id', Id())
end
