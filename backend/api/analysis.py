"""Skin analysis — POST /api/me/analyze-skin and POST /api/me/medical-flags."""

import base64
import json
import logging

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from openai import AsyncOpenAI
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.config import settings
from backend.db.profile_store import ProfileStore, ProfileStoreError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/me", tags=["analysis"])

_ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
_MAX_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

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
    if len(data) > _MAX_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large. Max 10 MB.")

    b64 = base64.b64encode(data).decode()
    mime = file.content_type

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
    try:
        parsed = json.loads(raw)
        result = SkinAnalysisResult(**parsed)
    except Exception as exc:
        logger.error("Failed to parse vision response for %s: %r", username, raw[:200])
        raise HTTPException(
            status_code=502, detail="Could not parse analysis result."
        ) from exc

    logger.info(
        "Skin analysis for %s: condition=%s confidence=%.2f",
        username, result.condition, result.confidence,
    )
    return result


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
