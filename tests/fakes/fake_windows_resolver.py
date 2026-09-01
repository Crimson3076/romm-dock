"""In-memory ``WindowsResolver`` implementation for service tests.

Lets the launch-bake consumers (library sync, download-complete, RetroDECK-home
migration) and the exe-picker service inject the native-Windows resolution seam
without standing up a real ``WindowsLaunchResolver`` (directory scan + a real
``ProtonLocator``). Configure per-install ``.exe`` lists and the rendered launch
command each install resolves to; each resolve call is recorded so a consumer
test can assert the seam was reached with the right pin.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.rom_install import RomInstall
    from domain.windows_launch import WindowsExecutable


class FakeWindowsResolver:
    """Maps an install's directory to a configured ``.exe`` list, keyed by ``rom_dir``
    (or ``file_path`` for a single-file install) for tests.

    Seed executables via ``set_executables(key, executables)``; a key with none
    seeded enumerates empty. Seed the rendered launch command a ``rom_id``
    resolves to via ``set_launch_options(rom_id, launch_options)``; a ``rom_id``
    with none seeded resolves to ``""`` (mirroring "no Proton found or no .exe
    present"). An install the system cannot launch (``launchable is False``)
    resolves to ``""`` before any exe work, matching the real resolver.
    """

    def __init__(self) -> None:
        self._executables_by_key: dict[str, list[WindowsExecutable]] = {}
        self._launch_options_by_rom_id: dict[int, str] = {}
        self.calls: list[tuple[int, str | None]] = []

    def set_executables(self, key: str, executables: list[WindowsExecutable]) -> None:
        self._executables_by_key[key] = executables

    def set_launch_options(self, rom_id: int, launch_options: str) -> None:
        self._launch_options_by_rom_id[rom_id] = launch_options

    def _key(self, install: RomInstall) -> str:
        return install.rom_dir if install.rom_dir is not None else install.file_path

    def enumerate_executables(self, install: RomInstall) -> list[WindowsExecutable]:
        return list(self._executables_by_key.get(self._key(install), []))

    def resolve_exe_path(self, install: RomInstall, selected_exe: str | None) -> str:
        if not install.launchable:
            return ""
        executables = self.enumerate_executables(install)
        if not executables:
            return ""
        if selected_exe is not None:
            for exe in executables:
                if exe.filename == selected_exe:
                    return exe.path
        return executables[0].path

    def resolve_launch_options(self, install: RomInstall, selected_exe: str | None) -> str:
        self.calls.append((install.rom_id, selected_exe))
        if not install.launchable:
            return ""
        return self._launch_options_by_rom_id.get(install.rom_id, "")
