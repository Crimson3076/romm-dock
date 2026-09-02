"""Native-Windows launch-target enumeration and resolution — pure decision kernel.

The Windows-launch picker's compute layer: turn a flat list of files in a
``platform_slug == "win"`` ROM's install directory into an ordered list of
launchable targets, and resolve which one a launch should bake given the
user's persisted selection (``roms.selected_exe``). Analogous to
:mod:`domain.disc_selection`'s multi-disc kernel, but simpler — a native-Windows
ROM has no emulator/core step at all, so there is no ``file_path`` fallback and
no in-place-playlist concept (no ``.m3u`` equivalent): the only decision is
"which target", and the default is always "the first one enumerated".

A target is either a ``.exe`` (``kind == "exe"``, launched through Proton) or a
bundled Linux launcher script (``kind == "native"``, launched directly — no
Proton, no Wine). The latter exists for community tooling shipped alongside a
game that Proton itself cannot run: e.g. a third-party patcher/launcher script
distributed as a RomM asset (``uranium-shellpatch``'s ``patcher-start.sh`` was
the motivating case — a one-time patch step for Pokémon Uranium, run like any
other selectable target rather than requiring a separate mechanism). v1 covers
only ``.sh``; no other native-script shape (``.py``, extension-less) is
enumerated.

Resolution is a bake-time launch-target layer only: it returns the target a
caller bakes into the Steam shortcut's launch_options (wrapped in the Proton
invocation, or the native invocation, an adapter/domain builder renders), it
never rewrites the install's ``file_path``.

No I/O, no service/adapter/lib imports. Pure functions only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

# Basename extension (lowercased) -> the WindowsExecutable.kind it enumerates
# as. ".exe" runs through Proton; everything else here runs natively (no
# Proton, no Wine) via domain.shortcut_data.resolve_native_invocation.
_LAUNCH_TARGET_KINDS: dict[str, Literal["exe", "native"]] = {
    ".exe": "exe",
    ".sh": "native",
}


@dataclass(frozen=True, slots=True)
class WindowsExecutable:
    """One launchable target within a native-Windows ROM's install directory.

    ``filename`` is the basename (the stable selection key persisted in
    ``roms.selected_exe``); ``path`` is the full path to bake as the launch
    target. ``kind`` is ``"exe"`` (Proton-launched) or ``"native"`` (a bundled
    Linux script, launched directly) — see the module docstring. Unlike
    :class:`domain.disc_selection.Disc` there is no ``label`` (the basename
    already reads fine as a picker entry — there is no "(Disc N)" tag to parse
    into a friendlier one) and no ``index`` (nothing downstream needs a
    persisted position; enumeration order is exactly list order).
    """

    filename: str
    path: str
    kind: Literal["exe", "native"]


def enumerate_executables(files: Sequence[str]) -> list[WindowsExecutable]:
    """Enumerate the launchable targets among *files*, in a stable order.

    Parameters
    ----------
    files:
        Paths to every file in the ROM's install directory (a flat,
        already-recursive listing), in whatever order the caller's filesystem
        walk produced. A file whose extension is not in
        :data:`_LAUNCH_TARGET_KINDS` (``.exe``, ``.sh``) is ignored. v1
        supports no other launch-target shape (no ``.bat``, no ``.lnk``, no
        ``.py``).

    Returns
    -------
    list[WindowsExecutable]
        Targets ordered by basename, case-insensitively, ``.exe`` and
        ``.sh`` interleaved in the same alphabetical order. Unlike multi-disc
        images there is no numbering scheme to parse, so alphabetical order by
        filename is the only ordering this listing can offer deterministically
        across repeated enumerations of the same install.
    """
    matches: list[tuple[str, Literal["exe", "native"]]] = []
    for path in files:
        kind = _LAUNCH_TARGET_KINDS.get(os.path.splitext(os.path.basename(path))[1].lower())
        if kind is not None:
            matches.append((path, kind))
    matches.sort(key=lambda pair: os.path.basename(pair[0]).lower())
    return [WindowsExecutable(filename=os.path.basename(path), path=path, kind=kind) for path, kind in matches]


def resolve_launch_target(files: Sequence[str], selected_exe: str | None) -> WindowsExecutable | None:
    """Resolve the launch target (path + kind) to bake into the launch command.

    If *selected_exe* names one of the targets enumerated from *files*,
    returns it. Otherwise — no selection has been made yet, or the pinned file
    is no longer present among *files* (a stale pin) — falls back to the first
    target :func:`enumerate_executables` returns (alphabetical order), with no
    distinction made between the two cases: the caller cannot tell "never
    selected" from "selection went stale" from the return value alone. Returns
    ``None`` only when *files* contains no launchable target at all, which the
    caller should treat as "nothing to launch", not as a default to retry.
    """
    targets = enumerate_executables(files)
    if not targets:
        return None
    if selected_exe is not None:
        for target in targets:
            if target.filename == selected_exe:
                return target
    return targets[0]


def resolve_launch_path(files: Sequence[str], selected_exe: str | None) -> str | None:
    """Resolve the launch target's bare path — see :func:`resolve_launch_target`.

    For callers that only need the path, not the ``kind`` (Proton-vs-native
    branch, which lives in ``WindowsLaunchResolver.resolve_launch_options``).
    """
    target = resolve_launch_target(files, selected_exe)
    return target.path if target is not None else None
