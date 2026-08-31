# A launcher-backend seam behind `LaunchCommandRenderer`; switching backends is the existing fan-out re-bake, not a new migration

## Status

Accepted. Implements [#918](https://github.com/danielcopper/romm-tender/issues/918) (the `PlatformEnvironment`-style
seam) ahead of its stated trigger — epic [#1735](https://github.com/danielcopper/romm-tender/issues/1735) named it
"net-new work... not built until a second launcher is concrete" — because EmuDeck is now that second launcher.

## Context

Before this change, the launch command baked into every Steam shortcut's `launch_options` came from exactly one place:
`domain.shortcut_data.resolve_emulator_invocation`, a RetroDECK-only pure function imported directly by five call
sites (`DiscService`, `RelaunchOptionsResolver`, `CoreService`, `RomInstallRecorder`, `SyncOrchestrator`'s
`build_shortcuts_data` calls). [core-emulator-selection.md](../architecture/core-emulator-selection.md) documented this
explicitly: "RetroDECK is the V1 target... a non-RetroDECK launcher behind a `Frontend`-style port is net-new work and
is not built until a second launcher is concrete." Adding EmuDeck support makes that seam necessary.

Epic #1735 ("emu-atlas adoption") had already decided how a second launcher's installation-detection and path
knowledge should be sourced: [emu-atlas](https://github.com/danielcopper/emu-atlas), an external library this project
extracted its own RetroArch/ES-DE/firmware knowledge into, which already models RetroDECK, EmuDeck, and bare-RetroArch
arrangements behind one `Installation` protocol (`detect(home)`, `every_installation(home)`). The epic sequences two
waves: Wave A swaps RetroDECK's own in-tree kernels onto atlas (behavior-preserving); Wave B is "every installed
arrangement" — multi-installation launch + save-sync. Building EmuDeck's installation detection and path resolution
by hand in this plugin, ahead of Wave A, would duplicate exactly the work the epic says building on in-tree tables
first and swapping later would cost twice.

This PR does not run the epic's full sequence. It adopts atlas **for EmuDeck only** — RetroDECK's existing in-tree
kernels (`domain/save_path.py`, `adapters/es_de_config.py`, `adapters/retrodeck_paths.py`, …) are untouched, and Wave
A (the RetroDECK source swap) remains separate, sequenced work. What this PR needs from #1735 is narrower than the
whole epic: a second concrete `LauncherBackend` behind the #918 seam, sourced from atlas rather than hand-rolled.

The user-facing ask that triggered this work also proposed a specific shortcut architecture: a stable, backend-neutral
Steam shortcut whose `launch_options` names a rom id and lets a runtime dispatcher in `bin/rom-launcher` read the
active backend and choose the concrete invocation at launch time — explicitly to avoid "rewriting thousands of Steam
shortcuts whenever the launcher changes." That shape is [ADR-0005](0005-launcher-resolves-path-from-sqlite.md)'s
interim design, retired by [ADR-0009](0009-launcher-pure-exec-wrapper-baked-launch-options.md) once
[#827](https://github.com/danielcopper/decky-romm-sync/issues/827) proved `SetAppLaunchOptions` on an existing
shortcut reliable — reintroducing it here would trade back the exact benefit ADR-0009 established (a resolution-free
launcher, no DB coupling, no runtime resolution cost) for a problem #827 already solved. ADR-0009 also already
provides the general answer to "a global setting changes and every affected shortcut must be re-baked, without
delete/recreate churn": `CoreService.set_system_core`'s per-platform core switch does exactly this today, fanning out
a `rebake_items` list the frontend confirm-sets via `SetAppLaunchOptions` + read-back poll.

## Decision

**The seam.** `services/protocols/launcher_backend.py` defines two Protocols:

- `LauncherBackendFactory` — `detect_installations() -> list[DetectedInstallation]`, `bind(installation_id) ->
  LauncherBackend | None`. One factory per backend, registered in `LauncherBackendRegistry`
  (`services/launcher_backend/registry.py`) — the extensibility point a third backend (or a second EmuDeck-like
  frontend) registers against with no call-site change anywhere else.
- `LauncherBackend` — a factory-bound instance: `resolve_invocation(rom, emulator)`, `build_launch_options(invocation,
  path)`, `roms_root()`, `bios_root()`, `saves_root()`, `validate()`.

A narrower `LaunchCommandRenderer` Protocol (just the two rendering methods) is what the five existing bake call sites
actually take as an injected config field, replacing their direct `domain.shortcut_data` imports.
`LauncherBackendService` (`services/launcher_backend/service.py`) implements `LaunchCommandRenderer` by delegating to
whichever `LauncherBackend` is currently bound — so a backend switch takes effect at every bake site's very next call,
with no re-wiring. `domain.shortcut_data.build_shortcuts_data` gained `resolve_invocation`/`render_launch_options`
keyword parameters defaulting to its own RetroDECK functions, so every existing caller (and every existing test) is
unaffected unless it opts in.

**RetroDECK is a thin, behavior-preserving wrapper.** `adapters/retrodeck_launcher_backend.py` wraps the existing
`resolve_emulator_invocation`/`build_launch_options`/`RetroDeckPaths` verbatim — zero behavior change, and it stays
the default backend (`launcher_backend: "retrodeck"` in `settings.json`, seeded by migration v14).

**EmuDeck is sourced from vendored emu-atlas, not hand-rolled.** `py_modules/_vendor/atlas/` vendors emu-atlas v0.3.0
(tag `v0.3.0`, commit `2a074cd`) — see `_vendor/README.md` for provenance and the import-rewrite patch its size
required. `adapters/emudeck_launcher_backend.py` uses `atlas.detect(home)`'s `EmuDeck` handle for installation
detection and ROM/BIOS/save roots, and `installation.emulators_for(system)` for the ES-DE catalogue — the same
`<command>` grammar RetroDECK's own `es_systems.xml` uses, so the plugin's existing bakeability classifier
(`domain/emulator_commands.py`) is reused unchanged against atlas's catalogue text rather than reimplemented.
Rendering resolves `%EMULATOR_<NAME>%`/`%CORE_RETROARCH%` placeholders through EmuDeck's own `es_find_rules.xml`
(`adapters/emudeck_find_rules.py`) — which is how EmuDeck itself wires those tokens onto its own
`Emulation/tools/launchers/<name>.sh` scripts, so EmuDeck stays responsible for choosing between an AppImage, a
Flatpak, a native binary, or a Proton executable (each script's own probe), never this plugin. A command routed
through Proton (a `z:%ROM%`-suffixed argument) is recognized and refused rather than baked wrong — path-mapping into
Wine's drive-letter form is out of scope for this pass.

**Switching backends is the existing fan-out re-bake, unchanged in kind.** `LauncherBackendService.set_active_backend`
validates the target, binds it, persists the choice, and returns `installed_relaunch_items()` from the existing
`RelaunchOptionsResolver` — the exact seam ADR-0009's migration and startup-reconcile already draw from — as
`rebake_items`. `main.py`'s `set_launcher_backend` callable mirrors `set_system_core` byte for byte: same
`{success, rebake_items}` shape, same prune-conflict lease, same frontend confirm-set loop
(`setLaunchOptionsConfirmed` via `SetAppLaunchOptions` + read-back poll). Every existing property this mechanism
carries — appId-safe, artwork/collection/playtime-preserving, no delete/recreate — applies unchanged, because it is
the same write, just triggered by a different setting. There is no separate "shortcut migration" for switching
backends: the fan-out re-bake **is** the migration, re-baking every existing shortcut's `launch_options` (however it
got there — a pre-#918 RetroDECK bake or a stale EmuDeck one) to the newly-selected backend's command.

## Consequences

- `bin/rom-launcher` is untouched — still `exec "$@"`, no launcher-backend awareness, no runtime dispatch, no state
  read at launch. The property ADR-0009 established (resolution-free, no DB coupling) is preserved for both backends.
- Switching backends re-bakes `launch_options` for every installed+bound ROM in one round trip, exactly like a
  per-platform core change today. This is "rewriting shortcuts" only in the narrow, already-proven-safe sense ADR-0009
  established: a confirmed `SetAppLaunchOptions` write, never a delete/recreate, never a raw VDF edit. It is **not**
  the zero-shortcut-touch design the originating request proposed — that design was ADR-0005's retired shape, and
  reintroducing it would regress a decision already made on hardware evidence (#827).
- RetroDECK's own kernels are untouched; Wave A of epic #1735 (swapping them onto atlas) remains separate future work,
  not entangled with this change.
- EmuDeck coverage is intentionally partial for v1: libretro cores and native-Linux standalone emulators render;
  Proton-routed commands (Cemu Proton, Xenia, BigPEmu Proton, Model2, and any future `z:%ROM%`-suffixed launcher
  entry) are refused rather than baked, degrading to the next catalogue option or "no launch target" — never a broken
  command. The standalone-existence probe RetroDECK has (`downgrade_if_not_installed`, sandboxed `es_find_rules.xml`
  walk) has no EmuDeck equivalent yet: a bakeable EmuDeck entry whose emulator is not actually installed bakes
  anyway, and the failure surfaces from the launcher script itself rather than the picker disabling it up front.
- `py_modules/_vendor/atlas/` adds ~2MB of vendored third-party source, excluded from ruff/basedpyright/Sonar per the
  existing `_vendor/` convention, with every internal `from atlas...` import mechanically rewritten to
  `from _vendor.atlas...` (documented, scripted, reversible on re-pin — see `_vendor/README.md`).

> **Errata (2026-08-30).** Real-hardware testing (a Steam Deck running EmuDeck) surfaced
> `ModuleNotFoundError: No module named 'xml.etree'` on plugin load: Decky's PyInstaller-frozen Python does not bundle
> `xml.etree` at all, and the vendored `atlas` package's own ES-DE parsing (`installations.py`, `esde.py`) imports
> `xml.etree.ElementTree` — a gap this ADR's "excluded from ruff/basedpyright" line did not catch because nothing in
> this project's own toolchain (a normal CPython venv) reproduces Decky's frozen interpreter. Fixed by vendoring the
> two CPython stdlib modules `ElementTree` is implemented on top of (`_vendor/elementtree/`, PSF-licensed, verbatim)
> rather than rewriting emu-atlas's own tree-walking onto `xml.parsers.expat` by hand; both degrade to their
> pure-Python, expat-backed path exactly as `adapters/es_de_config.py`'s own hand-written parsing already does. See
> `_vendor/README.md`'s `atlas` and `elementtree` entries for the full account. This is a real gap in this ADR's own
> verification, not a design change: no consequence stated above moves.
>
> **Errata (2026-08-30).** The Decision section above scoped `LauncherBackend` to rendering only (`resolve_invocation`,
> `build_launch_options`, plus path getters that existed on the Protocol but were not yet consumed by anything besides
> `RetroDeckLauncherBackend` itself). That left every downloads/BIOS/save/cleanup/adoption path consumer reading
> `RetroDeckPaths` directly regardless of the active backend — an EmuDeck-only install (no RetroDECK present at all)
> could launch games but would still download ROMs, fetch BIOS files, and place saves under RetroDECK's paths, which
> do not exist on such a machine. Closed by renaming the path getters for naming consistency (`roms_root`/`bios_root`/
> `saves_root` → `roms_path`/`bios_path`/`saves_path`, plus a new `states_path`) and introducing `LauncherPaths`, a
> Protocol narrower than `RetroDeckPaths` (the same four getters, omitting `retrodeck_home`/`config_path`/
> `config_health`), which `LauncherBackendService` implements by delegating to the active backend exactly as it
> already does for `LaunchCommandRenderer`. Eleven services (`DownloadService`, `GameDetailService`,
> `FirmwareService`, `RomRemovalService`, `RomAdoptionService` and its `AdoptionRenamer`/`CandidateSearch`
> sub-services, `SaveService` and its `RomInfoService`/`PruneSaveSupport` sub-services, `PruneService` and its
> `PreviewBuilder`/`RecoveryCoordinator` sub-services) now take `launcher_paths: LauncherPaths` instead of
> `retrodeck_paths: RetroDeckPaths`. `MigrationService` and `StartupHealingService` are unaffected — both read
> `retrodeck_home()`/`config_path()`/`config_health()`, which stay RetroDECK-migration-specific concepts with no
> backend-neutral equivalent, so they keep the concrete `RetroDeckPaths`. See
> [launcher-backends.md](../architecture/launcher-backends.md) for the current-truth account. No consequence stated
> above moves — this closes the "let the user install what they want and only what they want" gap the Decision
> section's `LauncherBackend` scope left open, it does not change the seam's shape.
>
> **Errata (2026-08-30).** Real-hardware testing (an EmuDeck-only Steam Deck, no RetroDECK installed) surfaced
> `ModuleNotFoundError: No module named 'atlas'` on a ROM download, immediately after the previous errata's
> `launcher_paths` wiring first put a real EmuDeck arrangement on the download path. The `from atlas...` sed rewrite
> `_vendor/README.md` documents only rewrites Python import statements — it is blind to `importlib.resources.files
> ("atlas")`, a package name passed as a plain string, which 15 of the vendored package's own modules use to load a
> bundled JSON file (BIOS hashes, per-core oddities, platform ID crosswalks, and similar). Every one of those sites
> was still asking for a top-level `atlas` package that does not exist under vendoring. Fixed the same way as the
> `xml.etree` errata: a mechanical, scripted string rewrite to `importlib.resources.files("_vendor.atlas")` across
> all 16 call sites, documented in `_vendor/README.md`'s `atlas` entry alongside the other two import rewrites.
> `machine.py`'s `python -m atlas._core_probe` subprocess call is deliberately NOT one of these — it manipulates the
> child process's own `PYTHONPATH` instead, and stays correct as-is. This is the second gap in a row that a plain
> `from _vendor import atlas` import success does not catch, because the failure lives in code paths only a real
> arrangement being read exercises — this project's own test suite fakes `atlas.EmuDeck` at the seam
> (`tests/fakes/`) rather than running the vendored package's real data-loading functions, so neither errata's bug
> was caught before real hardware found it. No consequence stated above moves.
>
> **Errata (2026-08-31).** With the previous errata's `atlas` import fixed, the same real-hardware EmuDeck arrangement
> downloaded ROMs correctly but baked **empty** `launch_options` for every game on two unrelated systems (GBC, N64) —
> pressing Play started and instantly exited the process (`journalctl`: a `post_exit_sync` call seconds after every
> Play press), because `EmuDeckLauncherBackend.resolve_invocation` had nothing to bake. Traced to
> `installation.emulators_for()` reporting real emulator labels (`Gambatte`, `mGBA`, …) with `command=""` for every
> one — atlas's own documented degraded mode when it cannot read ES-DE's real catalogue (`emulator-catalogue-sealed`
> / `emulator-list-derived` caveats). Root cause, confirmed via `unsquashfs -s` on the user's real
> `ES-DE.AppImage`: ES-DE ships its default `es_systems.xml` **inside** the AppImage as a zstd-compressed squashfs
> image, and atlas's vendored squashfs reader can decompress zstd only when a decompressor is importable as
> `compression.zstd` (Python >= 3.14) or `backports.zstd` — neither exists in this project's Python 3.11 target, so
> every AppImage-embedded catalogue read silently fell back to the derived, command-less list. Fixed by vendoring
> `backports.zstd` itself (`_vendor/backports_zstd/`, a **compiled** dependency — the first of its kind under
> `_vendor/`, alongside the ctypes-loaded `.so` files `native/` already carries, but this one is a real importable
> Python C-extension module) plus a one-line addition to atlas's own `_ZSTD_PROVIDERS` probe list — the exact
> extension point `squashfs.py`'s own docstring already documented ("a host application that vendors the backport
> grants its runtime the capability"). See `_vendor/README.md`'s `backports_zstd` entry for the full account,
> including why the vendored package is trimmed to six files rather than copied whole, and
> `tests/adapters/test_emudeck_launcher_backend.py::TestVendoredZstdCatalogueReading` for the real
> `mksquashfs -comp zstd`-built AppImage fixture that proves a genuine embedded catalogue now resolves to a real,
> placeholder-free launch command end to end — reverting the `_ZSTD_PROVIDERS` addition makes that test fail with the
> user's exact symptom (an empty invocation), confirmed before shipping. This is the third real-hardware gap in the
> same vendored dependency in three days; all three share the same blind spot named in the previous errata (nothing
> in this project's own test suite exercised atlas's real data-loading code before real hardware did), which is why
> this fix adds a real-fixture test rather than another mock. No consequence stated above moves.
>
> **Errata (2026-08-31).** With the zstd fix above shipped, the same real-hardware EmuDeck arrangement still baked
> **empty** `launch_options` after toggling the active backend and back — a genuinely different bug, not a regression
> of the zstd fix. Traced to `RelaunchOptionsResolver`, `CoreService`, and `DiscService` all building the rom dict
> passed to `resolve_invocation` as `{"id": rom_id}`, omitting `platform_slug` — harmless for RetroDECK (whose
> `resolve_emulator_invocation` ignores `rom` entirely) but fatal for EmuDeck (whose `resolve_invocation` needs
> `platform_slug` to resolve the ES-DE system). Fixed by threading `platform_slug` through all four call sites
> (`RelaunchOptionsResolver._resolve_item`, `CoreService._set_system_core_io`/`_launch_options_for`,
> `DiscService._bake_launch_options`, the last of which now takes the `Rom` aggregate instead of a bare `rom_id`).
>
> Investigating that fix surfaced a second, larger gap this ADR's Decision section left open: **emulator selection
> itself** — the menu of available cores/emulators the System page and per-game picker offer, and the system-layer
> default `ActiveCoreResolver` falls back to — was still sourced unconditionally from RetroDECK's `es_systems.xml`
> (`adapters.es_de_config.CoreResolver`, injected as `AdapterBundle.core_info_provider`) on **every** backend. A
> genuinely EmuDeck-only user (no RetroDECK flatpak present at all) got an empty picker on both pages; a user who
> still had RetroDECK's flatpak sitting unused got a picker listing RetroDECK's cores while EmuDeck rendered the
> pick, which only worked by coincidence when the two catalogues happened to share a label. Per-game and
> per-platform pins were a single value shared across backends too — switching backends re-interpreted the same
> pinned label against a different catalogue instead of keeping each backend's own choice.
>
> Closed by extending the `LauncherBackend` Protocol to also implement `CoreInfoProvider` (`get_active_core`,
> `get_default_emulator`, `get_emulator_options`, `resolve_sandbox_launcher`, `reset_cache`) — RetroDECK's
> implementation delegates unchanged to the injected `CoreResolver`; EmuDeck's implementation classifies atlas's
> `emulators_for()` catalogue with the same `domain.emulator_commands` kernel already used for rendering.
> `LauncherBackendService` delegates all five methods to whichever backend is active, the same pattern already used
> for `LaunchCommandRenderer`/`LauncherPaths`. `ActiveCoreResolver`, `CoreService`, and `FirmwareService` now take
> this active `core_info` instead of the concrete `CoreResolver` (`ActiveCoreResolver`'s is `LateBinding`-wrapped —
> it is constructed before `LauncherBackendService` in the same producer/consumer cycle `launch_renderer` already
> breaks). Storage became per-backend to match: `roms.emulator_override` (migration
> `024_emulator_override_per_backend.sql`) now holds a JSON object keyed by `backend_id` instead of a bare label, and
> `settings.json`'s `platform_cores` (migration bumping settings to v15) nests under `backend_id` — each pre-existing
> pin folded under `"retrodeck"`, the only backend that existed when it was set. See
> [launcher-backends.md](../architecture/launcher-backends.md) and
> [core-emulator-selection.md](../architecture/core-emulator-selection.md) for the current-truth account. This
> closes the same "let the user install what they want and only what they want" gap the path-consumer errata above
> closed for file placement — it does not change the seam's shape, only completes it.

## Alternatives considered

- **The originating runtime-dispatch shape** (Steam shortcut carries a stable rom-id marker; `bin/rom-launcher` reads
  the active backend from disk at launch and dispatches). Rejected: this is ADR-0005's retired interim design,
  reintroduced for a problem (unreliable shortcut updates) ADR-0009 already closed with hardware evidence. It would
  also reopen the exact tradeoff ADR-0005 recorded — dynamic resolution costs a DB/state read on every launch — with
  no corresponding benefit, since the fan-out re-bake achieves the stated goal (no unreliable bulk shortcut mutation)
  through the mechanism already proven for it.
- **Hand-rolled EmuDeck detection and `settings.sh`/`es_systems.xml` parsing in this plugin**, ignoring emu-atlas.
  Rejected: duplicates work epic #1735 already scoped to atlas, and would need to be thrown away (or carried as a
  second implementation to keep in sync) whenever Wave A/B eventually land.
- **Running epic #1735's full Wave A before Wave B** (migrate RetroDECK itself onto atlas first). Deferred, not
  rejected: matches the epic's stated sequencing most closely, but is a much larger, separate migration with its own
  risk surface (re-verifying every existing ADR/test against a new source for behavior that already works). Scoped
  out of this change; RetroDECK's in-tree kernels are untouched here.

See also: [ADR-0009](0009-launcher-pure-exec-wrapper-baked-launch-options.md) (the exec-wrapper + baked-command
model this seam extends), [ADR-0005](0005-launcher-resolves-path-from-sqlite.md) (the retired dynamic-resolution
design), [core-emulator-selection.md](../architecture/core-emulator-selection.md) (emulator selection this seam does
not change), [database-design.md](../architecture/database-design.md).
