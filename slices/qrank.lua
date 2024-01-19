-- A module to lookup an OSM item's qrank, if it has a Wikidata ID.
-- See https://qrank.wmcloud.org/ for more info.
local qrank = {}

local driver = nil
local env = nil
local con = nil

function qrank.init()
	driver = require 'luasql.sqlite3'
	env = assert (driver.sqlite3())
	con = assert (env:connect('../qrank.db'))
end

function qrank.close()
	con:close()
	env:close()
end

-- id: a Wikidata ID, eg Q1261
--
-- Returns the item's qrank, or 1 if it has none.
function qrank.get(id)
	if id == '' then
		return 1
	end
	local rv = 1

	local sql = "SELECT qrank FROM qrank WHERE id = '" .. con:escape(string.sub(id, 2, 100)) .. "'"
	cur = assert (con:execute(sql))
	row = cur:fetch({}, 'a')
	if row ~= nil then
		rv = row['qrank'] or 1
	end
	cur:close()
	return rv
end

return qrank
