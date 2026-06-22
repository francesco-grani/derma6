"""Skin analysis — POST /api/me/analyze-skin, GET /api/me/skin-analyses, POST /api/me/medical-flags."""

import base64
import io
import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openai import AsyncOpenAI
from PIL import Image, ImageOps
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.config import settings
from backend.db.models import SkinAnalysis, User, engine
from backend.db.profile_store import ProfileStore, ProfileStoreError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["analysis"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB
_VISION_MAX_PX = 2048  # longest side sent to the vision model
_THUMB_MAX_PX = 256    # thumbnail stored for list view


def _prepare_for_vision(data: bytes) -> tuple[bytes, str]:
    """Resize and re-encode image so it fits comfortably in the API payload.

    Returns (jpeg_bytes, "image/jpeg"). Capping at 1024px on the longest side
    keeps the base64 payload under ~400 KB while preserving enough detail for
    dermatology screening.
    """
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # apply EXIF rotation before anything else
    img = img.convert("RGB")
    img.thumbnail((_VISION_MAX_PX, _VISION_MAX_PX), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85, optimize=True)
    return buf.getvalue(), "image/jpeg"

_SYSTEM_PROMPT = (
    "You are a dermatology screening assistant. Analyse the skin image and return a JSON object "
    "with this exact shape — no markdown fences, pure JSON only:\n"
    '{"condition":"<primary condition>","confidence":<float 0-1>,'
    '"alternatives":[{"condition":"<name>","probability":"<e.g. 12.3%>"}],'
    '"reasoning":"<1-2 sentence description of visible features>",'
    '"disclaimer":"This is an AI screening tool for educational purposes only. '
    'It does not constitute a medical diagnosis. Please consult a qualified dermatologist."}\n\n'
    "Focus on these 12 conditions: Acne, Actinic Keratosis, Basal Cell Carcinoma, "
    "Benign Keratosis, Dermatofibroma, Eczema, Melanocytic Nevi, Melanoma, Nail Fungus, "
    "Psoriasis, Ringworm, Vascular Lesion. "
    "If the image does not clearly show a skin condition, set condition to \"Unclear\" and confidence to 0.0. "
    "Include up to 3 alternatives with probability > 5%."
)


class Alternative(BaseModel):
    condition: str
    probability: str


class SkinAnalysisResult(BaseModel):
    condition: str
    confidence: float
    alternatives: list[Alternative]
    reasoning: str
    disclaimer: str


class SkinAnalysisRecord(BaseModel):
    id: int
    condition: str
    confidence: float
    alternatives: list[Alternative]
    reasoning: str
    disclaimer: str
    image_b64: str | None
    thumbnail_b64: str | None
    created_at: datetime


class SaveConditionRequest(BaseModel):
    condition: str


@router.post("/analyze-skin", response_model=SkinAnalysisResult)
async def analyze_skin(
    file: UploadFile = File(...),
    username: str = Depends(get_current_user),
):
    if file.content_type not in _ALLOWED_TYPES:
        raise HTTPException(
            status_code=415,
            detail="Unsupported image type. Use JPEG, PNG, or WebP.",
        )

    data = await file.read()
    logger.info(
        "analyze-skin: user=%s content_type=%r size_bytes=%d",
        username, file.content_type, len(data),
    )
    if len(data) > _MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large. Max 10 MB.")

    try:
        data, mime = _prepare_for_vision(data)
    except Exception as exc:
        logger.error("Image preparation failed for %s: %s", username, exc)
        raise HTTPException(status_code=422, detail="Could not process image. Please upload a valid JPEG, PNG, or WebP file.") from exc

    b64 = base64.b64encode(data).decode()
    logger.info("analyze-skin: resized payload size_bytes=%d", len(data))

    client = AsyncOpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
    )

    try:
        response = await client.chat.completions.create(
            model=settings.vision_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {"type": "text", "text": "Analyse this skin image."},
                    ],
                },
            ],
            max_tokens=512,
            temperature=0.1,
        )
    except Exception as exc:
        logger.error("Vision model call failed for %s: %s", username, exc)
        raise HTTPException(
            status_code=502, detail="Vision model unavailable. Please try again."
        ) from exc

    raw = (response.choices[0].message.content or "").strip()
    logger.info("Vision raw response for %s: %r", username, raw[:500])
    try:
        parsed = json.loads(raw)
        result = SkinAnalysisResult(**parsed)
    except Exception as exc:
        logger.error("Failed to parse vision response for %s: %r", username, raw[:200])
        raise HTTPException(
            status_code=502, detail="Could not parse analysis result."
        ) from exc

    logger.info(
        "Skin analysis for %s: condition=%s confidence=%.2f reasoning=%r",
        username, result.condition, result.confidence, result.reasoning,
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
        with Session(engine) as db:
            user = db.query(User).filter(User.username == username).first()
            if user:
                record = SkinAnalysis(
                    user_id=user.id,
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
                logger.info("Saved skin analysis id=%d for %s", record.id, username)
    except Exception as exc:
        logger.error("Failed to persist skin analysis for %s: %s", username, exc)

    return result


@router.get("/skin-analyses", response_model=list[SkinAnalysisRecord])
def get_skin_analyses(username: str = Depends(get_current_user)):
    with Session(engine) as db:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            return []
        rows = (
            db.query(SkinAnalysis)
            .filter(SkinAnalysis.user_id == user.id)
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
def delete_skin_analysis(analysis_id: int, username: str = Depends(get_current_user)):
    with Session(engine) as db:
        user = db.query(User).filter(User.username == username).first()
        if not user:
            raise HTTPException(status_code=404, detail="Not found.")
        record = (
            db.query(SkinAnalysis)
            .filter(SkinAnalysis.id == analysis_id, SkinAnalysis.user_id == user.id)
            .first()
        )
        if not record:
            raise HTTPException(status_code=404, detail="Analysis not found.")
        db.delete(record)
        db.commit()
        logger.info("Deleted skin analysis id=%d for %s", analysis_id, username)


@router.post("/medical-flags")
def save_medical_flag(
    body: SaveConditionRequest,
    username: str = Depends(get_current_user),
):
    condition = body.condition.strip()
    if not condition:
        raise HTTPException(status_code=422, detail="Condition name is required.")
    try:
        ProfileStore().add_medical_flag(username, condition)
        logger.info("Medical flag '%s' saved for %s via analysis page", condition, username)
        return {"saved": True, "condition": condition}
    except ProfileStoreError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
