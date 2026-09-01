# Native-Windows Games and Proton Launch

Technical reference for how the plugin launches native-Windows ROMs — games RomM serves as raw Windows executables
rather than console dumps — by locating and invoking a Proton build itself, entirely outside the RetroDECK/ES-DE
emulator machinery every other platform goes through.

## What a native-Windows ROM is

RomM tags a native-Windows game with the raw platform slug `"win"`. The plugin checks for that slug **before** any
`resolve_system`/`platform_map` normalization (`adapters/romm/http.py`, `defaults/config.json`) —
`domain.shortcut_data.WINDOWS_PLATFORM_SLUG` is compared against the ROM's raw `platform_slug` field, the same field
every other platform's `platform_map` lookup would otherwise consume.

`"win"` deliberately has **no** `platform_map` entry, and that absence is load-bearing rather than an oversight to fix:
every other slug in `platform_map` names a RetroDECK/ES-DE **system** directory (`gba`, `psx`, `ps3`, …) — the thing a
libretro core or a standalone emulator loads a ROM from. A native-Windows game has no such system; it is a Windows
executable that Proton runs directly. Giving `"win"` a `platform_map` entry would imply it participates in that
resolution, when the entire point of detecting it early is to keep it out of that resolution altogether. Detection must
never come to depend on `"win"` gaining one.

## Why it bypasses emulator/core selection entirely

This branch does not layer on top of the existing core-selection code — it sidesteps it. There is no `LauncherBackend`
or `CoreInfoProvider` abstraction in this codebase that a "Windows backend" could implement alongside a "RetroDECK
backend"; the emulator/core machinery (`ActiveCoreResolver`, `DiscLaunchResolver`, `EmulatorInvocation`, the
`-e "%EMULATOR_*%"` render) is built entirely around picking a libretro core or standalone emulator for a
RetroDECK-managed system directory. None of that has anything to answer for a raw `.exe`.

The bypass lives in `domain.shortcut_data._resolve_launch_options`, the single point every shortcut's `launch_options`
is composed from:

```python
def _resolve_launch_options(rom, bake_path, core_overrides, windows_launch_options):
    if rom.get("platform_slug") == WINDOWS_PLATFORM_SLUG:
        return windows_launch_options.get(rom["id"], "")
    return build_launch_options(resolve_emulator_invocation(rom, core_overrides.get(rom["id"])), bake_path)
```

A native-Windows ROM never reaches `resolve_emulator_invocation`, never consults `core_overrides`, and never resolves a
disc path — its `launch_options` is whatever the caller's Proton resolution already rendered into
`windows_launch_options`, keyed by `rom_id`. An absent entry (no Proton located, or no `.exe` present) renders as `""` —
the same empty placeholder every other unlaunchable install produces (see
[Steam Non-Steam Shortcuts](steam-non-steam-shortcuts.md)). `build_shortcuts_data`'s `core_overrides` parameter is
required precisely so a new bake site can never silently skip the override for every other platform; for a
native-Windows ROM it is simply never read.

## The `WindowsLaunchResolver` seam

Every launch-bake site (library sync preview and per-unit apply, download/adoption-complete, RetroDECK-home migration,
the startup relaunch reconcile) and the exe-picker's own read/write callables draw the same answer from one place:
`services.windows_launch_resolver.WindowsLaunchResolver`, injected everywhere through the `WindowsResolver` Protocol
(`services/protocols/cross_service.py`). It mirrors [`DiscLaunchResolver`](core-emulator-selection.md)'s role for
multi-disc ROMs exactly, and for the same reason: if the bake path and the picker each resolved the selection
independently, they could disagree the moment either one's logic drifted, and the game would show one `.exe` as selected
while actually launching another.

`WindowsLaunchResolver` exposes three methods, layered so each can be used alone:

- **`enumerate_executables(install)`** — lists the launchable `.exe` files in the install's directory (a single-file
  install enumerates over its own `file_path` alone — a native-Windows ROM can ship as a bare `.exe`; a folder-backed
  install is scanned recursively). This is what the exe-picker's menu is built from.
- **`resolve_exe_path(install, selected_exe)`** — folds the persisted pin over that enumeration: the pinned filename
  when it still names a present `.exe`, else the first one found (alphabetical by basename — there is no numbering
  scheme to parse the way multi-disc labels have one). An unlaunchable install (`launchable is False`) resolves to `""`
  before any exe work, matching every other bake seam's convention.
- **`resolve_launch_options(install, selected_exe)`** — wraps the resolved `.exe` path in a full Proton invocation via
  the injected `ProtonLocator`. `""` when there is no `.exe` to launch, **or** when no Proton build is located — "no
  Proton installed" is a first-class answer here, never an exception, because a user without Steam's Proton (or with it
  in a non-standard location) must degrade to "Windows games unavailable" rather than crash the sync.

Because the picker's `get_windows_executables`/`select_executable` callables (`services/windows_game.py`) and every bake
site's read path (`services/library/shortcut_launch_resolver.py`'s `do_scan_windows_launch_options` /
`do_read_windows_launch_options`) all call through this one resolver, a baked `launch_options` and the picker's shown
selection can never diverge — there is only one function that turns "which `.exe`" into "what Proton runs".

## `ProtonLocatorAdapter` — discovery and the tie-break rule

`adapters/proton_locator.py` scans the two standard Steam install roots — `~/.local/share/Steam` checked first, then
`~/.steam/steam` — the same candidates and ordering `SteamConfigAdapter.find_steam_user_dir` and
`SteamRecoveryAdapter._resolve_user` already use, since `.steam/steam` is a symlink that does not exist on every install
method.

Under the resolved Steam root, two build families are scanned:

- **Community builds** (GE-Proton and similar) under `compatibilitytools.d/*/proton`.
- **Official Valve builds** under `steamapps/common/Proton*/proton` — restricted to directory names starting with
  `Proton`, since that directory also holds unrelated Steam Play tooling.

**The tie-break rule — stated in the adapter's own docstring, because it is a judgment call and not a provable
contract:** a community build is preferred over an official one whenever at least one community build is installed,
regardless of either one's modification time. Within each group, the newest build by directory `mtime` wins. No Proton
version string is parsed — a name like `"Proton - Experimental"` has no numeric version to compare against
`"GE-Proton9-27"` or `"Proton 9.0"` in the first place, so `mtime` is the only ordering signal available. This also
covers "only `Proton - Experimental` is installed" without a special case: it is simply the sole (and therefore newest)
member of the official group. Only the `proton` binary's presence is checked, not its executable bit — a build a user
extracted without preserving permissions should still be found; whether it actually runs is Proton's own problem, not
the locator's.

`locate()` returns `None` — never raises — when neither Steam root exists or neither group yields a build.
`compat_data_path(rom_id)` computes **and creates** the per-ROM `STEAM_COMPAT_DATA_PATH` prefix
(`<runtime_dir>/proton-prefixes/<rom_id>`, idempotently, on every call) — see the next section for why the creation
lives here rather than in the baked command.

## Why the compat-data prefix is created in Python, not in the baked command

The Proton invocation `resolve_proton_invocation` renders is a **single flat command with no shell control operators**:

```text
env -C "<exe_dir>" STEAM_COMPAT_DATA_PATH="<prefix>" STEAM_COMPAT_CLIENT_INSTALL_PATH="<steam_root>" "<proton_binary>" run "<exe>"
```

An earlier version of this code chained `mkdir -p "<prefix>" && env …` to self-heal the per-ROM compat-data directory
before Proton's first run. That was dropped (commit `d4c00cd`) once it was noticed that
[`bin/rom-launcher`](steam-non-steam-shortcuts.md#key-files) is a plain `exec "$@"` wrapper, and whether Steam hands a
shortcut's launch options to that wrapper as pre-split argv or through a real shell that interprets `&&` as a control
operator was never verified either way. If it is the former, `&&` becomes a literal garbage argument to `mkdir` instead
of a control operator, and the whole launch silently fails — a command that only a shell could interpret correctly is
not safe to bake without proof the shortcut is actually launched through one.

The reasoning that first replaced the `mkdir -p` — "Proton's own launcher script creates `STEAM_COMPAT_DATA_PATH` on
first run, the same behavior Steam's own compat-tool assignment relies on" — turned out to be unverified and wrong for
this launch path specifically, and shipped that way until real-hardware testing surfaced a silent "Play does nothing"
failure. A real Steam-library game gets that directory for free because **Steam itself** creates
`steamapps/compatdata/<appid>/` before ever invoking Proton; Proton has never needed to create its own prefix root from
scratch. This plugin's per-ROM prefix lives under its own `runtime_dir` (`<runtime_dir>/proton-prefixes/<rom_id>`), a
tree nothing else creates — so on a fresh install nothing ever did, and Proton exited before reaching the target `.exe`
with no surfaced error.

The fix keeps the no-shell-operator property (the baked command still has none) while dropping the unverified
assumption: `ProtonLocatorAdapter.compat_data_path` calls `os.makedirs(path, exist_ok=True)` itself, in Python, before
ever returning the path to `resolve_proton_invocation` — a real filesystem side effect performed by the adapter that
already owns I/O, not a command handed to a shell that may or may not be in the loop. Most paths rendered into the
invocation — the compat-data prefix, Steam's own install root, the Proton binary — are plugin/system-derived, never
attacker-controlled, so they are not escaped; `exe_dir` and the final `.exe` argument `build_launch_options` appends ARE
(backslash and double-quote escaped via the shared `_escape_launch_arg` helper, mirroring the RetroDECK launch's own
path escaping — see [Steam Non-Steam Shortcuts](steam-non-steam-shortcuts.md)) — both are derived from the same on-disk
directory/file names a server-controlled download could shape.

## Why the invocation sets a working directory

`env -C "<exe_dir>"` is the other half of the real-hardware fix, found right after the directory fix above let Proton
actually start: Pokémon Uranium's `Patcher.exe` raised Wine's own "file not found" dialog for `neoncube\neoncube.ini` —
a path relative to the exe's own folder. Every Steam shortcut this plugin creates shares one fixed `exe`
(`bin/rom-launcher`) and `start_dir` (the plugin's own `bin/`) regardless of platform (ADR-0009) — correct for every
other platform, since RetroDECK/ES-DE takes the ROM path as an argument and never depends on the launcher's own working
directory. A native-Windows executable is different: many resolve their own data files relative to their own folder,
exactly as a real Windows game launched from its own install directory would, and nothing in the launch model gave one
that folder as its working directory until this fix. `-C` folds into the SAME flat `env` invocation rather than a second
command or a shell `cd`, so the no-shell-operator property still holds.

## Why the plugin locates and invokes Proton itself

Steam has its own per-shortcut compat-tool assignment UI, but the plugin does not use it. Assigning a compat tool to a
shortcut through `SteamClient` — rather than baking a Proton invocation into `launch_options` the way this feature does
— was not the path taken; the tradeoffs behind that choice, and why appId stability was the deciding factor, are
recorded in [ADR-0029](../adr/0029-plugin-owns-proton-invocation.md).

## The exe-picker flow

A native-Windows install can enumerate more than one `.exe` (an installer's own uninstaller, a launcher plus the real
game binary, per-DLC executables). `ExeSelector` (`src/components/ExeSelector.tsx`) is the structural twin of
`DiscSelector`, mounted immediately to its right in the play-section row on the game detail page. It renders a compact
icon-only trigger for an installed native-Windows ROM whose install enumerates at least one `.exe` (neutral grey when
following the default pick, accent-tinted when a specific `.exe` is pinned) and nothing at all otherwise — unknown,
not-installed, non-Windows, and no-`.exe` ROMs all collapse to the backend's `{"has_executables": false}` answer.

The flow, mirroring the multi-disc picker:

1. **Enumerate.** On mount (and again on `download_complete` for that ROM), the frontend calls
   `get_windows_executables(rom_id)`. The backend (`WindowsGameService._get_windows_executables_io`) enumerates via the
   shared `WindowsLaunchResolver` and returns the candidate list plus the current `roms.selected_exe`. A stale pin — one
   whose file the enumeration no longer finds — is down-validated to `None` here, so the picker's badge always matches
   what the bake would actually launch.
2. **Pin.** Choosing an entry calls `select_executable(rom_id, filename)`. The backend validates the filename against a
   fresh enumeration inside one Unit of Work — an unknown filename hard-fails with `not_found` and writes nothing — then
   persists the pick via `Rom.pin_selected_exe(filename)` (or `clear_selected_exe()` for `filename = None`, reverting to
   the default) through the repository's pin-only `set_selected_exe` write path. Like `selected_disc`, this column is
   **excluded from the sync UPSERT**, so a re-sync can never silently wipe a user's pick (migration
   `024_add_selected_exe.sql`).
3. **Re-bake.** Only after the write's Unit of Work closes does the service call
   `WindowsLaunchResolver.resolve_launch_options` again (a real Proton filesystem probe, deliberately kept outside the
   write transaction — the same non-nesting rule `DiscService` follows) and return the freshly-baked `launch_options` in
   the response. The frontend confirm-writes it onto the live Steam shortcut with `setLaunchOptionsConfirmed`, through
   the same prune-lease flow the disc and version pickers use, so the Play button launches the newly-selected executable
   immediately — no re-sync required.

There is no "reset to default" menu entry, matching the disc picker's own non-`.m3u` case: a native-Windows install has
no playlist concept to fall back to, only "the first `.exe` enumerated," which the enumeration order already supplies.

## `CoreService` refuses a native-Windows ROM outright

`services/cores.py` (`set_game_core`, `clear_game_core`, `set_system_core`, `get_platform_core_info`) is the one launch
seam that is **not** built on `WindowsLaunchResolver` — a native-Windows ROM has no emulator/core concept at all
(ADR-0029), so there is nothing for `CoreService` to resolve through. Each entry point guards
`rom.platform_slug ==
"win"` explicitly and refuses (`{"success": False, "reason": "unsupported", ...}` for the per-game
pin/clear; `get_platform_core_info` reports no emulators; `set_system_core` is a silent no-op) rather than depending on
`"win"` happening to have no `es_systems.xml` entry to fall back on. That absence is what keeps the picker/gear-button
UI from rendering for a Windows platform today (`platform.emulators.length > 1` in `SystemPage.tsx` /
`RomMPlaySection.tsx` stays `0`), but it was never a proof — a future `platform_map` entry, or any other change that
gives `"win"` ES-DE options, would otherwise let a per-game or per-platform core pin resolve through
`ActiveCoreResolver` and re-bake the shortcut's `launch_options` via the plain RetroDECK path
(`disc_resolver.resolve_for_install`, i.e. the install's raw `file_path` — for a multi-file native-Windows ROM, whatever
`detect_launch_file`'s largest-file heuristic guessed at download time, almost never an `.exe`), silently discarding the
Proton-wrapped launch the exe picker built. The explicit guard makes the refusal the enforced contract instead of an
accident of today's data.

## Key Files

| File                                                      | Purpose                                                                                              |
| --------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `py_modules/domain/windows_launch.py`                     | Pure kernel: `enumerate_executables`, `resolve_launch_path` — no I/O                                 |
| `py_modules/domain/proton.py`                             | `ProtonInstallation` value object crossing the adapters/services boundary                            |
| `py_modules/domain/shortcut_data.py`                      | `WINDOWS_PLATFORM_SLUG`, `resolve_proton_invocation`, the bypass branch in `_resolve_launch_options` |
| `py_modules/adapters/proton_locator.py`                   | `ProtonLocatorAdapter` — Steam-root scan, tie-break rule, `compat_data_path`                         |
| `py_modules/services/protocols/proton.py`                 | `ProtonLocator` Protocol                                                                             |
| `py_modules/services/protocols/cross_service.py`          | `WindowsResolver` Protocol                                                                           |
| `py_modules/services/windows_launch_resolver.py`          | `WindowsLaunchResolver` — the single read-path seam                                                  |
| `py_modules/services/windows_game.py`                     | `WindowsGameService` — the exe-picker's two callables                                                |
| `py_modules/services/library/shortcut_launch_resolver.py` | `do_scan_windows_launch_options` / `do_read_windows_launch_options`, the bake sites' entry points    |
| `py_modules/services/cores.py`                            | `CoreService` — refuses `platform_slug == "win"` outright (no emulator/core concept applies)         |
| `py_modules/db/migrations/024_add_selected_exe.sql`       | Adds `roms.selected_exe`                                                                             |
| `src/components/ExeSelector.tsx`                          | The picker UI, structural twin of `DiscSelector`                                                     |
