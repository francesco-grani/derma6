"""Auth routes: register and login."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth import create_access_token, hash_password, verify_password
from backend.db.deps import get_db
from backend.db.models import User
from backend.schemas import LoginRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.query(User).filter_by(username=req.username).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already taken.")
    user = User(username=req.username, password_hash=hash_password(req.password))
    db.add(user)
    db.commit()
    return TokenResponse(access_token=create_access_token(req.username), username=req.username)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=req.username).first()
    if user is None or not user.password_hash or not verify_password(req.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )
    return TokenResponse(access_token=create_access_token(req.username), username=req.username)
