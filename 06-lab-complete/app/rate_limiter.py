"""Atomic sliding window shared across workers and restarts."""
import hashlib
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r, unavailable

WINDOW_SCRIPT = """
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - 60000)
local count = redis.call('ZCARD', KEYS[1])
local limit = tonumber(ARGV[1])
if count >= limit then
    local first = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
    local retry = math.max(1, math.ceil((tonumber(first[2]) + 60000 - now) / 1000))
    return {0, 0, retry}
end
redis.call('ZADD', KEYS[1], now, ARGV[2])
redis.call('PEXPIRE', KEYS[1], 61000)
return {1, limit - count - 1, 0}
"""


def check_rate_limit(key: str) -> dict:
    digest = hashlib.sha256(key.encode()).hexdigest()
    redis_key = f"{settings.redis_prefix}:rate:{digest}"
    try:
        allowed, remaining, retry = r.eval(
            WINDOW_SCRIPT, 1, redis_key, settings.rate_limit_per_minute, uuid.uuid4().hex
        )
    except RedisError as exc:
        raise unavailable() from exc
    headers = {
        "X-RateLimit-Limit": str(settings.rate_limit_per_minute),
        "X-RateLimit-Remaining": str(remaining),
    }
    if not allowed:
        headers["Retry-After"] = str(retry)
        raise HTTPException(status_code=429, detail="Rate limit exceeded", headers=headers)
    return headers
