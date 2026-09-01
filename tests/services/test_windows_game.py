"""Tests for WindowsGameService — get_windows_executables (read) + select_executable (write)."""

from __future__ import annotations

import asyncio
import contextlib
import logging

import pytest
from fakes.fake_unit_of_work import FakeUnitOfWork, FakeUnitOfWorkFactory
from fakes.fake_windows_resolver import FakeWindowsResolver

from domain.rom import Rom
from domain.rom_install import RomInstall
from domain.windows_launch import WindowsExecutable
from services.windows_game import WindowsGameService, WindowsGameServiceConfig

_ROM_DIR = "/roms/win/game-1"
_EXE1 = "Game.exe"
_EXE2 = "Setup.exe"
_EXE1_PATH = f"{_ROM_DIR}/{_EXE1}"
_EXE2_PATH = f"{_ROM_DIR}/{_EXE2}"


@contextlib.contextmanager
def uow_unwrap(uow):
    """Open the shared fake UoW to read committed state after the service closed it."""
    with uow as u:
        yield u


def _seed_rom(uow: FakeUnitOfWork, *, rom_id: int, platform_slug: str = "win", selected_exe: str | None = None) -> None:
    uow.roms.save(
        Rom(
            rom_id=rom_id,
            platform_slug=platform_slug,
            name=f"rom-{rom_id}",
            fs_name=f"rom-{rom_id}",
            shortcut_app_id=42,
            last_synced_at="2026-01-01T00:00:00+00:00",
            selected_exe=selected_exe,
        )
    )


def _seed_install(uow: FakeUnitOfWork, *, rom_id: int, platform_slug: str = "win") -> None:
    uow.rom_installs.save(
        RomInstall(
            rom_id=rom_id,
            file_path=_EXE1_PATH,
            rom_dir=_ROM_DIR,
            platform_slug=platform_slug,
            system=platform_slug,
            installed_at="2026-01-01T00:00:00+00:00",
        )
    )


def _executables() -> list[WindowsExecutable]:
    return [
        WindowsExecutable(filename=_EXE1, path=_EXE1_PATH),
        WindowsExecutable(filename=_EXE2, path=_EXE2_PATH),
    ]


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def uow() -> FakeUnitOfWork:
    return FakeUnitOfWork()


@pytest.fixture
def uow_factory(uow) -> FakeUnitOfWorkFactory:
    return FakeUnitOfWorkFactory(uow=uow)


@pytest.fixture
def windows_resolver() -> FakeWindowsResolver:
    resolver = FakeWindowsResolver()
    resolver.set_executables(_ROM_DIR, _executables())
    return resolver


@pytest.fixture
def service(event_loop, uow_factory, windows_resolver) -> WindowsGameService:
    return WindowsGameService(
        config=WindowsGameServiceConfig(
            loop=event_loop,
            logger=logging.getLogger("test_windows_game"),
            uow_factory=uow_factory,
            windows_resolver=windows_resolver,
        ),
    )


# ── get_windows_executables ──────────────────────────────────────────────


class TestGetWindowsExecutables:
    def test_returns_full_descriptor(self, event_loop, service, uow):
        _seed_rom(uow, rom_id=1, selected_exe=_EXE2)
        _seed_install(uow, rom_id=1)
        result = event_loop.run_until_complete(service.get_windows_executables(1))
        assert result == {
            "has_executables": True,
            "executables": [{"filename": _EXE1}, {"filename": _EXE2}],
            "selected": _EXE2,
        }

    def test_unpinned_selected_is_none(self, event_loop, service, uow):
        _seed_rom(uow, rom_id=1, selected_exe=None)
        _seed_install(uow, rom_id=1)
        result = event_loop.run_until_complete(service.get_windows_executables(1))
        assert result["selected"] is None

    def test_stale_pin_down_validated_to_none(self, event_loop, service, uow):
        _seed_rom(uow, rom_id=1, selected_exe="Missing.exe")
        _seed_install(uow, rom_id=1)
        result = event_loop.run_until_complete(service.get_windows_executables(1))
        assert result["has_executables"] is True
        assert result["selected"] is None

    def test_no_executables_reports_false(self, event_loop, service, uow, windows_resolver):
        windows_resolver.set_executables(_ROM_DIR, [])
        _seed_rom(uow, rom_id=1)
        _seed_install(uow, rom_id=1)
        result = event_loop.run_until_complete(service.get_windows_executables(1))
        assert result == {"has_executables": False}

    def test_not_installed_reports_false(self, event_loop, service, uow):
        _seed_rom(uow, rom_id=1)  # rom but no install record
        result = event_loop.run_until_complete(service.get_windows_executables(1))
        assert result == {"has_executables": False}

    def test_unknown_rom_reports_false(self, event_loop, service):
        result = event_loop.run_until_complete(service.get_windows_executables(999))
        assert result == {"has_executables": False}

    def test_non_windows_rom_reports_false(self, event_loop, service, uow):
        _seed_rom(uow, rom_id=1, platform_slug="psx")
        _seed_install(uow, rom_id=1, platform_slug="psx")
        result = event_loop.run_until_complete(service.get_windows_executables(1))
        assert result == {"has_executables": False}


# ── select_executable ─────────────────────────────────────────────────────


class TestSelectExecutable:
    def test_pin_happy_path_persists_and_bakes(self, event_loop, service, uow, windows_resolver):
        windows_resolver.set_launch_options(1, f'proton run "{_EXE2_PATH}"')
        _seed_rom(uow, rom_id=1, selected_exe=None)
        _seed_install(uow, rom_id=1)
        result = event_loop.run_until_complete(service.select_executable(1, _EXE2))
        assert result["success"] is True
        assert result["selected"] == _EXE2
        assert result["launch_options"] == f'proton run "{_EXE2_PATH}"'
        with uow_unwrap(uow) as u:
            assert u.roms.get(1).selected_exe == _EXE2

    def test_clear_to_default_persists_null(self, event_loop, service, uow, windows_resolver):
        windows_resolver.set_launch_options(1, f'proton run "{_EXE1_PATH}"')
        _seed_rom(uow, rom_id=1, selected_exe=_EXE2)
        _seed_install(uow, rom_id=1)
        result = event_loop.run_until_complete(service.select_executable(1, None))
        assert result["success"] is True
        assert result["selected"] is None
        with uow_unwrap(uow) as u:
            assert u.roms.get(1).selected_exe is None

    def test_invalid_filename_fails_and_writes_nothing(self, event_loop, service, uow):
        _seed_rom(uow, rom_id=1, selected_exe=None)
        _seed_install(uow, rom_id=1)
        result = event_loop.run_until_complete(service.select_executable(1, "Missing.exe"))
        assert result == {
            "success": False,
            "reason": "not_found",
            "message": "'Missing.exe' is not an executable of ROM 1",
        }
        with uow_unwrap(uow) as u:
            assert u.roms.get(1).selected_exe is None

    def test_not_installed_fails(self, event_loop, service, uow):
        _seed_rom(uow, rom_id=1)  # no install record
        result = event_loop.run_until_complete(service.select_executable(1, _EXE1))
        assert result["success"] is False
        assert result["reason"] == "not_installed"
        assert "message" in result

    def test_unknown_rom_fails(self, event_loop, service):
        result = event_loop.run_until_complete(service.select_executable(999, _EXE1))
        assert result["success"] is False
        assert result["reason"] == "not_installed"

    def test_non_windows_rom_fails_unsupported(self, event_loop, service, uow):
        _seed_rom(uow, rom_id=1, platform_slug="psx")
        _seed_install(uow, rom_id=1, platform_slug="psx")
        result = event_loop.run_until_complete(service.select_executable(1, _EXE1))
        assert result["success"] is False
        assert result["reason"] == "unsupported"

    def test_rescan_picks_up_a_newly_appeared_exe(self, event_loop, service, uow, windows_resolver):
        # Between the picker's last read and the write, a new .exe appeared on
        # disk (e.g. a delta-patch install). select_executable re-scans rather
        # than trusting a stale enumeration.
        _seed_rom(uow, rom_id=1, selected_exe=None)
        _seed_install(uow, rom_id=1)
        windows_resolver.set_executables(
            _ROM_DIR, [*_executables(), WindowsExecutable(filename="New.exe", path=f"{_ROM_DIR}/New.exe")]
        )
        windows_resolver.set_launch_options(1, f'proton run "{_ROM_DIR}/New.exe"')
        result = event_loop.run_until_complete(service.select_executable(1, "New.exe"))
        assert result["success"] is True
        assert result["selected"] == "New.exe"
