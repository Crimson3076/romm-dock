"""Tests for adapters.retroarch_install.retroarch_installed — the shared RetroArch presence probe."""

from __future__ import annotations

from adapters.retroarch_install import retroarch_installed


def _standalone_retroarch_flatpak(tmp_path) -> None:
    files_dir = (
        tmp_path / ".local" / "share" / "flatpak" / "app" / "org.libretro.RetroArch" / "current" / "active" / "files"
    )
    files_dir.mkdir(parents=True, exist_ok=True)


def _retrodeck_bundled_retroarch(tmp_path) -> None:
    files_dir = (
        tmp_path
        / ".local"
        / "share"
        / "flatpak"
        / "app"
        / "net.retrodeck.retrodeck"
        / "current"
        / "active"
        / "files"
        / "retrodeck"
        / "components"
        / "retroarch"
    )
    files_dir.mkdir(parents=True, exist_ok=True)


class TestRetroarchInstalled:
    def test_false_when_neither_present(self, tmp_path):
        assert retroarch_installed(str(tmp_path)) is False

    def test_true_for_standalone_flatpak(self, tmp_path):
        _standalone_retroarch_flatpak(tmp_path)
        assert retroarch_installed(str(tmp_path)) is True

    def test_true_for_retrodeck_bundled_component(self, tmp_path):
        _retrodeck_bundled_retroarch(tmp_path)
        assert retroarch_installed(str(tmp_path)) is True

    def test_true_when_both_present(self, tmp_path):
        _standalone_retroarch_flatpak(tmp_path)
        _retrodeck_bundled_retroarch(tmp_path)
        assert retroarch_installed(str(tmp_path)) is True

    def test_retrodeck_flatpak_present_without_the_retroarch_component_is_false(self, tmp_path):
        """RetroDECK itself installed, but without its bundled RetroArch component."""
        files_dir = (
            tmp_path
            / ".local"
            / "share"
            / "flatpak"
            / "app"
            / "net.retrodeck.retrodeck"
            / "current"
            / "active"
            / "files"
        )
        files_dir.mkdir(parents=True, exist_ok=True)
        assert retroarch_installed(str(tmp_path)) is False
