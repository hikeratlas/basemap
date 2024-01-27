-- Thread-safe file append.
--
-- tilemaker runs multiple threads, we use BSD-style file locks to synchronize
-- writes.

print('file_append')
print(package.path)
local flock = require "flock"
print('file_append after flock')
print(flock)

local file_append = {}

function file_append.write(fname, data)
	-- see https://github.com/SolraBizna/luaflock
	local lockf = io.open('/tmp/tilemaker.lock', 'a+')

	local locked, lock_error = flock(lockf, 'write')

	if not locked or lock_error then
		error('unable to lock file: ' .. str(lock_error))
	end

	local out = io.open(fname, 'a')
	out:write(data)
	io.close(out)

	-- Closing the lock file releases the lock.
	io.close(lockf)
end

return file_append
