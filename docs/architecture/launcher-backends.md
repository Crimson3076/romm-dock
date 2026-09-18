# Launcher Backends

## Overview

RomM-Dock launches every ROM through a **launcher backend** — RetroDECK by default, or EmuDeck. A launcher backend
answers, per (system, emulator, rom): the launch invocation and the roms/bios/saves/savestates roots, plus its own
installation detection and pre-switch validation. This is
[#918](https://github.com/danielcopper/romm-tender/issues/918)'s seam, built once EmuDeck became a concrete second
target (see [ADR-0029](../adr/0029-launcher-backend-seam-and-switch-as-rebake.md) for the full decision record,
including why it does not reintroduce the runtime-dispatch shape ADR-0009 retired).

The seam covers three independent things a backend answers: **rendering** (`LaunchCommandRenderer` — how an
`EmulatorInvocation` becomes an OS-executable command), **file placement** (`LauncherPaths` — where downloads, BIOS
files, saves, and savestates land on disk), and **emulator selection** (`CoreInfoProvider` — which emulators exist to
choose between for a system, and which one is the default). An install that has only EmuDeck — no RetroDECK at all —
needs all three: rendering and paths alone would launch games and place files correctly, but the System-page and
per-game picker menus would still be empty (RetroDECK's `es_systems.xml` is unreadable with no RetroDECK installed), and
there would be nothing to pick.

**Emulator selection follows the active backend too.** [Core & Emulator Selection](core-emulator-selection.md)'s
`ActiveCoreResolver` still decides WHICH `EmulatorInvocation` a ROM resolves to — the per-game/per-platform override
layered over the system default — but both the OPTIONS it chooses from and EACH LAYER'S STORAGE are now scoped to
whichever backend is currently active: `CoreInfoProvider.get_emulator_options` comes from the active backend's own
catalogue (RetroDECK's `es_systems.xml`, or EmuDeck's atlas-read catalogue), and the per-game (`roms.emulator_override`,
a JSON object keyed by `backend_id`) and per-platform (`settings.json` `platform_cores`, nested
`{backend_id: {platform_slug: label}}`) pins are independent per backend — pinning a core under EmuDeck never touches,
overwrites, or is visible from RetroDECK's pin for the same ROM/platform, and vice versa. Switching backends switches
the picker's contents and which pin layer applies, exactly like it already switches rendering and file placement.

## The seam

Two Protocols in `services/protocols/launcher_backend.py`:

- **`LauncherBackendFactory`** — `detect_installations() -> list[DetectedInstallation]`,
  `bind(installation_id) ->
  LauncherBackend | None`. One factory per backend, held in `LauncherBackendRegistry`
  (`services/launcher_backend/registry.py`) — the extensibility point a third backend registers against with no
  call-site change anywhere else.
- **`LauncherBackend`** — a factory-bound instance: `resolve_invocation(rom, emulator)`,
  `build_launch_options(invocation,
  path)`, `roms_path()`, `bios_path()`, `saves_path()`, `states_path()`,
  `validate()`, plus the five `CoreInfoProvider` methods (`get_active_core`, `get_default_emulator`,
  `get_emulator_options`, `resolve_sandbox_launcher`, `reset_cache` — `LauncherBackend` extends `CoreInfoProvider`). The
  path getters use the same names as `RetroDeckPaths` on purpose — same shape, same best-effort/never-raise contract —
  so a backend is a drop-in behind `LauncherPaths` wherever a service used to read RetroDECK's paths directly.
  `states_path()` may return `""` where a backend has no flat savestate root (EmuDeck's savestate location is
  per-core/per-content via atlas, not a single directory the way saves/roms/bios are).

`LauncherBackendService` (`services/launcher_backend/service.py`) owns the **active** binding — read from
`settings.json`'s `launcher_backend` / `launcher_backend_installation` keys (seeded to `"retrodeck"` by migration v14) —
and implements three narrower Protocols by delegating to whichever `LauncherBackend` is currently bound:

- **`LaunchCommandRenderer`** (`resolve_invocation` / `build_launch_options` only). Five call sites take this renderer
  as an injected config field instead of importing `domain.shortcut_data`'s RetroDECK functions directly: `DiscService`,
  `RelaunchOptionsResolver`, `CoreService`, `RomInstallRecorder`, and `SyncOrchestrator` (via
  `domain.shortcut_data.build_shortcuts_data`'s `resolve_invocation`/`render_launch_options` keyword parameters, which
  default to the RetroDECK functions so every caller that doesn't opt in is unaffected).
- **`CoreInfoProvider`** (all five methods). `ActiveCoreResolver`, `CoreService`, and `FirmwareService` take this as an
  injected `core_info` field instead of the concrete `adapters.es_de_config.CoreResolver` — the same three consumers
  [Core & Emulator Selection](core-emulator-selection.md) already documents, now reading through the active backend
  rather than always RetroDECK's `es_systems.xml`. `ActiveCoreResolver` is constructed before `LauncherBackendService`
  exists (the same producer/consumer cycle `launch_renderer` breaks), so its `core_info` and `active_backend_id` fields
  are `LateBinding`, bound once `LauncherBackendService` is built; `CoreService`/`FirmwareService` are constructed after
  and take plain values.
- **`LauncherPaths`** (`roms_path` / `bios_path` / `saves_path` / `states_path`, deliberately omitting
  `retrodeck_home`/`config_path`/`config_health`, which stay RetroDECK-specific vocabulary). Eleven services take this
  as an injected `launcher_paths` config field instead of `RetroDeckPaths` directly — every downloads, BIOS, save, and
  cleanup/adoption/removal path consumer: `DownloadService`, `GameDetailService`, `FirmwareService`,
  `RomRemovalService`, `RomAdoptionService` (+ its `AdoptionRenamer`/`CandidateSearch` sub-services), `SaveService` (+
  its `RomInfoService`/`PruneSaveSupport` sub-services), and `PruneService` (+ its `PreviewBuilder`/
  `RecoveryCoordinator` sub-services). `MigrationService` and `StartupHealingService` are the deliberate exceptions —
  both read `retrodeck_home()`/`config_path()`/`config_health()`, RetroDECK-home-migration concepts with no
  backend-neutral equivalent, so they keep depending on the concrete `RetroDeckPaths` regardless of which backend is
  active.

Because the service is the thing injected — not a snapshot of the active backend — a switch takes effect at every bake
site's and every path consumer's very next call, with no re-wiring. This is what makes an EmuDeck-only install (no
RetroDECK present at all) work end-to-end: downloads, BIOS files, and saves land under EmuDeck's own `Emulation/roms` /
`Emulation/bios` / `Emulation/saves` subtree from the moment EmuDeck is the active backend, not just the launch command.

`RelaunchOptionsResolverConfig`'s `launch_renderer` field is a `LateBinding[LaunchCommandRenderer]`
(`lib/late_binding.py`), not the service itself: `LauncherBackendService` needs `RelaunchOptionsResolver` as its
`installed_relaunch_items()` source for the switch fan-out (below), and `RelaunchOptionsResolver` needs the active
renderer — a construction cycle `bootstrap/services.py` breaks the same way it breaks every other producer/consumer
cycle in that function.

## RetroDECK — the default, behavior-preserving backend

`adapters/retrodeck_launcher_backend.py` wraps the existing `domain.shortcut_data.resolve_emulator_invocation` /
`build_launch_options` and the `RetroDeckPaths` Protocol verbatim. Zero behavior change: every ROM that resolved to a
plain `flatpak run net.retrodeck.retrodeck` (or its `-e` override) before this seam existed resolves to the exact same
string through it. RetroDECK has exactly one installation (the plugin's original, hard-required target), so its factory
always reports at most one `DetectedInstallation`, keyed `"retrodeck"`; `validate()` blocks on
`RetroDeckConfigHealth.NOT_INSTALLED` / `UNREADABLE` / `ROOT_MISSING` (an `ABSENT` config — the Flatpak IS installed but
hasn't been configured yet — is the long-standing fresh-install fallback, not a switch-blocking error; see
[Readiness](#readiness-is-the-backend-actually-there) below for what distinguishes the two).

## EmuDeck — sourced from vendored emu-atlas

`adapters/emudeck_launcher_backend.py` is the second concrete backend. It does not re-parse `settings.sh` or
`retroarch.cfg` itself — installation detection and ROM/BIOS/save roots come from
[emu-atlas](https://github.com/danielcopper/emu-atlas)'s `EmuDeck` installation handle (`_vendor.atlas.detect(home)`),
the library this project has already committed to for exactly this knowledge (epic
[#1735](https://github.com/danielcopper/romm-tender/issues/1735)). See `py_modules/_vendor/README.md` for the vendor
provenance (pinned tag, and why its internal imports needed a mechanical rewrite this large a package could not avoid).

### Detection and paths

`EmuDeckLauncherBackendFactory.detect_installations()` probes the one resolved user home (`decky.DECKY_USER_HOME` —
never a hardcoded username or a Bazzite-specific `/home` vs `/var/home` guess) via `atlas.detect`, filtering to the
`EmuDeck` handle. `roms_path()` / `bios_path()` / `saves_path()` delegate to `installation.roms_dir()` / `bios_dir()` /
`saves_root()`; `states_path()` always returns `""` — atlas has no flat savestates root for EmuDeck, resolving savestate
location per-core/per-content instead; `validate()` delegates to `installation.health()`.

### Rendering: reusing the plugin's own ES-DE classifier against atlas's catalogue

The ROM's system's ES-DE catalogue entry is read through `installation.emulators_for(system)` — the same `<command>`
grammar RetroDECK's own `es_systems.xml` uses, so the plugin's existing bakeability classifier
(`domain/emulator_commands.py` — `classify_command`, `select_default_option`, the same pure kernel
`adapters/es_de_config.CoreResolver` uses for RetroDECK) is reused **unchanged** against atlas's catalogue text, rather
than reimplemented for a second frontend. A per-game/per-platform pin (`emulator.label`) is matched by label first,
exactly like `label_to_invocation` does for RetroDECK; an unmatched or unresolvable pin falls through to the system
default.

`installation.emulators_for(system)` itself depends on atlas being able to read ES-DE's catalogue, which ships
**inside** `ES-DE.AppImage` as a compressed squashfs image by default (no `~/ES-DE/custom_systems/es_systems.xml`
override needed for common systems). Atlas's vendored squashfs reader needs a zstd decompressor to open one compressed
with zstd (`mksquashfs`'s default codec since squashfs-tools 4.5+, and what real EmuDeck AppImages use) —
`py_modules/_vendor/backports_zstd/` supplies it (see `_vendor/README.md`'s entry for why it's vendored and what it cost
to get right). Without a working zstd decompressor, atlas silently degrades to a catalogue built from the installed
libretro cores' own names, with no command text at all — nothing bakes, and every affected shortcut's `launch_options`
end up empty (ADR-0029's second EmuDeck errata).

The classified command's placeholders are then resolved to real host paths via EmuDeck's own `es_find_rules.xml`
(`adapters/emudeck_find_rules.py`, reading `<home>/ES-DE/custom_systems/es_find_rules.xml` — where EmuDeck's own
installer deploys it):

- `%EMULATOR_<NAME>%` → the `<emulator name="NAME">` `staticpath` entry — for most standalone emulators this is
  literally `.../Emulation/tools/launchers/<name>.sh`, and for RetroArch itself
  `.../Emulation/tools/launchers/retroarch.sh`. This is how EmuDeck itself wires those tokens onto its launcher scripts,
  so **EmuDeck stays responsible for choosing between an AppImage, a Flatpak, a native binary, or a Proton executable**
  (each script's own probe) — this plugin never makes that choice.
- `%CORE_RETROARCH%` → the `<core name="RETROARCH">` `corepath` entry (EmuDeck's bare `org.libretro.RetroArch` flatpak's
  cores directory).
- The trailing `%ROM%` is stripped (not substituted) — `resolve_invocation` returns everything **before** it, and
  `build_launch_options` appends the actual resolved path as the final quoted argument, the same contract
  `domain.shortcut_data.build_launch_options` already uses for RetroDECK.

Unlike RetroDECK — where `%EMULATOR_*%`/`%ROM%` stay as literal ES-DE placeholders in `launch_options`, resolved at
launch time by RetroDECK's own patched `run_game.sh` — EmuDeck has no such runtime resolver on the plugin's
direct-Steam-shortcut launch path. So the EmuDeck backend does the full substitution **at bake time**, producing a
plain, already-resolved command line with no placeholders left; `bin/rom-launcher` needs no changes at all (still a pure
`exec "$@"` wrapper on both backends).

No `eval`, no shell-string concatenation beyond the same trusted-invocation + escaped-path composition
`build_launch_options` already uses for RetroDECK.

### Known v1 limitations

- **Proton-routed commands are refused, not baked wrong.** A command whose ROM argument carries a Windows drive-letter
  prefix (`z:%ROM%` / `Z:%ROM%` — Cemu Proton, Xenia, BigPEmu Proton) needs Wine path-mapping this backend does not
  implement; `_PROTON_ROM_SUFFIX_RE` recognizes and refuses it, degrading to the next catalogue option or the empty "no
  launch target" command (never a broken one). Native-Linux standalone emulators (Cemu via `cemu.sh`'s native branch,
  RPCS3, DuckStation, PCSX2-Qt, Azahar, MelonDS, Vita3K, …) and libretro cores are unaffected.
- **No standalone-existence probe.** RetroDECK's `downgrade_if_not_installed` walks its sandboxed `es_find_rules.xml` to
  downgrade a bakeable standalone entry whose emulator is not actually installed (ADR-0020) — EmuDeck's unsandboxed
  layout has no equivalent probe yet, so a bakeable EmuDeck entry whose emulator the user has not installed bakes
  anyway; the launcher script itself reports the failure at launch rather than the picker disabling it up front.
- **Savestates have no flat root on EmuDeck.** `states_path()` returns `""` for the EmuDeck backend (atlas resolves
  savestate location per-core/per-content, not as a single directory) — save-sync flows that need a savestate base
  directory degrade the same way they already do for an unresolved RetroDECK root.
- **AppImage-embedded catalogue reading covers gzip and zstd squashfs only.** Atlas's vendored squashfs reader (used
  when ES-DE has no on-disk `custom_systems`/resource-override catalogue) supports exactly the two compressors named
  above — an AppImage built with a squashfs codec neither handles (lzo, lz4, xz) would degrade the same way the
  missing-zstd case did before this was fixed: a real, non-empty catalogue silently replaced by the derived,
  command-less one. Not something either RetroDECK or a stock EmuDeck AppImage build is known to do today.

## Switching backends: the existing fan-out re-bake, not a new migration

`LauncherBackendService.set_active_backend(backend_id, installation_id)` validates the target (`factory.bind` +
`backend.validate()`), binds it, persists the two settings keys, and returns
`RelaunchOptionsResolver.installed_relaunch_items()` — the exact seam ADR-0009's RetroDECK-home migration and
startup-reconcile already draw from — as `rebake_items`. The `set_launcher_backend` callable (`main.py`) mirrors
`set_system_core` byte for byte: same `{success, rebake_items}` shape, same prune-conflict lease, same frontend
confirm-set loop (`setLaunchOptionsConfirmed` via `SetAppLaunchOptions` + read-back poll, ADR-0009). Every property that
mechanism carries — appId-safe, artwork/collection/playtime-preserving, no delete/recreate, no raw VDF edits — applies
unchanged, because it is the same write, just triggered by a different setting. **There is no separate
shortcut-migration path**: the fan-out re-bake IS the migration, re-baking every existing shortcut's `launch_options`
(however it got there) to the newly-selected backend's command.

## Readiness: is the backend actually there?

Both concrete backends used to assume their own presence rather than checking it. RetroDECK's paths adapter fell back
silently to a guessed `<home>/retrodeck/*` root whenever `retrodeck.json` was missing or unreadable, and
`LauncherBackendService._bind` falls back to binding RetroDECK whenever nothing else can be bound — so a machine with
neither RetroDECK nor EmuDeck installed still got a bound RetroDECK backend with fictitious paths, and every libretro
core was treated as bakeable on the unchecked assumption that "RetroArch ships with RetroDECK". Neither holds once a
user can run the plugin without RetroDECK installed at all, or with RetroDECK installed but its bundled RetroArch
component removed.

Every `LauncherBackend` now answers two readiness questions honestly, alongside `validate()`:

- **`is_installed() -> bool`** — is THIS bound installation genuinely present?
  - RetroDECK (`RetroDeckLauncherBackend.is_installed`) delegates to `RetroDeckPathsAdapter.is_installed()`, which
    checks the RetroDECK Flatpak's own `app/net.retrodeck.retrodeck/current/active/files` presence
    (`adapters.flatpak_install.flatpak_app_files_dirs`) — independent of `retrodeck.json`. This is also what splits
    `RetroDeckConfigHealth.ABSENT` (config not written yet, quiet — the Flatpak IS there) from the new
    `RetroDeckConfigHealth.NOT_INSTALLED` (the Flatpak itself isn't there at all, loud) in `config_health()`.
  - EmuDeck (`EmuDeckLauncherBackend.is_installed`) always returns `True` — an `EmuDeckLauncherBackend` instance only
    exists when `EmuDeckLauncherBackendFactory.bind` re-ran `atlas.detect` and found the arrangement, so (unlike
    RetroDECK) there is no bindable fallback that can go stale.
- **`retroarch_installed() -> bool`** — is RetroArch itself present? Every libretro-core launch depends on it
  regardless of which backend is active, but the two arrangements differ: EmuDeck's RetroArch is the standalone
  `org.libretro.RetroArch` Flatpak; RetroDECK's is bundled as one of RetroDECK's own components
  (`retrodeck/components/retroarch`) under the RetroDECK Flatpak's files tree, not a separate Flatpak install.
  `adapters/retroarch_install.py`'s `retroarch_installed(user_home)` checks both shapes and is the one function both
  backends call — RetroDECK's `es_de_config.CoreResolver.retroarch_installed()` additionally reuses the existing
  `es_find_rules.xml` staticpath probe (the same one [Core & Emulator Selection](core-emulator-selection.md)'s
  standalone-existence probe already runs) for its own `%EMULATOR_RETROARCH%` find-rule entry, which is the more
  precise of the two checks inside a RetroDECK arrangement and is what actually downgrades a libretro option to
  `needs_setup` in the picker — see that page's existence-probe section for how a bakeable libretro option is now
  downgraded the same way a bakeable standalone option always was.

`LauncherBackendService.get_backend_readiness()` reports the ACTIVE backend's answer to both questions as
`{backend, backend_installed, retroarch_installed, message}` — the `get_backend_readiness` callable below. The QAM
readiness banner (`src/utils/backendReadinessStore.ts` + `backendReadinessBanner.ts`) polls it on every panel open and
again after a backend switch (`LauncherBackendSection.tsx`) — this stays a **blanket** "is the launcher/RetroArch there
at all" read, unscoped to any one ROM, because that is exactly the "overall setup health" question the banner answers.

The pre-launch gate needs a narrower, PER-ROM answer instead: `retroarch_installed` only matters for a ROM whose
resolved active emulator (`ActiveCoreResolver.active_emulator_for_rom`) is actually a **libretro** core. A ROM whose
active emulator is `standalone` (Dolphin, PCSX2, Ryubing, …) never routes through RetroArch, so RetroArch's absence must
not block that ROM's launch — `backend_installed` still blocks every ROM regardless of kind, since nothing launches
through either launcher if the launcher itself is gone. `CoreService.get_launch_readiness(rom_id)` (the
`get_launch_readiness` callable) folds `LauncherBackendService.get_backend_readiness()` with the ROM's resolved kind —
reusing `ActiveCoreResolver` rather than re-deriving kind resolution — and returns
`{backend, backend_installed, retroarch_installed, retroarch_relevant, ready, message}`. It lives on `CoreService`
(not `LauncherBackendService`) because `CoreService` already holds the no-cycle `ActiveCoreReader` seam
`LauncherBackendService` cannot depend on without a producer/consumer cycle (`ActiveCoreResolver` itself depends on
`LauncherBackendService` via `core_info`/`active_backend_id`). The shared pre-launch gate (`launchGate.ts`'s
`checkBackendReady` step, backed by `checkBackendReady(romId)` in `launchTarget.ts`, which calls
`get_launch_readiness`) blocks a launch with `backend_not_ready` on the `ready` verdict instead of letting it fail
silently the moment RetroArch (or the launcher itself) turns out not to be there. `CustomPlayButton.tsx` also probes
`get_launch_readiness` proactively (on mount and on a version switch) to paint the Play button in a blocked/error tint
BEFORE the press — a visual hint only, never a substitute for the click-time gate.

## Callables

- **`get_launcher_backends()`** — every registered backend (`backend_id`, `display_name`) with its detected
  installations (`installation_id`, `display_name`, `home`, `healthy`, `detail`). A backend with zero detected
  installations (EmuDeck absent) still appears, with an empty list, so the QAM picker can show it as a
  currently-unselectable option rather than omitting it.
- **`set_launcher_backend(backend_id, installation_id)`** — `@migration_blocked` + `@prune_active_blocked`, same as
  `set_system_core`. Returns `{success, rebake_items}` on success, `{success: False, reason, message}` on failure
  (`"unknown_backend"`, `"not_detected"`, or the backend's own `BackendValidation.reason`).
- **`get_backend_readiness()`** — `{backend, backend_installed, retroarch_installed, message}` for the ACTIVE backend.
  Always succeeds (both probes are best-effort filesystem checks); see
  [Readiness](#readiness-is-the-backend-actually-there) above. Blanket — the QAM banner's read.
- **`get_launch_readiness(rom_id)`** — `{backend, backend_installed, retroarch_installed, retroarch_relevant, ready,
  message}` for `rom_id`. The PER-ROM, kind-aware sibling the pre-launch gate (and the Play button's proactive visual
  hint) use instead; see [Readiness](#readiness-is-the-backend-actually-there) above.

## Related pages

- [Core & Emulator Selection](core-emulator-selection.md) — the per-game/per-platform precedence chain, and the
  per-backend storage shape this page's `CoreInfoProvider` section covers.
- [Steam Non-Steam Shortcuts](steam-non-steam-shortcuts.md) — `launch_options` writes, appId stability.
- [ADR-0029](../adr/0029-launcher-backend-seam-and-switch-as-rebake.md) — the decision record.
- [ADR-0009](../adr/0009-launcher-pure-exec-wrapper-baked-launch-options.md) — the exec-wrapper + baked-command model
  this seam extends.
