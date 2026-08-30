"""LauncherBackendService — the active-launcher-backend seam (issue #918).

Single source of truth for "which launcher backend is Tender using right
now," and the fan-out re-bake when it changes. Implements
``LaunchCommandRenderer`` by delegating to whichever
:class:`~services.protocols.launcher_backend.LauncherBackend` is currently
bound, so every bake site sees a switch on its very next call — changing the
setting, not every shortcut. Preserves current behavior: an unset or unknown
setting binds RetroDECK, the plugin's original and only backend before this
seam existed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.launcher_backend import RETRODECK_BACKEND_ID, DetectedInstallation

if TYPE_CHECKING:
    import logging

    from domain.shortcut_data import EmulatorInvocation
    from services.launcher_backend.registry import LauncherBackendRegistry
    from services.protocols import LauncherBackend, RelaunchOptionsReader, SettingsPersister

_SETTINGS_BACKEND_KEY = "launcher_backend"
_SETTINGS_INSTALLATION_KEY = "launcher_backend_installation"


@dataclass(frozen=True)
class LauncherBackendServiceConfig:
    """Frozen wiring bundle handed to ``LauncherBackendService.__init__``.

    ``settings`` is the plugin's live settings dict (the same object every
    writer mutates) — read at construction to bind the persisted choice, and
    written back through ``settings_persister`` on a successful switch, the
    same live-dict pattern ``PlatformCoreReaderAdapter`` uses. ``relaunch_items``
    is the existing installed+bound relaunch-items seam
    (``RelaunchOptionsResolver``) — a backend switch's fan-out re-bake is
    exactly that seam's batch build, re-resolved through the newly-bound
    backend.
    """

    registry: LauncherBackendRegistry
    settings: dict[str, Any]
    settings_persister: SettingsPersister
    relaunch_items: RelaunchOptionsReader
    logger: logging.Logger


class LauncherBackendService:
    """Owns the active launcher-backend binding and its switch fan-out."""

    def __init__(self, *, config: LauncherBackendServiceConfig) -> None:
        self._registry = config.registry
        self._settings = config.settings
        self._settings_persister = config.settings_persister
        self._relaunch_items = config.relaunch_items
        self._logger = config.logger
        self._active: LauncherBackend | None = self._bind(
            self._settings.get(_SETTINGS_BACKEND_KEY, RETRODECK_BACKEND_ID),
            self._settings.get(_SETTINGS_INSTALLATION_KEY, RETRODECK_BACKEND_ID),
        )

    # -- LaunchCommandRenderer --------------------------------------------------

    def resolve_invocation(self, rom: dict[str, Any], emulator: EmulatorInvocation | None) -> str:
        if self._active is None:
            return ""
        return self._active.resolve_invocation(rom, emulator)

    def build_launch_options(self, invocation: str, path: str) -> str:
        if self._active is None:
            return ""
        return self._active.build_launch_options(invocation, path)

    # -- QAM surface --------------------------------------------------------

    def active_backend_id(self) -> str:
        return self._active.backend_id if self._active is not None else RETRODECK_BACKEND_ID

    def active_installation_id(self) -> str:
        return self._active.installation_id if self._active is not None else RETRODECK_BACKEND_ID

    def list_backends(self) -> list[dict[str, Any]]:
        """Every registered backend with its detected installations, for the QAM picker.

        ``installations`` is always a list — a backend with no detected
        installation (EmuDeck not present on this machine) still appears,
        with an empty list, so the picker can show it as an option that is
        not currently selectable rather than omitting it entirely. Each
        backend and each installation carries ``is_active`` so the picker
        can render the CURRENT selection without a second callable —
        exactly one backend and, within it, at most one installation are
        ever active at once.
        """
        active_backend_id = self.active_backend_id()
        active_installation_id = self.active_installation_id()
        return [
            {
                "backend_id": factory.backend_id,
                "display_name": factory.display_name,
                "is_active": factory.backend_id == active_backend_id,
                "installations": [
                    _installation_payload(i, active=i.installation_id == active_installation_id)
                    for i in factory.detect_installations()
                ],
            }
            for factory in self._registry.factories()
        ]

    def set_active_backend(self, backend_id: str, installation_id: str) -> dict[str, Any]:
        """Validate, bind, persist, and fan out the re-bake for a backend switch.

        Returns the canonical ``{success, reason, message}`` shape on
        failure; on success, ``{success: True, rebake_items: [...]}`` — the
        same ``{app_id, launch_options}`` list ``set_system_core`` returns,
        which the frontend confirm-sets onto each live shortcut via the
        existing ``SetAppLaunchOptions``-confirm mechanism (ADR-0009). Nothing
        is written to ``settings.json`` and no ROM is re-baked unless
        validation passes — a failed switch leaves the previous backend
        active.
        """
        factory = self._registry.get(backend_id)
        if factory is None:
            return {"success": False, "reason": "unknown_backend", "message": f"No launcher backend {backend_id!r}."}

        candidate = factory.bind(installation_id)
        if candidate is None:
            return {
                "success": False,
                "reason": "not_detected",
                "message": f"{factory.display_name} installation {installation_id!r} was not detected.",
            }

        validation = candidate.validate()
        if not validation.ok:
            return {"success": False, "reason": validation.reason, "message": validation.message}

        self._active = candidate
        self._settings[_SETTINGS_BACKEND_KEY] = backend_id
        self._settings[_SETTINGS_INSTALLATION_KEY] = installation_id
        self._settings_persister.save_settings()

        return {"success": True, "rebake_items": self._relaunch_items.installed_relaunch_items()}

    def _bind(self, backend_id: str, installation_id: str) -> LauncherBackend | None:
        """Bind the persisted (backend_id, installation_id) pair, falling back to RetroDECK.

        A fallback rather than a raise: settings.json can name a backend or
        installation this machine no longer has (an EmuDeck arrangement was
        removed, a settings.json was copied from another machine), and every
        bake site needs something to render through regardless.
        """
        backend = self._try_bind(backend_id, installation_id)
        if backend is not None:
            return backend
        if backend_id != RETRODECK_BACKEND_ID:
            self._logger.warning(
                "launcher_backend_service: %s/%s not available, falling back to RetroDECK",
                backend_id,
                installation_id,
            )
        return self._try_bind(RETRODECK_BACKEND_ID, RETRODECK_BACKEND_ID)

    def _try_bind(self, backend_id: str, installation_id: str) -> LauncherBackend | None:
        factory = self._registry.get(backend_id)
        return factory.bind(installation_id) if factory is not None else None


def _installation_payload(installation: DetectedInstallation, *, active: bool) -> dict[str, Any]:
    return {
        "installation_id": installation.installation_id,
        "display_name": installation.display_name,
        "home": installation.home,
        "healthy": installation.healthy,
        "detail": installation.detail,
        "is_active": active,
    }
