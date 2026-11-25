"""Bounded conversation turns, isolated by credential and stored atomically in Redis."""
from datetime import datetime, timezone
import hashlib
import json
from uuid import UUID

from fastapi import HTTPException
from redis.exceptions import RedisError

from app.config import settings
from app.redis_client import r, unavailable

APPEND_SCRIPT = """
redis.call('RPUSH', KEYS[1], ARGV[1])
redis.call('LTRIM', KEYS[1], -tonumber(ARGV[2]), -1)
redis.call('EXPIRE', KEYS[1], ARGV[3])
return redis.call('LLEN', KEYS[1])
"""


def history_key(api_key: str, session_id: UUID) -> str:
    owner = hashlib.sha256(api_key.encode()).hexdigest()
    return f"{settings.redis_prefix}:history:{owner}:{session_id}"


def append_turn(api_key: str, session_id: UUID, question: str, answer: str, cost_usd: float) -> int:
    turn = json.dumps({"question": question, "answer": answer, "cost_usd": cost_usd,
                       "created_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False)
    try:
        turns = r.eval(APPEND_SCRIPT, 1, history_key(api_key, session_id), turn,
                       settings.history_max_turns, settings.history_ttl_seconds)
    except RedisError as exc:
        raise unavailable() from exc
    return int(turns) * 2


def read_history(api_key: str, session_id: UUID) -> list[dict]:
    try:
        turns = r.lrange(history_key(api_key, session_id), 0, -1)
    except RedisError as exc:
        raise unavailable() from exc
    if not turns:
        raise HTTPException(status_code=404, detail="Session not found")
    messages = []
    for raw in turns:
        turn = json.loads(raw)
        messages.extend([
            {"role": "user", "content": turn["question"]},
            {"role": "assistant", "content": turn["answer"]},
        ])
    return messages
