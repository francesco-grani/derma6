"""JWT authentication middleware for FastAPI.

Validates Bearer tokens on all routes except public paths.
On success, sets request.state.username from the token's 'sub' claim.
"""

from jose import JWTError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from backend.auth import decode_access_token

_PUBLIC_PATHS = frozenset({
    "/api/auth/login",
    "/api/auth/register",
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
            username = decode_access_token(token)
        except JWTError:
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)

        request.state.username = username
        return await call_next(request)
