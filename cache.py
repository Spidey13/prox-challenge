"""In-memory exact-match query cache. Swap for Redis + vector similarity at scale."""

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

    @classmethod
    def make_key(
        cls,
        query: str,
        product_id: str | None = None,
        fault_category: str | None = None,
    ) -> str:
        """Return a stable cache key.

        Structured fault queries key on "{product_id}:{fault_category}" —
        deterministic across sessions because the same fault on the same
        product always queries the same manual content.
        Falls back to the raw query string for text/photo paths.
        """
        if fault_category and product_id:
            return f"{product_id}:{fault_category}"
        return query
