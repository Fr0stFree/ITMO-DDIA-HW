local rateLimiterKey = "rate:" .. ARGV[1]
local limit = tonumber(ARGV[2])
local timeWindow = tonumber(ARGV[3])

local requestsAmount = redis.call("INCR", rateLimiterKey)

if requestsAmount == 1 then
    redis.call("EXPIRE", rateLimiterKey, timeWindow)
end

local shouldDeny = requestsAmount > limit
if shouldDeny then
    return "DENY"
else
    return "OK"
end
