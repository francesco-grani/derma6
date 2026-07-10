"""JWT authentication middleware for FastAPI.

Validates Supabase-issued Bearer tokens on all routes except public paths.
On success, sets request.state.user_id from the token's 'sub' claim (the
Supabase user UUID).
"""

from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.auth import verify_supabase_jwt

_PUBLIC_PATHS = frozenset({
    "/api/auth/complete-signup",
    "/api/auth/username-available",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
})


class JWTAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in _PUBLIC_PATHS:
            return await call_next(request)

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        token = auth_header[len("Bearer "):]
        try:
            claims = verify_supabase_jwt(token)
        except JWTError:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        request.state.user_id = claims["sub"]
        return await call_next(request)
