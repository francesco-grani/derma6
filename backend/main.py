"""FastAPI application entry point for Derma6 v2."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import admin, analysis, auth, chat, export, profile, routines
from backend.logging_config import setup_logging
from backend.middleware.auth import JWTAuthMiddleware

setup_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Derma6 API",
    description="AI skincare assistant — FastAPI + LangGraph backend",
    version="2.0.0",
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Dev: allow Vite dev server. Production: set ALLOWED_ORIGINS env var.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Auth middleware (all routes except public paths) ─────────────────────────
app.add_middleware(JWTAuthMiddleware)

# ── Routers ──────────────────────────────────────────────────────────────────
app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(profile.router)
app.include_router(routines.router)
app.include_router(export.router)
app.include_router(admin.router)
app.include_router(analysis.router)


@app.get("/health")
def health():
    return {"status": "ok"}
