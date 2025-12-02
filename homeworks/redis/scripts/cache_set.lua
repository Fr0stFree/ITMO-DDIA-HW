local key = ARGV[1]
local ttl = ARGV[2]
local filePath = ARGV[3]

redis.call("SET", key, filePath)
redis.call("EXPIRE", key, ttl)

return "OK"
