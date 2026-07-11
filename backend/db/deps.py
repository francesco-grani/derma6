"""FastAPI dependency providers for shared DB resources.

All stores are module-level singletons that share the single SQLAlchemy engine
defined in models.py. init_db() must be called before the first request (done
in the FastAPI lifespan handler in main.py).
"""

from collections.abc import Generator

from sqlalchemy.orm import Session

from backend.db.memory_store import MemoryStore
from backend.db.models import engine
from backend.db.profile_store import ProfileStore
from backend.db.session_store import SessionStore

_profile_store = ProfileStore(engine=engine)
_session_store = SessionStore(engine=engine)
_memory_store = MemoryStore(engine=engine)


def get_db() -> Generator[Session, None, None]:
    """Yield a SQLAlchemy Session backed by the shared engine."""
    with Session(engine) as db:
        yield db


def get_profile_store() -> ProfileStore:
    return _profile_store


def get_session_store() -> SessionStore:
    return _session_store


def get_memory_store() -> MemoryStore:
    return _memory_store
