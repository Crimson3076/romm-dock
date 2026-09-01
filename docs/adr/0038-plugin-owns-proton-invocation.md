# Native-Windows ROMs bypass emulator selection entirely; the plugin locates and invokes Proton itself

## Status

Accepted. Extends [ADR-0009](0009-launcher-pure-exec-wrapper-baked-launch-options.md) (`bin/rom-launcher` is a pure
`exec "$@"` wrapper, and the launch command is baked build-time into the shortcut's `launch_options`) to a launch target
that is not an emulator invocation at all — a Proton-wrapped Windows executable. See
[Native-Windows Games and Proton Launch](../architecture/windows-proton-launch.md) for the implementation this decision
produced.

## Context

RomM can serve a game whose raw `platform_slug` is `"win"` — a native-Windows title, distributed as a `.exe` rather than
a console dump. Every other platform this plugin supports launches through RetroDECK's ES-DE/RetroArch stack:
`ActiveCoreResolver` folds a per-game or per-platform override over the live `es_systems.xml` default, and the result is
baked as a `flatpak run net.retrodeck.retrodeck -e "…"` invocation (see
[Core and Emulator Selection](../architecture/core-emulator-selection.md)). None of that machinery has anything to say
about a Windows executable — there is no libretro core for it, and RetroDECK does not run Windows binaries.

Two decisions had to be made, and both are recorded here because a future change to either could plausibly reopen them.

## Decision

### 1. Bypass emulator/core selection entirely, rather than model native-Windows as a third backend

This codebase has no `LauncherBackend` / `CoreInfoProvider` abstraction that a "Windows launcher" could register itself
under alongside "RetroDECK" — the entire core-selection surface (`ActiveCoreResolver`, `DiscLaunchResolver`,
`EmulatorInvocation`, the `-e "%EMULATOR_*%"` render) is built around one concept: picking a libretro core or standalone
emulator for a system directory RetroDECK understands. Building such an abstraction just to give native-Windows a slot
in it would mean inventing generality for exactly one consumer, years before a second one exists to prove the shape is
right.

Instead, `domain.shortcut_data._resolve_launch_options` branches on the raw `platform_slug` **before** any of that
machinery runs: a native-Windows ROM's `launch_options` is whatever the caller's Proton resolution already rendered,
full stop — `core_overrides` and the disc-resolved `bake_path` are never consulted for it. The branch sits at the one
place every shortcut's launch command is composed, so no bake site can accidentally route a Windows ROM through the
emulator path by omission.

This is a **deliberate narrowing, not a placeholder for a future generalization**. If a second non-RetroDECK launch
target appears later, the right abstraction to extract will be informed by what that second case actually needs —
guessing it now from one example would very likely guess wrong.

### 2. The plugin locates and invokes Proton itself, rather than assigning Steam's own compat-tool to the shortcut

Steam has a native mechanism for running a non-Steam Windows executable under Proton: assign a compat tool to the
shortcut through Steam's own Play settings (or, in principle, `SteamClient` calls this plugin could drive), and let
Steam launch it. That path was **not** taken. Instead, `bin/rom-launcher`'s baked `launch_options` **is** the Proton
invocation — `env STEAM_COMPAT_DATA_PATH=… STEAM_COMPAT_CLIENT_INSTALL_PATH=… "<proton>" run "<exe>"` — composed by
`domain.shortcut_data.resolve_proton_invocation` and located by `adapters.proton_locator.ProtonLocatorAdapter`, exactly
like every other platform's emulator invocation is baked rather than delegated to some Steam feature.

Two tradeoffs decided it:

- **appId stability.** Every other launch-target decision this plugin makes — which core, which disc, and now which
  `.exe` — is expressed entirely inside `launch_options`, which
  [ADR-0009](0009-launcher-pure-exec-wrapper-baked-launch-options.md) established is appId-safe to rewrite on an
  existing shortcut: the shortcut's identity, artwork, collection membership, and `roms.shortcut_app_id` binding all
  survive a `launch_options`-only change (see
  [Steam Non-Steam Shortcuts](../architecture/steam-non-steam-shortcuts.md#updating-existing-shortcuts)). Whether
  assigning a compat tool through `SteamClient` would touch appId-affecting shortcut state — or whether it is even
  reachable for a plugin-created shortcut the way the exe-picker needs to re-select at any time — is unknown. Baking the
  invocation ourselves keeps native-Windows on the exact same appId-safety guarantee every other launch decision already
  relies on, with nothing new to prove.
- **No dependency on an unproven `SteamClient` surface.** This plugin's entire shortcut-mutation model (`AddShortcut` /
  `Set*` / `SetAppLaunchOptions`) was arrived at empirically, on real hardware, and documented with its failure modes as
  they were found (see [Steam Non-Steam Shortcuts](../architecture/steam-non-steam-shortcuts.md)). A per-shortcut
  compat-tool assignment API carries none of that history here — its behavior on a plugin-created shortcut, its
  interaction with the exe-picker's re-bake, and whether it round-trips reliably at all are all unverified. Composing
  the invocation ourselves, in a code path this plugin already fully controls and tests, avoids taking on an unverified
  dependency for a feature that does not need it: Proton, once located, is invoked no differently than any other
  command-line program.

The `ProtonLocator` Protocol's own docstring states this plainly: it is "independent of Steam's own per-shortcut
compat-tool assignment (which only applies to a shortcut Steam itself launches through its compat-tool UI, not a command
this plugin bakes directly)."

### 3. The Proton-build tie-break rule is a judgment call, not a provable contract

Locating "the" Proton build to use is underdetermined — a user can have several installed. `ProtonLocatorAdapter`
resolves it by: **prefer any community build (GE-Proton, under `compatibilitytools.d/`) over any official Valve build
(under `steamapps/common/Proton*`), regardless of either one's modification time; within each group, the newest by
directory `mtime` wins.** No Proton version string is parsed — a name like `"Proton - Experimental"` has no numeric
version to compare against `"GE-Proton9-27"` or `"Proton 9.0"`, so `mtime` is the only ordering signal available at all.

This is recorded as a decision, not left implicit, because it is not provably correct — it is stated in the adapter's
own docstring as "a judgment call, not a provable contract" for exactly that reason. Community Proton builds are
_generally_ the more compatible choice for a non-Steam, native title, which is the reasoning behind preferring them
unconditionally over recency. A user who deliberately wants an official build over an installed community one has no
override today; that is accepted as a reasonable v1 default, not as the final word.

### 4. The invocation must never depend on a shell control operator

An earlier version self-healed the per-ROM Proton compat-data prefix directory by chaining
`mkdir -p "<prefix>" && env …`. This was reverted before merge once it was noticed that
[ADR-0009](0009-launcher-pure-exec-wrapper-baked-launch-options.md) already establishes `bin/rom-launcher` as a plain
`exec "$@"` — and whether Steam hands a shortcut's launch options to that wrapper as pre-split argv, or through an
actual shell that would interpret `&&` as a control operator, has never been verified in either direction. If it is the
former, `&&` is not a control operator at all — it is a literal, meaningless argument `mkdir` receives alongside the
path, and the entire launch silently fails. A command whose correctness depends on shell interpretation is not safe to
bake without proof that a shell is actually in the loop, and no such proof exists for this launch path.

The fix needed no workaround: Proton's own launcher script creates `STEAM_COMPAT_DATA_PATH` (and initializes the wine
prefix inside it) on first run when it does not already exist — the same behavior Steam's own compat-tool assignment
already relies on for every other non-Steam Windows game. Dropping the `mkdir -p` prefix entirely leaves a single flat
`env VAR=… VAR=… "<proton>" run "<exe>"` command with no control operators of any kind, safe under either invocation
mechanism.

## Consequences

- **Native-Windows support adds no new abstraction layer to the codebase.** It is one raw-slug branch at the launch
  composition seam plus one new resolver (`WindowsLaunchResolver`) shaped like the existing `DiscLaunchResolver` — not a
  parallel "backend" concept that every future platform kind must now fit into or explicitly opt out of.
- **The plugin owns a second kind of runtime discovery (Proton) alongside its existing RetroDECK/ES-DE reads**, with the
  same "not found is a first-class, non-fatal answer" posture `es_systems.xml` resolution already has: no Proton located
  degrades a native-Windows ROM to "unavailable," never a crash.
- **The Proton build pick is not user-configurable in v1.** A user with both an official and a community build installed
  always gets the community one, however recent the official one is. This is a known, accepted limitation rather than an
  oversight — an explicit per-game or per-user Proton-build override is future work if it turns out to matter in
  practice.
- **Every future change to the Proton invocation string must preserve the no-shell-operator property.** This is not
  mechanically enforced (see the invariant register in `CLAUDE.md`) — it holds only if a reviewer re-applies this ADR's
  reasoning to the next change that touches `resolve_proton_invocation` or `bin/rom-launcher`.

## Alternatives considered

- **Model native-Windows as a third `LauncherBackend`.** Rejected for now: no such abstraction exists in this codebase,
  and building one to accommodate a single concrete case, with no second case to validate the shape against, risks
  guessing the wrong generalization. Revisit if a second non-RetroDECK launch target appears.
- **Assign Steam's own compat tool to the shortcut and let Steam launch it.** Rejected: it would make native-Windows the
  one launch decision not fully expressed in `launch_options`, breaking the appId-safety property every other bake site
  relies on, and it depends on `SteamClient` behavior this plugin has not verified on a plugin-created shortcut. Baking
  the invocation ourselves keeps the feature inside the same tested, documented shortcut-mutation model as everything
  else.
- **Parse Proton version strings to rank builds numerically.** Rejected: directory names are not uniformly versioned
  (`"Proton - Experimental"` has no number at all), so any parser would need a fallback for the unparseable case anyway
  — at which point `mtime` alone is simpler and no less correct for the common case.
- **Self-heal the compat-data prefix with `mkdir -p "<prefix>" && env …`.** Reverted before merge (see decision 4) once
  the shell-operator dependency was identified as unverified and avoidable.

## See also

- [ADR-0009](0009-launcher-pure-exec-wrapper-baked-launch-options.md) — the pure `exec "$@"` launcher and the baked
  `launch_options` model this decision extends to a non-emulator launch target
- [ADR-0014](0014-per-game-disc-selection-in-db-applied-as-bake-time-launch-path-override.md) — the bake-time
  launch-path override pattern `WindowsLaunchResolver`'s exe pin mirrors
- [Native-Windows Games and Proton Launch](../architecture/windows-proton-launch.md) — the full implementation:
  detection, the bypass, the resolver seam, the locator, and the exe-picker flow
- [Core and Emulator Selection](../architecture/core-emulator-selection.md) — the machinery native-Windows ROMs bypass
- [Steam Non-Steam Shortcuts](../architecture/steam-non-steam-shortcuts.md) — why a `launch_options`-only change is
  appId-safe
