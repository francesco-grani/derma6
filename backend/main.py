"""FastAPI application entry point for Derma6 v2."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.agent.graph import close_checkpointer, init_checkpointer
from backend.api import admin, analysis, auth, chat, export, hitl, profile, routines, sessions
from backend.config import settings
from backend.db.models import init_db
from backend.logging_config import init_langsmith, setup_logging
from backend.middleware.auth import JWTAuthMiddleware

setup_logging()
init_langsmith()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    await init_checkpointer()
    yield
    await close_checkpointer()


app = FastAPI(
    title="Derma6 API",
    description="AI skincare assistant — FastAPI + LangGraph backend",
    version="2.0.0",
    lifespan=lifespan,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth middleware (all routes except public paths) ─────────────────────────
app.add_middleware(JWTAuthMiddleware)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(hitl.router)
app.include_router(profile.router)
app.include_router(routines.router)
app.include_router(export.router)
app.include_router(admin.router)
app.include_router(analysis.router)
app.include_router(sessions.router)


@app.get("/health")
def health():
    return {"status": "ok"}
