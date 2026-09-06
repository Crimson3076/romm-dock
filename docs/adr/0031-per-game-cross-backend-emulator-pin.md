# A per-game cross-backend emulator pin, additive to the per-backend override

## Status

Accepted.

## Context

`emulator_override` (migration `002_add_emulator_override.sql`, made per-backend by
`024_emulator_override_per_backend.sql`) lets a user pin one ROM to a specific emulator/core — but the pin is always
scoped to whichever launcher backend is the **globally active** one (issue #918's per-backend picker follow-up,
recorded in [ADR-0029](0029-launcher-backend-seam-and-switch-as-rebake.md)'s errata and
[core-emulator-selection.md](../architecture/core-emulator-selection.md)). A RetroDECK pin and an EmuDeck pin for the
same ROM coexist as independent map entries, but only the entry for the CURRENTLY active backend is ever read —
`ActiveCoreResolver._resolve_by_precedence` looks up `rom.emulator_override_for(backend_id)` where `backend_id` is
`LauncherBackendService.active_backend_id()`.

A user reported the resulting gap directly: with EmuDeck active, the per-game "Emulator Core" picker only ever lists
EmuDeck's own catalogue (Dolphin Standalone, the libretro Dolphin core, PrimeHack, …) — there is no way to pick a
RetroDECK emulator for that one game while EmuDeck is the globally active backend, and vice versa. The per-backend
design was correct for its stated purpose (a RetroDECK preference and an EmuDeck preference for the same ROM should not
clobber each other across a switch), but it cannot express "always launch THIS game through THIS SPECIFIC backend,
regardless of which one is active" — that is a different question the existing map has no slot for.

`LauncherBackendRegistry` already holds every registered `LauncherBackendFactory` (not just the active one) and
`LauncherBackendFactory.bind()` can produce a working `LauncherBackend` instance for any registered, detected backend
at any time — `LauncherBackendService` just never exposed that capability, because every existing consumer only ever
needed "the active one."

## Decision

**A new, separate, nullable column**: `roms.cross_backend_pin` (migration `026_add_cross_backend_pin.sql`), JSON
`{"backend_id": str, "label": str}` or `NULL`. This is deliberately NOT a new key inside the existing
`emulator_override` JSON object — that object's whole meaning is "one independent slot per backend, read only when that
backend is active"; a cross-backend pin means the opposite ("read regardless of which backend is active"), so folding
it into the same column would make the column's own semantics ambiguous per-key. Excluded from the sync UPSERT
`_SYNC_COLUMNS` exactly like `emulator_override`/`selected_disc`/`selected_exe`, so a re-sync never wipes it.

**`Rom.pin_cross_backend_emulator(backend_id, label)` / `clear_cross_backend_emulator()`** — verb-named aggregate
mutations mirroring `pin_emulator_override`/`clear_emulator_override`'s validation (`ValueError` on a blank
`backend_id` or `label`). The pin is mutually exclusive with `emulator_override`, enforced from both directions in the
same write: `CoreService.set_game_cross_backend_pin` clears the CURRENTLY active backend's `emulator_override` entry
for the ROM, and — the symmetric half, since `cross_backend_render_for_rom` is checked BEFORE `emulator_override` at
every bake site and would otherwise silently keep winning over a fresh pick — `set_game_core` and `clear_game_core`
each clear any existing `cross_backend_pin` for the ROM. A ROM never carries two live deviations that could disagree
about which wins.

**A new `BackendBinder` seam** (`services/protocols/launcher_backend.py`) — `bind_backend(backend_id) ->
LauncherBackend | None` — implemented by `LauncherBackendService.bind_backend`, which looks `backend_id` up in its own
registry and binds its FIRST detected installation, without ever touching `self._active` or `settings.json`. This is
the mechanism that makes rendering through an arbitrary NON-active backend possible at all: every other seam
(`LaunchCommandRenderer`, `LauncherPaths`, `CoreInfoProvider`) answers questions about whichever backend is active,
and `BackendBinder` is the one exception, by design.

**A new precedence layer, checked FIRST**: `ActiveCoreResolver.cross_backend_render_for_rom(rom_id, rom, path)`.
Additive and separate from `active_emulator_for_rom`'s existing three-layer chain — it is a full render (through the
pinned backend's OWN `resolve_invocation`/`build_launch_options`), not a fourth precedence layer inside that method,
because the whole point is that RetroDECK's `flatpak run ... -e "..."` wrapping and EmuDeck's directly-resolved host
command are different shapes, and only the pinned backend's own instance renders its own shape correctly. Returns
`None` (cheap, the overwhelmingly common case) when the ROM has no pin, when the pinned backend is not installed on
this machine, or when the pinned label no longer resolves on that backend's catalogue — each degrade case logs a
WARNING and never raises, mirroring `_resolve_by_precedence`'s existing stale-label discipline.

**Every render call site checks the new layer before its existing logic.** `RelaunchOptionsResolver._resolve_item`,
`DiscService._bake_launch_options`, `CoreService._set_system_core_io`/`_launch_options_for`, `RomInstallRecorder
.do_resolve_launch_bake`, and the sync bake path (`ShortcutLaunchResolver.do_build_overrides` builds a
`cross_backend_launch_options: dict[rom_id, str]` map of already-rendered commands, threaded through
`domain.shortcut_data.build_shortcuts_data` as a new parameter checked before `core_overrides`, mirroring the existing
`windows_launch_options` map's shape) all call `cross_backend_render_for_rom` first and fall through to their existing
render unchanged when it returns `None` — so an absent pin leaves every one of these sites byte-for-byte unaffected.

**Two new callables**: `CoreService.set_game_cross_backend_pin(rom_id, backend_id, label)` resolves `label` against
`backend_id`'s OWN catalogue (via `BackendBinder`) BEFORE writing anything — the same "resolve first, hard-fail if
unresolvable, write only on success" discipline `set_game_core` already follows — and `clear_game_cross_backend_pin
(rom_id)` drops the pin. Both mirror `set_game_core`/`clear_game_core`'s response shape
(`{success, launch_options, app_id}`) exactly.

**The per-game picker's read payload gains two fields**: `cross_backend_pin` (the ROM's current pin, verbatim) and
`other_backends` (every registered backend OTHER than the active one that is actually detected on this machine, each
with its own emulator catalogue projected through the existing `options_to_payload`, so the frontend's per-backend
list rendering generalizes to N backends with no new parsing logic). A backend that fails to bind (not detected) is
omitted entirely, not listed as empty/disabled — the common single-backend-installed case reports `other_backends: []`.

## Consequences

- Per-game only in this first cut — there is no per-platform cross-backend pin. A per-platform pin would need its own
  precedence question (does it beat or lose to a per-game `emulator_override` on the active backand?) that does not
  arise for a per-game pin, which is scoped to one ROM and checked before every other layer unconditionally.
- **v1 gap: only a backend's FIRST detected installation is bindable via `BackendBinder`.** Both backends this plugin
  ships (RetroDECK, EmuDeck) only ever detect at most one installation in practice, so this is not a regression for
  anyone today — but a hypothetical backend with multiple installations could only ever be cross-backend-pinned to its
  first one.
- **v1 gap: no folder-boot rewrite for a cross-backend render.** `active_emulator_for_rom`'s folder-boot-to-`direct`
  rewrite (ADR-0019) needs the RESOLVED backend's own sandbox-launcher probe
  (`core_info.resolve_sandbox_launcher`); `cross_backend_render_for_rom` does not attempt it. A folder-boot title (PS3)
  cross-pinned to a foreign backend bakes the standard `run_game` form and may fail to launch — a known, documented
  gap, not a silently-broken feature.
- Setting a cross-backend pin clears the active backend's own `emulator_override` for that ROM (and vice versa is not
  needed: `set_game_core` has no cross-backend pin to clear before this feature existed, and after it, a user setting
  the per-active-backend override while a cross-backend pin is live would leave two deviations disagreeing about which
  wins — this was flagged and intentionally left as a known follow-up rather than growing `set_game_core`'s own
  write path for a case it did not previously need to consider; the cross-backend pin still wins per precedence order,
  so nothing bakes incorrectly, but `has_game_override`/`cross_backend_pin` could both read as set until either is
  explicitly cleared).

## Alternatives considered

- **A per-key flag inside `emulator_override`'s existing JSON object** (e.g. `{"emudeck": "DuckStation",
  "_pinned_backend": "emudeck"}`). Rejected: conflates two columns with genuinely different read rules (per-backend
  slot vs. backend-agnostic override) into one, which is exactly the ambiguity the existing column's docstring already
  warns against introducing.
- **Reinterpreting `emulator_override` so the active backend's own key means "pin," and a foreign key means
  "cross-backend."** Rejected: this redefines existing, tested, documented behavior for every user who already has a
  per-backend pin set — the explicit non-goal stated when this work was scoped.

See also: [ADR-0029](0029-launcher-backend-seam-and-switch-as-rebake.md) (the `LauncherBackend`/`LaunchCommandRenderer`
seam this pin renders through), [core-emulator-selection.md](../architecture/core-emulator-selection.md) (the existing
per-backend override this pin is additive to), [launcher-backends.md](../architecture/launcher-backends.md) (the
registry/factory seam `BackendBinder` reaches into).
