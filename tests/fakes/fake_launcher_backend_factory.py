"""In-memory ``LauncherBackendFactory`` / ``LauncherBackend`` for service tests."""

from __future__ import annotations

from typing import Any

from domain.emulator_commands import option_to_invocation, select_default_option
from domain.launcher_backend import BackendValidation, DetectedInstallation
from domain.shortcut_data import build_launch_options, resolve_emulator_invocation

_NO_OPTIONS: dict[str, Any] = {"available": False, "options": []}


class FakeLauncherBackend:
    """A bound, in-memory ``LauncherBackend`` — also a ``CoreInfoProvider``.

    ``emulator_options`` is ``{system_name: {"available": bool, "options":
    [EmulatorOption, ...]}}``, this backend's own emulator-selection
    catalogue (issue #918's per-backend picker follow-up) — a system absent
    from the map reports "unavailable, no options", the same default-safe
    answer a backend with no catalogue at all gives. Tests set it directly
    (``fake.emulator_options["n64"] = {...}``) or at construction.
    """

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
        emulator_options: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.backend_id = backend_id
        self.installation_id = installation_id
        self.roms = roms
        self.bios = bios
        self.saves = saves
        self.states = states
        self.validation = validation if validation is not None else BackendValidation(ok=True)
        self.emulator_options: dict[str, dict[str, Any]] = emulator_options or {}

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

    # -- CoreInfoProvider -----------------------------------------------------

    def get_emulator_options(self, system_name: str) -> dict[str, Any]:
        return self.emulator_options.get(system_name, _NO_OPTIONS)

    def get_default_emulator(self, system_name: str) -> Any:
        result = self.get_emulator_options(system_name)
        if not result["available"]:
            return None
        return option_to_invocation(select_default_option(result["options"]))

    def get_active_core(self, system_name: str) -> tuple[str | None, str | None]:
        for option in self.get_emulator_options(system_name)["options"]:
            if option.kind == "libretro" and option.core_so:
                return (option.core_so, option.label)
        return (None, None)

    def resolve_sandbox_launcher(self, command: str) -> str | None:
        return None

    def reset_cache(self) -> None:
        pass


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
        emulator_options: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.backend_id = backend_id
        self.display_name = display_name or backend_id
        self.emulator_options = emulator_options or {}
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
        return FakeLauncherBackend(
            backend_id=self.backend_id, installation_id=installation_id, emulator_options=self.emulator_options
        )
