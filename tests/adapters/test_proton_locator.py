"""Tests for ``ProtonLocatorAdapter`` — Proton build discovery under a fake home."""

from __future__ import annotations

import os

from adapters.proton_locator import ProtonLocatorAdapter


def _adapter(tmp_path) -> ProtonLocatorAdapter:
    return ProtonLocatorAdapter(user_home=str(tmp_path), runtime_dir=str(tmp_path / "runtime"))


def _make_proton(root, *container: str, name: str, mtime: float) -> None:
    """Create ``<root>/<container>/<name>/proton`` and stamp its directory mtime."""
    build_dir = root
    for part in container:
        build_dir = build_dir / part
    build_dir = build_dir / name
    build_dir.mkdir(parents=True)
    (build_dir / "proton").write_text("#!/usr/bin/env python3\n")
    os.utime(str(build_dir), (mtime, mtime))


class TestNoProtonAnywhere:
    def test_no_steam_install_returns_none(self, tmp_path):
        assert _adapter(tmp_path).locate() is None

    def test_steam_install_with_no_proton_returns_none(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        (steam_root / "steamapps" / "common").mkdir(parents=True)
        assert _adapter(tmp_path).locate() is None


class TestOfficialProtonOnly:
    def test_single_official_build_is_found(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        _make_proton(steam_root, "steamapps", "common", name="Proton 9.0", mtime=1000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "Proton 9.0"
        assert result.binary_path == str(steam_root / "steamapps" / "common" / "Proton 9.0" / "proton")
        assert result.steam_install_path == str(steam_root)

    def test_newest_official_build_wins_by_mtime(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        _make_proton(steam_root, "steamapps", "common", name="Proton 8.0", mtime=1000)
        _make_proton(steam_root, "steamapps", "common", name="Proton 9.0", mtime=2000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "Proton 9.0"

    def test_only_experimental_present_is_used(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        _make_proton(steam_root, "steamapps", "common", name="Proton - Experimental", mtime=1000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "Proton - Experimental"

    def test_non_proton_prefixed_dir_is_ignored(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        _make_proton(steam_root, "steamapps", "common", name="Proton 9.0", mtime=1000)
        # An unrelated common/ entry (a regular game) must never be mistaken
        # for a Proton build even if it happens to ship a file named "proton".
        _make_proton(steam_root, "steamapps", "common", name="SomeGame", mtime=5000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "Proton 9.0"


class TestGeProtonOnly:
    def test_single_community_build_is_found(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        _make_proton(steam_root, "compatibilitytools.d", name="GE-Proton9-27", mtime=1000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "GE-Proton9-27"
        assert result.binary_path == str(steam_root / "compatibilitytools.d" / "GE-Proton9-27" / "proton")

    def test_newest_community_build_wins_by_mtime(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        _make_proton(steam_root, "compatibilitytools.d", name="GE-Proton9-20", mtime=1000)
        _make_proton(steam_root, "compatibilitytools.d", name="GE-Proton9-27", mtime=2000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "GE-Proton9-27"


class TestBothPresent:
    def test_community_build_wins_over_official_regardless_of_mtime(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        # Official is newer, but a community build is still preferred (#tie-break rule).
        _make_proton(steam_root, "steamapps", "common", name="Proton 9.0", mtime=9000)
        _make_proton(steam_root, "compatibilitytools.d", name="GE-Proton9-27", mtime=1000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "GE-Proton9-27"


class TestMalformedEntries:
    def test_unreadable_directory_entry_is_skipped_not_fatal(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        _make_proton(steam_root, "compatibilitytools.d", name="GE-Proton9-27", mtime=1000)
        # A directory entry that is actually a broken symlink must not crash
        # the scan — it is skipped and the real build is still found.
        broken = steam_root / "compatibilitytools.d" / "broken-symlink"
        broken.symlink_to(steam_root / "does-not-exist")

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "GE-Proton9-27"

    def test_entry_without_proton_binary_is_skipped(self, tmp_path):
        steam_root = tmp_path / ".local" / "share" / "Steam"
        empty_dir = steam_root / "compatibilitytools.d" / "EmptyDir"
        empty_dir.mkdir(parents=True)

        result = _adapter(tmp_path).locate()

        assert result is None


class TestSteamRootResolution:
    def test_prefers_local_share_over_dot_steam(self, tmp_path):
        _make_proton(tmp_path / ".local" / "share" / "Steam", "compatibilitytools.d", name="GE-Proton9-27", mtime=1000)
        _make_proton(tmp_path / ".steam" / "steam", "compatibilitytools.d", name="GE-Proton9-30", mtime=2000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.name == "GE-Proton9-27"

    def test_falls_back_to_dot_steam_when_local_share_absent(self, tmp_path):
        steam_root = tmp_path / ".steam" / "steam"
        _make_proton(steam_root, "compatibilitytools.d", name="GE-Proton9-27", mtime=1000)

        result = _adapter(tmp_path).locate()

        assert result is not None
        assert result.steam_install_path == str(steam_root)


class TestCompatDataPath:
    def test_computes_path_without_creating_it(self, tmp_path):
        adapter = _adapter(tmp_path)

        path = adapter.compat_data_path(42)

        assert path == str(tmp_path / "runtime" / "proton-prefixes" / "42")
        assert not os.path.exists(path)

    def test_distinct_rom_ids_get_distinct_paths(self, tmp_path):
        adapter = _adapter(tmp_path)

        assert adapter.compat_data_path(1) != adapter.compat_data_path(2)
