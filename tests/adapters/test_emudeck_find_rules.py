"""Tests for adapters.emudeck_find_rules — es_find_rules.xml resolution."""

from __future__ import annotations

import logging
import os

from adapters.emudeck_find_rules import EmuDeckFindRulesAdapter

_SAMPLE_XML = """<?xml version="1.0"?>
<ruleList>
    <emulator name="RETROARCH">
        <rule type="staticpath"><entry>{retroarch}</entry></rule>
    </emulator>
    <core name="RETROARCH">
        <rule type="corepath"><entry>~/.var/app/org.libretro.RetroArch/config/retroarch/cores</entry></rule>
    </core>
    <emulator name="AZAHAR">
        <rule type="staticpath"><entry>{azahar}</entry></rule>
    </emulator>
</ruleList>
"""


def _write_rules(tmp_path, *, retroarch: str = "", azahar: str = "") -> str:
    xml_path = tmp_path / "es_find_rules.xml"
    xml_path.write_text(_SAMPLE_XML.format(retroarch=retroarch, azahar=azahar))
    return str(xml_path)


def _adapter(tmp_path, xml_path: str, user_home: str | None = None) -> EmuDeckFindRulesAdapter:
    return EmuDeckFindRulesAdapter(
        find_rules_path=xml_path, user_home=user_home or str(tmp_path), logger=logging.getLogger("test")
    )


class TestResolveEmulator:
    def test_resolves_when_target_file_exists(self, tmp_path):
        launcher = tmp_path / "retroarch.sh"
        launcher.write_text("#!/bin/sh\n")
        xml_path = _write_rules(tmp_path, retroarch=str(launcher))
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("RETROARCH") == str(launcher)

    def test_returns_none_when_target_file_missing(self, tmp_path):
        xml_path = _write_rules(tmp_path, retroarch=str(tmp_path / "does-not-exist.sh"))
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("RETROARCH") is None

    def test_returns_none_for_unknown_token(self, tmp_path):
        xml_path = _write_rules(tmp_path)
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("NOT_A_REAL_EMULATOR") is None

    def test_glob_wildcard_entry_resolves_when_a_match_exists(self, tmp_path):
        apps_dir = tmp_path / "Applications"
        apps_dir.mkdir()
        appimage = apps_dir / "Cemu-2.0.AppImage"
        appimage.write_text("binary")
        xml_path = _write_rules(tmp_path, azahar="~/Applications/Cemu*.AppImage")
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("AZAHAR") == str(appimage)

    def test_entry_with_only_a_launch_command_and_no_path_is_skipped(self, tmp_path):
        # An entry whose text is only a "|<launch-command>" tail strips to an
        # empty path (_expand returns "") -- skipped rather than glob'd.
        xml_path = _write_rules(tmp_path, retroarch="|--some-flag")
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("RETROARCH") is None

    def test_glob_special_characters_in_an_existing_literal_filename_still_resolve(self, tmp_path):
        # A filename that itself contains glob metacharacters (e.g. RetroArch
        # core filenames bracketed by a version tag) can fail to match its own
        # literal glob pattern -- the os.path.exists() fallback still finds it.
        cores_dir = tmp_path / "cores"
        cores_dir.mkdir()
        core_file = cores_dir / "core[1].so"
        core_file.write_text("binary")
        xml_path = _write_rules(tmp_path, retroarch=str(core_file))
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("RETROARCH") == str(core_file)

    def test_glob_wildcard_entry_returns_none_when_nothing_matches(self, tmp_path):
        xml_path = _write_rules(tmp_path, azahar="~/Applications/Cemu*.AppImage")
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("AZAHAR") is None


class TestResolveCoreDir:
    def test_resolves_without_requiring_existence(self, tmp_path):
        xml_path = _write_rules(tmp_path)
        adapter = _adapter(tmp_path, xml_path)
        expected = os.path.join(str(tmp_path), ".var", "app", "org.libretro.RetroArch", "config", "retroarch", "cores")
        assert adapter.resolve_core_dir("RETROARCH") == expected
        assert not os.path.exists(expected)

    def test_returns_none_for_unknown_core(self, tmp_path):
        xml_path = _write_rules(tmp_path)
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_core_dir("UNKNOWN_CORE") is None


class TestTildeExpansion:
    def test_expands_against_user_home_param_not_hardcoded_username(self, tmp_path):
        fake_home = tmp_path / "some-other-user-home"
        fake_home.mkdir()
        xml_path = _write_rules(tmp_path)
        adapter = _adapter(tmp_path, xml_path, user_home=str(fake_home))
        expected = os.path.join(str(fake_home), ".var", "app", "org.libretro.RetroArch", "config", "retroarch", "cores")
        assert adapter.resolve_core_dir("RETROARCH") == expected

    def test_bare_tilde_expands_to_user_home(self, tmp_path):
        xml = """<ruleList>
            <emulator name="X"><rule type="staticpath"><entry>~</entry></rule></emulator>
        </ruleList>"""
        xml_path = tmp_path / "es_find_rules.xml"
        xml_path.write_text(xml)
        adapter = _adapter(tmp_path, str(xml_path))
        # The bare-tilde entry resolves to user_home itself, which exists (tmp_path).
        assert adapter.resolve_emulator("X") == str(tmp_path)


class TestPathSafety:
    def test_traversal_entry_is_resolved_literally_without_raising(self, tmp_path):
        xml_path = _write_rules(tmp_path, retroarch="../../etc/passwd")
        adapter = _adapter(tmp_path, xml_path)
        # No exception, and no unintended access: the literal relative path
        # almost certainly does not exist relative to the process cwd, so it
        # resolves to None rather than being executed or read.
        result = adapter.resolve_emulator("RETROARCH")
        assert result is None or isinstance(result, str)

    def test_absolute_hostile_path_is_resolved_literally_without_raising(self, tmp_path):
        xml_path = _write_rules(tmp_path, azahar="/etc/passwd")
        adapter = _adapter(tmp_path, xml_path)
        # /etc/passwd exists on any Linux box this test runs on, but the
        # adapter only ever returns the path string — it does not open or
        # execute it, so getting the literal path back is the safe outcome.
        result = adapter.resolve_emulator("AZAHAR")
        assert result in (None, "/etc/passwd")


class TestMalformedInput:
    def test_missing_file_returns_none_without_raising(self, tmp_path):
        adapter = _adapter(tmp_path, str(tmp_path / "does-not-exist.xml"))
        assert adapter.resolve_emulator("RETROARCH") is None
        assert adapter.resolve_core_dir("RETROARCH") is None

    def test_malformed_xml_returns_none_without_raising(self, tmp_path):
        xml_path = tmp_path / "es_find_rules.xml"
        xml_path.write_text("<ruleList><emulator name='X'><rule>")
        adapter = _adapter(tmp_path, str(xml_path))
        assert adapter.resolve_emulator("X") is None
        assert adapter.resolve_core_dir("X") is None

    def test_empty_file_returns_none_without_raising(self, tmp_path):
        xml_path = tmp_path / "es_find_rules.xml"
        xml_path.write_text("")
        adapter = _adapter(tmp_path, str(xml_path))
        assert adapter.resolve_emulator("RETROARCH") is None


class TestMtimeCache:
    def test_second_call_reflects_a_changed_file(self, tmp_path):
        # Correctness over internals: change the file's content + mtime
        # between two reads and confirm the cache is not stale forever.
        launcher_a = tmp_path / "a.sh"
        launcher_a.write_text("a")
        launcher_b = tmp_path / "b.sh"
        launcher_b.write_text("b")

        xml_path = _write_rules(tmp_path, retroarch=str(launcher_a))
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("RETROARCH") == str(launcher_a)

        # Force a distinct mtime (some filesystems have 1s resolution).
        new_mtime = os.path.getmtime(xml_path) + 5
        with open(xml_path, "w") as f:
            f.write(_SAMPLE_XML.format(retroarch=str(launcher_b), azahar=""))
        os.utime(xml_path, (new_mtime, new_mtime))

        assert adapter.resolve_emulator("RETROARCH") == str(launcher_b)

    def test_unchanged_mtime_serves_cached_result(self, tmp_path, monkeypatch):
        launcher_a = tmp_path / "a.sh"
        launcher_a.write_text("a")
        xml_path = _write_rules(tmp_path, retroarch=str(launcher_a))
        adapter = _adapter(tmp_path, xml_path)

        assert adapter.resolve_emulator("RETROARCH") == str(launcher_a)

        parse_calls = []
        original_parse = adapter._parse

        def _counting_parse(path):
            parse_calls.append(path)
            return original_parse(path)

        monkeypatch.setattr(adapter, "_parse", _counting_parse)
        # Same file, same mtime: a second read must not reparse.
        assert adapter.resolve_emulator("RETROARCH") == str(launcher_a)
        assert parse_calls == []

    def test_reset_cache_forces_reparse(self, tmp_path, monkeypatch):
        launcher_a = tmp_path / "a.sh"
        launcher_a.write_text("a")
        xml_path = _write_rules(tmp_path, retroarch=str(launcher_a))
        adapter = _adapter(tmp_path, xml_path)
        assert adapter.resolve_emulator("RETROARCH") == str(launcher_a)

        adapter.reset_cache()

        parse_calls = []
        original_parse = adapter._parse

        def _counting_parse(path):
            parse_calls.append(path)
            return original_parse(path)

        monkeypatch.setattr(adapter, "_parse", _counting_parse)
        assert adapter.resolve_emulator("RETROARCH") == str(launcher_a)
        assert len(parse_calls) == 1
