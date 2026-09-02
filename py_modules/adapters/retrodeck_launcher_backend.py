"""RetroDECK launcher backend — the behavior-preserving first implementation of
:class:`services.protocols.launcher_backend.LauncherBackend` (issue #918).

Wraps the existing RetroDECK-only rendering (``domain.shortcut_data``) and path
resolution (``RetroDeckPaths``) with zero behavior change — every ROM that
resolved to a plain ``flatpak run net.retrodeck.retrodeck`` (or its ``-e``
override) before this seam existed resolves to the exact same string through
it. RetroDECK has exactly one installation, so the factory always reports at
most one :class:`DetectedInstallation` and ``bind`` accepts only its id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from domain.launcher_backend import RETRODECK_BACKEND_ID, BackendValidation, DetectedInstallation
from domain.shortcut_data import build_launch_options, resolve_emulator_invocation
from lib.retrodeck_health import RetroDeckConfigHealth

if TYPE_CHECKING:
    from domain.shortcut_data import EmulatorInvocation

_DISPLAY_NAME = "RetroDECK"

# Structurally the RetroDeckPaths Protocol (services/protocols/paths.py) — not
# imported by name: adapters may not import services.protocols (import-linter
# "Adapters must not import services"), so this adapter's dependency on
# RetroDeckPathsAdapter is typed by shape here instead of by importing the
# Protocol services depend on it through. ``core_info`` (a CoreResolver — see
# adapters/es_de_config.py) is typed the same way: it structurally satisfies
# CoreInfoProvider, the emulator-selection half of LauncherBackend.


class RetroDeckLauncherBackend:
    """RetroDECK bound as the active launcher backend. Implements ``LauncherBackend``."""

    backend_id = RETRODECK_BACKEND_ID
    installation_id = RETRODECK_BACKEND_ID

    def __init__(self, *, paths: Any, core_info: Any) -> None:
        self._paths = paths
        self._core_info = core_info

    def resolve_invocation(self, rom: dict[str, Any], emulator: EmulatorInvocation | None) -> str:
        return resolve_emulator_invocation(rom, emulator)

    def build_launch_options(self, invocation: str, path: str) -> str:
        return build_launch_options(invocation, path)

    # -- CoreInfoProvider: delegates unchanged to the existing es_systems.xml
    # reader — RetroDECK's emulator-selection menu is exactly what it always
    # was, unaffected by this seam.

    def get_active_core(self, system_name: str) -> tuple[str | None, str | None]:
        return self._core_info.get_active_core(system_name)

    def get_default_emulator(self, system_name: str) -> EmulatorInvocation | None:
        return self._core_info.get_default_emulator(system_name)

    def get_emulator_options(self, system_name: str) -> dict[str, Any]:
        return self._core_info.get_emulator_options(system_name)

    def resolve_sandbox_launcher(self, command: str) -> str | None:
        return self._core_info.resolve_sandbox_launcher(command)

    def reset_cache(self) -> None:
        self._core_info.reset_cache()

    def roms_path(self) -> str:
        return self._paths.roms_path()

    def bios_path(self) -> str:
        return self._paths.bios_path()

    def saves_path(self) -> str:
        return self._paths.saves_path()

    def states_path(self) -> str:
        return self._paths.states_path()

    def validate(self) -> BackendValidation:
        """RetroDECK is switchable unless its config is known-broken.

        ``ABSENT`` (no ``retrodeck.json`` yet) still validates — the adapter's
        ``~/retrodeck`` fallback is the plugin's long-standing fresh-install
        behavior, not a switch-blocking error. ``UNREADABLE`` and
        ``ROOT_MISSING`` are the loud states RetroDeckPaths already surfaces
        to the frontend banner; switching onto them would only compound the
        confusion, so they block here too.
        """
        health = self._paths.config_health()
        if health in (RetroDeckConfigHealth.UNREADABLE, RetroDeckConfigHealth.ROOT_MISSING):
            return BackendValidation(
                ok=False,
                reason=health.value,
                message=f"RetroDECK configuration is {health.value.replace('_', ' ')} — fix it before switching.",
            )
        return BackendValidation(ok=True)


class RetroDeckLauncherBackendFactory:
    """Detects RetroDECK (always exactly zero or one installation) and binds it."""

    backend_id = RETRODECK_BACKEND_ID
    display_name = _DISPLAY_NAME

    def __init__(self, *, paths: Any, core_info: Any) -> None:
        self._paths = paths
        self._core_info = core_info

    def detect_installations(self) -> list[DetectedInstallation]:
        """Always reports the one RetroDECK installation the plugin has always assumed.

        RetroDECK is this plugin's original, hard-required target (V1 default);
        even an ``ABSENT`` config resolves via the adapter's own fallback, so
        there is always exactly one entry to offer — its ``healthy`` flag, not
        its presence, carries whether the resolved paths are trustworthy.
        """
        health = self._paths.config_health()
        return [
            DetectedInstallation(
                installation_id=RETRODECK_BACKEND_ID,
                display_name=_DISPLAY_NAME,
                home=self._paths.retrodeck_home(),
                healthy=health == RetroDeckConfigHealth.OK,
                detail=health.value,
            )
        ]

    def bind(self, installation_id: str) -> RetroDeckLauncherBackend | None:
        if installation_id != RETRODECK_BACKEND_ID:
            return None
        return RetroDeckLauncherBackend(paths=self._paths, core_info=self._core_info)
