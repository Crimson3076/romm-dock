"""Proton discovery — locating an installed Proton build for native-Windows launches.

A native-Windows ROM (``platform_slug == "win"``) has no emulator/core step;
instead it launches through a Proton build this plugin locates and invokes
itself, independent of Steam's own per-shortcut compat-tool assignment (which
only applies to a shortcut Steam itself launches through its compat-tool UI,
not a command this plugin bakes directly). ``ProtonLocator`` is the read seam
services query for "is a usable Proton build present, and where"; "not found"
is a first-class ``None`` answer, not an exception — a user without Steam's
Proton installed, or on a non-standard Steam path, must degrade to "Windows
games unavailable" rather than crash.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from domain.proton import ProtonInstallation


class ProtonLocator(Protocol):
    """Locate an installed Proton build and compute where its per-ROM prefix lives.

    ``locate`` scans the standard Steam install locations for a Proton build
    (official Valve Proton and community GE-Proton) and returns the one to
    launch with, or ``None`` when none is found. ``compat_data_path`` computes
    AND creates the directory a ROM's ``STEAM_COMPAT_DATA_PATH`` should point
    at — unlike a real Steam-library game, nothing else ever creates this
    directory (it lives under the plugin's own ``runtime_dir``, not Steam's
    ``compatdata/`` layout), so the read seam owns making it exist too.
    """

    def locate(self) -> ProtonInstallation | None:
        """Return the Proton build to launch native-Windows ROMs with, or ``None``.

        ``None`` means no usable Proton build was found — callers must treat
        this as "Windows games unavailable", never retry it as an error.
        """
        ...

    def compat_data_path(self, rom_id: int) -> str:
        """Return the per-ROM ``STEAM_COMPAT_DATA_PATH`` prefix for *rom_id*, creating it.

        Idempotent — safe to call on every bake, not just the first launch.
        """
        ...
