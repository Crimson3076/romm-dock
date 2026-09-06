"""In-memory ``BackendBinder`` implementation for service tests."""

from __future__ import annotations

from typing import Any


class FakeBackendBinder:
    """Maps ``backend_id`` to a configured bound backend (or ``None``) for tests.

    ``backends`` is ``{backend_id: bound_backend_or_None}`` — a ``backend_id``
    absent from it resolves to ``None`` (not installed on this machine), the
    same default-safe answer the real ``LauncherBackendService.bind_backend``
    gives for an unregistered/undetected backend. ``calls`` records each
    queried ``backend_id`` so a consumer test can assert the seam was reached.
    """

    def __init__(self, backends: dict[str, Any] | None = None) -> None:
        self.backends: dict[str, Any] = backends if backends is not None else {}
        self.calls: list[str] = []

    def bind_backend(self, backend_id: str) -> Any:
        self.calls.append(backend_id)
        return self.backends.get(backend_id)
