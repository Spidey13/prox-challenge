"""In-memory exact-match query cache. Swap for Redis + vector similarity at scale."""

import time
from collections import OrderedDict
from threading import Lock

# Entries older than this are stale — the corpus may have been re-ingested and
# answers cite page content that no longer matches. 6h covers a demo session
# comfortably without surviving a corpus change for long.
_DEFAULT_TTL_SECONDS = 6 * 3600
_DEFAULT_MAX_ENTRIES = 500


class SemanticCache:
    """In-memory exact-match cache keyed on query text, LRU-bounded with TTL.

    All comparisons are case-sensitive exact matches on the raw query string.
    Extend ``get`` with a similarity search when migrating to a vector-backed
    cache (e.g. Redis + sentence-transformers or a dedicated vector store).
    """

    def __init__(
        self,
        ttl_seconds: float = _DEFAULT_TTL_SECONDS,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
    ) -> None:
        self._store: OrderedDict[str, tuple[str, float]] = OrderedDict()
        self._ttl = ttl_seconds
        self._max = max_entries
        self._lock = Lock()

    def get(self, query: str) -> str | None:
        """Return the cached response for *query*, or ``None`` if absent/expired."""
        with self._lock:
            item = self._store.get(query)
            if item is None:
                return None
            response, expires_at = item
            if time.monotonic() >= expires_at:
                del self._store[query]
                return None
            self._store.move_to_end(query)  # LRU touch
            return response

    def set(self, query: str, response: str) -> None:
        """Store *response* under *query*, evicting the LRU entry when full."""
        with self._lock:
            if query in self._store:
                self._store.move_to_end(query)
            self._store[query] = (response, time.monotonic() + self._ttl)
            while len(self._store) > self._max:
                self._store.popitem(last=False)

    def clear(self) -> None:
        """Drop everything — call after re-ingestion so stale answers can't serve."""
        with self._lock:
            self._store.clear()

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
