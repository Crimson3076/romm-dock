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
- **Local patches:**
  - Every internal `from atlas...` import rewritten to `from _vendor.atlas...` — a mechanical, scripted rewrite
    (`sed -E 's/^from atlas\b/from _vendor.atlas/'` over every `.py` file), never by hand, and never touching anything
    but the import line. Same fix `vdf/__init__.py`'s own patch makes (an absolute self-import resolving under the
    package's real vendored location, not a top-level name Decky's plugin has no path for) — atlas just needed it
    applied file-wide (21 of ~30 files) rather than in one `__init__.py`, because its internal modules cross-reference
    each other by absolute import throughout.
  - `installations.py` and `esde.py`: `import xml.etree.ElementTree as _ET`/`as ET` rewritten to
    `from _vendor.elementtree import ElementTree as _ET`/`as ET`. Decky Loader's PyInstaller-frozen Python does not
    bundle `xml.etree` at all (`ModuleNotFoundError: No module named 'xml.etree'`, confirmed on real hardware,
    2026-08-30) — `adapters/es_de_config.py` already routes around this in the plugin's own code by parsing with
    `xml.parsers.expat` directly, but hand-rewriting emu-atlas's ES-DE tree-walking (`.find()`/`.findall()`/`.text`
    over `ET.Element`) onto expat's SAX API would mean forking a meaningful slice of third-party parsing logic. Vendoring
    the two CPython stdlib modules `ElementTree` is built on (`_vendor/elementtree/`, see below) instead keeps this a
    one-line-per-file import swap, and both those modules parse through `xml.parsers.expat` internally on the
    pure-Python path (proven exercised, not just present — see that entry). No other line in either file changed; a
    re-pin re-applies both rewrites (the `sed` above, plus this one, done by hand since it is two occurrences total).
  - Every `importlib.resources.files("atlas")` call rewritten to `importlib.resources.files("_vendor.atlas")` — 16
    occurrences across 15 files (`content_tree_wiring.py`, `emulator_settings.py`, `evidence.py`, `firmware.py`,
    `launch_formats.py`, `mods.py`, `oddities.py` (×2), `platforms.py`, `save_memory.py`, `standalone_firmware.py`,
    `standalone_saves.py`, `standalone_savestates.py`, `systems.py`, `textures.py`), all loading a bundled JSON file
    under `data/`. The `from atlas...` sed rewrite above only touches Python import statements — a package name
    passed as a string literal to `importlib.resources.files(...)` is invisible to it, so every one of these sites
    still asked the resource-loader for a top-level `atlas` package that does not exist under vendoring, failing
    `ModuleNotFoundError: No module named 'atlas'` (confirmed on real hardware from a ROM download that triggered
    EmuDeck arrangement-caveat lookups, 2026-08-30). `machine.py`'s `python -m atlas._core_probe` subprocess call is
    NOT one of these — `_probe_environment()` deliberately prepends this package's own parent directory (`_vendor/`)
    to the child's `PYTHONPATH`, so the subprocess's bare `import atlas` resolves against the vendored `atlas/`
    directory on its own, unrelated to the host process's `_vendor.atlas` dotted name. Leave it alone on a re-pin.
    A re-pin re-applies this rewrite too: `grep -rn 'importlib\.resources\.files("atlas")' atlas/` should stay empty
    after any re-copy.
- **Why vendored, not pip-installed:** same reason as every other entry on this page — Decky has no plugin-level
  package manager, so a runtime third-party dependency has to ship inside the plugin's own files. emu-atlas is the
  config-aware emulator-knowledge library this project has committed to (epic #1735) for RetroDECK/EmuDeck
  installation detection, ROM/BIOS/save-path resolution, and ES-DE catalogue parsing — consumed today by the
  EmuDeck launcher backend (`adapters/emudeck_launcher_backend.py`, issue #918) via `from _vendor import atlas`.
  RetroDECK's own in-tree kernels (`domain/save_path.py`, `adapters/es_de_config.py`, …) are unchanged by this vendor
  — the epic's Wave A (swapping RetroDECK itself onto atlas) is separate, sequenced, and not part of this change.
- **Update procedure:** re-copy the `atlas/` directory + `LICENSE` from a newer tagged release (never `main`, per the
  epic's own "every wave pins a tagged emu-atlas release" rule), re-apply all three import rewrites above, bump the
  version/commit here, and re-run `mise run test` — the self-conformance suite
  (`tests/test_atlas_machine_vectors.py`, vendored separately under `tests/atlas_vectors/`) and this package's own
  callers are what would catch a behavior change on re-pin. `grep -rn "^import xml.etree" atlas/` and
  `grep -rn 'importlib\.resources\.files("atlas")' atlas/` should both stay empty after any re-copy — a newer
  emu-atlas release adding a new site of either kind needs the same rewrite. None of these three rewrites is caught
  by any test that doesn't actually exercise the affected code path (a plain import success is not enough for the
  `importlib.resources` one) — the gap that let this exact class of bug ship once already.

## elementtree

- **Upstream:** CPython 3.11 standard library (`Lib/xml/etree/ElementTree.py` + `Lib/xml/etree/ElementPath.py`)
- **Version:** 3.11.15 — copied verbatim from this project's own pinned toolchain Python (`mise.toml`'s `python`,
  which the dependency-management doc requires to match "Decky Loader's embedded libpython3.11")
- **License:** PSF License — see [`elementtree/LICENSE`](elementtree/LICENSE)
- **Local patches:** none — verbatim copy of both files. `ElementTree.py`'s own `from . import ElementPath` resolves
  correctly as-is because both files live together in this real subpackage (`_vendor.elementtree`); no rewrite needed.
- **Why vendored:** Decky Loader's PyInstaller-frozen Python does not bundle the `xml.etree` package at all (confirmed
  on real hardware: `ModuleNotFoundError: No module named 'xml.etree'`) — only the standalone `xml.parsers.expat`
  module survives the freeze, which is why `adapters/es_de_config.py` parses ES-DE's own XML with expat directly
  rather than `ElementTree`. The vendored `atlas` package (above) uses `xml.etree.ElementTree` for its own ES-DE
  parsing; rather than hand-rewriting that third-party parsing onto expat's SAX API, this vendors the two stdlib
  modules `ElementTree` is implemented on top of. Both degrade gracefully to their pure-Python classes when the
  `_elementtree` C accelerator is unavailable (it is not, in the frozen build) — the pure-Python path itself is built
  on `xml.parsers.expat.ParserCreate()`, so this holds for the same underlying reason `es_de_config.py`'s own
  hand-written parsing does. Verified on a python3.11 interpreter with `xml.etree` forcibly blocked via `sys.meta_path`
  (simulating the frozen build) that `_vendor.atlas` still imports and a real `ElementTree.fromstring(...).find(...)`
  parse still runs correctly.
- **Update procedure:** re-copy both files from a newer 3.11.x patch release only if `mise.toml`'s pinned Python
  version moves — these two stdlib modules change rarely and only for bugfixes; there is no reason to track anything
  but the toolchain's own Python version here.
