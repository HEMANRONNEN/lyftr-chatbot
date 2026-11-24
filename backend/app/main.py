import logging
import time

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .config import Settings, load_settings
from .db import Database
from .llm import AllProvidersUnavailable, LLMGateway, parse_simulation
from .schemas import ChatRequest

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("api")


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    db = Database(settings.database_url)
    gateway = LLMGateway(settings)

    app = FastAPI(title="LLM Chatbot with Key Failover and Response Caching")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )

    # ---- error handling: always JSON with a `detail` field, never a stack trace ----
    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError):
        detail = [
            {"loc": list(e.get("loc", [])), "msg": str(e.get("msg", "")), "type": e.get("type", "")}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": detail})

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(Exception)
    async def unhandled_handler(_: Request, exc: Exception):
        log.exception("unhandled error")
        return JSONResponse(status_code=500, content={"detail": "internal server error"})

    # ---- endpoints ----
    @app.get("/health")
    def health():
        try:
            db.ping()
        except Exception:
            raise HTTPException(status_code=503, detail="database unreachable")
        if not gateway.keys:
            raise HTTPException(status_code=503, detail="no API keys configured")
        return {"status": "ok", "keys_configured": len(gateway.keys), "cache_enabled": True}

    @app.post("/chat")
    def chat(body: ChatRequest, x_simulate_failure: str | None = Header(default=None)):
        started = time.perf_counter()
        simulate = (
            parse_simulation(x_simulate_failure) if settings.enable_failure_simulation else {}
        )

        system_prompt = (
            body.system_prompt
            or db.get_system_prompt(body.session_id)
            or settings.default_system_prompt
        )
        history = db.get_history(body.session_id, settings.max_history_messages)
        messages = (
            [{"role": "system", "content": system_prompt}]
            + history
            + [{"role": "user", "content": body.message}]
        )

        try:
            result = gateway.complete(messages, simulate)
        except AllProvidersUnavailable:
            raise HTTPException(status_code=503, detail="all providers unavailable")

        latency_ms = max(1, round((time.perf_counter() - started) * 1000))
        metadata = {
            "resolution_source": result.resolution_source,
            "model": result.model,
            "latency_ms": latency_ms,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
            "key_id": result.key_id,
            "fallback_attempts": result.fallback_attempts,
        }
        db.save_exchange(body.session_id, body.system_prompt, body.message, result.reply, metadata)
        return {"session_id": body.session_id, "reply": result.reply, "metadata": metadata}

    @app.get("/sessions/{session_id}/messages")
    def session_messages(session_id: str):
        if not db.session_exists(session_id):
            raise HTTPException(status_code=404, detail="session not found")
        return {"session_id": session_id, "messages": db.get_messages(session_id)}

    return app


app = create_app()
