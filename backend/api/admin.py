"""Admin routes: read-only user list (admin only, no SQL editor)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.auth import get_current_user
from backend.db.models import User, engine
from sqlalchemy.orm import Session

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserSummary(BaseModel):
    id: int
    username: str
    skin_type: str | None
    skin_concerns: str | None
    has_shaving_routine: bool | None
    medical_flags: str | None
    onboarding_complete: bool

    model_config = {"from_attributes": True}


def require_admin(username: str = Depends(get_current_user)) -> str:
    if username != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return username


@router.get("/users", response_model=list[UserSummary])
def list_users(username: str = Depends(require_admin)):
    with Session(engine) as session:
        users = session.query(User).order_by(User.id).all()
        return [UserSummary.model_validate(u) for u in users]
