"""Native-Windows executable enumeration and launch-path resolution — pure decision kernel.

The Windows-launch picker's compute layer: turn a flat list of files in a
``platform_slug == "win"`` ROM's install directory into an ordered list of
launchable ``.exe`` files, and resolve which one a launch should bake given the
user's persisted selection (``roms.selected_exe``). Analogous to
:mod:`domain.disc_selection`'s multi-disc kernel, but simpler — a native-Windows
ROM has no emulator/core step at all, so there is no ``file_path`` fallback and
no in-place-playlist concept (no ``.m3u`` equivalent): the only decision is
"which ``.exe``", and the default is always "the first one enumerated".

Resolution is a bake-time launch-target layer only: it returns the path a
caller bakes into the Steam shortcut's launch_options (wrapped in the Proton
invocation an adapter builds), it never rewrites the install's ``file_path``.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class WindowsExecutable:
    """One launchable ``.exe`` within a native-Windows ROM's install directory.

    ``filename`` is the basename (the stable selection key persisted in
    ``roms.selected_exe``); ``path`` is the full path to bake as the Proton
    launch target. Unlike :class:`domain.disc_selection.Disc` there is no
    ``label`` (the basename already reads fine as a picker entry — there is no
    "(Disc N)" tag to parse into a friendlier one) and no ``index`` (nothing
    downstream needs a persisted position; enumeration order is exactly list
    order).
    """

    filename: str
    path: str


def enumerate_executables(files: Sequence[str]) -> list[WindowsExecutable]:
    """Enumerate the launchable ``.exe`` files among *files*, in a stable order.

    Parameters
    ----------
    files:
        Paths to every file in the ROM's install directory (a flat,
        already-recursive listing), in whatever order the caller's filesystem
        walk produced. Non-``.exe`` files are ignored. v1 supports no other
        Windows launch-target shape (no ``.bat``, no ``.lnk``).

    Returns
    -------
    list[WindowsExecutable]
        Executables ordered by basename, case-insensitively. Unlike multi-disc
        images there is no numbering scheme to parse, so alphabetical order by
        filename is the only ordering this listing can offer deterministically
        across repeated enumerations of the same install.
    """
    matches = [path for path in files if os.path.splitext(os.path.basename(path))[1].lower() == ".exe"]
    matches.sort(key=lambda path: os.path.basename(path).lower())
    return [WindowsExecutable(filename=os.path.basename(path), path=path) for path in matches]


def resolve_launch_path(files: Sequence[str], selected_exe: str | None) -> str | None:
    """Resolve the ``.exe`` path to bake into the Proton launch command.

    If *selected_exe* names one of the ``.exe`` files enumerated from *files*,
    returns its path. Otherwise — no selection has been made yet, or the
    pinned file is no longer present among *files* (a stale pin) — falls back
    to the first executable :func:`enumerate_executables` returns (alphabetical
    order), with no distinction made between the two cases: the caller cannot
    tell "never selected" from "selection went stale" from the return value
    alone. Returns ``None`` only when *files* contains no ``.exe`` at all,
    which the caller should treat as "nothing to launch", not as a default to
    retry.
    """
    executables = enumerate_executables(files)
    if not executables:
        return None
    if selected_exe is not None:
        for executable in executables:
            if executable.filename == selected_exe:
                return executable.path
    return executables[0].path
