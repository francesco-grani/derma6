"""FastAPI dependency providers for shared DB resources.

Most stores are module-level singletons that share the single SQLAlchemy engine
defined in models.py. init_db() must be called before the first request (done
in the FastAPI lifespan handler in main.py). ProductCacheStore is the one
exception — it deliberately owns its own disposable SQLite file instead of the
shared engine (see backend/db/product_cache_store.py).
"""

from collections.abc import Generator

from sqlalchemy.orm import Session

from backend.config import settings
from backend.db.memory_store import MemoryStore
from backend.db.models import engine
from backend.db.product_cache_store import ProductCacheStore
from backend.db.profile_store import ProfileStore
from backend.db.session_store import SessionStore
from backend.db.source_discovery_store import SourceDiscoveryStore

_profile_store = ProfileStore(engine=engine)
_session_store = SessionStore(engine=engine)
_memory_store = MemoryStore(engine=engine)
_product_cache_store = ProductCacheStore(db_path=settings.product_cache_db_path)
_source_discovery_store = SourceDiscoveryStore(db_path=settings.source_discovery_db_path)


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


def get_product_cache_store() -> ProductCacheStore:
    return _product_cache_store


def get_source_discovery_store() -> SourceDiscoveryStore:
    return _source_discovery_store
