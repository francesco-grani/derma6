"""Skin analysis — POST /api/me/analyze-skin, GET /api/me/skin-analyses, POST /api/me/medical-flags."""

import base64
import io
import json
import logging
from collections.abc import Generator

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openai import AsyncOpenAI
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.config import settings
from backend.db.deps import get_db, get_profile_store
from backend.db.models import SkinAnalysis
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.llm.structured import StructuredOutputError, structured_completion
from backend.rate_limiter import RateLimiter
from backend.schemas import (
    Alternative,
    SaveConditionRequest,
    SkinAnalysisRecord,
    SkinAnalysisResult,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["analysis"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
_VISION_MAX_PX = 2048  # longest side sent to the vision model
_THUMB_MAX_PX = 256    # thumbnail stored for list view

# Dedicated limiter instance (Req 22.1) — analyze-skin calls a paid vision LLM
# per request, so it gets its own bucket rather than sharing state with the
# chat endpoint's limiter in backend/agent/graph.py, even though both currently
# draw from the same global settings.rate_limit_requests/window_seconds config.
_rate_limiter = RateLimiter()


def _prepare_for_vision(data: bytes) -> tuple[bytes, str]:
    """Resize and re-encode image so it fits comfortably in the API payload."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    img.thumbnail((_VISION_MAX_PX, _VISION_MAX_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), "image/jpeg"

_SYSTEM_PROMPT = (
    "You are a dermatology screening assistant. Analyse the skin image and identify: the "
    "primary condition; your confidence (a float between 0 and 1); up to 3 alternative "
    "conditions with probability > 5% each; a 1-2 sentence reasoning describing visible "
    "features; and a disclaimer stating this is an AI screening tool for educational "
    "purposes only, does not constitute a medical diagnosis, and the user should consult "
    "a qualified dermatologist.\n\n"
    "Focus on these 12 conditions: Acne, Actinic Keratosis, Basal Cell Carcinoma, "
    "Benign Keratosis, Dermatofibroma, Eczema, Melanocytic Nevi, Melanoma, Nail Fungus, "
    "Psoriasis, Ringworm, Vascular Lesion. "
    "If the image does not clearly show a skin condition, set condition to \"Unclear\" and confidence to 0.0."
)

# Explicit JSON-shape instruction for the prompt-only fallback path (Req 1.3) — the
# schema-constrained primary path relies on structured_completion()'s response_format
# instead, so this is only ever appended when that path is unavailable/rejected.
_FALLBACK_JSON_SHAPE_SUFFIX = (
    "Return ONLY valid JSON matching this exact shape — no markdown fences, pure JSON only:\n"
    '{"condition":"<primary condition>","confidence":<float 0-1>,'
    '"alternatives":[{"condition":"<name>","probability":"<e.g. 12.3%, or null if unknown>"}],'
    '"reasoning":"<1-2 sentence description of visible features>",'
    '"disclaimer":"This is an AI screening tool for educational purposes only. '
    'It does not constitute a medical diagnosis. Please consult a qualified dermatologist."}'
)


@router.post("/analyze-skin", response_model=SkinAnalysisResult)
async def analyze_skin(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Req 22.1: per-user rate limit before invoking the (paid) vision LLM.
    if not _rate_limiter.check(user_id):
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Please wait before trying again.",
        )

    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image type. Use JPEG, PNG, or WebP.",
        )

    # Req 22.2/22.3: reject oversized uploads using the size Starlette's multipart
    # parser already observed while writing the upload to disk/spool (UploadFile.size
    # is populated incrementally by UploadFile.write() during body parsing, which
    # completes before this handler runs) rather than only finding out after an
    # unconditional `await file.read()` has buffered the whole payload into a
    # separate in-memory `bytes` object. Falls through to the post-read check below
    # for the rare case `file.size` isn't populated (e.g. a non-Starlette UploadFile).
    declared_size = getattr(file, "size", None)
    if declared_size is not None and declared_size > _MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large. Max 10 MB.")

    data = await file.read()
    logger.info(
        "analyze-skin: user=%s content_type=%r size_bytes=%d",
        user_id, file.content_type, len(data),
    )
    if len(data) > _MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large. Max 10 MB.")

    try:
        data, mime = _prepare_for_vision(data)
    except Exception as exc:
        logger.error("Image preparation failed for %s: %s", user_id, exc)
        raise HTTPException(status_code=422, detail="Could not process image. Please upload a valid JPEG, PNG, or WebP file.") from exc

    b64 = base64.b64encode(data).decode()
    logger.info("analyze-skin: resized payload size_bytes=%d", len(data))

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )

    try:
        result, used_fallback = await structured_completion(
            client,
            model=settings.vision_model,
            system_prompt=_SYSTEM_PROMPT,
            user_content=[
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                },
                {"type": "text", "text": "Analyse this skin image."},
            ],
            schema_model=SkinAnalysisResult,
            max_tokens=512,
            temperature=0.1,
            fallback_prompt_suffix=_FALLBACK_JSON_SHAPE_SUFFIX,
        )
    except StructuredOutputError as exc:
        logger.error("Could not parse vision response for %s: %s", user_id, exc)
        raise HTTPException(
            status_code=502, detail="Could not parse analysis result."
        ) from exc
    except Exception as exc:
        logger.error("Vision model call failed for %s: %s", user_id, exc)
        raise HTTPException(
            status_code=502, detail="Vision model unavailable. Please try again."
        ) from exc

    logger.info(
        "Skin analysis for %s: condition=%s confidence=%.2f reasoning=%r used_fallback=%s",
        user_id, result.condition, result.confidence, result.reasoning, used_fallback,
    )

    # Build thumbnail (256px longest side)
    img_full = Image.open(io.BytesIO(data))
    thumb = img_full.copy()
    thumb.thumbnail((_THUMB_MAX_PX, _THUMB_MAX_PX), Image.LANCZOS)
    thumb_buf = io.BytesIO()
    thumb.save(thumb_buf, format="JPEG", quality=80, optimize=True)
    thumb_b64 = base64.b64encode(thumb_buf.getvalue()).decode()
    full_b64 = base64.b64encode(data).decode()

    try:
        record = SkinAnalysis(
            user_id=user_id,
            condition=result.condition,
            confidence=result.confidence,
            alternatives_json=json.dumps([a.model_dump() for a in result.alternatives]),
            reasoning=result.reasoning,
            disclaimer=result.disclaimer,
            image_b64=full_b64,
            thumbnail_b64=thumb_b64,
        )
        db.add(record)
        db.commit()
        logger.info("Saved skin analysis id=%d for %s", record.id, user_id)
    except Exception as exc:
        logger.error("Failed to persist skin analysis for %s: %s", user_id, exc)

    return result


@router.get("/skin-analyses", response_model=list[SkinAnalysisRecord])
def get_skin_analyses(
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(SkinAnalysis)
        .filter(SkinAnalysis.user_id == user_id)
        .order_by(SkinAnalysis.created_at.asc())
        .all()
    )
    return [
        SkinAnalysisRecord(
            id=r.id,
            condition=r.condition,
            confidence=r.confidence,
            alternatives=[Alternative(**a) for a in json.loads(r.alternatives_json)],
            reasoning=r.reasoning,
            disclaimer=r.disclaimer,
            image_b64=r.image_b64,
            thumbnail_b64=r.thumbnail_b64,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.delete("/skin-analyses/{analysis_id}", status_code=204)
def delete_skin_analysis(
    analysis_id: int,
    user_id: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    record = (
        db.query(SkinAnalysis)
        .filter(SkinAnalysis.id == analysis_id, SkinAnalysis.user_id == user_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="Analysis not found.")
    db.delete(record)
    db.commit()
    logger.info("Deleted skin analysis id=%d for %s", analysis_id, user_id)


@router.post("/medical-flags")
def save_medical_flag(
    body: SaveConditionRequest,
    user_id: str = Depends(get_current_user),
    store: ProfileStore = Depends(get_profile_store),
):
    condition = body.condition.strip()
    if not condition:
        raise HTTPException(status_code=422, detail="Condition name is required.")
    try:
        store.add_medical_flag(user_id, condition)
        logger.info("Medical flag '%s' saved for %s via analysis page", condition, user_id)
        return {"saved": True, "condition": condition}
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
