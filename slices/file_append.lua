-- Thread-safe file append.
--
-- tilemaker runs multiple threads, we use POSIX file locks to synchronize
-- writes.

local M = require 'posix.fcntl'
local S = require 'posix.sys.stat'

local file_append = {}

function sleep(n)
  os.execute("sleep " .. tonumber(n))
end

function file_append.write(fname, data)
	local fd = M.open(
		'/tmp/tilemaker.lock',
		M.O_CREAT + M.O_WRONLY + M.O_TRUNC,
		S.S_IRUSR + S.S_IWUSR + S.S_IRGRP + S.S_IROTH
	)

	-- Set lock on file
	local lock = {
		l_type = M.F_WRLCK;     -- Exclusive lock
		l_whence = M.SEEK_SET;  -- Relative to beginning of file
		l_start = 0;            -- Start from 1st byte
		l_len = 0;              -- Lock whole file
	}

	while M.fcntl(fd, M.F_SETLK, lock) == nil do
		-- Yeah, spinlocks aren't great. What are ya gonna do.
	end

	local out = io.open(fname, 'a')
	out:write(data)
	io.close(out)

	-- Release the lock
	lock.l_type = M.F_UNLCK
	M.fcntl(fd, M.F_SETLK, lock)
end

return file_append
