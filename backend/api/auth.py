"""Auth routes: Supabase signup completion.

The old locally-issued token flow (`/register`, `/login`,
`hash_password`/`verify_password`/`create_access_token`) is gone entirely:
Supabase now owns credentials and token issuance, and this module only
provisions the local `users` row keyed by the Supabase-issued UUID.
"""

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.db.deps import get_profile_store
from backend.db.profile_store import ProfileStore, ProfileStoreError

router = APIRouter(prefix="/api/auth", tags=["auth"])

_MIN_USERNAME_LENGTH = 2
_MAX_USERNAME_LENGTH = 50


# Task 61 spike finding (capstone-round security-remediation, recorded
# 2026-07-11): confirmed live via the Supabase dashboard (Authentication →
# Providers → Email, project hadqrljodgffcdsitxrv) that "Confirm email" is
# enabled — supabase.auth.signUp() returns no session/access token until the
# user verifies their email. This route can therefore never be called with a
# Bearer token at signUp() time, so it moved off the public-path exception
# entirely: it now runs at the user's first *authenticated* session
# (post-verification login), requiring a valid bearer token like every other
# route (see `_PUBLIC_PATHS` in `backend/middleware/auth.py`). Identity is
# derived entirely from the verified JWT's claims (Req 21.1) — `sub` for the
# user id, `email` for the email, and `user_metadata.username` for the
# display name the user chose at signUp() time (threaded through via
# signUp()'s `options.data.username`, which Supabase folds into the JWT's
# claims once a session is later issued). No request body is trusted, or
# needed, at all.
@router.post("/complete-signup", status_code=201)
def complete_signup(
    request: Request, store: ProfileStore = Depends(get_profile_store)
) -> dict:
    user_id = request.state.user_id
    claims = request.state.user_claims
    email = claims.get("email")
    username = (claims.get("user_metadata") or {}).get("username")
    username = username.strip() if isinstance(username, str) else ""
    if not email or not (_MIN_USERNAME_LENGTH <= len(username) <= _MAX_USERNAME_LENGTH):
        raise HTTPException(
            status_code=422,
            detail="Signup is missing a valid email/username in the verified identity.",
        )
    try:
        profile = store.get_or_create_user_by_id(user_id, email, username)
        return {"user_id": profile.user_id, "username": profile.username}
    except ProfileStoreError as exc:
        # "email already registered" is the only conflict left possible here.
        raise HTTPException(
            status_code=409 if "already" in str(exc) else 500, detail=str(exc)
        ) from exc
