"""WindowsLaunchResolver — the single read-path native-Windows launch seam per ROM.

The one place that answers "which ``.exe`` will this native-Windows ROM
actually launch with, and what Proton command runs it?", folding the user's
persisted ``roms.selected_exe`` pick over the live enumeration of ``.exe``
files in the ROM's install directory, then wrapping the winner in a Proton
invocation via the located build. Every launch-bake site (library sync,
download-complete/adoption, RetroDECK-home migration + startup reconcile) and
the exe-picker service draw from this SAME seam, so the baked launch_options
never diverges from the picker's current selection — mirroring
:class:`services.disc_launch_resolver.DiscLaunchResolver`'s role for
multi-disc ROMs.

Resolution is a bake-time launch-target layer only: it never rewrites the
install's ``file_path``. An install the system cannot launch
(``launchable is False``) resolves to ``""`` before any exe work, matching
every other bake seam's convention. No Proton found or no ``.exe`` present
both resolve to ``""`` too — a native-Windows ROM has no "pick before you can
play" step; there is simply nothing to launch yet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.shortcut_data import build_launch_options, resolve_proton_invocation
from domain.windows_launch import WindowsExecutable, enumerate_executables, resolve_launch_path

if TYPE_CHECKING:
    from domain.rom_install import RomInstall
    from services.protocols import DirectoryFileListerFn, ProtonLocator


@dataclass(frozen=True)
class WindowsLaunchResolverConfig:
    """Frozen wiring bundle handed to ``WindowsLaunchResolver.__init__``.

    Carries the recursive directory file lister (to scan a folder-backed
    native-Windows install's directory for ``.exe`` candidates) and the
    ``ProtonLocator`` (which build to invoke, and where its per-ROM compat-data
    prefix lives).
    """

    list_files: DirectoryFileListerFn
    proton_locator: ProtonLocator


class WindowsLaunchResolver:
    """Resolve the launch-bake command and exe list for one installed native-Windows ROM."""

    def __init__(self, *, config: WindowsLaunchResolverConfig) -> None:
        self._list_files = config.list_files
        self._proton_locator = config.proton_locator

    def enumerate_executables(self, install: RomInstall) -> list[WindowsExecutable]:
        """Enumerate the launchable ``.exe`` files in *install*'s directory.

        A single-file install (``rom_dir is None``) enumerates over its own
        ``file_path`` alone — a native-Windows ROM can ship as a bare ``.exe``.
        A folder-backed install is scanned recursively. Pure file listing — no
        mutation.
        """
        return enumerate_executables(self._files_for(install))

    def resolve_exe_path(self, install: RomInstall, selected_exe: str | None) -> str:
        """Return the bare ``.exe`` path to bake, or ``""`` when *install* has none.

        An unlaunchable install (``launchable is False``) and an install with
        no ``.exe`` present both resolve to ``""`` — the caller renders that as
        the empty launch command. Otherwise mirrors
        :func:`domain.windows_launch.resolve_launch_path`: the pinned
        *selected_exe* when it still names a present ``.exe``, else the first
        enumerated one.
        """
        if not install.launchable:
            return ""
        return resolve_launch_path(self._files_for(install), selected_exe) or ""

    def resolve_launch_options(self, install: RomInstall, selected_exe: str | None) -> str:
        """Return the full Proton-wrapped Steam-shortcut launch command for *install*.

        ``""`` when there is no ``.exe`` to launch (:meth:`resolve_exe_path`) OR
        no Proton build is located (:class:`ProtonLocator` — "no Proton
        installed" is a first-class answer, never fatal) — a native-Windows ROM
        with either gap has no launchable command at all, the same empty
        placeholder every other unlaunchable install renders.
        """
        exe_path = self.resolve_exe_path(install, selected_exe)
        if not exe_path:
            return ""
        proton = self._proton_locator.locate()
        if proton is None:
            return ""
        invocation = resolve_proton_invocation(
            proton, self._proton_locator.compat_data_path(install.rom_id), os.path.dirname(exe_path)
        )
        return build_launch_options(invocation, exe_path)

    def _files_for(self, install: RomInstall) -> list[str]:
        return [install.file_path] if install.rom_dir is None else self._list_files(install.rom_dir)
