"""Filesystem discovery of an installed Proton build for native-Windows launches.

Scans the two standard Steam install roots (``~/.local/share/Steam``,
``~/.steam/steam`` — the same candidates :class:`adapters.steam_config.
SteamConfigAdapter` and :class:`adapters.steam_recovery.SteamRecoveryAdapter`
probe, in the same order) for installed Proton builds and picks one to launch
native-Windows ROMs with.

Tie-break rule (a judgment call, not a provable contract — stated here so it
is reviewable rather than implicit): official Valve Proton builds live under
``<steam_root>/steamapps/common/Proton*/proton``; community GE-Proton builds
live under ``<steam_root>/compatibilitytools.d/*/proton``. A community build
is preferred over an official one whenever at least one is installed —
community builds are generally the most compatible choice for launching a
non-Steam/native title — and within each group the newest by directory
modification time wins. This also covers "only 'Proton - Experimental'
exists" without a special case: it is simply the sole (and so newest) member
of the official group. No Proton version string is parsed; ``mtime`` is the
only ordering signal, since a directory name like ``"Proton - Experimental"``
has no numeric version to compare against ``"GE-Proton9-27"`` or ``"Proton
9.0"`` in the first place.

Only the executable's presence is checked, not its executable bit — a build a
user extracted without preserving permissions should still be found; whether
it actually runs is Proton's problem, not this adapter's.
"""

from __future__ import annotations

import os

from domain.proton import ProtonInstallation

_STEAM_ROOT_CANDIDATES = (
    (".local", "share", "Steam"),
    (".steam", "steam"),
)


class ProtonLocatorAdapter:
    """Locate an installed Proton build under the user's Steam install."""

    def __init__(self, *, user_home: str, runtime_dir: str) -> None:
        self._user_home = user_home
        self._runtime_dir = runtime_dir

    def locate(self) -> ProtonInstallation | None:
        steam_root = self._resolve_steam_root()
        if steam_root is None:
            return None

        community = self._newest(self._scan(os.path.join(steam_root, "compatibilitytools.d")))
        if community is not None:
            return self._to_installation(community, steam_root)

        official = self._newest(self._scan_official(os.path.join(steam_root, "steamapps", "common")))
        if official is not None:
            return self._to_installation(official, steam_root)

        return None

    def compat_data_path(self, rom_id: int) -> str:
        # Created here, not baked as a shell `mkdir` in the launch command
        # (ADR-0030 decision 4 rejected that for depending on unverified shell
        # interpretation). This directory is under the plugin's OWN runtime_dir
        # tree, not Steam's compatdata layout, so nothing else — not Steam, not
        # Proton — has ever created `proton-prefixes/` or the per-ROM leaf
        # under it; a real Steam-library game gets this for free because Steam
        # itself pre-creates the compatdata dir before invoking Proton, which
        # doesn't apply to a non-Steam-launched executable like this one's.
        path = os.path.join(self._runtime_dir, "proton-prefixes", str(rom_id))
        os.makedirs(path, exist_ok=True)
        return path

    def _resolve_steam_root(self) -> str | None:
        # .local/share/Steam checked first — matches SteamConfigAdapter.find_steam_user_dir
        # and SteamRecoveryAdapter._resolve_user, since .steam/steam is a symlink
        # that does not exist on every install method.
        for parts in _STEAM_ROOT_CANDIDATES:
            candidate = os.path.join(self._user_home, *parts)
            if os.path.isdir(candidate):
                return os.path.realpath(candidate)
        return None

    @staticmethod
    def _scan(container: str) -> list[tuple[str, str, float]]:
        """List every ``<container>/<name>/proton`` found, unfiltered by name."""
        try:
            entries = os.listdir(container)
        except OSError:
            return []
        found: list[tuple[str, str, float]] = []
        for name in entries:
            build_dir = os.path.join(container, name)
            binary = os.path.join(build_dir, "proton")
            try:
                if not os.path.isfile(binary):
                    continue
                mtime = os.stat(build_dir).st_mtime
            except OSError:
                # An unreadable or malformed entry is skipped, not fatal — one
                # bad directory must not hide every other Proton build.
                continue
            found.append((name, binary, mtime))
        return found

    @staticmethod
    def _scan_official(container: str) -> list[tuple[str, str, float]]:
        """Like :meth:`_scan`, restricted to Valve's ``Proton*`` naming convention."""
        return [entry for entry in ProtonLocatorAdapter._scan(container) if entry[0].startswith("Proton")]

    @staticmethod
    def _newest(found: list[tuple[str, str, float]]) -> tuple[str, str, float] | None:
        if not found:
            return None
        return max(found, key=lambda entry: entry[2])

    @staticmethod
    def _to_installation(entry: tuple[str, str, float], steam_root: str) -> ProtonInstallation:
        name, binary, _mtime = entry
        return ProtonInstallation(name=name, binary_path=binary, steam_install_path=steam_root)
