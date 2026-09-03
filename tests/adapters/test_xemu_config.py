"""Tests for adapters.xemu_config.XemuConfigAdapter."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

import pytest

from adapters.xemu_config import XemuConfigAdapter

if TYPE_CHECKING:
    from pathlib import Path


def _native_toml_path(user_home: Path) -> Path:
    return user_home / ".local" / "share" / "xemu" / "xemu" / "xemu.toml"


def _flatpak_toml_path(user_home: Path) -> Path:
    return user_home / ".var" / "app" / "app.xemu.xemu" / "data" / "xemu" / "xemu" / "xemu.toml"


def _make_adapter(user_home: Path) -> XemuConfigAdapter:
    return XemuConfigAdapter(user_home=str(user_home), logger=logging.getLogger("test"))


class TestCandidatePaths:
    def test_native_then_flatpak_order(self, tmp_path):
        adapter = _make_adapter(tmp_path)
        assert adapter.candidate_paths() == [str(_native_toml_path(tmp_path)), str(_flatpak_toml_path(tmp_path))]


class TestGetSysFiles:
    def test_reads_native_config_when_present(self, tmp_path):
        path = _native_toml_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text('[sys.files]\nbootrom_path = "/bios/mcpx_1.0.bin"\n')

        sys_files, config_path = _make_adapter(tmp_path).get_sys_files()

        assert sys_files == {"bootrom_path": "/bios/mcpx_1.0.bin"}
        assert config_path == str(path)

    def test_falls_back_to_flatpak_when_native_absent(self, tmp_path):
        path = _flatpak_toml_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text('[sys.files]\nflashrom_path = "/bios/Complex.bin"\n')

        sys_files, config_path = _make_adapter(tmp_path).get_sys_files()

        assert sys_files == {"flashrom_path": "/bios/Complex.bin"}
        assert config_path == str(path)

    def test_neither_candidate_exists_returns_none_none(self, tmp_path):
        sys_files, config_path = _make_adapter(tmp_path).get_sys_files()
        assert sys_files is None
        assert config_path is None

    def test_malformed_toml_returns_none_sys_files_but_names_the_path(self, tmp_path):
        path = _native_toml_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text("not valid [ toml")

        sys_files, config_path = _make_adapter(tmp_path).get_sys_files()

        assert sys_files is None
        assert config_path == str(path)

    def test_unreadable_file_returns_none_sys_files_but_names_the_path(self, tmp_path):
        path = _native_toml_path(tmp_path)
        path.parent.mkdir(parents=True)
        path.write_text('[sys.files]\nbootrom_path = "/bios/mcpx_1.0.bin"\n')
        os.chmod(path, 0o000)
        try:
            if os.access(path, os.R_OK):
                pytest.skip("running as a user that bypasses file permissions (e.g. root)")
            sys_files, config_path = _make_adapter(tmp_path).get_sys_files()
            assert sys_files is None
            assert config_path == str(path)
        finally:
            os.chmod(path, 0o644)

    def test_native_present_but_empty_still_wins_over_flatpak(self, tmp_path):
        native = _native_toml_path(tmp_path)
        native.parent.mkdir(parents=True)
        native.write_text("")
        flatpak = _flatpak_toml_path(tmp_path)
        flatpak.parent.mkdir(parents=True)
        flatpak.write_text('[sys.files]\nbootrom_path = "/bios/mcpx_1.0.bin"\n')

        sys_files, config_path = _make_adapter(tmp_path).get_sys_files()

        assert sys_files == {}
        assert config_path == str(native)
