"""Unit tests for ``domain/windows_launch`` — launch-target enumeration + resolution."""

from __future__ import annotations

from domain.windows_launch import (
    WindowsExecutable,
    enumerate_executables,
    resolve_launch_path,
    resolve_launch_target,
)

_WIN_DIR = "/roms/win/Some Game"


def _p(name: str) -> str:
    return f"{_WIN_DIR}/{name}"


class TestEnumerateExecutables:
    def test_single_exe_returns_one(self):
        executables = enumerate_executables([_p("Game.exe")])
        assert executables == [WindowsExecutable(filename="Game.exe", path=_p("Game.exe"), kind="exe")]

    def test_empty_input_returns_empty(self):
        assert enumerate_executables([]) == []

    def test_no_exe_files_returns_empty(self):
        assert enumerate_executables([_p("readme.txt"), _p("cover.png")]) == []

    def test_non_exe_siblings_are_ignored(self):
        files = [_p("Game.exe"), _p("data.pak"), _p("readme.txt")]
        executables = enumerate_executables(files)
        assert [e.filename for e in executables] == ["Game.exe"]

    def test_extension_match_is_case_insensitive(self):
        executables = enumerate_executables([_p("Launcher.EXE")])
        assert [e.filename for e in executables] == ["Launcher.EXE"]

    def test_multiple_exes_ordered_alphabetically_case_insensitive(self):
        files = [_p("zeta.exe"), _p("Alpha.exe"), _p("beta.exe")]
        executables = enumerate_executables(files)
        assert [e.filename for e in executables] == ["Alpha.exe", "beta.exe", "zeta.exe"]

    def test_order_is_stable_regardless_of_input_order(self):
        files_a = [_p("b.exe"), _p("a.exe")]
        files_b = [_p("a.exe"), _p("b.exe")]
        assert [e.filename for e in enumerate_executables(files_a)] == [
            e.filename for e in enumerate_executables(files_b)
        ]

    def test_dotexe_substring_in_name_but_not_extension_is_excluded(self):
        # A filename that merely contains "exe" is not one just because of that.
        assert enumerate_executables([_p("Game.exe.bak")]) == []

    def test_filename_and_path_fields(self):
        executables = enumerate_executables([_p("Sub/Game.exe")])
        assert executables[0].filename == "Game.exe"
        assert executables[0].path == _p("Sub/Game.exe")

    def test_sh_script_is_enumerated_as_native(self):
        executables = enumerate_executables([_p("patcher-start.sh")])
        assert executables == [
            WindowsExecutable(filename="patcher-start.sh", path=_p("patcher-start.sh"), kind="native")
        ]

    def test_sh_extension_match_is_case_insensitive(self):
        executables = enumerate_executables([_p("Launcher.SH")])
        assert executables[0].kind == "native"

    def test_exe_and_sh_interleave_in_one_alphabetical_order(self):
        files = [_p("zeta.exe"), _p("alpha.sh"), _p("mid.exe")]
        executables = enumerate_executables(files)
        assert [(e.filename, e.kind) for e in executables] == [
            ("alpha.sh", "native"),
            ("mid.exe", "exe"),
            ("zeta.exe", "exe"),
        ]

    def test_other_extensions_are_still_ignored(self):
        assert enumerate_executables([_p("readme.sh.bak"), _p("run.bat"), _p("patch.py")]) == []


def _executables() -> list[str]:
    return [_p("Alpha.exe"), _p("Beta.exe"), _p("Gamma.exe")]


class TestResolveLaunchPath:
    def test_no_selection_falls_back_to_first_enumerated(self):
        path = resolve_launch_path(_executables(), None)
        assert path == _p("Alpha.exe")

    def test_pinned_exe_returns_its_path(self):
        path = resolve_launch_path(_executables(), "Beta.exe")
        assert path == _p("Beta.exe")

    def test_stale_pin_falls_back_to_first_enumerated(self):
        path = resolve_launch_path(_executables(), "NoSuchFile.exe")
        assert path == _p("Alpha.exe")

    def test_empty_files_returns_none_even_with_a_selection(self):
        assert resolve_launch_path([], "Alpha.exe") is None

    def test_empty_files_and_no_selection_returns_none(self):
        assert resolve_launch_path([], None) is None

    def test_single_exe_with_no_selection_returns_it(self):
        assert resolve_launch_path([_p("Only.exe")], None) == _p("Only.exe")

    def test_no_exe_among_files_returns_none(self):
        assert resolve_launch_path([_p("readme.txt")], "Alpha.exe") is None


class TestResolveLaunchTarget:
    def test_pinned_sh_script_returns_it_with_native_kind(self):
        files = [_p("Game.exe"), _p("patcher-start.sh")]
        target = resolve_launch_target(files, "patcher-start.sh")
        assert target == WindowsExecutable(filename="patcher-start.sh", path=_p("patcher-start.sh"), kind="native")

    def test_default_pick_when_only_a_script_is_present_is_native(self):
        target = resolve_launch_target([_p("patcher-start.sh")], None)
        assert target is not None
        assert target.kind == "native"

    def test_default_pick_among_exe_and_sh_is_alphabetically_first_regardless_of_kind(self):
        target = resolve_launch_target([_p("zeta.exe"), _p("alpha.sh")], None)
        assert target is not None
        assert target.filename == "alpha.sh"

    def test_no_targets_returns_none(self):
        assert resolve_launch_target([_p("readme.txt")], None) is None
