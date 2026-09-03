# Packaged defaults

Reference data that ships inside the plugin. The Decky CLI flattens this directory into the plugin root at package time,
so the runtime reads these files by their bare name (no `defaults/` prefix); do not move or rename them.

## `bios_registry.json` — vendored from emu-atlas

The BIOS registry: which firmware files each platform and libretro core want, with the hashes and sizes that identify
them. Read at runtime by `FirmwareService` (via `domain/bios.py`) to classify what a platform needs and whether a local
file is the right one.

It is **vendored verbatim** from [emu-atlas](https://github.com/danielcopper/emu-atlas), where the registry and its
generator now live:

- **Upstream:** <https://github.com/danielcopper/emu-atlas>
- **Release:** `v0.1.0`
- **Upstream path:** `atlas/data/bios_registry.json`
- **Checksum:** pinned in `bios_registry.json.sha256` (SHA-256)

This repo carries only the data snapshot — there is no in-tree generator. Generation is a dev-time, offline step that
lives upstream (emu-atlas `scripts/generate_bios_registry.py`, documented in emu-atlas `atlas/data/README.md`); it
derives the registry from the libretro `libretro-core-info` and `libretro-database` checkouts. **Never hand-edit the
data here** — a manual edit would silently diverge from the released snapshot and break the checksum gate.

### How to update

1. Fetch the registry at the release tag (emu-atlas releases carry no binary assets — the tagged source tree is the
   artifact):

   ```sh
   curl -fL -o defaults/bios_registry.json \
     "https://raw.githubusercontent.com/danielcopper/emu-atlas/<tag>/atlas/data/bios_registry.json"
   ```

2. Regenerate the pinned checksum and verify it (the bare filename keeps `sha256sum -c` working from within this
   directory):

   ```sh
   cd defaults && sha256sum bios_registry.json > bios_registry.json.sha256 && sha256sum -c bios_registry.json.sha256
   ```

3. Bump the **Release** tag above.
4. Re-run the firmware tests (`tests/services/test_firmware.py`, `tests/domain/test_bios.py`) — a `required` flag flip,
   a removed entry, or a changed hash is a behavior change for consumers, so call it out in the PR description.

The checksum is re-verified by CI (`.github/workflows/ci.yml`, mirrored in `mise run gate` / `mise run lint`) and the
release smoke test asserts the registry ships in the plugin zip, so both a hand-edited snapshot and a dropped file fail
the pipeline.

## `config.json` — in-tree default

The platform-slug map and other default configuration. Unlike `bios_registry.json`, this is maintained in this repo (not
vendored) and carries no checksum gate.

## `xbox_bios_registry.json` — in-tree default

Firmware identification data for `xemu` (the Xbox emulator), in the same shape as `bios_registry.json` but maintained in
this repo — like `config.json`, not vendored and not checksum-gated. It exists as a separate file rather than an entry in
`bios_registry.json` because xemu is a standalone emulator, not a libretro core: it falls entirely outside what the
emu-atlas generator that produces `bios_registry.json` covers, and this repo's own rule against hand-editing a
checksum-pinned vendored file (see `.claude/rules/vendored-assets.md`) rules out adding it there directly.

`FirmwareService.load_bios_registry()` loads this file and merges its `platforms` into the same in-memory registry
`bios_registry.json` populates, so every existing consumer (classification, status, install-path resolution, download)
handles Xbox the same way it handles every other platform — no Xbox-specific code path exists beyond the merge and the
content-hash fallback lookup (`services/firmware.py`'s `_bios_files_by_hash`) that lets a differently-named file still be
identified by its content.

Update by hand-editing this file directly (it is not a snapshot of anything upstream) when a new Xbox BIOS/MCPX variant's
hash needs adding, then re-run the firmware tests (`tests/services/test_firmware.py`, `tests/domain/test_bios.py`).
