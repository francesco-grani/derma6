"""Authentication utilities: password hashing and JWT token management.

Uses bcrypt directly (not passlib — passlib is incompatible with bcrypt 4.x+).
"""

import re
from datetime import datetime, timedelta, timezone

import bcrypt
from fastapi import Request
from jose import JWTError, jwt

from backend.config import settings

ALGORITHM = "HS256"

# Minimum 8 chars, at least one non-alpha character
_PASSWORD_RE = re.compile(r"^(?=.*[^a-zA-Z]).{8,}$")


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


def validate_password_strength(password: str) -> None:
    """Raise ValueError if password does not meet policy."""
    if not _PASSWORD_RE.match(password):
        raise ValueError(
            "Password must be at least 8 characters and contain at least one non-letter character."
        )


def create_access_token(username: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": username, "exp": expire},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> str:
    """Decode and verify a JWT. Returns the username ('sub') on success.

    Raises JWTError on any validation failure.
    """
    payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    sub = payload.get("sub")
    if not sub:
        raise JWTError("Token missing 'sub' claim")
    return sub


def get_current_user(request: Request) -> str:
    """FastAPI Depends() helper — reads username set by JWTAuthMiddleware.

    No re-decoding: the middleware already validated the token and stored the
    username in request.state. This keeps route signatures clean and avoids
    redundant JWT work on every protected endpoint.
    """
    return request.state.username
