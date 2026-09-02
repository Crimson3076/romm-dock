"""WindowsLaunchResolver — the single read-path native-Windows launch seam per ROM.

The one place that answers "which target will this native-Windows ROM
actually launch with, and what command runs it?", folding the user's
persisted ``roms.selected_exe`` pick over the live enumeration of launchable
targets (``.exe`` or a bundled ``.sh``) in the ROM's install directory, then
either wrapping a ``.exe`` in a Proton invocation via the located build, or
rendering a ``.sh`` script's direct ``bash`` invocation — see
:func:`domain.windows_launch.enumerate_executables`'s ``kind`` field. Every
launch-bake site (library sync, download-complete/adoption, RetroDECK-home
migration + startup reconcile) and the exe-picker service draw from this SAME
seam, so the baked launch_options never diverges from the picker's current
selection — mirroring :class:`services.disc_launch_resolver.DiscLaunchResolver`'s
role for multi-disc ROMs.

Resolution is a bake-time launch-target layer only: it never rewrites the
install's ``file_path``. An install the system cannot launch
(``launchable is False``) resolves to ``""`` before any target work, matching
every other bake seam's convention. No launchable target present resolves to
``""`` too; for a ``.exe`` target specifically, no Proton found also resolves
to ``""`` (a ``.sh`` target never consults Proton at all) — a native-Windows
ROM has no "pick before you can play" step; there is simply nothing to launch
yet.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.shortcut_data import build_launch_options, resolve_native_invocation, resolve_proton_invocation
from domain.windows_launch import (
    WindowsExecutable,
    enumerate_executables,
    resolve_launch_path,
    resolve_launch_target,
)

if TYPE_CHECKING:
    from domain.rom_install import RomInstall
    from services.protocols import DirectoryFileListerFn, ProtonLocator


@dataclass(frozen=True)
class WindowsLaunchResolverConfig:
    """Frozen wiring bundle handed to ``WindowsLaunchResolver.__init__``.

    Carries the recursive directory file lister (to scan a folder-backed
    native-Windows install's directory for ``.exe``/``.sh`` candidates) and the
    ``ProtonLocator`` (which build to invoke, and where its per-ROM compat-data
    prefix lives — consulted only for a ``.exe`` target).
    """

    list_files: DirectoryFileListerFn
    proton_locator: ProtonLocator


class WindowsLaunchResolver:
    """Resolve the launch-bake command and target list for one installed native-Windows ROM."""

    def __init__(self, *, config: WindowsLaunchResolverConfig) -> None:
        self._list_files = config.list_files
        self._proton_locator = config.proton_locator

    def enumerate_executables(self, install: RomInstall) -> list[WindowsExecutable]:
        """Enumerate the launchable targets (``.exe`` or ``.sh``) in *install*'s directory.

        A single-file install (``rom_dir is None``) enumerates over its own
        ``file_path`` alone — a native-Windows ROM can ship as a bare ``.exe``.
        A folder-backed install is scanned recursively. Pure file listing — no
        mutation.
        """
        return enumerate_executables(self._files_for(install))

    def resolve_exe_path(self, install: RomInstall, selected_exe: str | None) -> str:
        """Return the bare launch-target path to bake, or ``""`` when *install* has none.

        An unlaunchable install (``launchable is False``) and an install with
        no launchable target present both resolve to ``""`` — the caller
        renders that as the empty launch command. Otherwise mirrors
        :func:`domain.windows_launch.resolve_launch_path`: the pinned
        *selected_exe* when it still names a present target, else the first
        enumerated one.
        """
        if not install.launchable:
            return ""
        return resolve_launch_path(self._files_for(install), selected_exe) or ""

    def resolve_launch_options(self, install: RomInstall, selected_exe: str | None) -> str:
        """Return the full Steam-shortcut launch command for *install*.

        ``""`` when *install* is unlaunchable or has no launch target at all
        (mirroring :meth:`resolve_exe_path`). Otherwise branches on the
        resolved target's ``kind``: a ``.exe`` target (``"exe"``) renders the
        Proton-wrapped command, and ``""`` if no Proton build is located
        (:class:`ProtonLocator` — "no Proton installed" is a first-class
        answer, never fatal); a bundled Linux script (``"native"``) renders
        the direct ``bash``-invocation command instead — Proton is never
        consulted for it, so a system with no Proton build installed can still
        launch a native target. Either branch renders the same empty
        placeholder every other unlaunchable install does when it cannot
        resolve.
        """
        if not install.launchable:
            return ""
        target = resolve_launch_target(self._files_for(install), selected_exe)
        if target is None:
            return ""
        if target.kind == "native":
            invocation = resolve_native_invocation(os.path.dirname(target.path))
            return build_launch_options(invocation, target.path)
        proton = self._proton_locator.locate()
        if proton is None:
            return ""
        invocation = resolve_proton_invocation(
            proton, self._proton_locator.compat_data_path(install.rom_id), os.path.dirname(target.path)
        )
        return build_launch_options(invocation, target.path)

    def _files_for(self, install: RomInstall) -> list[str]:
        return [install.file_path] if install.rom_dir is None else self._list_files(install.rom_dir)
