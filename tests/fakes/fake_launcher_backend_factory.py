"""In-memory ``LauncherBackendFactory`` / ``LauncherBackend`` for service tests."""

from __future__ import annotations

from typing import Any

from domain.launcher_backend import BackendValidation, DetectedInstallation
from domain.shortcut_data import build_launch_options, resolve_emulator_invocation


class FakeLauncherBackend:
    """A bound, in-memory ``LauncherBackend``."""

    def __init__(
        self,
        *,
        backend_id: str,
        installation_id: str,
        roms: str = "",
        bios: str = "",
        saves: str = "",
        states: str = "",
        validation: BackendValidation | None = None,
    ) -> None:
        self.backend_id = backend_id
        self.installation_id = installation_id
        self.roms = roms
        self.bios = bios
        self.saves = saves
        self.states = states
        self.validation = validation if validation is not None else BackendValidation(ok=True)

    def resolve_invocation(self, rom: dict[str, Any], emulator: Any) -> str:
        return resolve_emulator_invocation(rom, emulator)

    def build_launch_options(self, invocation: str, path: str) -> str:
        return build_launch_options(invocation, path)

    def roms_path(self) -> str:
        return self.roms

    def bios_path(self) -> str:
        return self.bios

    def saves_path(self) -> str:
        return self.saves

    def states_path(self) -> str:
        return self.states

    def validate(self) -> BackendValidation:
        return self.validation


class FakeLauncherBackendFactory:
    """A registrable ``LauncherBackendFactory`` over a fixed set of installations.

    Defaults to reporting exactly one healthy installation named after
    *backend_id* itself (mirroring RetroDECK's always-one-installation
    shape), so a bare ``FakeLauncherBackendFactory("retrodeck")`` slots into
    ``LauncherBackendRegistry`` and binds successfully with no further setup —
    the shape most bootstrap-level tests need.
    """

    def __init__(
        self,
        backend_id: str,
        *,
        display_name: str | None = None,
        installations: list[DetectedInstallation] | None = None,
    ) -> None:
        self.backend_id = backend_id
        self.display_name = display_name or backend_id
        self._installations = (
            installations
            if installations is not None
            else [
                DetectedInstallation(
                    installation_id=backend_id,
                    display_name=self.display_name,
                    home="",
                    healthy=True,
                    detail="ok",
                )
            ]
        )
        self.bound: list[str] = []

    def detect_installations(self) -> list[DetectedInstallation]:
        return list(self._installations)

    def bind(self, installation_id: str) -> FakeLauncherBackend | None:
        self.bound.append(installation_id)
        if installation_id not in {i.installation_id for i in self._installations}:
            return None
        return FakeLauncherBackend(backend_id=self.backend_id, installation_id=installation_id)
