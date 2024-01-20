local debug = false

node_keys = {'natural=peak'}

function init_function()
end

function exit_function()
end

function node_function()
	local natural = Find('natural')

	if natural ~= 'peak' then return end

	local name = Find('name')

	if name == '' then return end

	local ele = 0
	local orig_ele = Find('ele')

	if orig_ele ~= "" then
		ele = tonumber(orig_ele)

		if ele == nil then
			-- TODO: some peaks seem to have elevation with a semicolon in them?
			-- print(orig_ele)
			ele = 0
		end
	end

	Layer('peak', false)
	Attribute('name', name)

	if ele > 0 then
		Attribute('ele', ele)
	end

	-- TODO/CONSIDER: should we use a blend of qrank and elevation?
	-- eg it'd be nice if Charlie's Bunion showed up: http://localhost:8081/#13.66/35.63611/-83.3814
	ZOrder(ele)
end

function way_function()
end
