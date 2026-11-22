"""NOVA backend entrypoint.

Run locally:  uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .agent import llm
from .agent.worker import worker
from .api import api_router
from .config import settings
from .db import SessionLocal, init_db
from .models import AuditLog, User
from .realtime import bus
from .security import decode_token
from .services import media

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("nova")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.ensure_dirs()
    init_db()
    db = SessionLocal()
    try:
        db.add(AuditLog(actor="system", action="system.start", target=settings.env,
                        data_json=json.dumps({"ai": llm.active_provider() or "offline"})))
        db.commit()
    finally:
        db.close()
    if settings.worker_enabled:
        await worker.start()
    logger.info(
        "NOVA ready · env=%s · ai=%s · ffmpeg=%s · db=%s",
        settings.env, llm.active_provider() or "offline",
        bool(media.capabilities()["ffmpeg"]), settings.database_url.split(":")[0],
    )
    try:
        yield
    finally:
        await worker.stop()


app = FastAPI(
    title="NOVA API",
    version="1.0.0",
    description="Personal autonomous AI agent — tasks, tools, memory, approvals and publishing.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=r"https://[a-z0-9-]+\.style\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/")
def root() -> dict:
    return {"service": "nova", "docs": "/docs", "health": "/api/system/health"}


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.websocket("/ws")
async def websocket_events(websocket: WebSocket, token: str = Query("")):
    """Live task events for native/mobile clients. Web dashboard uses SSE."""
    try:
        payload = decode_token(token)
    except Exception:
        await websocket.close(code=4401)
        return
    db = SessionLocal()
    try:
        if db.get(User, payload.get("sub")) is None:
            await websocket.close(code=4401)
            return
    finally:
        db.close()
    await websocket.accept()
    queue = bus.subscribe()

    async def sender() -> None:
        async for event in bus.stream(queue):
            await websocket.send_text(json.dumps(event))

    async def receiver() -> None:
        while True:
            message = await websocket.receive_text()
            if message == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))

    try:
        await asyncio.gather(sender(), receiver())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        bus.unsubscribe(queue)
