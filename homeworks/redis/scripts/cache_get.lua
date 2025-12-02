local key = ARGV[1]
local value = redis.call("GET", key)

return value
