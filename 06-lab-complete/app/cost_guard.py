"""Atomic UTC budgets with reservation and reconciliation in Redis.

Fixed prices below are mock accounting values, not live provider prices.
Integer nanodollars avoid accumulating floating-point error.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import uuid

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r, unavailable

PRICE_INPUT_PER_1K = Decimal("0.00015")
PRICE_OUTPUT_PER_1K = Decimal("0.0006")
UNITS_PER_USD = 1_000_000_000

RESERVE_SCRIPT = """
local amount = tonumber(ARGV[1])
for i = 1, 2 do
    local used = tonumber(redis.call('GET', KEYS[i]) or '0')
    local limit = tonumber(ARGV[i + 1])
    if used >= limit or used + amount > limit then return 0 end
end
for i = 1, 2 do
    redis.call('INCRBY', KEYS[i], amount)
    redis.call('EXPIREAT', KEYS[i], ARGV[i + 3])
end
redis.call('SET', KEYS[3], amount, 'EX', 86400)
return 1
"""

SETTLE_SCRIPT = """
local held = redis.call('GET', KEYS[3])
if not held then return -1 end
local reserved = tonumber(held)
if not reserved then return 0 end
local actual = tonumber(ARGV[1])
if actual > reserved then return -1 end
for i = 1, 2 do
    redis.call('INCRBY', KEYS[i], actual - reserved)
end
redis.call('SET', KEYS[3], ARGV[2], 'EX', 86400)
return 1
"""


@dataclass(frozen=True)
class Reservation:
    keys: tuple[str, str, str]


def token_cost_units(input_tokens: int, output_tokens: int) -> int:
    if input_tokens < 0 or output_tokens < 0:
        raise ValueError("Token counts cannot be negative")
    return int((input_tokens * PRICE_INPUT_PER_1K + output_tokens * PRICE_OUTPUT_PER_1K)
               * UNITS_PER_USD / 1000)


def check_budget(input_tokens: int = 0, output_tokens: int = 0) -> Reservation:
    now = datetime.now(timezone.utc)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    next_month = (now.replace(day=28) + timedelta(days=4)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    prefix = f"{settings.redis_prefix}:budget"
    keys = (
        f"{prefix}:day:{now:%Y-%m-%d}",
        f"{prefix}:month:{now:%Y-%m}",
        f"{prefix}:reservation:{uuid.uuid4().hex}",
    )
    try:
        allowed = r.eval(
            RESERVE_SCRIPT, 3, *keys,
            token_cost_units(input_tokens, output_tokens),
            int(settings.daily_budget_usd * UNITS_PER_USD),
            int(settings.monthly_budget_usd * UNITS_PER_USD),
            int((tomorrow + timedelta(days=1)).timestamp()),
            int((next_month + timedelta(days=1)).timestamp()),
        )
    except RedisError as exc:
        raise unavailable() from exc
    if not allowed:
        raise HTTPException(status_code=402, detail="Budget exhausted or insufficient for this request")
    return Reservation(keys)


def settle(reservation: Reservation, actual_units: int, state: str) -> None:
    try:
        result = r.eval(SETTLE_SCRIPT, 3, *reservation.keys, actual_units, state)
    except RedisError as exc:
        raise unavailable() from exc
    if result < 0:
        raise HTTPException(status_code=503, detail="Could not reconcile usage")


def record_cost(input_tokens: int, output_tokens: int, reservation: Reservation | None = None) -> float:
    units = token_cost_units(input_tokens, output_tokens)
    reservation = reservation or check_budget(input_tokens, output_tokens)
    settle(reservation, units, "settled")
    return units / UNITS_PER_USD


def release_reservation(reservation: Reservation) -> None:
    settle(reservation, 0, "released")
