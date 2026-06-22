"""FastAPI application entry point for Derma6 v2."""

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import admin, analysis, auth, chat, export, hitl, profile, routines, sessions
from backend.logging_config import init_langsmith, setup_logging
from backend.middleware.auth import JWTAuthMiddleware

setup_logging()
init_langsmith()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Derma6 API",
    description="AI skincare assistant — FastAPI + LangGraph backend",
    version="2.0.0",
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Dev defaults: Vite dev server. Production: set ALLOWED_ORIGINS env var
# (comma-separated, e.g. "https://1-2-3-4.sslip.io,https://www.example.com").
_raw_origins = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173,http://localhost:3000")
_origins = [o.strip() for o in _raw_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
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
