"""In-memory session store. Swap for Redis at scale without changing the interface."""

from threading import Lock


class SessionStore:
    """Thread-safe in-memory store for per-conversation message history."""

    def __init__(self) -> None:
        self._store: dict[str, list[dict]] = {}
        self._lock = Lock()

    def get(self, conversation_id: str) -> list[dict]:
        """Return a copy of the message list for *conversation_id*.

        Returns an empty list if the conversation has not been created yet.
        """
        with self._lock:
            return list(self._store.get(conversation_id, []))

    def append(self, conversation_id: str, role: str, content: str) -> None:
        """Append a message to the conversation history.

        Args:
            conversation_id: Unique identifier for the conversation.
            role: Either ``"user"`` or ``"assistant"``.
            content: Plain-text message body.
        """
        with self._lock:
            if conversation_id not in self._store:
                self._store[conversation_id] = []
            self._store[conversation_id].append({"role": role, "content": content})

    def clear(self, conversation_id: str) -> None:
        """Delete all messages for *conversation_id* (no-op if not found)."""
        with self._lock:
            self._store.pop(conversation_id, None)
