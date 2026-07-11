"""Unit test for backend.db.deps's module-level singleton providers."""

from backend.db.deps import get_memory_store
from backend.db.memory_store import MemoryStore


class TestGetMemoryStore:
    def test_returns_memory_store_instance(self):
        assert isinstance(get_memory_store(), MemoryStore)

    def test_returns_same_instance_across_calls(self):
        assert get_memory_store() is get_memory_store()
