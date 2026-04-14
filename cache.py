"""Exact-match cache for MVP. Replace with Redis + cosine similarity at scale
using sentence-transformers."""

from threading import Lock


class SemanticCache:
    """In-memory exact-match cache keyed on query text.

    All comparisons are case-sensitive exact matches on the raw query string.
    Extend ``get`` with a similarity search when migrating to a vector-backed
    cache (e.g. Redis + sentence-transformers or a dedicated vector store).
    """

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._lock = Lock()

    def get(self, query: str) -> str | None:
        """Return the cached response for *query*, or ``None`` if not cached."""
        with self._lock:
            return self._store.get(query)

    def set(self, query: str, response: str) -> None:
        """Store *response* under *query*."""
        with self._lock:
            self._store[query] = response
