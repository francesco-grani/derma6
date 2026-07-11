"""Auth routes: Supabase signup completion.

This route is public (no Bearer token required — see `_PUBLIC_PATHS` in
`backend/middleware/auth.py`). The old locally-issued token flow
(`/register`, `/login`, `hash_password`/`verify_password`/
`create_access_token`) is gone entirely: Supabase now owns credentials and
token issuance, and this module only provisions the local `users` row keyed
by the Supabase-issued UUID.
"""

from fastapi import APIRouter, Depends, HTTPException

from backend.db.deps import get_profile_store
from backend.db.profile_store import ProfileStore, ProfileStoreError
from backend.schemas import CompleteSignupRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/complete-signup", status_code=201)
def complete_signup(
    req: CompleteSignupRequest, store: ProfileStore = Depends(get_profile_store)
) -> dict:
    """Public (see design's "Design decision, flagged for review" rationale:
    Supabase issues no session/JWT at signUp() time while email confirmation
    is pending, so this endpoint cannot require a Bearer token; it is safe to
    leave public because `supabase_user_id` is an unguessable server-issued
    UUID and the endpoint can only ever create rows, never read or mutate
    existing ones).

    Called immediately after the frontend's supabase.auth.signUp() succeeds,
    to provision the local row with the chosen display name (Req 4.4).
    """
    try:
        profile = store.get_or_create_user_by_id(req.supabase_user_id, req.email, req.username)
        return {"user_id": profile.user_id, "username": profile.username}
    except ProfileStoreError as exc:
        # "email already registered" is the only conflict left possible here.
        raise HTTPException(
            status_code=409 if "already" in str(exc) else 500, detail=str(exc)
        ) from exc
