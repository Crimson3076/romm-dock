# A per-game Steam compat-tool override, applied by the frontend via `SpecifyCompatTool`

## Status

Accepted.

## Context

A user had a native-Linux game — an extracted AppImage, launched via a bundled `launch.sh` wrapper script — living
inside a RomM `"win"` (native-Windows) platform ROM folder. The plugin already resolved and baked this correctly as a
`kind == "native"` launch target ([windows-proton-launch.md](../architecture/windows-proton-launch.md#native-linux-launch-targets-sh-bypassing-proton-entirely)):
the baked Steam shortcut's `launch_options` was a plain `env -C "<dir>" bash "<script.sh>"` invocation with zero Proton
involved — confirmed correct by running that exact string in a terminal.

The game still would not launch **from Steam**. The root cause, confirmed live via Steam's own CEF devtools console on
the user's device: the user had Steam's global "Enable Steam Play for all other titles" setting ON (forced to Proton
Experimental). For a **non-Steam shortcut** specifically, Steam's own Properties → Compatibility UI does not offer an
"off"/native option once that global setting is on — it only lets you pick which Proton version, because Steam has no
store metadata proving a non-Steam shortcut is native. So Steam was wrapping the entire already-correct, Proton-free
launch command in Proton anyway, and the launch failed silently.

The confirmed fix, run live in the console against the real shortcut's appId: `await
SteamClient.Apps.SpecifyCompatTool(appId, "")` (empty string) immediately made the game launch correctly.
`SteamClient.Apps.GetAvailableCompatTools(appId)` (also confirmed live) returns `Promise<Array<{strToolName: string,
strDisplayName: string}>>` — e.g. `{strToolName: "proton_experimental", strDisplayName: "Proton Experimental"}`,
`{strToolName: "steamlinxruntime_sniper", ...}`. There is no `RemoveUserCompatToolOverride` method on this Steam
build — `SpecifyCompatTool(appId, "")` is the confirmed way to clear/force-off the compat tool for one appId.

Both calls are **frontend-only** — `SteamClient` is a browser-context global reachable only from the Decky frontend;
the Python backend has no access to it and never will (mirrors why `AddShortcut`/`Set*` shortcut writes already live in
frontend JS, [steam-non-steam-shortcuts.md](../architecture/steam-non-steam-shortcuts.md)). But a one-time devtools fix
is not durable: this repo's own "shortcut appId is assigned, not derived" trap (CLAUDE.md) means the appId
`SpecifyCompatTool` is scoped to can change over the ROM's lifetime — a version switch, an uninstall/reinstall — so
whatever the user (or the plugin's own default) wants applied has to be **remembered per-ROM** and **re-applied**
whenever the shortcut is rebound to a new appId. The backend cannot make the `SpecifyCompatTool` call itself, but it
can be the thing that remembers the decision.

## Decision

**A new, nullable `TEXT` column**: `roms.compat_tool_override` (migration `027_add_compat_tool_override.sql`).
Anchored on `roms`, not `rom_installs`, mirroring `selected_exe` — the override survives uninstall/reinstall, which is
the entire reason it needs to exist rather than being a one-off devtools fix: it must outlive the appId it was
originally applied to.

This is a **3-state field, not a boolean**, and the states are not interchangeable:

- `NULL` — no override. The plugin never touches this ROM's compat-tool setting.
- `""` (empty string) — force **no** compat tool (native, Proton-bypassed launch). Written two ways: an explicit
  "Force Native (No Proton)" user pick, or **automatically**, with no user action, the first time the ROM's launch
  target resolves to `kind == "native"` — the general fix for the Dusklight bug class this ADR records, applied by
  default to every native-Linux-under-`"win"` game rather than requiring devtools.
- any other string — force that specific `strToolName` (e.g. `"proton_experimental"`, `"GE-Proton10-28"`), taken
  verbatim from whatever `SteamClient.Apps.GetAvailableCompatTools` returned on the user's machine.

**Why `""` must not collapse into "no override" the way a blank value collapses into "invalid" for every other pin
column on this table.** `emulator_override`, `selected_disc`, `selected_exe`, and `cross_backend_pin` all reject a
blank/empty pin as meaningless input (`pin_selected_exe("")` raises `ValueError` — there is no such thing as "pin the
empty-string executable"). Here the opposite is true: `""` is the single most important state this column can hold, the
one that actually fixes the reported bug. `Rom.pin_compat_tool_override(value)` therefore does **not** reuse those
methods' blank-rejection validation — it accepts any string, including `""`, unconditionally. There is nothing to
validate at all: the value is opaque to the backend, interpreted only by the frontend against `SteamClient.Apps`, which
is the sole authority on what Proton builds exist on this machine. `clear_compat_tool_override()` is the separate,
distinct verb that returns to `NULL`.

Like every other per-game pin, this column is **excluded from the sync UPSERT** (`_SYNC_COLUMNS` in
`adapters/repositories/rom.py`) — a re-sync builds a fresh `Rom` with `compat_tool_override=None`, and writing it
through `save()` would silently wipe the pin (and the plugin's own auto-applied default) on every library sync.
`SqliteRomRepository.set_compat_tool_override(rom_id, value)` is the only write path, mirroring
`set_selected_exe`/`set_cross_backend_pin` exactly.

**Two new callables**, mirroring `select_executable`'s failure discipline: `WindowsGameService.set_compat_tool_override
(rom_id, value)` pins `value` (which may legitimately be `""` — that is "force native," not "clear"), and
`clear_compat_tool_override(rom_id)` drops the override back to `NULL`. Both share `select_executable`'s
not-installed/unsupported guards (unknown/uninstalled ROM, or a non-`"win"` platform). **Neither response carries a
`launch_options` key** — this setting is not part of the baked shortcut command at all; it is a wholly separate
Steam-side setting the frontend applies directly via `SpecifyCompatTool`, so there is nothing for the backend to
re-bake.

**`get_windows_executables` gains two fields**: each enumerated executable now reports `kind` (`"exe"` | `"native"`,
already computed by `domain.windows_launch.WindowsExecutable.kind` but not previously surfaced), and the top-level
response gains `compat_tool_override` (the ROM's current value, verbatim — `""` renders as `""`, not `null` or a
dropped key). This is the hand-off point to the frontend: with `kind` and the current override both visible in one
read, the frontend can decide — at bake-confirm time, when it already knows a launch was just confirmed — whether to
auto-apply the native-compat-tool default and call `SpecifyCompatTool` accordingly.

**The backend does not implement the auto-apply decision itself, and that is deliberate, not a gap to close later.**
Deciding "this ROM just resolved to `kind == "native"`, therefore write `""` and call `SpecifyCompatTool`" requires
calling `SteamClient`, which only the frontend can do. The backend's job stops at making `kind` and
`compat_tool_override` visible and letting the frontend write back through the two callables above; the frontend is
the one that recognizes the moment (a bake-confirm) and drives both the persistence call and the live `SpecifyCompatTool`
call together, so the two [`SteamClient` object and the persisted intent] never fall out of sync with each other.

## Consequences

- The override is inert on its own — persisting `compat_tool_override` changes nothing on a live Steam shortcut by
  itself. The frontend must (a) read it after every appId rebind (version switch, reinstall) and (b) call
  `SpecifyCompatTool` accordingly. A frontend bug that reads the field but forgets to re-apply it after a rebind would
  silently regress to the exact bug this ADR fixes, with no error surfaced anywhere the backend can see.
- No validation at all on non-empty values. A stale or misspelled `strToolName` (e.g. a Proton build the user later
  uninstalled) round-trips faithfully and is the frontend's `SpecifyCompatTool` call's problem to fail loudly on, not
  something this backend can detect or degrade — the same opacity contract `cross_backend_pin`'s `label` field already
  accepts for a different picker.
- No per-platform default, only per-game — a user with many native-Linux-under-`"win"` games gets the automatic `""`
  default applied to each independently as its launch target first resolves to `"native"`, not as a one-time
  platform-wide setting.

## Alternatives considered

- **A boolean `force_native` column.** Rejected outright: it cannot express "force this specific non-default Proton
  build," which `GetAvailableCompatTools` proves is a real, user-visible choice (community builds like
  `GE-Proton10-28` alongside Valve's official ones) — the exact same reasoning
  [ADR-0030](0030-plugin-owns-proton-invocation.md) and the Proton-locator's tie-break rule
  ([windows-proton-launch.md](../architecture/windows-proton-launch.md#protonlocatoradapter--discovery-and-the-tie-break-rule))
  already establish for the plugin's own baked Proton invocation.
- **Backend-driven auto-apply**, e.g. a callable that both persists the default AND tells the frontend to call
  `SpecifyCompatTool` in the same round trip. Rejected: the backend has no channel to invoke `SteamClient` at all —
  every existing shortcut-mutating flow in this plugin (`AddShortcut`, `Set*`) already runs frontend-side for exactly
  this reason, and inventing a "backend requests a specific SteamClient call" protocol for one setting would duplicate
  machinery the picker flows (`select_executable`, `switch_version`) already solve by returning data for the frontend
  to act on.

See also: [windows-proton-launch.md](../architecture/windows-proton-launch.md) (the launch-resolution and exe-picker
machinery this override rides alongside), [ADR-0030](0030-plugin-owns-proton-invocation.md) (why the plugin bakes its
own Proton invocation rather than relying on Steam's per-shortcut compat-tool UI for the `.exe` case — this ADR is the
complementary fix for the case where Steam's own compat-tool machinery intercepts a launch that was never supposed to
go through it at all).
