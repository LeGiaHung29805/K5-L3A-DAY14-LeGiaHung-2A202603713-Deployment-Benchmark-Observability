"""Validated environment configuration; no credentials in source."""
import os
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)


def positive_integer(name: str, default: int, maximum: int, minimum: int = 1) -> int:
    value = int(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def budget(name: str, default: str) -> Decimal:
    try:
        value = Decimal(os.getenv(name, default))
    except InvalidOperation as exc:
        raise ValueError(f"{name} must be a decimal number") from exc
    if not value.is_finite() or not Decimal(0) <= value <= Decimal("1000000"):
        raise ValueError(f"{name} must be finite and between 0 and 1000000")
    return value


@dataclass(frozen=True)
class Settings:
    port: int = field(default_factory=lambda: positive_integer("PORT", 8000, 65535))
    environment: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "development"))
    agent_api_key: str = field(default_factory=lambda: os.getenv("AGENT_API_KEY", ""))
    redis_url: str = field(default_factory=lambda: os.getenv("REDIS_URL") or "redis://localhost:6379/0")
    redis_namespace: str = field(default_factory=lambda: os.getenv("REDIS_NAMESPACE", "day14"))
    rate_limit_per_minute: int = field(default_factory=lambda: positive_integer("RATE_LIMIT_PER_MINUTE", 10, 1000000))
    daily_budget_usd: Decimal = field(default_factory=lambda: budget("DAILY_BUDGET_USD", "1"))
    monthly_budget_usd: Decimal = field(default_factory=lambda: budget("MONTHLY_BUDGET_USD", "10"))
    max_output_tokens: int = field(default_factory=lambda: positive_integer("MAX_OUTPUT_TOKENS", 500, 8192, minimum=2))
    history_max_turns: int = field(default_factory=lambda: positive_integer("HISTORY_MAX_TURNS", 50, 200))
    history_ttl_seconds: int = field(default_factory=lambda: positive_integer("HISTORY_TTL_SECONDS", 86400, 604800))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    @property
    def redis_prefix(self) -> str:
        return f"{self.redis_namespace}:{self.environment}"


settings = Settings()
