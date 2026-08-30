# Vendored third-party packages

Decky Loader has no plugin-level package manager, so third-party runtime dependencies are vendored here and imported as
`from _vendor import <package>`. Only adapters import from `_vendor.*`. The release zip redistributes this directory, so
each package keeps its upstream `LICENSE`, and the provenance below makes updating a vendored dep a deliberate diff
rather than "diff and pray". See the `_vendor/` rules in [`CLAUDE.md`](../../CLAUDE.md).

## vdf

- **Upstream:** <https://github.com/ValvePython/vdf>
- **Version:** 3.4 — tag `v3.4`, commit `8104cb27c0b222bd802b69df58204ab389fc714c`
- **License:** MIT — see [`vdf/LICENSE`](vdf/LICENSE)
- **Local patches:** `vdf/__init__.py` — `from vdf.vdict import VDFDict` changed to `from .vdict import VDFDict`
  (relative self-import so the package resolves under `_vendor.vdf`, not a top-level `vdf`).

## atlas

- **Upstream:** <https://github.com/danielcopper/emu-atlas>
- **Version:** 0.3.0 — tag `v0.3.0`, commit `2a074cdc840a26f5a17f325dda363bf2b6b25a1c`
- **License:** MIT — see [`atlas/LICENSE`](atlas/LICENSE)
- **Local patches:** every internal `from atlas...` import rewritten to `from _vendor.atlas...` — a mechanical,
  scripted rewrite (`sed -E 's/^from atlas\b/from _vendor.atlas/'` over every `.py` file), never by hand, and never
  touching anything but the import line. Same fix `vdf/__init__.py`'s own patch makes (an absolute self-import
  resolving under the package's real vendored location, not a top-level name Decky's plugin has no path for) — atlas
  just needed it applied file-wide (21 of ~30 files) rather than in one `__init__.py`, because its internal modules
  cross-reference each other by absolute import throughout. No other line changed; a re-pin re-applies the same sed.
- **Why vendored, not pip-installed:** same reason as every other entry on this page — Decky has no plugin-level
  package manager, so a runtime third-party dependency has to ship inside the plugin's own files. emu-atlas is the
  config-aware emulator-knowledge library this project has committed to (epic #1735) for RetroDECK/EmuDeck
  installation detection, ROM/BIOS/save-path resolution, and ES-DE catalogue parsing — consumed today by the
  EmuDeck launcher backend (`adapters/emudeck_launcher_backend.py`, issue #918) via `from _vendor import atlas`.
  RetroDECK's own in-tree kernels (`domain/save_path.py`, `adapters/es_de_config.py`, …) are unchanged by this vendor
  — the epic's Wave A (swapping RetroDECK itself onto atlas) is separate, sequenced, and not part of this change.
- **Update procedure:** re-copy the `atlas/` directory + `LICENSE` from a newer tagged release (never `main`, per the
  epic's own "every wave pins a tagged emu-atlas release" rule), re-apply the import rewrite above, bump the
  version/commit here, and re-run `mise run test` — the self-conformance suite
  (`tests/test_atlas_machine_vectors.py`, vendored separately under `tests/atlas_vectors/`) and this package's own
  callers are what would catch a behavior change on re-pin.
