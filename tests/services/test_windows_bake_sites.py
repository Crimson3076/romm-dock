"""The Windows resolver is honored at the launch-bake sites.

Bake sites covered:
  * ``services.library.shortcut_launch_resolver`` — the ``do_scan_windows_launch_
    options`` / ``do_read_windows_launch_options`` maps both the preview scan and
    the per-unit apply read hand to the bake.
  * ``services.rom_install_recorder`` — ``do_resolve_launch_bake``, which both a
    completed download and an adoption re-bake through.

``RelaunchOptionsResolver``'s Windows behavior is pinned in
``test_relaunch_options_resolver.py``; ``WindowsLaunchResolver``'s own decisions
(exe enumeration, Proton composition) are pinned in
``test_windows_launch_resolver.py``. This file only proves each site reaches the
seam with the raw ``platform_slug`` check and never falls through to the
RetroDECK/ES-DE emulator path for a native-Windows ROM.
"""

from __future__ import annotations

import logging

from fakes.fake_active_core_resolver import FakeActiveCoreResolver
from fakes.fake_disc_resolver import FakeDiscResolver
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.fake_windows_resolver import FakeWindowsResolver
from fakes.system_time import FakeClock

from domain.rom import Rom
from domain.rom_install import RomInstall
from domain.windows_launch import WindowsExecutable

_ROM_DIR = "/roms/win/game-1"
_EXE_PATH = f"{_ROM_DIR}/Game.exe"
_WIN_LAUNCH_OPTIONS = f'env ... proton run "{_EXE_PATH}"'


def _seed_windows(
    uow: FakeUnitOfWork,
    *,
    rom_id: int,
    app_id: int | None = 99,
    selected_exe: str | None = None,
) -> None:
    with uow:
        uow.roms.save(
            Rom(
                rom_id=rom_id,
                platform_slug="win",
                name=f"rom-{rom_id}",
                fs_name=f"rom-{rom_id}",
                shortcut_app_id=app_id,
                last_synced_at="2026-01-01T00:00:00+00:00",
            )
        )
        uow.rom_installs.save(
            RomInstall(
                rom_id=rom_id,
                file_path=_EXE_PATH,
                rom_dir=_ROM_DIR,
                platform_slug="win",
                system="win",
                installed_at="2026-01-01T00:00:00+00:00",
            )
        )
        if selected_exe is not None:
            uow.roms.set_selected_exe(rom_id, selected_exe)


def _seed_non_windows(uow: FakeUnitOfWork, *, rom_id: int, app_id: int | None = 42) -> None:
    with uow:
        uow.roms.save(
            Rom(
                rom_id=rom_id,
                platform_slug="n64",
                name=f"rom-{rom_id}",
                fs_name=f"rom-{rom_id}",
                shortcut_app_id=app_id,
                last_synced_at="2026-01-01T00:00:00+00:00",
            )
        )
        uow.rom_installs.save(
            RomInstall(
                rom_id=rom_id,
                file_path="/roms/n64/game.z64",
                rom_dir=None,
                platform_slug="n64",
                system="n64",
                installed_at="2026-01-01T00:00:00+00:00",
            )
        )


def _windows_resolver() -> FakeWindowsResolver:
    resolver = FakeWindowsResolver()
    resolver.set_executables(_ROM_DIR, [WindowsExecutable(filename="Game.exe", path=_EXE_PATH)])
    resolver.set_launch_options(1, _WIN_LAUNCH_OPTIONS)
    return resolver


# ── library-sync bake site ───────────────────────────────────────────────


class TestLibrarySyncBakeSite:
    def _launch_resolver(self, uow_factory, windows_resolver):
        from services.library.shortcut_launch_resolver import ShortcutLaunchResolver, ShortcutLaunchResolverConfig

        return ShortcutLaunchResolver(
            config=ShortcutLaunchResolverConfig(
                uow_factory=uow_factory,
                active_core=FakeActiveCoreResolver(default=(None, None)),
                disc_resolver=FakeDiscResolver(),
                windows_resolver=windows_resolver,
            )
        )

    def test_scan_windows_launch_options_honors_pin(self):
        uow = FakeUnitOfWork()
        _seed_windows(uow, rom_id=1, selected_exe="Game.exe")
        windows_resolver = _windows_resolver()
        resolver = self._launch_resolver(FakeUnitOfWorkFactory(uow=uow), windows_resolver)
        assert resolver.do_scan_windows_launch_options() == {1: _WIN_LAUNCH_OPTIONS}
        assert windows_resolver.calls == [(1, "Game.exe")]

    def test_read_windows_launch_options_honors_pin(self):
        uow = FakeUnitOfWork()
        _seed_windows(uow, rom_id=1, selected_exe="Game.exe")
        resolver = self._launch_resolver(FakeUnitOfWorkFactory(uow=uow), _windows_resolver())
        assert resolver.do_read_windows_launch_options({1}) == {1: _WIN_LAUNCH_OPTIONS}

    def test_scan_ignores_non_windows_installs(self):
        uow = FakeUnitOfWork()
        _seed_non_windows(uow, rom_id=2)
        resolver = self._launch_resolver(FakeUnitOfWorkFactory(uow=uow), _windows_resolver())
        assert resolver.do_scan_windows_launch_options() == {}

    def test_scan_omits_a_rom_with_no_resolved_launch(self):
        # No Proton found / no exe present — the resolver has no seeded launch
        # options for this rom_id, so it must be ABSENT (not "": absent, so
        # build_shortcuts_data's presence check semantics stay simple).
        uow = FakeUnitOfWork()
        _seed_windows(uow, rom_id=5)
        empty_resolver = FakeWindowsResolver()  # nothing seeded
        resolver = self._launch_resolver(FakeUnitOfWorkFactory(uow=uow), empty_resolver)
        assert resolver.do_scan_windows_launch_options() == {}

    def test_read_ignores_non_windows_rom_ids(self):
        uow = FakeUnitOfWork()
        _seed_non_windows(uow, rom_id=2)
        resolver = self._launch_resolver(FakeUnitOfWorkFactory(uow=uow), _windows_resolver())
        assert resolver.do_read_windows_launch_options({2}) == {}


# ── install-recorder bake site ───────────────────────────────────────────


class TestInstallRecorderBakeSite:
    """The bake both a completed download and an adoption resolve through."""

    def _recorder(self, uow_factory, windows_resolver, *, active_core=None):
        from services.rom_install_recorder import RomInstallRecorder, RomInstallRecorderConfig

        return RomInstallRecorder(
            config=RomInstallRecorderConfig(
                logger=logging.getLogger("test_windows_bake"),
                clock=FakeClock(),
                uow_factory=uow_factory,
                system_extensions=lambda system_name: frozenset(),
                active_core=active_core if active_core is not None else FakeActiveCoreResolver(default=(None, None)),
                disc_resolver=FakeDiscResolver(),
                windows_resolver=windows_resolver,
            )
        )

    def test_resolve_launch_bake_bakes_through_windows_resolver(self):
        uow = FakeUnitOfWork()
        _seed_windows(uow, rom_id=1, app_id=1234, selected_exe="Game.exe")
        active_core = FakeActiveCoreResolver(per_rom={1: ("should_never_resolve", "x")})
        recorder = self._recorder(FakeUnitOfWorkFactory(uow=uow), _windows_resolver(), active_core=active_core)
        app_id, launch_options = recorder.do_resolve_launch_bake(1, {"platform_slug": "win"}, _EXE_PATH)
        assert app_id == 1234
        assert launch_options == _WIN_LAUNCH_OPTIONS
        assert active_core.emulator_calls == []

    def test_resolve_launch_bake_returns_empty_command_with_no_proton(self):
        uow = FakeUnitOfWork()
        _seed_windows(uow, rom_id=1, app_id=1234)
        empty_resolver = FakeWindowsResolver()  # nothing seeded → resolves ""
        recorder = self._recorder(FakeUnitOfWorkFactory(uow=uow), empty_resolver)
        app_id, launch_options = recorder.do_resolve_launch_bake(1, {"platform_slug": "win"}, _EXE_PATH)
        assert app_id == 1234
        assert launch_options == ""

    def test_resolve_launch_bake_non_windows_rom_unaffected(self):
        # Zero-regression proof: a non-Windows ROM never reaches windows_resolver.
        uow = FakeUnitOfWork()
        _seed_non_windows(uow, rom_id=2, app_id=42)
        windows_resolver = _windows_resolver()
        recorder = self._recorder(FakeUnitOfWorkFactory(uow=uow), windows_resolver)
        app_id, launch_options = recorder.do_resolve_launch_bake(2, {"platform_slug": "n64"}, "/roms/n64/game.z64")
        assert app_id == 42
        assert launch_options == 'flatpak run net.retrodeck.retrodeck "/roms/n64/game.z64"'
        assert windows_resolver.calls == []

    def test_resolve_launch_bake_missing_rom_row_is_empty_for_windows(self):
        uow = FakeUnitOfWork()  # no rom row at all — the rare race
        recorder = self._recorder(FakeUnitOfWorkFactory(uow=uow), _windows_resolver())
        app_id, launch_options = recorder.do_resolve_launch_bake(999, {"platform_slug": "win"}, _EXE_PATH)
        assert app_id is None
        assert launch_options == ""
