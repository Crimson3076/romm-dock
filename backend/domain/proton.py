"""Proton-installation value object — the discovery result native-Windows launches bake from.

No I/O, no imports from services, adapters, or lib. The discovery itself (which
Steam paths exist, which build is newest) is real filesystem work and lives in
:mod:`adapters.proton_locator`; this module holds only the resolved shape that
crosses the adapters/services Protocol boundary
(:class:`services.protocols.proton.ProtonLocator`), mirroring how
:class:`domain.shortcut_data.EmulatorInvocation` crosses the equivalent
RetroArch/ES-DE boundary.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProtonInstallation:
    """One discovered Proton build, resolved enough to invoke it directly.

    ``binary_path`` is the ``proton`` script/binary itself (not just its
    containing directory) — the launch command runs it directly
    (``<binary_path> run "<picked.exe>"``). ``steam_install_path`` is the Steam
    installation root this build was found under, which a launch command needs
    verbatim for ``STEAM_COMPAT_CLIENT_INSTALL_PATH`` (Proton uses it to locate
    Steam's runtime pieces). ``name`` is the build's directory basename (e.g.
    ``"GE-Proton9-27"``, ``"Proton 9.0"``, ``"Proton - Experimental"``) — not
    parsed for anything, kept only so logging and tests can say which build was
    picked without re-deriving it from ``binary_path``.
    """

    name: str
    binary_path: str
    steam_install_path: str
