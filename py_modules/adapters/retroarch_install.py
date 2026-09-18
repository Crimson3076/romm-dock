"""RetroArch presence probe — shared by the RetroDECK and EmuDeck launcher backends.

Both backends ultimately launch libretro cores through a RetroArch instance,
but the two arrangements differ: EmuDeck's is the standalone
``org.libretro.RetroArch`` Flatpak (the same one ``_vendor.atlas`` resolves),
while RetroDECK bundles RetroArch as one of its own components under its own
Flatpak's files tree (mirroring how ``adapters.es_de_config`` locates the
bundled ES-DE component under ``retrodeck/components/``). A libretro launch is
not safely bakeable when neither is present, so this is the one place both
backends check for it — reusing :func:`adapters.flatpak_install.flatpak_app_files_dirs`,
the same Flatpak-presence mechanism ``adapters.retrodeck_paths`` uses for
RetroDECK's own presence.
"""

from __future__ import annotations

import os

from adapters.flatpak_install import flatpak_app_files_dirs

_RETROARCH_FLATPAK_APP_ID = "org.libretro.RetroArch"
_RETRODECK_APP_ID = "net.retrodeck.retrodeck"
_RETRODECK_RETROARCH_COMPONENT = os.path.join("retrodeck", "components", "retroarch")


def retroarch_installed(user_home: str) -> bool:
    """Whether a usable RetroArch is present for either launcher backend.

    ``True`` when the standalone ``org.libretro.RetroArch`` Flatpak is
    installed (EmuDeck's arrangement), OR the RetroDECK Flatpak's bundled
    ``retrodeck/components/retroarch`` directory exists (RetroDECK's
    arrangement). Checked independently — a machine could plausibly carry
    either without the other.
    """
    if flatpak_app_files_dirs(user_home, _RETROARCH_FLATPAK_APP_ID):
        return True
    return any(
        os.path.isdir(os.path.join(files_dir, _RETRODECK_RETROARCH_COMPONENT))
        for files_dir in flatpak_app_files_dirs(user_home, _RETRODECK_APP_ID)
    )
