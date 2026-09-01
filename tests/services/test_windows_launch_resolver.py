"""Tests for services/windows_launch_resolver.py — WindowsLaunchResolver."""

from __future__ import annotations

from fakes.fake_proton_locator import FakeProtonLocator

from domain.proton import ProtonInstallation
from domain.rom_install import RomInstall
from services.windows_launch_resolver import WindowsLaunchResolver, WindowsLaunchResolverConfig

_ROM_DIR = "/roms/win/game-1"
_EXE1 = f"{_ROM_DIR}/Game.exe"
_EXE2 = f"{_ROM_DIR}/Setup.exe"
_PROTON = ProtonInstallation(name="GE-Proton9-27", binary_path="/steam/proton", steam_install_path="/steam")


def _install(*, rom_dir: str | None = _ROM_DIR, file_path: str = _EXE1, launchable: bool = True) -> RomInstall:
    return RomInstall(
        rom_id=1,
        file_path=file_path,
        rom_dir=rom_dir,
        platform_slug="win",
        system="win",
        installed_at="2026-01-01T00:00:00+00:00",
        launchable=launchable,
    )


def _resolver(*, files: list[str], proton: ProtonInstallation | None = _PROTON) -> WindowsLaunchResolver:
    return WindowsLaunchResolver(
        config=WindowsLaunchResolverConfig(
            list_files=lambda directory: list(files) if directory == _ROM_DIR else [],
            proton_locator=FakeProtonLocator(installation=proton, runtime_dir="/runtime"),
        )
    )


class TestEnumerateExecutables:
    def test_folder_backed_install_lists_exe_files(self):
        resolver = _resolver(files=[_EXE2, _EXE1, f"{_ROM_DIR}/readme.txt"])
        result = resolver.enumerate_executables(_install())
        assert [e.filename for e in result] == ["Game.exe", "Setup.exe"]

    def test_single_file_install_enumerates_over_its_own_file_path(self):
        resolver = _resolver(files=[])
        install = _install(rom_dir=None, file_path="/roms/win/Standalone.exe")
        result = resolver.enumerate_executables(install)
        assert [e.filename for e in result] == ["Standalone.exe"]

    def test_no_exe_present_enumerates_empty(self):
        resolver = _resolver(files=[f"{_ROM_DIR}/data.bin"])
        assert resolver.enumerate_executables(_install()) == []


class TestResolveExePath:
    def test_pinned_exe_wins(self):
        resolver = _resolver(files=[_EXE1, _EXE2])
        assert resolver.resolve_exe_path(_install(), "Setup.exe") == _EXE2

    def test_unpinned_defaults_to_first_alphabetically(self):
        resolver = _resolver(files=[_EXE2, _EXE1])
        assert resolver.resolve_exe_path(_install(), None) == _EXE1

    def test_stale_pin_falls_back_to_default(self):
        resolver = _resolver(files=[_EXE1])
        assert resolver.resolve_exe_path(_install(), "Missing.exe") == _EXE1

    def test_no_exe_present_resolves_empty(self):
        resolver = _resolver(files=[])
        assert resolver.resolve_exe_path(_install(), None) == ""

    def test_unlaunchable_install_resolves_empty(self):
        resolver = _resolver(files=[_EXE1])
        assert resolver.resolve_exe_path(_install(launchable=False), None) == ""


class TestResolveLaunchOptions:
    def test_happy_path_renders_proton_command(self):
        resolver = _resolver(files=[_EXE1])
        result = resolver.resolve_launch_options(_install(), None)
        assert result.startswith('mkdir -p "/runtime/proton-prefixes/1"')
        assert result.endswith(f'"{_EXE1}"')
        assert '"/steam/proton" run' in result

    def test_no_proton_found_is_unlaunchable(self):
        resolver = _resolver(files=[_EXE1], proton=None)
        assert resolver.resolve_launch_options(_install(), None) == ""

    def test_no_exe_found_is_unlaunchable(self):
        resolver = _resolver(files=[])
        assert resolver.resolve_launch_options(_install(), None) == ""

    def test_unlaunchable_install_is_unlaunchable_regardless_of_proton(self):
        resolver = _resolver(files=[_EXE1])
        assert resolver.resolve_launch_options(_install(launchable=False), None) == ""

    def test_pinned_exe_is_baked(self):
        resolver = _resolver(files=[_EXE1, _EXE2])
        result = resolver.resolve_launch_options(_install(), "Setup.exe")
        assert result.endswith(f'"{_EXE2}"')
