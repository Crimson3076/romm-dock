"""Launcher-backend subsystem (issue #918).

The package's public API is :class:`LauncherBackendService` — the active
launcher-backend seam every launch-command bake site renders through — and
:class:`LauncherBackendRegistry`, the extensibility point a new backend
factory registers against. The two share no state of their own; they are
grouped here (rather than as two top-level ``services/`` modules) because
the registry exists only to be handed to the service, exactly the internal
collaboration ``services/library/`` and ``services/saves/`` group for.
"""

from services.launcher_backend.registry import LauncherBackendRegistry
from services.launcher_backend.service import LauncherBackendService, LauncherBackendServiceConfig

__all__ = ["LauncherBackendRegistry", "LauncherBackendService", "LauncherBackendServiceConfig"]
