"""Auth routes: register and login."""

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, field_validator

from backend.auth import create_access_token, hash_password, validate_password_strength, verify_password
from backend.db.models import engine
from backend.db.profile_store import ProfileStore
from sqlalchemy.orm import Session
from backend.db.models import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def username_valid(cls, v: str) -> str:
        v = v.strip()
        if not v or len(v) < 2:
            raise ValueError("Username must be at least 2 characters.")
        if len(v) > 50:
            raise ValueError("Username must be 50 characters or fewer.")
        return v

    @field_validator("password")
    @classmethod
    def password_valid(cls, v: str) -> str:
        try:
            validate_password_strength(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc
        return v


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest):
    with Session(engine) as session:
        existing = session.query(User).filter_by(username=req.username).first()
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username already taken.")
        user = User(username=req.username, password_hash=hash_password(req.password))
        session.add(user)
        session.commit()

    token = create_access_token(req.username)
    return TokenResponse(access_token=token, username=req.username)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest):
    with Session(engine) as session:
        user = session.query(User).filter_by(username=req.username).first()

    if user is None or not user.password_hash or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    token = create_access_token(req.username)
    return TokenResponse(access_token=token, username=req.username)
