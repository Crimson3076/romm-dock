"""Pure functions for building shortcut data dicts and launch commands.

No I/O, no imports from services, adapters, or lib.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.sibling_group import compute_sibling_group_key

if TYPE_CHECKING:
    from domain.proton import ProtonInstallation

# Raw RomM platform slug for a native-Windows ROM. Checked BEFORE any
# resolve_system/platform_map normalization (adapters/romm/http.py,
# defaults/config.json) — a native-Windows ROM has no emulator/core step at
# all, so it must never depend on "win" gaining a platform_map entry.
WINDOWS_PLATFORM_SLUG = "win"

# RetroDECK's flatpak application id — the single source of the string across the
# plugin. Its plain ``flatpak run <app>`` form is the emulator invocation prefix
# the launch command wraps the resolved ROM path with; the folder-boot ``direct``
# form threads a ``--command=<launcher>`` between the ``flatpak run`` verb and the
# app id (see :func:`resolve_emulator_invocation`). It is also the identity the
# stop-game path resolves live processes by, so it is public.
RETRODECK_APP_ID = "net.retrodeck.retrodeck"
RETRODECK_INVOCATION = f"flatpak run {RETRODECK_APP_ID}"

# The leading ``%EMULATOR_<NAME>%`` binary token and the trailing ``%ROM%`` target
# of an ES-DE ``<command>`` — stripped from a standalone command to recover the
# middle launcher args (e.g. ``--no-gui``) for the folder-boot ``direct`` bake.
_EMULATOR_TOKEN_RE = re.compile(r"%EMULATOR_[A-Z0-9_-]+%")

# RetroArch cores dir as seen INSIDE the RetroDECK flatpak sandbox. Baked
# literally into the -e override; %EMULATOR_RETROARCH% and %ROM% stay as ES-DE
# placeholders (run_game.sh resolves and quotes them at launch).
_RETROARCH_CORES_DIR = "/var/config/retroarch/cores"


@dataclass(frozen=True)
class EmulatorInvocation:
    """What a ROM launches with — a libretro core, a standalone emulator, or a direct sandbox launch.

    The plugin resolves one of these per ROM and bakes it into the shortcut's
    ``launch_options`` via :func:`resolve_emulator_invocation`. The payload
    carried depends on ``kind``:

    - ``kind == "libretro"`` → ``core_so`` is the BARE core name (no ``.so``); the
      renderer emits the RetroArch ``-L <coresdir>/<so>.so %ROM%`` form (the cores
      dir is baked literally because RetroDECK does not expand ``%CORE_RETROARCH%``
      through ``-e``).
    - ``kind == "standalone"`` → ``command`` is the full ES-DE ``<command>`` text
      (already ending in ``%ROM%``, e.g. ``%EMULATOR_RPCS3% --no-gui %ROM%``),
      baked verbatim into ``-e``. RetroDECK's ``run_game.sh`` resolves
      ``%EMULATOR_*%`` and substitutes ``%ROM%`` with the trailing rom path.
    - ``kind == "direct"`` → the folder-boot form (ADR-0019): ``command`` is the
      same full ES-DE standalone command AND ``launcher`` is the emulator's
      sandbox launcher path (e.g.
      ``/app/retrodeck/components/rpcs3/component_launcher.sh``). The renderer
      emits ``flatpak run --command=<launcher> <app> <args>`` — running the
      emulator launcher directly INSIDE the sandbox, bypassing ``run_game.sh``,
      because ``run_game.sh`` reinterprets any directory ``%ROM%`` as an ES-DE
      "directory as a file" and can never launch a bare game folder. The ``<args>``
      are the standalone command's middle (``%EMULATOR_*%`` and ``%ROM%``
      stripped, e.g. ``--no-gui``); the game folder is appended by
      :func:`build_launch_options`.

    ``label`` is the ES-DE display label (diagnostics only). This is the
    standalone-emulator seam (#129); read-path consumers that only understand
    libretro keep reading ``core_so`` (``None`` for a standalone or direct
    emulator) and degrade exactly as they do for a ``(None, None)`` resolution.
    """

    kind: str  # "libretro" | "standalone" | "direct"
    label: str | None = None
    core_so: str | None = None
    command: str | None = None
    launcher: str | None = None

    @classmethod
    def libretro(cls, core_so: str, label: str | None = None) -> EmulatorInvocation:
        """A RetroArch libretro core, identified by its bare ``.so`` name."""
        return cls(kind="libretro", label=label, core_so=core_so)

    @classmethod
    def standalone(cls, command: str, label: str | None = None) -> EmulatorInvocation:
        """A standalone emulator, identified by its full ES-DE ``<command>`` text."""
        return cls(kind="standalone", label=label, command=command)

    @classmethod
    def direct(cls, command: str, launcher: str, label: str | None = None) -> EmulatorInvocation:
        """A standalone emulator launched directly via its sandbox *launcher* (folder-boot form).

        *command* is the full ES-DE standalone ``<command>`` (its middle args are
        recovered at render time); *launcher* is the emulator's sandbox launcher
        path handed to ``flatpak run --command=``.
        """
        return cls(kind="direct", label=label, command=command, launcher=launcher)


def resolve_emulator_invocation(rom: dict[str, Any], emulator: EmulatorInvocation | None = None) -> str:
    """Return the emulator invocation prefix for *rom*.

    With *emulator* unset (``None``) the ROM follows the plain RetroDECK flatpak
    command (the single genuine fallback for a platform with no resolvable
    emulator). A **libretro** invocation renders the RetroDECK ``-e`` override that
    forces that RetroArch core:
    ``flatpak run … -e "%EMULATOR_RETROARCH% -L <cores>/<so>.so %ROM%"`` (cores dir
    literal; ``%EMULATOR_RETROARCH%`` / ``%ROM%`` stay ES-DE placeholders). A
    **standalone** invocation bakes the emulator's full ES-DE command verbatim:
    ``flatpak run … -e "<command … %ROM%>"`` (e.g. ``%EMULATOR_RPCS3% --no-gui
    %ROM%``) — RetroDECK resolves ``%EMULATOR_*%`` and substitutes ``%ROM%`` at
    launch. *rom* is the per-emulator-branch seam and is ignored today.
    """
    del rom  # reserved for the future per-emulator branch
    # Branch explicitly so a half-resolved invocation never reaches the f-string
    # (no "None.so" / empty -e); anything unrenderable degrades to the plain launch.
    if emulator is None:
        return RETRODECK_INVOCATION
    if emulator.kind == "direct" and emulator.launcher and emulator.command:
        # Run the emulator's sandbox launcher directly, bypassing run_game.sh's
        # directory-as-a-file reinterpretation (ADR-0019). The game folder is
        # appended by build_launch_options; only the middle args ride here.
        args = _direct_launch_args(emulator.command)
        base = f"flatpak run --command={emulator.launcher} {RETRODECK_APP_ID}"
        return f"{base} {args}" if args else base
    if emulator.kind == "standalone" and emulator.command:
        return f'{RETRODECK_INVOCATION} -e "{emulator.command}"'
    if emulator.kind == "libretro" and emulator.core_so:
        # The bare core name + ".so" forms the on-disk RetroArch core path -L expects.
        return f'{RETRODECK_INVOCATION} -e "%EMULATOR_RETROARCH% -L {_RETROARCH_CORES_DIR}/{emulator.core_so}.so %ROM%"'
    return RETRODECK_INVOCATION


def _direct_launch_args(command: str) -> str:
    """Recover a standalone command's middle launcher args for the ``direct`` bake.

    Strips the leading ``%EMULATOR_<NAME>%`` binary token(s) and the ``%ROM%``
    target from an ES-DE ``<command>``, collapsing surrounding whitespace, so
    ``%EMULATOR_RPCS3% --no-gui %ROM%`` yields ``--no-gui`` and
    ``%EMULATOR_RPCS3% %ROM%`` yields ``""``. Pure text.
    """
    stripped = _EMULATOR_TOKEN_RE.sub("", command).replace("%ROM%", "")
    return " ".join(stripped.split())


def _escape_launch_arg(path: str) -> str:
    """Backslash-escape ``\\`` and ``"`` in *path* for embedding in a double-quoted launch token.

    Shared by every launch-command builder that embeds a filesystem path
    inside a double-quoted argument, so a server-controlled filename or
    directory name can never break out of the quoting and inject extra argv
    elements.
    """
    return path.replace("\\", "\\\\").replace('"', '\\"')


def build_launch_options(invocation: str, path: str) -> str:
    """Compose the Steam shortcut launch command from *invocation* and ROM *path*.

    An empty *path* means the ROM has **no launch target**, and yields the empty
    launch command. Composing one anyway would hand the emulator a bare ``""``
    argument — the silent failure this rule exists to prevent.

    **An empty launch command means two different things, and nothing may infer
    which.** A ROM that is *not downloaded* and one that is *downloaded but not
    launchable* (``RomInstall.launchable is False``, resolved to ``""`` by the
    disc-resolver seam every bake site draws its path from) produce the same
    empty string, and at the Steam-shortcut layer the two are indistinguishable:
    the shortcut holds ``""`` either way. Only the data layer separates them —
    no ``rom_installs`` row versus a row with ``launchable = 0``. Never read
    emptiness as "not downloaded"; ask the install record.

    Empty is the established uninstalled state, not a new one invented here:
    ``addShortcut`` leaves a new shortcut's options untouched when the command
    is ``""`` (``src/utils/steamShortcuts.ts``), the sync update/adoption path
    writes ``""`` explicitly (``rewriteShortcutIdentity`` in
    ``src/utils/syncManager.ts``), and an uninstall records ``""`` as the ROM's
    ``applied_launch_options`` (``services/rom_removal.py``).

    The path is double-quoted so paths with spaces survive the launcher's
    ``exec "$@"``. Embedded ``\\`` and ``"`` in the path are backslash-escaped
    (backslash first, then quote) so a server-controlled ROM filename cannot
    break out of the quoted token and inject extra argv elements into the
    emulator invocation. Only the path is escaped — *invocation* is trusted
    build-time text whose own ``-e "..."`` quoting must survive verbatim.
    """
    if not path:
        return ""
    return f'{invocation} "{_escape_launch_arg(path)}"'


def resolve_proton_invocation(proton: ProtonInstallation, compat_data_path: str, exe_dir: str) -> str:
    """Render a native-Windows ROM's Proton launch invocation prefix.

    Mirrors :func:`resolve_emulator_invocation`'s role for the RetroDECK/ES-DE
    launch: the prefix :func:`build_launch_options` appends the picked ``.exe``
    path to (single-quoted-argument composition, same call). This is a single
    flat ``env -C <dir> VAR=... VAR=... <binary> run`` command, deliberately
    with no shell control operators (no ``&&``, no ``;``): ``bin/rom-launcher``
    is a plain ``exec "$@"``, and whether Steam hands a shortcut's exe+launch
    options to that as pre-split argv or through a real shell is not
    something this plugin controls or has verified either way — a command
    that only a shell could interpret correctly is not safe to bake. The
    per-ROM compat-data prefix is therefore never created HERE (this function
    stays pure, no I/O) — ``ProtonLocator.compat_data_path`` creates it before
    this function ever sees the path (ADR-0029 decision 4).

    ``exe_dir`` becomes GNU ``env``'s ``-C`` (``--chdir``) argument, so the
    launched ``.exe`` runs with its own install directory as the working
    directory rather than inheriting the launcher's fixed ``bin/`` (every
    Steam shortcut's ``start_dir``, regardless of platform). A native-Windows
    executable that resolves its own data files by a path relative to its own
    location — as many do — silently fails to find them without this: real
    hardware testing hit exactly that (Pokémon Uranium's ``Patcher.exe``
    raised Windows' own "file not found" for ``neoncube\\neoncube.ini``, a
    path relative to the exe's own folder). ``exe_dir`` is escaped the same
    way :func:`build_launch_options` escapes its path argument — unlike the
    compat-data prefix and the other paths here, it is derived from the same
    on-disk directory name a server-controlled download could shape.

    Every OTHER path rendered here — the compat-data prefix, Steam's own
    install root, the Proton binary — is plugin/system-derived, never
    attacker-controlled, so (like ``RETRODECK_APP_ID`` and the RetroArch cores
    dir above) none of it is escaped; only ``exe_dir`` and the final ``.exe``
    argument :func:`build_launch_options` appends are.
    """
    return (
        f"env "
        f'-C "{_escape_launch_arg(exe_dir)}" '
        f'STEAM_COMPAT_DATA_PATH="{compat_data_path}" '
        f'STEAM_COMPAT_CLIENT_INSTALL_PATH="{proton.steam_install_path}" '
        f'"{proton.binary_path}" run'
    )


def resolve_native_invocation(exe_dir: str) -> str:
    """Render a bundled native-Windows-ROM Linux script's launch invocation prefix.

    Mirrors :func:`resolve_proton_invocation`'s role, for the OTHER kind of
    target :func:`domain.windows_launch.enumerate_executables` can resolve
    (``kind == "native"``, currently ``.sh`` only): a Linux launcher/patcher
    script shipped alongside a native-Windows ROM as a RomM asset, which Proton
    cannot run and must not be handed to. It is invoked directly via ``bash``
    rather than executed in place, because a downloaded file is not guaranteed
    to carry its executable bit; :func:`build_launch_options` appends the
    quoted script path the same way it appends a ``.exe`` path for
    :func:`resolve_proton_invocation`.

    ``exe_dir`` becomes GNU ``env``'s ``-C`` (``--chdir``) argument, exactly as
    in :func:`resolve_proton_invocation`, so the script sees its own install
    directory as its working directory rather than the launcher's fixed
    ``bin/`` — the same working-directory need a native ``.exe`` has, and for
    the same reason (a script resolving sibling files by a path relative to
    its own location). Escaped for the same reason ``exe_dir`` is escaped
    there: unlike a plugin/system-derived path, it comes from an on-disk
    directory name a server-controlled download could shape. Deliberately a
    single flat ``env`` invocation with no shell control operators, matching
    :func:`resolve_proton_invocation`'s no-shell-operator property (ADR-0029).
    """
    return f'env -C "{_escape_launch_arg(exe_dir)}" bash'


def _resolve_launch_options(
    rom: dict[str, Any],
    bake_path: str,
    core_overrides: dict[int, EmulatorInvocation],
    windows_launch_options: dict[int, str],
) -> str:
    """Return *rom*'s launch command given it IS installed (``bake_path`` resolved).

    A native-Windows ROM (raw ``platform_slug == "win"``, checked before any
    system normalization) bypasses the emulator/core machinery entirely: its
    command is whatever the caller's Proton resolution already rendered into
    *windows_launch_options*, keyed by ``rom_id`` — absent (no Proton found, or
    no ``.exe`` present) renders as the same empty launch command every other
    unlaunchable install does. Every other platform keeps the existing
    RetroDECK/ES-DE emulator-invocation render.
    """
    if rom.get("platform_slug") == WINDOWS_PLATFORM_SLUG:
        return windows_launch_options.get(rom["id"], "")
    return build_launch_options(resolve_emulator_invocation(rom, core_overrides.get(rom["id"])), bake_path)


def extract_version_metadata(rom: dict[str, Any]) -> dict[str, Any]:
    """Extract a raw RomM ROM dict's sibling-group identity + version dimensions.

    The server-derived facts (ADR-0021) persisted on the ``Rom`` aggregate: the
    sibling-group key plus the ``regions`` / ``languages`` / ``revision`` /
    ``tags`` / ``is_main_sibling`` dimensions. Shared by the sync shortcut build
    (:func:`build_shortcuts_data`) and the version-switch persist path so both
    derive the group key and ``is_main_sibling`` identically — one source of
    truth for the extraction, no drift between the two call sites.

    Prefers a ``sibling_group_key`` already on the dict (the incremental-skip
    path carries the authoritative key) and recomputes only when absent.
    ``is_main_sibling`` sits under ``rom_user``; a missing or ``null``
    ``rom_user`` degrades to ``False``.
    """
    return {
        "sibling_group_key": rom.get("sibling_group_key") or compute_sibling_group_key(rom),
        "regions": list(rom.get("regions") or []),
        "languages": list(rom.get("languages") or []),
        "revision": rom.get("revision") or "",
        "tags": list(rom.get("tags") or []),
        "is_main_sibling": bool((rom.get("rom_user") or {}).get("is_main_sibling", False)),
    }


def build_shortcuts_data(
    roms: list[dict[str, Any]],
    plugin_dir: str,
    installed_paths: dict[int, str],
    core_overrides: dict[int, EmulatorInvocation],
    windows_launch_options: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Transform ROM list into shortcut data dicts for frontend AddShortcut calls.

    *installed_paths* maps ``rom_id`` to the resolved on-disk launch path. An
    installed ROM gets a full launch command in ``launch_options``; a ROM absent
    from the map gets ``""`` (empty placeholder) until it is downloaded. An
    installed ROM the system cannot launch (``RomInstall.launchable is False``)
    stays IN the map — it is downloaded, and the sibling-group representative
    choice reads the key set — but maps to the empty path, which
    :func:`build_launch_options` renders as the same empty placeholder.

    *core_overrides* maps ``rom_id`` to the **already-resolved**
    :class:`EmulatorInvocation` the ROM launches with (its full active emulator —
    libretro core or standalone — folding the per-game/per-platform override over
    the es_systems default). Only ROMs that resolved to an emulator appear (the
    caller omits the ``(None, None)`` fallback); a ROM absent from the map follows
    the plain RetroDECK launch, a present ROM bakes its ``-e`` form into
    ``launch_options``. Required so a new bake site can never silently skip the
    override. Ignored entirely for a native-Windows ROM (see
    *windows_launch_options*).

    *windows_launch_options* maps ``rom_id`` to the **already-rendered** Proton
    launch command for a native-Windows ROM (raw ``platform_slug == "win"``,
    checked before any system normalization) — the caller's
    :func:`resolve_proton_invocation` + :func:`build_launch_options` composition,
    already folding the ROM's persisted ``selected_exe`` pin and the located
    Proton build. Only ROMs that resolved to a launchable command appear; a
    Windows ROM absent from the map (no Proton found, or no ``.exe`` present)
    bakes the same empty launch command an uninstalled ROM does. Ignored for
    every other platform.

    The sibling-group key (ADR-0021) and RomM's version dimensions (``regions`` /
    ``languages`` / ``revision`` / ``tags`` / ``is_main_sibling``) are derived
    from each raw ROM dict here and carried through so the commit persists them
    on the ``Rom`` aggregate. ``is_main_sibling`` sits under ``rom_user``; the
    lookup is guarded so a missing or ``null`` ``rom_user`` degrades to ``False``.
    """
    exe = os.path.join(plugin_dir, "bin", "rom-launcher")
    start_dir = os.path.join(plugin_dir, "bin")
    windows_launch_options = windows_launch_options or {}
    return [
        {
            "rom_id": rom["id"],
            "name": rom["name"],
            "fs_name": rom.get("fs_name", ""),
            # Alphabetical tie-break key for sibling-group representative
            # resolution (ADR-0021): RomM ships it on the list endpoint; fall
            # back to the filename stem when absent. No DB column — carried only
            # through the sync pipeline, never persisted.
            "fs_name_no_ext": rom.get("fs_name_no_ext") or os.path.splitext(rom.get("fs_name", ""))[0],
            "exe": exe,
            "start_dir": start_dir,
            "launch_options": (
                _resolve_launch_options(rom, installed_paths[rom["id"]], core_overrides, windows_launch_options)
                if rom["id"] in installed_paths
                else ""
            ),
            "platform_name": rom.get("platform_name", "Unknown"),
            "platform_slug": rom.get("platform_slug", ""),
            "igdb_id": rom.get("igdb_id"),
            "sgdb_id": rom.get("sgdb_id"),
            "ra_id": rom.get("ra_id"),
            # Server-reported ROM size in bytes (#1395), carried through so the
            # commit persists it on the Rom aggregate (it rides the sync UPSERT
            # like the version dimensions). Absent/None → "size unknown".
            "fs_size_bytes": rom.get("fs_size_bytes"),
            "cover_path": "",
            # The sibling-group key + version dimensions (ADR-0021), extracted by
            # the shared helper so the sync build and the version-switch persist
            # path derive them identically. The incremental-skip path reconstructs
            # ROM dicts from persisted rows carrying the authoritative key (real
            # platform_id baked in) but no ``platform_id`` field, so the helper
            # prefers that key over recomputing (which would yield ``…:None`` and
            # split the group's bucket, #1296).
            **extract_version_metadata(rom),
        }
        for rom in roms
    ]
