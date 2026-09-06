"""Tests for domain.xemu_config pure functions."""

from __future__ import annotations

import tomllib

import pytest

from domain.xemu_config import compute_xemu_alignment, parse_xemu_sys_files


class TestParseXemuSysFiles:
    def test_parses_all_three_keys(self):
        text = """
        [sys.files]
        bootrom_path = "/home/deck/retrodeck/bios/mcpx_1.0.bin"
        flashrom_path = "/home/deck/retrodeck/bios/Complex_4627v1.03.bin"
        hdd_path = "/home/deck/retrodeck/bios/xbox_hdd.qcow2"
        """
        result = parse_xemu_sys_files(text)
        assert result == {
            "bootrom_path": "/home/deck/retrodeck/bios/mcpx_1.0.bin",
            "flashrom_path": "/home/deck/retrodeck/bios/Complex_4627v1.03.bin",
            "hdd_path": "/home/deck/retrodeck/bios/xbox_hdd.qcow2",
        }

    def test_missing_sys_files_table_returns_empty(self):
        assert parse_xemu_sys_files("[general]\nshow_welcome = false\n") == {}

    def test_empty_document_returns_empty(self):
        assert parse_xemu_sys_files("") == {}

    def test_partial_keys_present(self):
        text = '[sys.files]\nbootrom_path = "/bios/mcpx_1.0.bin"\n'
        assert parse_xemu_sys_files(text) == {"bootrom_path": "/bios/mcpx_1.0.bin"}

    def test_ignores_unrelated_keys_in_sys_files(self):
        text = """
        [sys.files]
        bootrom_path = "/bios/mcpx_1.0.bin"
        eeprom_path = "/bios/eeprom.bin"
        """
        assert parse_xemu_sys_files(text) == {"bootrom_path": "/bios/mcpx_1.0.bin"}

    def test_non_string_value_treated_as_absent(self):
        text = "[sys.files]\nbootrom_path = 42\n"
        assert parse_xemu_sys_files(text) == {}

    def test_sys_files_wrong_type_treated_as_empty(self):
        text = "[sys]\nfiles = 42\n"
        assert parse_xemu_sys_files(text) == {}

    def test_malformed_toml_raises(self):
        with pytest.raises(tomllib.TOMLDecodeError):
            parse_xemu_sys_files("not valid [ toml")


class TestComputeXemuAlignment:
    def test_both_firmware_keys_aligned(self):
        sys_files = {
            "bootrom_path": "/bios/mcpx_1.0.bin",
            "flashrom_path": "/bios/Complex_4627v1.03.bin",
        }
        result = compute_xemu_alignment(sys_files, "/bios")
        assert result["bootrom_path"] == {"configured_path": "/bios/mcpx_1.0.bin", "in_plugin_bios_dir": True}
        assert result["flashrom_path"] == {
            "configured_path": "/bios/Complex_4627v1.03.bin",
            "in_plugin_bios_dir": True,
        }

    def test_key_pointing_elsewhere_is_not_aligned(self):
        sys_files = {"bootrom_path": "/some/other/place/mcpx_1.0.bin"}
        result = compute_xemu_alignment(sys_files, "/bios")
        assert result["bootrom_path"]["in_plugin_bios_dir"] is False

    def test_absent_key_reports_none_and_not_aligned(self):
        result = compute_xemu_alignment({}, "/bios")
        assert result["hdd_path"] == {"configured_path": None, "in_plugin_bios_dir": False}

    def test_trailing_slash_in_expected_dir_still_matches(self):
        sys_files = {"bootrom_path": "/bios/mcpx_1.0.bin"}
        result = compute_xemu_alignment(sys_files, "/bios/")
        assert result["bootrom_path"]["in_plugin_bios_dir"] is True

    def test_result_covers_all_three_keys_even_when_none_are_set(self):
        result = compute_xemu_alignment({}, "/bios")
        assert set(result.keys()) == {"bootrom_path", "flashrom_path", "hdd_path"}

    def test_empty_expected_dir_never_aligns(self):
        sys_files = {"bootrom_path": "/bios/mcpx_1.0.bin"}
        result = compute_xemu_alignment(sys_files, "")
        assert result["bootrom_path"]["in_plugin_bios_dir"] is False
