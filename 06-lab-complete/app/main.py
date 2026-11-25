"""Public health, protected requests and shared Redis state for the lab agent."""
from contextlib import asynccontextmanager
import asyncio
from datetime import datetime, timezone
import json
import logging
import os
import time
import uuid

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from app.auth import verify_api_key
from app.config import settings
from app.cost_guard import check_budget, record_cost, release_reservation
from app.history import append_turn, read_history
from app.rate_limiter import check_rate_limit
from app.redis_client import r, redis_healthy
from utils.mock_llm import ask as llm_ask


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "pid": os.getpid(),
        }
        payload.update(getattr(record, "fields", {}))
        return json.dumps(payload, ensure_ascii=False)


logger = logging.getLogger("agent")
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.handlers = [handler]
logger.setLevel(settings.log_level)
logger.propagate = False


@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.shutting_down = False
    logger.info("startup", extra={"fields": {"environment": settings.environment}})
    try:
        yield
    finally:
        # Uvicorn drains requests before lifecycle cleanup. Keep its SIGTERM handler.
        application.state.shutting_down = True
        r.close()
        logger.info("shutdown_complete")


app = FastAPI(title="Production AI Agent", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def request_log(request: Request, call_next):
    request_id = uuid.uuid4().hex
    started = time.monotonic()
    try:
        response = await call_next(request)
    except Exception as exc:
        logger.error("request_failed", extra={"fields": {
            "request_id": request_id, "error_type": type(exc).__name__,
        }})
        response = JSONResponse(status_code=500, content={"detail": "Internal server error"})
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Served-By"] = os.getenv("HOSTNAME", "local")
    response.headers["X-Content-Type-Options"] = "nosniff"
    logger.info("request", extra={"fields": {
        "request_id": request_id, "method": request.method, "path": request.url.path,
        "status": response.status_code, "duration_ms": round((time.monotonic() - started) * 1000, 2),
    }})
    return response


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    session_id: uuid.UUID | None = None

    @field_validator("question")
    @classmethod
    def meaningful_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Question must contain non-whitespace text")
        return value


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/ready")
def ready():
    if getattr(app.state, "shutting_down", False) or not redis_healthy():
        raise HTTPException(status_code=503, detail="Agent not ready")
    return {"ready": True}


def generate_answer(body: AskRequest, key: str) -> tuple[dict, dict]:
    rate_headers = check_rate_limit(key)
    input_tokens = max(1, len(body.question.split()) * 2)
    reservation = check_budget(input_tokens, settings.max_output_tokens)
    try:
        answer = llm_ask(body.question)
        # The mock estimates two tokens per word; bound output by the reservation.
        words = answer.split()
        if len(words) * 2 > settings.max_output_tokens:
            words = words[:settings.max_output_tokens // 2]
            answer = " ".join(words)
        cost = record_cost(input_tokens, len(words) * 2, reservation)
    except Exception:
        release_reservation(reservation)
        raise
    session_id = body.session_id or uuid.uuid4()
    count = append_turn(key, session_id, body.question, answer, cost)
    payload = {"question": body.question, "answer": answer, "cost_usd": cost,
               "session_id": str(session_id), "message_count": count, "storage": "redis",
               "served_by": os.getenv("HOSTNAME", "local")}
    return payload, rate_headers


@app.post("/chat")
@app.post("/ask")
def ask(body: AskRequest, response: Response, key: str = Depends(verify_api_key)):
    payload, headers = generate_answer(body, key)
    response.headers.update(headers)
    return payload


@app.get("/history/{session_id}")
def history(session_id: uuid.UUID, key: str = Depends(verify_api_key)):
    messages = read_history(key, session_id)
    return {"session_id": str(session_id), "messages": messages, "message_count": len(messages),
            "storage": "redis", "served_by": os.getenv("HOSTNAME", "local")}


@app.post("/ask/stream")
def stream(body: AskRequest, key: str = Depends(verify_api_key)):
    # Validate auth/rate/budget and complete generation BEFORE committing HTTP 200.
    # Mock LLM returns one answer; this endpoint demonstrates incremental SSE delivery.
    payload, headers = generate_answer(body, key)

    async def events():
        for word in payload["answer"].split():
            yield "event: token\ndata: " + json.dumps({"text": word + " "}, ensure_ascii=False) + "\n\n"
            await asyncio.sleep(.02)
        yield "event: done\ndata: " + json.dumps(payload, ensure_ascii=False) + "\n\n"

    return StreamingResponse(events(), media_type="text/event-stream", headers={
        **headers, "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
