"""Atlas host grants — the capabilities this runtime hands the vendored resolver.

The vendored `emu-atlas <https://github.com/danielcopper/emu-atlas>`_ resolver
discovers what it can, states plainly where it found nothing, and takes what a
host hands over ahead of anything it found. A grant is **process-global** — one
running program, one answer — so it belongs to none of the three modules that
import the resolver: :mod:`adapters.atlas_firmware`,
:mod:`adapters.atlas_catalogue` and :mod:`adapters.atlas_saves` put their
questions to whatever was granted, and which of them a given grant actually
reaches is a property of the grant rather than of the module. The one below is
read by a single question in :mod:`adapters.atlas_saves` and by nothing else.

Two grants, and the shape is the reason it has a module of its own rather than a
corner of one of those three: the interpreter grant below, and the zstd codec
`backend/_vendor/backports_zstd/` carries — vendored so
:class:`adapters.emudeck_launcher_backend.EmuDeckLauncherBackend` can read an
EmuDeck arrangement's zstd-compressed, AppImage-embedded ES-DE catalogue on a
Python without a stdlib zstd codec (PEP 784 lands it in 3.14; this project
targets 3.11). Both grants are process-global slots of the same kind
(``squashfs._registered_provider`` beside ``machine._registered_interpreter``),
granted the same way, at the same point in the wiring, and read by every module
whose detection reaches the question the grant answers.

This module is where those grants are made, once, before the first atlas adapter
is built.
"""

from __future__ import annotations

import os
import sys

from _vendor import backports_zstd
from _vendor.atlas import core_probe_interpreter, register_core_probe_interpreter, register_zstd_provider

# A frozen program is not an interpreter, so atlas derives none from it. SteamOS
# carries CPython here (`/usr/bin/python3` → `python3.13`, 3.13.5 measured on the
# reference device); another Linux handheld may not, and atlas deliberately
# searches no PATH for one, so an absent path is granted nothing rather than
# guessed at.
_HOST_INTERPRETER = "/usr/bin/python3"


def grant_core_probe_interpreter() -> str:
    """Grant atlas an interpreter for its core probe; answer what a probe would run under.

    The probe loads a core's ``.so`` in a child process to ask it what it saves,
    and that child is a Python interpreter.

    **The grant is conditional, and removing it is not the simplification it
    looks like.** Running under a real interpreter — the backend hosted by its
    own process — ``sys.executable`` already names one, and it is the very
    interpreter this code is running, so registering a second path over it would
    replace a known-good answer with a guess about the machine. Running frozen,
    ``sys.executable`` is the loader binary rather than a Python, atlas derives
    nothing from it, and the path below is the only offer there is. Registering
    nothing in the frozen case fails no test and breaks no gate: atlas simply
    probes no core, every core answers unknown, and a libretro entry's save
    answer quietly loses the core's recorded behaviour.

    Either way the offer is made only where the path is a file this process could
    actually spawn. Atlas checks the shape of a registered path and deliberately
    not whether it is there, which leaves the existence question the host's, and
    the honest answer on a machine without that interpreter is to register
    nothing: the resolver then says so itself and every core comes back unknown,
    which is what it would answer anyway for a path that could not run.

    The answer is a **log line**, not the resolver's own
    :class:`_vendor.atlas.CoreProbeInterpreter`, because its only consumer is
    the log at the wiring site — and that site is ``bootstrap/``, which may not
    hold a ``_vendor`` type (only adapters import ``_vendor.*``). It names the
    interpreter a probe would run under and where that came from, including the
    case where a probe would start nothing at all: the caveats a missing grant
    leaves do reach the debug log and the wire, but the log line is the only
    place their **cause** is named, and "no interpreter" and "the core would not
    load" are the same caveat everywhere else.
    """
    if _running_frozen() and _is_spawnable_file(_HOST_INTERPRETER):
        register_core_probe_interpreter(_HOST_INTERPRETER)
    granted = core_probe_interpreter()
    if granted is None:
        return "atlas core probe: no interpreter to run under — every core answers unknown"
    origin = "granted by the plugin" if granted.registered else "atlas's own, from the running program"
    return f"atlas core probe: {granted.path} ({origin})"


def grant_zstd_provider() -> str:
    """Grant atlas the vendored zstd codec; answer what decompressor a zstd image would use.

    ES-DE's default AppImage-embedded catalogue is a zstd-compressed squashfs
    image (``mksquashfs``'s default codec since squashfs-tools 4.5+, and what
    real EmuDeck AppImages ship). Atlas's own squashfs reader can decompress
    zstd, but only when a codec is importable as ``compression.zstd`` (the PEP
    784 stdlib home, Python >= 3.14) or ``backports.zstd`` — neither of which
    this project's Python 3.11 target has. Handing over the vendored copy by
    the module object itself (``register_zstd_provider``), rather than
    aliasing it into ``sys.modules`` under one of those two probed names, is
    what atlas's own docstring documents as the seam for exactly this: "the
    registration is the seam for a host that vendors the backport under its
    own root."

    The grant is unconditional — unlike the interpreter grant above, the
    vendored codec has no real alternative to defer to and no existence check
    to fail, since it always ships inside this plugin's own tree. Never
    registering it fails no test and breaks no gate, and quietly degrades:
    atlas falls back to its own documented degraded mode for an unreadable
    zstd image (a catalogue derived from installed libretro cores' own names,
    with no command text at all), which is exactly the empty-``launch_options``
    symptom this grant exists to prevent for every AppImage-embedded system.
    """
    register_zstd_provider(backports_zstd)
    return "atlas zstd codec: _vendor.backports_zstd (granted by the plugin)"


def _running_frozen() -> bool:
    """Is the running program a frozen bundle rather than an interpreter?

    ``sys.frozen`` is what PyInstaller sets on the module it builds; a real
    CPython does not define it at all. It is the same question asked the same
    way by every library that has to tell the two apart.
    """
    return bool(getattr(sys, "frozen", False))


def _is_spawnable_file(path: str) -> bool:
    """Is *path* an existing file this process could hand to the operating system?

    ``isfile`` follows symlinks, which ``/usr/bin/python3`` is on the one
    machine this was measured on, and the execute bit is the difference between
    a path that runs and one the spawn refuses.
    """
    return os.path.isfile(path) and os.access(path, os.X_OK)
