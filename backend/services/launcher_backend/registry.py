"""LauncherBackendRegistry — the extensibility seam behind issue #918.

A third launcher backend registers here, keyed by its ``backend_id``, with no
change to any call site anywhere else: ``LauncherBackendService`` only ever
iterates or looks up through this registry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.protocols import LauncherBackendFactory


class LauncherBackendRegistry:
    """Immutable lookup over the launcher-backend factories known at wiring time."""

    def __init__(self, factories: list[LauncherBackendFactory]) -> None:
        self._factories = {factory.backend_id: factory for factory in factories}

    def factories(self) -> list[LauncherBackendFactory]:
        """Every registered factory, for detection fan-out (QAM listing)."""
        return list(self._factories.values())

    def get(self, backend_id: str) -> LauncherBackendFactory | None:
        """The factory for *backend_id*, or ``None`` when nothing registered it."""
        return self._factories.get(backend_id)
