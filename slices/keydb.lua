-- THIS MODULE IS INCREDIBLY UNSAFE.
--
-- It is OK in this particular project because its callers use it safely.

local keydb = {}

function get_pid()
	local pid = ''
	-- Read the PID from procfs
	local path = '/proc/self/stat'
	local file = io.open(path, "rb") 
	if not file then error({msg="cannot open " .. path}) end

	for line in io.lines(path) do
		for word in line:gmatch("%w+") do 
			pid = word
			break
		end    
		break
	end

	file:close()
	if pid == '' then error({msg="failed to read pid"}) end
	return pid
end

function keydb.init()
	local pid = get_pid()

	print('init: pid=' .. pid)
	keydb.tmp_dir = '/tmp/basemap_' .. pid

	-- yolo.
	os.execute('mkdir -p ' .. keydb.tmp_dir)
end

-- NB: `id` must be a safe filename.
-- This is incredibly dangerous; use with caution.
function keydb.set(id)
	local file = io.open(keydb.tmp_dir .. '/' .. id, "w")
	file:close()
end

function keydb.test(id)
	local file = io.open(keydb.tmp_dir .. '/' .. id, "rb") 
	if not file then return false end
	file:close()
	return true
end

return keydb
