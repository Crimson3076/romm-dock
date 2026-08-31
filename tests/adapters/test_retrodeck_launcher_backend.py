"""Tests for adapters.retrodeck_launcher_backend — the behavior-preserving RetroDECK ``LauncherBackend``."""

from __future__ import annotations

from fakes.fake_core_info_provider import FakeCoreInfoProvider
from fakes.fake_retrodeck_paths import FakeRetroDeckPaths

from adapters.retrodeck_launcher_backend import RetroDeckLauncherBackend, RetroDeckLauncherBackendFactory
from domain.launcher_backend import RETRODECK_BACKEND_ID
from domain.shortcut_data import (
    EmulatorInvocation,
    build_launch_options,
    resolve_emulator_invocation,
)
from lib.retrodeck_health import RetroDeckConfigHealth


def _backend(*, core_info: FakeCoreInfoProvider | None = None, **kwargs) -> RetroDeckLauncherBackend:
    return RetroDeckLauncherBackend(
        paths=FakeRetroDeckPaths(**kwargs), core_info=core_info if core_info is not None else FakeCoreInfoProvider()
    )


def _factory(**kwargs) -> RetroDeckLauncherBackendFactory:
    return RetroDeckLauncherBackendFactory(paths=FakeRetroDeckPaths(**kwargs), core_info=FakeCoreInfoProvider())


class TestResolveInvocationParity:
    """resolve_invocation/build_launch_options must equal calling domain.shortcut_data directly."""

    def test_no_emulator(self):
        rom: dict[str, str] = {"platform_slug": "snes"}
        backend = _backend()
        assert backend.resolve_invocation(rom, None) == resolve_emulator_invocation(rom, None)

    def test_libretro_invocation(self):
        rom: dict[str, str] = {"platform_slug": "snes"}
        emulator = EmulatorInvocation.libretro("snes9x_libretro", "Snes9x")
        backend = _backend()
        assert backend.resolve_invocation(rom, emulator) == resolve_emulator_invocation(rom, emulator)

    def test_standalone_invocation(self):
        rom: dict[str, str] = {"platform_slug": "ps3"}
        emulator = EmulatorInvocation.standalone("%EMULATOR_RPCS3% --no-gui %ROM%", "RPCS3")
        backend = _backend()
        assert backend.resolve_invocation(rom, emulator) == resolve_emulator_invocation(rom, emulator)

    def test_build_launch_options_matches_free_function(self):
        backend = _backend()
        invocation = "flatpak run net.retrodeck.retrodeck"
        assert backend.build_launch_options(invocation, "/roms/snes/Game.sfc") == build_launch_options(
            invocation, "/roms/snes/Game.sfc"
        )

    def test_build_launch_options_empty_path_matches_free_function(self):
        backend = _backend()
        assert backend.build_launch_options("flatpak run x", "") == build_launch_options("flatpak run x", "")


class TestPathDelegation:
    def test_roms_path_delegates_to_paths(self):
        backend = _backend(roms="/custom/roms")
        assert backend.roms_path() == "/custom/roms"

    def test_bios_path_delegates_to_paths(self):
        backend = _backend(bios="/custom/bios")
        assert backend.bios_path() == "/custom/bios"

    def test_saves_path_delegates_to_paths(self):
        backend = _backend(saves="/custom/saves")
        assert backend.saves_path() == "/custom/saves"

    def test_states_path_delegates_to_paths(self):
        backend = _backend(states="/custom/states")
        assert backend.states_path() == "/custom/states"


class TestCoreInfoDelegation:
    """RetroDECK's CoreInfoProvider methods delegate unchanged to the injected CoreResolver."""

    def test_get_emulator_options_delegates(self):
        core_info = FakeCoreInfoProvider(available_cores=[{"core_so": "snes9x_libretro", "label": "Snes9x"}])
        backend = _backend(core_info=core_info)
        assert backend.get_emulator_options("snes") == core_info.get_emulator_options("snes")

    def test_get_active_core_delegates(self):
        core_info = FakeCoreInfoProvider(active_core=("snes9x_libretro", "Snes9x"))
        backend = _backend(core_info=core_info)
        assert backend.get_active_core("snes") == ("snes9x_libretro", "Snes9x")
        assert core_info.active_core_calls == ["snes"]

    def test_get_default_emulator_delegates(self):
        core_info = FakeCoreInfoProvider(active_core=("snes9x_libretro", "Snes9x"))
        backend = _backend(core_info=core_info)
        assert backend.get_default_emulator("snes") == EmulatorInvocation.libretro("snes9x_libretro", "Snes9x")

    def test_resolve_sandbox_launcher_delegates(self):
        core_info = FakeCoreInfoProvider(sandbox_launchers={"cmd": "/app/launcher.sh"})
        backend = _backend(core_info=core_info)
        assert backend.resolve_sandbox_launcher("cmd") == "/app/launcher.sh"

    def test_reset_cache_delegates(self):
        core_info = FakeCoreInfoProvider()
        backend = _backend(core_info=core_info)
        backend.reset_cache()
        assert core_info.reset_cache_count == 1


class TestBackendIdentity:
    def test_backend_id_is_retrodeck(self):
        assert _backend().backend_id == RETRODECK_BACKEND_ID

    def test_installation_id_is_retrodeck(self):
        assert _backend().installation_id == RETRODECK_BACKEND_ID


class TestDetectInstallations:
    def test_ok_health_reports_healthy(self):
        factory = _factory(health=RetroDeckConfigHealth.OK, home="/home/deck/retrodeck")
        [installation] = factory.detect_installations()
        assert installation.healthy is True
        assert installation.detail == "ok"
        assert installation.installation_id == RETRODECK_BACKEND_ID
        assert installation.display_name == "RetroDECK"
        assert installation.home == "/home/deck/retrodeck"

    def test_absent_health_reports_unhealthy_but_present(self):
        factory = _factory(health=RetroDeckConfigHealth.ABSENT)
        [installation] = factory.detect_installations()
        assert installation.healthy is False
        assert installation.detail == "absent"

    def test_unreadable_health_reports_unhealthy(self):
        factory = _factory(health=RetroDeckConfigHealth.UNREADABLE)
        [installation] = factory.detect_installations()
        assert installation.healthy is False
        assert installation.detail == "unreadable"

    def test_root_missing_health_reports_unhealthy(self):
        factory = _factory(health=RetroDeckConfigHealth.ROOT_MISSING)
        [installation] = factory.detect_installations()
        assert installation.healthy is False
        assert installation.detail == "root_missing"

    def test_always_exactly_one_entry(self):
        factory = _factory()
        assert len(factory.detect_installations()) == 1


class TestValidate:
    def test_ok_validates(self):
        backend = _backend(health=RetroDeckConfigHealth.OK)
        validation = backend.validate()
        assert validation.ok is True
        assert validation.reason is None
        assert validation.message is None

    def test_absent_validates(self):
        # ABSENT is the legitimate fresh-install fallback — still switchable.
        backend = _backend(health=RetroDeckConfigHealth.ABSENT)
        validation = backend.validate()
        assert validation.ok is True

    def test_unreadable_blocks_with_reason(self):
        backend = _backend(health=RetroDeckConfigHealth.UNREADABLE)
        validation = backend.validate()
        assert validation.ok is False
        assert validation.reason == "unreadable"
        assert validation.message is not None

    def test_root_missing_blocks_with_reason(self):
        backend = _backend(health=RetroDeckConfigHealth.ROOT_MISSING)
        validation = backend.validate()
        assert validation.ok is False
        assert validation.reason == "root_missing"
        assert validation.message is not None


class TestFactoryBind:
    def test_bind_retrodeck_returns_working_backend(self):
        factory = _factory(roms="/roms")
        backend = factory.bind(RETRODECK_BACKEND_ID)
        assert backend is not None
        assert backend.roms_path() == "/roms"

    def test_bind_unknown_installation_returns_none(self):
        factory = _factory()
        assert factory.bind("something-else") is None
        assert factory.bind("emudeck:/home/deck") is None
