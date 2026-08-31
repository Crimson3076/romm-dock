# Where Your Data Lives

RomM-Dock keeps what it knows about your library in folders under your own home directory, each named after RomM-Dock
itself:

| Folder                       | What is in it                                                                                                                              |
| ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| `~/.config/romm-dock/`      | Your settings — server address, sign-in, which platforms and collections you sync                                                          |
| `~/.local/share/romm-dock/` | The library database, playtime and save-sync state, and the small `bin/rom-launcher` file every one of your Steam shortcuts starts through |
| `~/.cache/romm-dock/`       | Cached cover art and artwork                                                                                                               |
| `~/.local/state/romm-dock/` | RomM-Dock's log file, `backend.log`                                                                                                           |

Your **games** are not in any of them. Downloaded ROMs, BIOS files and save files live in RetroDECK's or EmuDeck's own
folders, exactly as before, and nothing on this page moves them.

## The split that matters

The database folder and the cache folder are separate on purpose. Everything in `~/.cache/romm-dock/` can be fetched
again from your RomM server — delete it and RomM-Dock re-downloads the covers as it needs them. Nothing in
`~/.local/share/romm-dock/` can: that folder holds the only record of what you have installed, synced and chosen.

So a cleanup tool that empties caches is safe to point at the first folder and never the second.

## Why they are named after RomM-Dock

Earlier versions kept this data inside Decky's plugin folders. Decky names those after the plugin's own folder, and that
name is not something RomM-Dock chooses — so when the project was renamed (first to Tender, later to RomM-Dock), every
user's data moved with it, and a freshly updated install opened on an empty library while everything was still sitting
in the old folder.

Naming the folders after RomM-Dock itself ends that. They no longer depend on how the plugin happens to be packaged, so
a rename cannot move them again.

## If your folders are somewhere else

The folders above are the defaults. RomM-Dock asks its environment first, so an installer that sets
`ROMM_DOCK_CONFIG_DIR`, `ROMM_DOCK_DATA_DIR`, `ROMM_DOCK_CACHE_DIR` or `ROMM_DOCK_STATE_DIR` decides where they go;
failing that it follows the standard `XDG_*` variables, and only then falls back to the paths in the table. It resolves
this once when it starts and writes the program, database and cache folders it settled on into its log, so the **last**
`host: code …` line in `backend.log` tells you which ones this install is actually using. Look for the last one rather
than the first: the log is appended to across runs, so the top of the file belongs to an older start.

## Coming from an older version

Nothing copies your data forward. If you used a version that stored its library inside Decky's plugin folders, that
library stays there and RomM-Dock starts with an empty one — set it up as if it were new.

The old folders are yours to keep or delete:

- `~/homebrew/settings/<folder>` — the settings that install used
- `~/homebrew/data/<folder>` — its library, covers and artwork

`<folder>` is `decky-romm-sync` or `romm-tender`, depending on which version wrote them. RomM-Dock reads neither, so
deleting them frees the space and changes nothing; leaving them alone is equally fine.

!!! warning "The older plugin itself is a separate question"

    If Decky still lists an older **"RomM Sync"** or **"Tender"** plugin, that is not the same thing as the folders
    above. Your Steam shortcuts may still start through a file inside it, and removing it before they have been
    repointed stops your games from launching. Check one of your games first —
    [Updating from an older Decky-plugin install](getting-started.md#updating-from-an-older-decky-plugin-install-romm-sync-tender)
    has the check.
