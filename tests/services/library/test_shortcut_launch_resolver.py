"""Tests for ShortcutLaunchResolver — it resolves each ROM's launch facts.

Driven through the shared ``plugin`` fixture so the emulator resolution runs
against the real :class:`ActiveCoreResolver` over the shared fake UoW — the same
seam the sync's bake sites draw from — rather than a mock of it.

The disc-resolved install paths (``do_scan_installed_paths`` /
``do_read_installed_paths``) are pinned in ``tests/services/test_disc_bake_sites.py``
alongside the other launch-bake sites, so a change to the disc pin's handling
fails every site at once.
"""

from fakes.fake_core_info_provider import libretro_option
from fakes.fake_launcher_backend_factory import FakeLauncherBackend

from domain.shortcut_data import EmulatorInvocation

# conftest.py patches decky before this import
from tests.services.library._helpers import _seed_install


class TestBuildCoreOverrides:
    """The ``core_overrides`` map both preview and apply pass to ``build_shortcuts_data``.

    Maps ``rom_id -> resolved core_so`` for every ROM in the unit that carries a
    still-valid ``emulator_override``; NULL pins never enter the map, and a stale
    LABEL is omitted with a WARNING so the bake degrades to the plain launch.
    """

    def test_resolved_override_included_null_omitted(self, plugin):
        """A resolvable pin maps to its libretro EmulatorInvocation; an unpinned ROM is absent."""
        plugin._core_info.available_cores = [
            {"core_so": "pcsx_rearmed_libretro", "label": "PCSX ReARMed", "is_default": True},
        ]
        _seed_install(plugin, 10, file_path="/roms/psx/a.chd", platform_slug="psx")
        _seed_install(plugin, 11, file_path="/roms/psx/b.chd", platform_slug="psx")
        with plugin._uow:
            plugin._uow.roms.set_emulator_override(10, "retrodeck", "PCSX ReARMed")

        roms = [{"id": 10, "platform_slug": "psx"}, {"id": 11, "platform_slug": "psx"}]
        result = plugin._sync_service._shortcut_launch_resolver.do_build_core_overrides(roms)

        assert result == {10: EmulatorInvocation.libretro("pcsx_rearmed_libretro", "PCSX ReARMed")}
        assert 11 not in result

    def test_stale_override_omitted_with_warning(self, plugin, caplog):
        """A pin whose LABEL no longer resolves is omitted and a WARNING is logged."""
        import logging

        plugin._core_info.available_cores = [
            {"core_so": "pcsx_rearmed_libretro", "label": "PCSX ReARMed", "is_default": True},
        ]
        _seed_install(plugin, 10, file_path="/roms/psx/a.chd", platform_slug="psx")
        with plugin._uow:
            plugin._uow.roms.set_emulator_override(10, "retrodeck", "Removed Core")

        roms = [{"id": 10, "platform_slug": "psx"}]
        with caplog.at_level(logging.WARNING):
            result = plugin._sync_service._shortcut_launch_resolver.do_build_core_overrides(roms)

        assert result == {}
        assert "Removed Core" in caplog.text
        assert "no longer resolves" in caplog.text

    def test_no_overrides_returns_empty(self, plugin):
        """No pins anywhere → empty map (no available-cores lookups needed)."""
        _seed_install(plugin, 10, file_path="/roms/n64/a.z64", platform_slug="n64")
        result = plugin._sync_service._shortcut_launch_resolver.do_build_core_overrides(
            [{"id": 10, "platform_slug": "n64"}]
        )
        assert result == {}


class TestBuildCrossBackendOverrides:
    """The ``cross_backend_launch_options`` map both preview and apply pass to
    ``build_shortcuts_data`` — additive and separate from ``do_build_core_overrides``."""

    def test_resolving_pin_is_rendered_through_the_named_backend(self, plugin):
        _seed_install(plugin, 10, file_path="/roms/psx/a.chd", platform_slug="psx")
        emudeck = FakeLauncherBackend(
            backend_id="emudeck",
            installation_id="emudeck",
            emulator_options={
                "psx": {
                    "available": True,
                    "options": [libretro_option("pcsx_rearmed_libretro", "PCSX ReARMed")],
                }
            },
        )
        plugin._backend_binder.backends["emudeck"] = emudeck
        with plugin._uow:
            rom = plugin._uow.roms.get(10)
            rom.pin_cross_backend_emulator("emudeck", "PCSX ReARMed")
            plugin._uow.roms.set_cross_backend_pin(10, rom.cross_backend_pin)

        roms = [{"id": 10, "platform_slug": "psx"}]
        installed_paths = {10: "/roms/psx/a.chd"}
        result = plugin._sync_service._shortcut_launch_resolver.do_build_cross_backend_overrides(roms, installed_paths)

        assert result == {
            10: (
                "flatpak run net.retrodeck.retrodeck -e "
                '"%EMULATOR_RETROARCH% -L /var/config/retroarch/cores/pcsx_rearmed_libretro.so %ROM%" '
                '"/roms/psx/a.chd"'
            )
        }

    def test_no_pin_returns_empty(self, plugin):
        _seed_install(plugin, 10, file_path="/roms/n64/a.z64", platform_slug="n64")
        result = plugin._sync_service._shortcut_launch_resolver.do_build_cross_backend_overrides(
            [{"id": 10, "platform_slug": "n64"}], {10: "/roms/n64/a.z64"}
        )
        assert result == {}

    def test_uninstalled_rom_is_skipped(self, plugin):
        """A ROM absent from installed_paths is never checked for a pin."""
        with plugin._uow:
            from domain.rom import Rom

            plugin._uow.roms.save(
                Rom(
                    rom_id=99,
                    platform_slug="psx",
                    name="uninstalled",
                    fs_name="uninstalled.chd",
                    shortcut_app_id=None,
                    last_synced_at="2026-01-01T00:00:00+00:00",
                )
            )
            rom = plugin._uow.roms.get(99)
            rom.pin_cross_backend_emulator("emudeck", "PCSX ReARMed")
            plugin._uow.roms.set_cross_backend_pin(99, rom.cross_backend_pin)

        result = plugin._sync_service._shortcut_launch_resolver.do_build_cross_backend_overrides(
            [{"id": 99, "platform_slug": "psx"}], {}
        )
        assert result == {}
