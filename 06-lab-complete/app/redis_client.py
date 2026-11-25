"""Lazy Redis connection: importing the app never pings Redis."""
import redis
from fastapi import HTTPException

from app.config import settings

r = redis.from_url(
    settings.redis_url, decode_responses=True,
    socket_connect_timeout=1, socket_timeout=1, health_check_interval=30,
)


def redis_healthy() -> bool:
    try:
        return bool(r.ping())
    except redis.RedisError:
        return False


def unavailable() -> HTTPException:
    return HTTPException(status_code=503, detail="Redis unavailable", headers={"Retry-After": "1"})
