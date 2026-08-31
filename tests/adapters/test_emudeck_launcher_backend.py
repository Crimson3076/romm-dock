"""Tests for adapters.emudeck_launcher_backend — the EmuDeck ``LauncherBackend``.

Rendering tests drive :class:`EmuDeckLauncherBackend` through its public
``resolve_invocation``/``build_launch_options`` with a hand-built fake
``installation`` (an ``atlas.EmuDeck``-shaped object exposing
``emulators_for``/``roms_dir``/``bios_dir``/``saves_root``/``health``) and a
REAL :class:`EmuDeckFindRulesAdapter` pointed at a small ``tmp_path``
``es_find_rules.xml`` fixture — isolating this backend's own placeholder
rendering from atlas's own catalogue-reading correctness (atlas's own test
suite's job).

Detection/bind tests exercise the REAL vendored ``_vendor.atlas.detect`` over
a real fixture tree under ``tmp_path`` — an EmuDeck arrangement is real once
``<home>/.config/EmuDeck/settings.sh`` exists.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, cast

import pytest
from _vendor import atlas

from adapters.emudeck_find_rules import EmuDeckFindRulesAdapter
from adapters.emudeck_launcher_backend import EmuDeckLauncherBackend, EmuDeckLauncherBackendFactory
from domain.launcher_backend import EMUDECK_BACKEND_ID
from domain.shortcut_data import EmulatorInvocation, build_launch_options

_LOGGER = logging.getLogger("test")


# ── Rendering fakes ──────────────────────────────────────────────────────


@dataclass
class _FakeEntry:
    """Duck-types atlas's ``EmulatorEntry`` — the two attributes this backend reads."""

    label: str
    command: str


@dataclass
class _FakeIssue:
    code: str


@dataclass
class _FakeCatalogueAnswer:
    entries: tuple[_FakeEntry, ...] = ()
    caveats: tuple[_FakeIssue, ...] = ()


@dataclass
class _FakeHealth:
    issues: tuple[_FakeIssue, ...] = ()


class _FakeInstallation:
    """Duck-types ``atlas.EmuDeck``'s surface this backend actually calls."""

    def __init__(
        self,
        *,
        entries_by_system: dict[str, list[_FakeEntry]] | None = None,
        roms: str | None = "",
        bios: str | None = "",
        saves: str | None = "",
        health: _FakeHealth | None = None,
        health_raises: Exception | None = None,
    ) -> None:
        self._entries_by_system = entries_by_system or {}
        self._roms = roms
        self._bios = bios
        self._saves = saves
        self._health = health if health is not None else _FakeHealth()
        self._health_raises = health_raises

    def emulators_for(self, system: str, *, content_path: str | None = None) -> _FakeCatalogueAnswer:
        return _FakeCatalogueAnswer(tuple(self._entries_by_system.get(system, [])))

    def roms_dir(self) -> str | None:
        return self._roms

    def bios_dir(self) -> str | None:
        return self._bios

    def saves_root(self) -> str | None:
        return self._saves

    def health(self) -> _FakeHealth:
        if self._health_raises is not None:
            raise self._health_raises
        return self._health


class _FakeSystemResolver:
    """In-memory ``SystemResolver`` — always resolves to a fixed system."""

    def __init__(self, system: str = "snes") -> None:
        self.system = system
        self.calls: list[tuple[str, str | None]] = []

    def __call__(self, platform_slug: str, platform_fs_slug: str | None = None) -> str:
        self.calls.append((platform_slug, platform_fs_slug))
        return self.system


_ROM: dict[str, Any] = {"platform_slug": "snes", "platform_fs_slug": None}


def _find_rules_xml(*, retroarch: str = "", azahar: str = "", cores_dir: str = "cores") -> str:
    return f"""<?xml version="1.0"?>
<ruleList>
    <emulator name="RETROARCH">
        <rule type="staticpath"><entry>{retroarch}</entry></rule>
    </emulator>
    <core name="RETROARCH">
        <rule type="corepath"><entry>{cores_dir}</entry></rule>
    </core>
    <emulator name="AZAHAR">
        <rule type="staticpath"><entry>{azahar}</entry></rule>
    </emulator>
</ruleList>
"""


def _write_find_rules(tmp_path, **kwargs) -> str:
    path = tmp_path / "es_find_rules.xml"
    path.write_text(_find_rules_xml(**kwargs))
    return str(path)


def _backend(
    tmp_path, installation: _FakeInstallation, *, find_rules_path: str | None = None, system: str = "snes"
) -> EmuDeckLauncherBackend:
    xml_path = find_rules_path or _write_find_rules(tmp_path)
    find_rules = EmuDeckFindRulesAdapter(find_rules_path=xml_path, user_home=str(tmp_path), logger=_LOGGER)
    return EmuDeckLauncherBackend(
        # _FakeInstallation duck-types atlas.EmuDeck's narrow surface this
        # backend actually calls (emulators_for/roms_dir/bios_dir/saves_root/
        # health) without inheriting from it — cast documents that the
        # structural match is deliberate, not overlooked.
        installation=cast("atlas.EmuDeck", installation),
        installation_id=f"{EMUDECK_BACKEND_ID}:{tmp_path}",
        find_rules=find_rules,
        resolve_system=_FakeSystemResolver(system),
        logger=_LOGGER,
    )


class TestResolveInvocationLibretro:
    def test_libretro_command_renders_resolved_paths(self, tmp_path):
        tools = tmp_path / "tools" / "launchers"
        tools.mkdir(parents=True)
        retroarch_sh = tools / "retroarch.sh"
        retroarch_sh.write_text("#!/bin/sh\n")
        cores_dir = str(tmp_path / "cores")

        xml_path = _write_find_rules(tmp_path, retroarch=str(retroarch_sh), cores_dir=cores_dir)
        installation = _FakeInstallation(
            entries_by_system={
                "snes": [
                    _FakeEntry(
                        label="Snes9x", command="%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/snes9x_libretro.so %ROM%"
                    )
                ]
            }
        )
        backend = _backend(tmp_path, installation, find_rules_path=xml_path)

        invocation = backend.resolve_invocation(_ROM, None)
        assert invocation == f"{retroarch_sh} -L {cores_dir}/snes9x_libretro.so"

        options = backend.build_launch_options(invocation, "/roms/snes/Game.sfc")
        assert options == build_launch_options(invocation, "/roms/snes/Game.sfc")
        assert options == f'{retroarch_sh} -L {cores_dir}/snes9x_libretro.so "/roms/snes/Game.sfc"'


class TestResolveInvocationStandalone:
    def test_standalone_via_launcher_script(self, tmp_path):
        tools = tmp_path / "tools" / "launchers"
        tools.mkdir(parents=True)
        azahar_sh = tools / "azahar.sh"
        azahar_sh.write_text("#!/bin/sh\n")

        xml_path = _write_find_rules(tmp_path, azahar=str(azahar_sh))
        installation = _FakeInstallation(
            entries_by_system={"n3ds": [_FakeEntry(label="Azahar", command="%EMULATOR_AZAHAR% %ROM%")]}
        )
        backend = _backend(tmp_path, installation, find_rules_path=xml_path, system="n3ds")

        invocation = backend.resolve_invocation(_ROM, None)
        assert invocation == str(azahar_sh)

    def test_standalone_with_verbatim_literal_path_and_extra_args(self, tmp_path):
        # No %EMULATOR_% token at all — already a literal path. Renders
        # verbatim minus the trailing %ROM%.
        command = "/bin/bash /home/deck/Emulation/tools/launchers/cemu.sh -f -g %ROM%"
        installation = _FakeInstallation(entries_by_system={"wiiu": [_FakeEntry(label="Cemu", command=command)]})
        backend = _backend(tmp_path, installation, system="wiiu")

        invocation = backend.resolve_invocation(_ROM, None)
        assert invocation == "/bin/bash /home/deck/Emulation/tools/launchers/cemu.sh -f -g"


class TestProtonRoutedRefusal:
    def test_lowercase_z_drive_is_refused(self, tmp_path):
        command = "/bin/bash /home/deck/Emulation/tools/launchers/cemu.sh -w -f -g z:%ROM%"
        installation = _FakeInstallation(entries_by_system={"wiiu": [_FakeEntry(label="Cemu", command=command)]})
        backend = _backend(tmp_path, installation, system="wiiu")

        assert backend.resolve_invocation(_ROM, None) == ""
        assert backend.build_launch_options("", "/roms/wiiu/Game.wux") == ""

    def test_uppercase_z_drive_is_refused(self, tmp_path):
        command = "/bin/bash /home/deck/Emulation/tools/launchers/xenia.sh Z:%ROM%"
        installation = _FakeInstallation(entries_by_system={"xbox360": [_FakeEntry(label="Xenia", command=command)]})
        backend = _backend(tmp_path, installation, system="xbox360")

        assert backend.resolve_invocation(_ROM, None) == ""


class TestUnresolvablePlaceholder:
    def test_unknown_emulator_token_falls_through(self, tmp_path):
        installation = _FakeInstallation(
            entries_by_system={"snes": [_FakeEntry(label="Ghost", command="%EMULATOR_GHOST% %ROM%")]}
        )
        backend = _backend(tmp_path, installation)
        assert backend.resolve_invocation(_ROM, None) == ""

    def test_known_token_whose_file_is_missing_falls_through(self, tmp_path):
        xml_path = _write_find_rules(tmp_path, retroarch=str(tmp_path / "does-not-exist.sh"))
        installation = _FakeInstallation(
            entries_by_system={"snes": [_FakeEntry(label="Snes9x", command="%EMULATOR_RETROARCH% %ROM%")]}
        )
        backend = _backend(tmp_path, installation, find_rules_path=xml_path)
        assert backend.resolve_invocation(_ROM, None) == ""

    def test_unresolvable_core_path_falls_through(self, tmp_path):
        # %CORE_RETROARCH% resolves fine (no existence check), but the
        # emulator token file is missing -> still falls through empty.
        tools = tmp_path / "tools" / "launchers"
        tools.mkdir(parents=True)
        retroarch_sh = tools / "retroarch.sh"
        retroarch_sh.write_text("#!/bin/sh\n")
        xml_path_no_core = tmp_path / "es_find_rules_no_core.xml"
        xml_path_no_core.write_text(f"""<ruleList>
            <emulator name="RETROARCH"><rule type="staticpath"><entry>{retroarch_sh}</entry></rule></emulator>
        </ruleList>""")
        installation = _FakeInstallation(
            entries_by_system={
                "snes": [
                    _FakeEntry(
                        label="Snes9x", command="%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/snes9x_libretro.so %ROM%"
                    )
                ]
            }
        )
        backend = _backend(tmp_path, installation, find_rules_path=str(xml_path_no_core))
        assert backend.resolve_invocation(_ROM, None) == ""

    def test_known_placeholder_this_backend_does_not_substitute_falls_through(self, tmp_path):
        # %GAMEDIR% is a KNOWN placeholder (classify_command bakes it), but
        # this backend only ever substitutes %CORE_RETROARCH% and one
        # %EMULATOR_% token -- an %GAMEDIR% surviving into the rendered body
        # is refused rather than baked half-resolved.
        tools = tmp_path / "tools" / "launchers"
        tools.mkdir(parents=True)
        azahar_sh = tools / "azahar.sh"
        azahar_sh.write_text("#!/bin/sh\n")
        xml_path = _write_find_rules(tmp_path, azahar=str(azahar_sh))

        installation = _FakeInstallation(
            entries_by_system={"n3ds": [_FakeEntry(label="Azahar", command="%EMULATOR_AZAHAR% %GAMEDIR% %ROM%")]}
        )
        backend = _backend(tmp_path, installation, find_rules_path=xml_path, system="n3ds")
        assert backend.resolve_invocation(_ROM, None) == ""


class TestRenderOptionDefensiveGuard:
    def test_render_option_rejects_a_command_not_ending_in_rom_token(self, tmp_path):
        # Unreachable through resolve_invocation/_select_option in practice
        # (classify_command only marks a command "bakeable" when it already
        # ends in %ROM%), but _render_option is handed the option directly
        # and must not assume that invariant blindly.
        from domain.emulator_commands import EmulatorOption

        backend = _backend(tmp_path, _FakeInstallation())
        option = EmulatorOption(
            label="Odd",
            kind="standalone",
            core_so=None,
            command="%EMULATOR_AZAHAR% %BASENAME%",
            status="bakeable",
            reason=None,
        )
        assert backend._render_option(option) is None


class TestUnbakeableCommandFallthrough:
    def test_falls_through_to_next_entry_when_one_follows(self, tmp_path):
        tools = tmp_path / "tools" / "launchers"
        tools.mkdir(parents=True)
        azahar_sh = tools / "azahar.sh"
        azahar_sh.write_text("#!/bin/sh\n")
        xml_path = _write_find_rules(tmp_path, azahar=str(azahar_sh))

        installation = _FakeInstallation(
            entries_by_system={
                "n3ds": [
                    _FakeEntry(label="Unbakeable", command="%EMULATOR_AZAHAR% %BASENAME%"),
                    _FakeEntry(label="Azahar", command="%EMULATOR_AZAHAR% %ROM%"),
                ]
            }
        )
        backend = _backend(tmp_path, installation, find_rules_path=xml_path, system="n3ds")
        assert backend.resolve_invocation(_ROM, None) == str(azahar_sh)

    def test_falls_through_to_empty_when_it_was_the_only_entry(self, tmp_path, caplog):
        installation = _FakeInstallation(
            entries_by_system={"n3ds": [_FakeEntry(label="Unbakeable", command="%EMULATOR_AZAHAR% %BASENAME%")]}
        )
        backend = _backend(tmp_path, installation, system="n3ds")
        with caplog.at_level(logging.WARNING):
            assert backend.resolve_invocation(_ROM, None) == ""
        assert any(
            "no bakeable option" in record.message
            and "no_rom_target" in record.message
            and "%EMULATOR_AZAHAR% %BASENAME%" in record.message
            for record in caplog.records
        )

    def test_empty_catalogue_logs_a_warning_naming_the_caveats(self, tmp_path, caplog):
        # The exact silent failure a real EmuDeck arrangement with no ES-DE
        # catalogue hits: zero entries at all, never even reaching a status to
        # classify. Reproduces the empty-launch_options report from #918's
        # real-hardware follow-up.
        installation = _FakeInstallation(entries_by_system={})
        answer_with_caveat = _FakeCatalogueAnswer(
            entries=(), caveats=(_FakeIssue(code="emulator-catalogue-unestablished"),)
        )

        def emulators_for(system: str, *, content_path: str | None = None) -> _FakeCatalogueAnswer:
            return answer_with_caveat

        installation.emulators_for = emulators_for  # type: ignore[method-assign]
        backend = _backend(tmp_path, installation, system="gbc")
        with caplog.at_level(logging.WARNING):
            assert backend.resolve_invocation(_ROM, None) == ""
        assert any(
            "no bakeable option" in record.message and "emulator-catalogue-unestablished" in record.message
            for record in caplog.records
        )


class TestPerGamePin:
    def _two_libretro_entries(self) -> dict[str, list[_FakeEntry]]:
        return {
            "snes": [
                _FakeEntry(label="Mgba", command="%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/mgba_libretro.so %ROM%"),
                _FakeEntry(label="Snes9x", command="%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/snes9x_libretro.so %ROM%"),
            ]
        }

    def test_matching_bakeable_pin_is_preferred_over_default(self, tmp_path):
        tools = tmp_path / "tools" / "launchers"
        tools.mkdir(parents=True)
        retroarch_sh = tools / "retroarch.sh"
        retroarch_sh.write_text("#!/bin/sh\n")
        cores_dir = str(tmp_path / "cores")
        xml_path = _write_find_rules(tmp_path, retroarch=str(retroarch_sh), cores_dir=cores_dir)

        installation = _FakeInstallation(entries_by_system=self._two_libretro_entries())
        backend = _backend(tmp_path, installation, find_rules_path=xml_path)

        pin = EmulatorInvocation.libretro("snes9x_libretro", "Snes9x")
        invocation = backend.resolve_invocation(_ROM, pin)
        assert invocation == f"{retroarch_sh} -L {cores_dir}/snes9x_libretro.so"

    def test_unmatched_pin_falls_through_to_default(self, tmp_path):
        tools = tmp_path / "tools" / "launchers"
        tools.mkdir(parents=True)
        retroarch_sh = tools / "retroarch.sh"
        retroarch_sh.write_text("#!/bin/sh\n")
        cores_dir = str(tmp_path / "cores")
        xml_path = _write_find_rules(tmp_path, retroarch=str(retroarch_sh), cores_dir=cores_dir)

        installation = _FakeInstallation(entries_by_system=self._two_libretro_entries())
        backend = _backend(tmp_path, installation, find_rules_path=xml_path)

        stale_pin = EmulatorInvocation.libretro("gone_libretro", "No Longer Offered")
        invocation = backend.resolve_invocation(_ROM, stale_pin)
        # Default is the first bakeable entry (Mgba), document order.
        assert invocation == f"{retroarch_sh} -L {cores_dir}/mgba_libretro.so"

    def test_unbakeable_pin_falls_through_to_default(self, tmp_path):
        tools = tmp_path / "tools" / "launchers"
        tools.mkdir(parents=True)
        azahar_sh = tools / "azahar.sh"
        azahar_sh.write_text("#!/bin/sh\n")
        xml_path = _write_find_rules(tmp_path, azahar=str(azahar_sh))

        installation = _FakeInstallation(
            entries_by_system={
                "n3ds": [
                    _FakeEntry(label="Azahar", command="%EMULATOR_AZAHAR% %ROM%"),
                    _FakeEntry(label="Broken", command="%EMULATOR_AZAHAR% %BASENAME%"),
                ]
            }
        )
        backend = _backend(tmp_path, installation, find_rules_path=xml_path, system="n3ds")

        unbakeable_pin = EmulatorInvocation.standalone("%EMULATOR_AZAHAR% %BASENAME%", "Broken")
        invocation = backend.resolve_invocation(_ROM, unbakeable_pin)
        assert invocation == str(azahar_sh)


class TestPathDelegation:
    def test_roms_path_delegates(self, tmp_path):
        backend = _backend(tmp_path, _FakeInstallation(roms="/emu/roms"))
        assert backend.roms_path() == "/emu/roms"

    def test_bios_path_delegates(self, tmp_path):
        backend = _backend(tmp_path, _FakeInstallation(bios="/emu/bios"))
        assert backend.bios_path() == "/emu/bios"

    def test_saves_path_delegates(self, tmp_path):
        backend = _backend(tmp_path, _FakeInstallation(saves="/emu/saves"))
        assert backend.saves_path() == "/emu/saves"

    def test_roms_path_degrades_to_empty_string_on_none(self, tmp_path):
        backend = _backend(tmp_path, _FakeInstallation(roms=None))
        assert backend.roms_path() == ""

    def test_bios_path_degrades_to_empty_string_on_none(self, tmp_path):
        backend = _backend(tmp_path, _FakeInstallation(bios=None))
        assert backend.bios_path() == ""

    def test_saves_path_degrades_to_empty_string_on_none(self, tmp_path):
        backend = _backend(tmp_path, _FakeInstallation(saves=None))
        assert backend.saves_path() == ""

    def test_states_path_is_always_empty(self, tmp_path):
        # atlas has no flat savestates root for EmuDeck — resolved per-content, not as a directory.
        backend = _backend(tmp_path, _FakeInstallation())
        assert backend.states_path() == ""


class TestValidate:
    def test_ok_when_no_issues(self, tmp_path):
        backend = _backend(tmp_path, _FakeInstallation(health=_FakeHealth(issues=())))
        validation = backend.validate()
        assert validation.ok is True
        assert validation.reason is None

    def test_not_ok_names_issue_codes(self, tmp_path):
        installation = _FakeInstallation(
            health=_FakeHealth(issues=(_FakeIssue(code="root-missing"), _FakeIssue(code="marker-unreadable")))
        )
        backend = _backend(tmp_path, installation)
        validation = backend.validate()
        assert validation.ok is False
        assert validation.reason == "unhealthy"
        assert validation.message is not None
        assert "root-missing" in validation.message
        assert "marker-unreadable" in validation.message

    def test_health_probe_raising_degrades_to_health_probe_failed(self, tmp_path):
        backend = _backend(tmp_path, _FakeInstallation(health_raises=RuntimeError("disk gone")))
        validation = backend.validate()
        assert validation.ok is False
        assert validation.reason == "health_probe_failed"
        assert validation.message is not None
        assert "disk gone" in validation.message


# ── Factory: real vendored atlas.detect over a real fixture tree ─────────


def _write_settings_sh(home) -> None:
    config_dir = home / ".config" / "EmuDeck"
    config_dir.mkdir(parents=True)
    (config_dir / "settings.sh").write_text(
        "romsPath=\nbiosPath=\nsavesPath=\n",
    )


def _factory(home) -> EmuDeckLauncherBackendFactory:
    return EmuDeckLauncherBackendFactory(user_home=str(home), resolve_system=_FakeSystemResolver(), logger=_LOGGER)


class TestFactoryDetection:
    def test_no_marker_detects_nothing(self, tmp_path):
        factory = _factory(tmp_path)
        assert factory.detect_installations() == []

    def test_atlas_detect_raising_degrades_to_no_installations(self, tmp_path, monkeypatch):
        _write_settings_sh(tmp_path)

        def _raise(home):
            raise RuntimeError("disk unreadable")

        monkeypatch.setattr(atlas, "detect", _raise)
        factory = _factory(tmp_path)
        assert factory.detect_installations() == []
        assert factory.bind(f"emudeck:{tmp_path}") is None

    def test_health_raising_during_detection_reports_unhealthy(self, tmp_path, monkeypatch):
        _write_settings_sh(tmp_path)

        def _raise_health(self):
            raise RuntimeError("settings.sh vanished mid-read")

        monkeypatch.setattr(atlas.EmuDeck, "health", _raise_health)
        factory = _factory(tmp_path)
        [installation] = factory.detect_installations()
        assert installation.healthy is False
        assert "settings.sh vanished mid-read" in installation.detail

    def test_marker_present_detects_exactly_one(self, tmp_path):
        _write_settings_sh(tmp_path)
        factory = _factory(tmp_path)
        installations = factory.detect_installations()
        assert len(installations) == 1
        assert installations[0].installation_id == f"emudeck:{tmp_path}"
        assert installations[0].display_name == "EmuDeck"
        assert installations[0].home == str(tmp_path)


class TestFactoryBind:
    def test_bind_with_mismatched_installation_id_returns_none(self, tmp_path):
        _write_settings_sh(tmp_path)
        factory = _factory(tmp_path)
        assert factory.bind("emudeck:/somewhere/else") is None
        assert factory.bind("retrodeck") is None

    def test_bind_with_no_marker_returns_none(self, tmp_path):
        factory = _factory(tmp_path)
        assert factory.bind(f"emudeck:{tmp_path}") is None

    def test_bind_with_matching_id_resolves_against_fixture_tree(self, tmp_path):
        _write_settings_sh(tmp_path)
        factory = _factory(tmp_path)
        backend = factory.bind(f"emudeck:{tmp_path}")
        assert backend is not None
        assert backend.backend_id == EMUDECK_BACKEND_ID
        assert backend.installation_id == f"emudeck:{tmp_path}"
        # bios/saves resolve to EmuDeck's documented default subtree — no ES-DE
        # install on this fixture, so roms_path degrades to "" (atlas's
        # documented None contract for an absent frontend).
        assert backend.bios_path() == os.path.join(str(tmp_path), "Emulation", "bios")
        assert backend.saves_path() == os.path.join(str(tmp_path), "Emulation", "saves")
        assert backend.roms_path() == ""

    def test_bound_backend_is_a_real_atlas_emudeck_installation(self, tmp_path):
        _write_settings_sh(tmp_path)
        factory = _factory(tmp_path)
        backend = factory.bind(f"emudeck:{tmp_path}")
        assert backend is not None
        assert isinstance(backend._installation, atlas.EmuDeck)


class TestRealAtlasVendoringIntegrity:
    """``validate()``/``resolve_invocation()`` against a REAL bound ``atlas.EmuDeck``.

    Every other test in this file drives rendering through a hand-built fake
    ``installation`` (module docstring above) — deliberately, to isolate this
    backend's own placeholder logic from atlas's own catalogue-reading
    correctness. That isolation has a blind spot: ``validate()`` calls the
    real ``installation.health()`` and ``resolve_invocation()`` calls the real
    ``installation.emulators_for()``, both of which read atlas's own bundled
    JSON data via ``importlib.resources.files("_vendor.atlas")`` internally
    (arrangement-caveat and catalogue lookups) — a vendoring regression there
    (see ``_vendor/README.md``'s `importlib.resources.files` patch note) would
    raise ``ModuleNotFoundError: No module named 'atlas'`` from deep inside
    atlas, never from this backend's own code, so no fake-installation test
    can catch it. This class is the one place that goes through the real
    thing end-to-end, on the same minimal fixture ``TestFactoryBind`` uses.
    """

    def test_validate_runs_real_health_without_a_vendoring_error(self, tmp_path):
        _write_settings_sh(tmp_path)
        factory = _factory(tmp_path)
        backend = factory.bind(f"emudeck:{tmp_path}")
        assert backend is not None
        validation = backend.validate()
        assert validation.ok is False  # this bare fixture has no ES-DE / RetroArch — expected
        assert validation.reason == "unhealthy"

    def test_resolve_invocation_runs_real_emulators_for_without_a_vendoring_error(self, tmp_path):
        _write_settings_sh(tmp_path)
        factory = _factory(tmp_path)
        backend = factory.bind(f"emudeck:{tmp_path}")
        assert backend is not None
        # No ES-DE catalogue on this fixture, so nothing bakes — the point is
        # that resolving gets there and back without atlas's own data loaders
        # raising, not that this bare fixture has anything to launch.
        assert backend.resolve_invocation(_ROM, None) == ""


class TestVendoredZstdCatalogueReading:
    """The `_vendor/backports_zstd` fix (issue #918's real-hardware follow-up).

    ES-DE ships its default ``es_systems.xml`` inside its AppImage, compressed
    with zstd. Atlas's own squashfs reader can decompress it, but only when a
    zstd codec is importable as ``compression.zstd`` (Python >= 3.14, not this
    project's target) or ``backports.zstd`` — neither exists in this runtime
    without vendoring one, so ``adapters/emudeck_launcher_backend.py``'s
    real-hardware report (every GBC/N64 catalogue entry reduced to an empty
    command) traced back to exactly this: atlas silently fell back to its
    documented degraded mode (derived-from-installed-cores, no command text)
    rather than reading the real, sealed-inside-the-AppImage catalogue.
    """

    def test_the_vendored_module_round_trips(self):
        from _vendor import backports_zstd

        data = b"emudeck es_systems.xml payload" * 200
        assert backports_zstd.decompress(backports_zstd.compress(data)) == data

    def test_atlas_squashfs_resolves_the_vendored_provider(self):
        from _vendor.atlas import squashfs

        module = squashfs._zstd_module()
        assert module is not None
        assert module.__name__ == "_vendor.backports_zstd"
        decompressor = squashfs._decompressor(squashfs._COMPRESSOR_ZSTD)
        payload = b"round-trip through atlas's own decompressor lookup" * 50
        assert decompressor(module.compress(payload)) == payload

    @pytest.mark.skipif(
        shutil.which("mksquashfs") is None or shutil.which("unsquashfs") is None,
        reason="requires squashfs-tools (mksquashfs/unsquashfs) to build a real fixture image",
    )
    def test_a_real_zstd_appimage_catalogue_yields_a_bakeable_command(self, tmp_path):
        # Reproduces the user's exact report end to end: a genuinely
        # zstd-compressed squashfs, appended after an ELF stub (a real
        # AppImage's own shape), read through atlas's real detection and
        # rendered by this backend into a real launch command — not a faked
        # `installation.emulators_for()` answer.
        _write_settings_sh(tmp_path)
        appimage_root = tmp_path / "_appimage_root"
        catalogue_dir = appimage_root / "usr" / "share" / "es-de" / "resources" / "systems" / "linux"
        catalogue_dir.mkdir(parents=True)
        (catalogue_dir / "es_systems.xml").write_text(
            "<?xml version='1.0'?>\n"
            "<systemList>\n"
            "  <system>\n"
            "    <name>gbc</name>\n"
            "    <path>%ROMPATH%/gbc</path>\n"
            "    <extension>.gbc .zip</extension>\n"
            '    <command label="Gambatte">%EMULATOR_RETROARCH% -L %CORE_RETROARCH%/gambatte_libretro.so '
            "%ROM%</command>\n"
            "    <platform>gbc</platform>\n"
            "  </system>\n"
            "</systemList>\n"
        )
        squashfs_image = tmp_path / "catalogue.sqfs"
        subprocess.run(
            ["mksquashfs", str(appimage_root), str(squashfs_image), "-comp", "zstd", "-noappend"],
            check=True,
            capture_output=True,
        )
        applications_dir = tmp_path / "Applications"
        applications_dir.mkdir()
        appimage_path = applications_dir / "ES-DE.AppImage"
        true_binary = shutil.which("true")
        assert true_binary is not None
        with appimage_path.open("wb") as out:
            # Any ELF works as the runtime stub — atlas locates the squashfs
            # by walking the ELF's own section headers, the same way a real
            # AppImage runtime finds its embedded image.
            with open(true_binary, "rb") as stub:
                out.write(stub.read())
            out.write(squashfs_image.read_bytes())
        appimage_path.chmod(0o755)

        # A real EmuDeck arrangement's es_find_rules.xml resolves BOTH tokens
        # this command carries: %EMULATOR_RETROARCH% (an <emulator> staticpath
        # to an existing launcher script) and %CORE_RETROARCH% (a <core>
        # corepath to the cores directory).
        retroarch_sh = tmp_path / "Emulation" / "tools" / "launchers" / "retroarch.sh"
        retroarch_sh.parent.mkdir(parents=True)
        retroarch_sh.write_text("#!/bin/sh\n")
        cores_dir = tmp_path / "Applications" / "RetroArch" / "cores"
        cores_dir.mkdir(parents=True)
        find_rules_dir = tmp_path / "ES-DE" / "custom_systems"
        find_rules_dir.mkdir(parents=True)
        (find_rules_dir / "es_find_rules.xml").write_text(
            "<?xml version='1.0'?>\n"
            "<ruleList>\n"
            '  <emulator name="RETROARCH">\n'
            '    <rule type="staticpath">\n'
            f"      <entry>{retroarch_sh}</entry>\n"
            "    </rule>\n"
            "  </emulator>\n"
            '  <core name="RETROARCH">\n'
            '    <rule type="corepath">\n'
            f"      <entry>{cores_dir}</entry>\n"
            "    </rule>\n"
            "  </core>\n"
            "</ruleList>\n"
        )

        factory = EmuDeckLauncherBackendFactory(
            user_home=str(tmp_path),
            resolve_system=lambda platform_slug, platform_fs_slug=None: "gbc",
            logger=_LOGGER,
        )
        backend = factory.bind(f"emudeck:{tmp_path}")
        assert backend is not None
        invocation = backend.resolve_invocation({"platform_slug": "gbc", "platform_fs_slug": None}, None)
        assert invocation == f"{retroarch_sh} -L {cores_dir}/gambatte_libretro.so"
