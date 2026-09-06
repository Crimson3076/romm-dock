"""ActiveCoreResolver — the single read-path core-resolution seam per ROM.

The one place that answers "which emulator will this ROM actually launch
with?", combining the per-game ``emulator_overrides`` and per-platform core
selection (the two deviations the plugin owns) with the ACTIVE launcher
backend's own system-layer resolution. Every per-game core read consumer and
every launch-bake site draws from this seam so the read-path core never
diverges from the launched core.

A separate, additive layer sits BEFORE all of this: :meth:`ActiveCoreResolver.
cross_backend_render_for_rom` renders the ROM's ``cross_backend_pin`` — an
explicit "always launch through backend X's emulator Y" pin, checked by every
render call site before the chain below and never reinterpreted by which
backend is active. It is a full render (through the PINNED backend's own
instance), not a layer of :meth:`active_emulator_for_rom` — that method and its
three-layer chain are unaffected when no such pin exists.

Precedence (three layers, then the plain launch): DB per-game override for the
active backend (top) → ``settings.json`` per-platform core for the active
backend → that backend's own live default → ``None``. Both pin layers are
scoped to whichever backend is CURRENTLY active — switching backends reads a
different (independent) pin, never reinterprets the same one (issue #918's
per-backend picker follow-up). The retired ES-DE gamelist
``<alternativeEmulator>`` is never consulted, and there is no offline snapshot
below the live default. A pinned per-game or per-platform label that no longer
resolves to a bakeable emulator degrades to the next layer rather than raising
— so a stale label never blocks a read or bakes a bogus ``-e`` override. The
per-game/per-platform label may name a **standalone** emulator (not just a
libretro core); it resolves the same way.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from domain.emulator_commands import label_to_invocation
from domain.rom_files import folder_boot_root
from domain.shortcut_data import EmulatorInvocation

if TYPE_CHECKING:
    import logging
    from typing import Any

    from domain.emulator_commands import EmulatorOption
    from domain.rom import Rom
    from domain.rom_install import RomInstall
    from lib.late_binding import LateBinding
    from services.protocols import (
        BackendBinder,
        CoreInfoProvider,
        PlatformCoreReader,
        SystemResolver,
        UnitOfWorkFactory,
    )


@dataclass(frozen=True)
class ActiveCoreResolverConfig:
    """Frozen wiring bundle handed to ``ActiveCoreResolver.__init__``.

    Carries the SQLite Unit-of-Work factory (to read the ROM's
    ``platform_slug`` + ``emulator_overrides``), the ACTIVE launcher backend's
    core-info read seam (the classified emulator options + the system-layer
    default — issue #918's per-backend picker follow-up) and its
    ``backend_id``, the per-platform core reader (the ``settings.json``
    ``platform_cores`` map, itself nested per backend), the platform-slug-to-
    system resolver, and the logger used to warn on a stale label.

    ``core_info``/``active_backend_id`` are ``LateBinding``, not the seam
    directly: this resolver is constructed before ``LauncherBackendService``
    (which needs THIS resolver as ``RelaunchOptionsResolver``'s
    ``active_core`` seam) — the same producer/consumer construction cycle
    every other cross-reference in ``bootstrap/services.py`` breaks the same
    way. Each read re-invokes the binding, so a backend switch is visible on
    this resolver's very next call.
    """

    uow_factory: UnitOfWorkFactory
    core_info: LateBinding[CoreInfoProvider]
    active_backend_id: LateBinding[str]
    platform_core_reader: PlatformCoreReader
    resolve_system: SystemResolver
    logger: logging.Logger
    # Binds ANY registered backend by id, regardless of which one is active —
    # the seam :meth:`ActiveCoreResolver.cross_backend_render_for_rom` renders
    # a per-game cross-backend pin through. A plain reference (not LateBinding)
    # would work too — unlike ``core_info``/``active_backend_id`` it never needs
    # to read through whichever backend is currently active, so it carries none
    # of their producer/consumer construction-order cycle — but it is
    # constructed alongside them in ``bootstrap/services.py`` (before
    # ``LauncherBackendService`` exists), so it is wrapped in ``LateBinding`` too,
    # for the same reason and resolved the same way.
    backend_binder: LateBinding[BackendBinder]


class ActiveCoreResolver:
    """Resolve the active RetroArch core for one ROM by ``rom_id``."""

    def __init__(self, *, config: ActiveCoreResolverConfig) -> None:
        self._uow_factory = config.uow_factory
        self._core_info = config.core_info
        self._active_backend_id = config.active_backend_id
        self._platform_core_reader = config.platform_core_reader
        self._resolve_system = config.resolve_system
        self._logger = config.logger
        self._backend_binder = config.backend_binder

    def active_emulator_for_rom(self, rom_id: int) -> EmulatorInvocation | None:
        """Return the :class:`EmulatorInvocation` the ROM ``rom_id`` will launch with.

        The launch-bake seam. Reads the ROM's ``platform_slug`` +
        ``emulator_overrides`` once, then resolves the ACTIVE backend's own
        ``backend_id`` and applies the three-layer precedence, each layer
        scoped to that backend:

        1. Per-game DB override for the active backend (an emulator LABEL from
           the picker, libretro OR standalone) → its invocation when the label
           resolves to a bakeable command.
        2. Per-platform ``settings.json`` core for the active backend (also a
           LABEL, libretro OR standalone) → its invocation when it resolves.
        3. The active backend's own live default via ``get_default_emulator``
           — the first safely-bakeable command, which may itself be standalone
           (PCSX2, RPCS3, Dolphin, …) or libretro.

        Returns ``None`` when the active backend has no resolvable emulator at
        all for this platform — including when its catalogue cannot be read —
        so the caller bakes the plain launch and lets that backend resolve the
        emulator itself. A stale per-game/per-platform label is never fatal —
        it degrades to the next layer with a WARNING.

        Final step: a resolved **standalone** emulator whose install is a
        folder-boot layout (PS3 — ``…/PS3_GAME/USRDIR/EBOOT.BIN``) is rewritten
        to the ``direct`` sandbox form (ADR-0019). RetroDECK's ``run_game.sh``
        reinterprets a directory ``%ROM%`` as an ES-DE "directory as a file" and
        can never launch a bare game folder, so a folder-boot game must run its
        emulator launcher directly inside the sandbox instead. The rewrite keys
        off :func:`folder_boot_root` — the same fact the disc/bake-path seam uses
        to fold the target to the game folder — so the invocation form and the
        baked path are always decided from one layout fact. A libretro emulator,
        a non-folder install, or an unresolvable sandbox launcher all leave the
        invocation unchanged.
        """
        rom, install = self._read_rom_and_install(rom_id)
        if rom is None:
            self._logger.warning("active_core_resolver: no ROM for rom_id=%s; resolving to plain launch", rom_id)
            return None

        core_info = self._core_info.get()
        backend_id = self._active_backend_id.get()
        system = self._resolve_system(rom.platform_slug)
        options = core_info.get_emulator_options(system)["options"]
        emulator = self._resolve_by_precedence(rom, rom_id, system, options, core_info, backend_id)
        return self._maybe_folder_boot_direct(emulator, install, rom_id, core_info)

    def _resolve_by_precedence(
        self,
        rom: Rom,
        rom_id: int,
        system: str,
        options: list[EmulatorOption],
        core_info: CoreInfoProvider,
        backend_id: str,
    ) -> EmulatorInvocation | None:
        """Apply the per-game → per-platform → system-default precedence chain.

        Every layer is scoped to *backend_id* — the ACTIVE backend's own pin,
        never a pin set under a different backend. Returns the resolved
        :class:`EmulatorInvocation` before the folder-boot rewrite. A stale
        per-game/per-platform label warns and degrades to the next layer; the
        bottom is *backend_id*'s own live default (or ``None``).
        """
        override = rom.emulator_override_for(backend_id)
        if override is not None:
            invocation = label_to_invocation(options, override)
            if invocation is not None:
                return invocation
            self._logger.warning(
                "active_core_resolver: per-game override '%s' for rom_id=%s no longer resolves on %s/%s; "
                "degrading to the per-platform/system default",
                override,
                rom_id,
                backend_id,
                system,
            )

        platform_label = self._platform_core_reader.get_platform_core(backend_id, rom.platform_slug)
        if platform_label is not None:
            invocation = label_to_invocation(options, platform_label)
            if invocation is not None:
                return invocation
            self._logger.warning(
                "active_core_resolver: per-platform core '%s' for %s/%s (rom_id=%s) no longer resolves; "
                "degrading to the system default",
                platform_label,
                backend_id,
                rom.platform_slug,
                rom_id,
            )

        return core_info.get_default_emulator(system)

    def _maybe_folder_boot_direct(
        self,
        emulator: EmulatorInvocation | None,
        install: RomInstall | None,
        rom_id: int,
        core_info: CoreInfoProvider,
    ) -> EmulatorInvocation | None:
        """Rewrite a standalone *emulator* to the folder-boot ``direct`` form when warranted.

        Fires only for a **standalone** emulator whose *install* is a folder-boot
        layout (:func:`folder_boot_root` returns a game root). Resolves the
        emulator's sandbox launcher via the es_find_rules probe and returns a
        ``direct`` invocation. Leaves the emulator unchanged for a libretro core,
        a non-folder install, a missing install, or an unresolvable launcher —
        the last is logged (the baked ``run_game`` form will fail to launch a
        folder until a later re-bake heals it).
        """
        if emulator is None or emulator.kind != "standalone" or emulator.command is None:
            return emulator
        if install is None or folder_boot_root(install.file_path, install.rom_dir) is None:
            return emulator
        launcher = core_info.resolve_sandbox_launcher(emulator.command)
        if launcher is None:
            self._logger.warning(
                "active_core_resolver: folder-boot rom_id=%s resolves to standalone '%s' but its sandbox "
                "launcher is unresolvable; keeping the run_game form (launch will fail until healed)",
                rom_id,
                emulator.label,
            )
            return emulator
        return EmulatorInvocation.direct(emulator.command, launcher, emulator.label)

    def active_core_for_rom(self, rom_id: int) -> tuple[str | None, str | None]:
        """Return the ``(core_so, label)`` the ROM ``rom_id`` will launch with.

        The read-path projection of :meth:`active_emulator_for_rom`, kept for the
        ``.so``-space consumers (BIOS status, per-core save dir, save-emulator
        tag, core-change detection, the cores menu's active marker). A **libretro**
        emulator yields its ``(core_so, label)``; a **standalone** emulator yields
        ``(None, label)`` — those consumers already degrade on a ``None`` core
        exactly as they did for the old ``(None, None)`` resolution, so the
        read-path core never disagrees with the (now possibly standalone) launch.
        """
        emulator = self.active_emulator_for_rom(rom_id)
        if emulator is None:
            return (None, None)
        return (emulator.core_so, emulator.label)

    def cross_backend_render_for_rom(self, rom_id: int, rom: dict[str, Any], path: str) -> str | None:
        """Render *rom_id*'s full launch_options through its pinned cross-backend emulator, if any.

        A NEW precedence layer, additive and separate from
        :meth:`active_emulator_for_rom`'s three-layer chain: it runs BEFORE that
        chain entirely, and does not read through it at all. Returns the fully
        rendered ``launch_options`` string when the ROM has a
        ``cross_backend_pin`` that still resolves to a bakeable emulator on its
        named backend, else ``None`` — the caller's signal to fall through to
        its normal active-backend render path unchanged. ``None`` is also the
        overwhelmingly common case (no pin at all), so this returns immediately
        on that check before doing any further work.

        A pin naming a backend that is no longer installed, or a label that no
        longer resolves to a bakeable option on that backend, degrades to
        ``None`` with a WARNING — never fatal, exactly like a stale
        per-game/per-platform label degrades in :meth:`_resolve_by_precedence`.

        The crux of the whole feature: the invocation is rendered through the
        PINNED backend's OWN ``resolve_invocation``/``build_launch_options`` —
        never through the active backend's rendering — because RetroDECK's
        ``flatpak run ... -e "..."`` wrapping and EmuDeck's directly-resolved
        host command are fundamentally different shapes, and only the pinned
        backend's own instance renders its own shape correctly.

        Known v1 gap: the folder-boot rewrite (:meth:`_maybe_folder_boot_direct`)
        is NOT applied to a cross-backend render — a folder-boot title (PS3)
        pinned to a foreign backend bakes the standard ``run_game`` form and may
        fail to launch. Not attempted here; a real fix needs the pinned
        backend's own sandbox-launcher resolution, which this seam does not
        have access to.
        """
        db_rom, _install = self._read_rom_and_install(rom_id)
        if db_rom is None or db_rom.cross_backend_pin is None:
            return None
        pin = db_rom.cross_backend_pin
        backend_id = pin["backend_id"]
        label = pin["label"]

        backend = self._backend_binder.get().bind_backend(backend_id)
        if backend is None:
            self._logger.warning(
                "active_core_resolver: cross_backend_pin for rom_id=%s names backend '%s', which is not "
                "installed on this machine; falling back to the active-backend resolution",
                rom_id,
                backend_id,
            )
            return None

        system = self._resolve_system(db_rom.platform_slug)
        options = backend.get_emulator_options(system)["options"]
        invocation = label_to_invocation(options, label)
        if invocation is None:
            self._logger.warning(
                "active_core_resolver: cross_backend_pin '%s' for rom_id=%s no longer resolves on %s/%s; "
                "falling back to the active-backend resolution",
                label,
                rom_id,
                backend_id,
                system,
            )
            return None

        invocation_str = backend.resolve_invocation(rom, invocation)
        return backend.build_launch_options(invocation_str, path)

    def _read_rom_and_install(self, rom_id: int) -> tuple[Rom | None, RomInstall | None]:
        with self._uow_factory() as uow:
            return (uow.roms.get(rom_id), uow.rom_installs.get(rom_id))
