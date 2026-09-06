"""CoreService — RetroArch core selection and overrides per platform/ROM.

Owns the plugin's two core-selection deviations: the per-platform core (the
``settings.json`` ``platform_cores`` map) and the per-game emulator override (the
``roms.emulator_override`` pin). Enumerating the cores available for a ROM's
platform, toggling the per-platform default (with the fan-out that re-bakes every
affected shortcut), and pinning/clearing a per-game core all live here; the
cross-service BIOS recheck that follows a per-platform core write is also
scheduled from this service.

Neither selection is written to the retired ES-DE gamelist: the per-platform core
lands in ``settings.json`` via the injected ``SettingsPersister`` and the per-game
pin lands on the ``Rom`` aggregate via the Unit-of-Work. The launch command for an
installed+bound ROM is recomputed from the shared ``ActiveCoreReader`` resolver so
the read-path core never diverges from the launched core, and the frontend can
confirm-set the freshly-baked ``launch_options`` on the live Steam shortcut.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from domain.emulator_commands import label_to_invocation, options_to_payload
from lib.list_result import ErrorCode

if TYPE_CHECKING:
    import asyncio
    import logging
    from collections.abc import Callable

    from domain.rom import Rom
    from domain.rom_install import RomInstall
    from domain.shortcut_data import EmulatorInvocation
    from services.protocols import (
        ActiveCoreReader,
        BackendBinder,
        BiosChecker,
        CoreInfoProvider,
        DiscResolver,
        LaunchCommandRenderer,
        LauncherBackendFactory,
        SettingsPersister,
        SystemResolver,
        UnitOfWorkFactory,
    )


@dataclass(frozen=True)
class CoreServiceConfig:
    """Frozen wiring bundle handed to ``CoreService.__init__``.

    Carries the runtime infrastructure (event loop, logger), the ACTIVE
    launcher backend's core-info read seam and its ``backend_id`` (issue
    #918's per-backend picker follow-up — both the per-platform/per-game pin
    storage below and the emulator catalogue are scoped to whichever backend
    is currently selected), the platform-slug-to-system resolver, the live
    ``settings`` dict + its persister (where the per-platform core lands), the
    cross-service BIOS checker, the SQLite Unit-of-Work factory (to read the ROM
    + its install and write the per-game pin), the shared per-ROM
    active-core resolver (the menu's active marker + the source of every
    re-baked launch command), the shared per-ROM disc resolver (so a re-baked
    launch command keeps the ROM's pinned disc rather than reverting to disc 1 /
    the m3u), and the active launcher backend's rendering seam (issue #918) so
    a re-bake matches whichever backend is currently selected. Bundled here so
    the ctor stays within the S107 parameter budget.

    Unlike ``ActiveCoreResolverConfig``, ``core_info``/``active_backend_id``
    are plain values here, not ``LateBinding`` — ``CoreService`` is
    constructed after ``LauncherBackendService`` exists in
    ``bootstrap/services.py``, so there is no producer/consumer cycle to break.
    """

    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    core_info: CoreInfoProvider
    active_backend_id: Callable[[], str]
    resolve_system: SystemResolver
    settings: dict[str, Any]
    settings_persister: SettingsPersister
    bios_checker: BiosChecker
    uow_factory: UnitOfWorkFactory
    active_core: ActiveCoreReader
    disc_resolver: DiscResolver
    launch_renderer: LaunchCommandRenderer
    # The cross-backend pin's read seams (get_platform_core_info's
    # ``other_backends`` catalogue, and set_game_cross_backend_pin's
    # resolve-before-write): every registered factory (to enumerate every
    # OTHER backend) and the seam that binds any one of them on demand.
    backend_factories: list[LauncherBackendFactory]
    backend_binder: BackendBinder


class CoreService:
    """RetroArch core override reads and writes — per-platform (settings) + per-game (DB)."""

    def __init__(self, *, config: CoreServiceConfig) -> None:
        self._loop = config.loop
        self._logger = config.logger
        self._core_info = config.core_info
        self._active_backend_id = config.active_backend_id
        self._resolve_system = config.resolve_system
        self._settings = config.settings
        self._settings_persister = config.settings_persister
        self._bios_checker = config.bios_checker
        self._uow_factory = config.uow_factory
        self._active_core = config.active_core
        self._disc_resolver = config.disc_resolver
        self._launch_renderer = config.launch_renderer
        self._backend_factories = config.backend_factories
        self._backend_binder = config.backend_binder

    async def get_platform_core_info(self, rom_id: int) -> dict[str, Any]:
        """Return the emulators available for ``rom_id``'s platform + the active one.

        The emulator list is platform-wide (system-level): every ES-DE
        ``<command>`` for the ROM's system, each annotated ``{label, kind,
        core_so, is_default, bakeable, reason}`` (libretro AND standalone). The
        active selection is the per-ROM resolution from
        :class:`ActiveCoreResolver`, so a pinned ``emulator_override`` (or
        per-platform core) surfaces over the system default and the menu can
        highlight the active emulator (or offer Reset). ``platform_core_label``
        carries the per-platform override label (``settings.json``
        ``platform_cores``) so the menu can mark the system-level selection
        distinctly from the active emulator. ``has_game_override`` reports
        whether a per-game pin is set — the menu can't infer this from the active
        emulator alone (pinning the same emulator as the per-platform override is
        indistinguishable), so the flag drives the "follow the system" reset
        item's checkmark. ``emulator_data_available`` is ``False`` when
        ``es_systems.xml`` cannot be read (RetroDECK not detected), so the menu
        can say so instead of showing an empty list. When ``rom_id`` is unknown
        the emulator list is empty and the active emulator is ``(None, None)``.

        ``cross_backend_pin`` is the ROM's ``{"backend_id", "label"}`` pin, or
        ``None`` — verbatim, for the picker to mark. ``other_backends`` lists
        every OTHER registered backend detected on this machine (the active one
        excluded, an undetected one excluded entirely), each with its own
        ``{backend_id, display_name, emulators}`` catalogue projected through
        the same payload shape as ``emulators`` above, so the picker can offer a
        cross-backend pin against any of them.
        """
        return await self._loop.run_in_executor(None, self._platform_core_info_io, rom_id)

    def _platform_core_info_io(self, rom_id: int) -> dict[str, Any]:
        rom = self._read_rom(rom_id)
        # A native-Windows ROM (raw platform_slug == "win") has no emulator/core
        # step at all (ADR-0030) — it launches through the dedicated exe picker +
        # Proton, never RetroDECK/ES-DE. Guarded explicitly rather than relying on
        # "win" having no es_systems.xml entry, which is what actually keeps this
        # unreachable today: CoreService has no windows_resolver seam of its own,
        # so a future platform_map entry for "win" would otherwise let a per-game
        # or per-platform core pin silently override the Proton-baked launch with
        # a plain RetroDECK one (the raw file_path — e.g. a Windows ROM's largest
        # data file, never an .exe — as the bake path).
        if rom is None or rom.platform_slug == "win":
            return {
                "emulators": [],
                "emulator_data_available": True,
                "active_core": None,
                "active_core_label": None,
                "platform_core_label": None,
                "has_game_override": False,
                "cross_backend_pin": None,
                "other_backends": [],
            }
        backend_id = self._active_backend_id()
        system = self._resolve_system(rom.platform_slug)
        options = self._core_info.get_emulator_options(system)
        active_so, active_label = self._active_core.active_core_for_rom(rom_id)
        backend_platform_cores = self._settings.get("platform_cores", {}).get(backend_id, {})
        return {
            "emulators": options_to_payload(options["options"]),
            "emulator_data_available": options["available"],
            "active_core": active_so,
            "active_core_label": active_label,
            "platform_core_label": backend_platform_cores.get(rom.platform_slug),
            "has_game_override": rom.emulator_override_for(backend_id) is not None,
            "cross_backend_pin": rom.cross_backend_pin,
            "other_backends": self._other_backends_payload(active_backend_id=backend_id, system=system),
        }

    def _other_backends_payload(self, *, active_backend_id: str, system: str) -> list[dict[str, Any]]:
        """Every registered backend OTHER than the active one, with its own emulator catalogue.

        Skips a factory that fails to bind (not detected on this machine)
        entirely — not even as an empty/error entry — so the common
        single-backend-installed case reports an empty list rather than noise.
        Each entry projects THAT backend's own ``get_emulator_options`` through
        the same :func:`options_to_payload` the active backend's ``emulators``
        field already uses, so the frontend's existing per-backend rendering
        generalizes to N backends with no new parsing logic.
        """
        other: list[dict[str, Any]] = []
        for factory in self._backend_factories:
            if factory.backend_id == active_backend_id:
                continue
            backend = self._backend_binder.bind_backend(factory.backend_id)
            if backend is None:
                continue
            options = backend.get_emulator_options(system)
            other.append(
                {
                    "backend_id": factory.backend_id,
                    "display_name": factory.display_name,
                    "emulators": options_to_payload(options["options"]),
                }
            )
        return other

    def _set_system_core_io(self, platform_slug: str, core_label: str) -> list[dict[str, Any]]:
        """Write the per-platform core selection and re-bake the affected shortcuts.

        Mutates ``settings["platform_cores"]`` — stores *core_label* under
        *platform_slug* when non-empty, pops the slug when blank (revert to the
        es_systems default) — and persists ``settings.json`` through the
        injected persister. The persister holds the same live dict, so the fan-out
        that follows resolves the freshly-written value.

        Returns one ``{"app_id", "launch_options"}`` entry per installed+bound ROM
        on the platform whose active core is the new per-platform selection. ROMs
        with a per-game override FOR THE ACTIVE BACKEND are skipped (the pin wins
        over the platform default), as are uninstalled or unbound ROMs (no live
        shortcut to rewrite) — a pin set under a DIFFERENT backend never blocks
        this fan-out. Each entry's ``launch_options`` is the FULL active core baked
        by the shared resolver — the ``-e`` override form, or the plain launch when
        the resolver yields ``(None, None)`` — over the disc-resolved bake path,
        so a multi-disc ROM keeps its persisted ``selected_disc`` rather than
        reverting to disc 1 / the m3u (a single-disc ROM bakes its ``file_path``
        unchanged).

        A no-op for the native-Windows pseudo-platform (``platform_slug ==
        "win"``, ADR-0030): it has no emulator/core concept, so nothing is
        written to ``settings.json`` and no ROM is rebaked. The caller
        (:meth:`set_system_core`) still returns success — there is nothing to
        fail, just nothing to do.
        """
        if platform_slug == "win":
            return []
        backend_id = self._active_backend_id()
        if core_label:
            self._settings["platform_cores"].setdefault(backend_id, {})[platform_slug] = core_label
        else:
            self._settings["platform_cores"].get(backend_id, {}).pop(platform_slug, None)
        self._settings_persister.save_settings()
        self._core_info.reset_cache()

        # Snapshot the installed+bound, non-overridden (rom, install) pairs in one
        # short read UoW, then close it before resolving each ROM's active core:
        # active_emulator_for_rom opens its own UoW, and the per-connection
        # BEGIN IMMEDIATE write lock is not re-entrant — resolving inside the
        # iteration UoW would block on the lock until busy_timeout then raise
        # "database is locked" (#1134). This read UoW performs no writes.
        pending: list[tuple[Rom, RomInstall]] = []
        with self._uow_factory() as uow:
            for rom in uow.roms.iter_by_platform(platform_slug):
                if rom.emulator_override_for(backend_id) is not None:
                    continue
                if rom.shortcut_app_id is None:
                    continue
                install = uow.rom_installs.get(rom.rom_id)
                if install is None:
                    continue
                pending.append((rom, install))

        rebake_items: list[dict[str, Any]] = []
        for rom, install in pending:
            # Fold the ROM's persisted disc pick over the install so a
            # per-platform core change re-bakes the pinned disc, not disc 1 /
            # the m3u. A single-disc ROM resolves to its own file_path.
            bake_path = self._disc_resolver.resolve_for_install(install, rom.selected_disc)
            rom_dict = {"id": rom.rom_id, "platform_slug": rom.platform_slug}
            cross_rendered = self._active_core.cross_backend_render_for_rom(rom.rom_id, rom_dict, bake_path)
            if cross_rendered is not None:
                launch_options = cross_rendered
            else:
                emulator = self._active_core.active_emulator_for_rom(rom.rom_id)
                invocation = self._launch_renderer.resolve_invocation(rom_dict, emulator)
                launch_options = self._launch_renderer.build_launch_options(invocation, bake_path)
            rebake_items.append({"app_id": rom.shortcut_app_id, "launch_options": launch_options})
        return rebake_items

    async def set_system_core(self, platform_slug: str, core_label: str) -> dict[str, Any]:
        """Set or clear the per-platform core selection for a platform.

        Empty ``core_label`` clears the selection (reverts to the es_systems
        default). On success the per-platform core is written to ``settings.json``
        and every installed+bound ROM on the platform (minus per-game-overridden
        ROMs) is re-baked: the response carries ``rebake_items`` (a list of
        ``{"app_id", "launch_options"}``) the frontend confirm-sets on the live
        Steam shortcuts, plus ``bios_status`` re-checked against the newly chosen
        core. On any failure (settings write error, fan-out error, BIOS recheck
        error) returns ``{"success": False, "message": ...}``.
        """
        try:
            rebake_items = await self._loop.run_in_executor(
                None,
                self._set_system_core_io,
                platform_slug,
                core_label,
            )
            bios = await self._bios_checker.check_platform_bios(platform_slug)
            return {"success": True, "bios_status": bios, "rebake_items": rebake_items}
        except Exception as e:
            self._logger.error(f"Failed to set system core: {e}")
            return {"success": False, "reason": ErrorCode.UNKNOWN.value, "message": str(e)}

    async def set_game_core(self, rom_id: int, label: str) -> dict[str, Any]:
        """Pin the per-game emulator override for ``rom_id`` to *label*.

        The picked LABEL is resolved to a bakeable :class:`EmulatorInvocation`
        FIRST (against the emulators ES-DE lists for the ROM's platform, libretro
        OR standalone). A label that does not resolve to a bakeable emulator —
        unknown, ``needs_setup``, or otherwise un-bakeable — is a hard failure:
        the canonical ``{"success": False, "reason": ..., "message": ...}`` shape
        is returned and **nothing is written**, so the DB never holds a label no
        consumer can bake. On success the pin is written via the Unit-of-Work and
        the response carries the freshly-baked ``launch_options`` (the ``-e``
        override form) and ``app_id`` for the frontend to confirm-set on the live
        Steam shortcut. When the ROM is not installed or not bound to a shortcut
        there is nothing to update live: the pin still lands and
        ``launch_options``/``app_id`` are ``None`` (the override applies on the
        next download).

        Mutually exclusive with :meth:`set_game_cross_backend_pin`'s pin: this
        also clears any cross-backend pin on ``rom_id``, since that pin is
        checked BEFORE this override at every bake site and would otherwise
        silently keep winning over this fresh pick.
        """
        return await self._loop.run_in_executor(None, self._set_game_core_io, rom_id, label)

    def _set_game_core_io(self, rom_id: int, label: str) -> dict[str, Any]:
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            if rom is None:
                return {
                    "success": False,
                    "reason": "not_found",
                    "message": f"ROM {rom_id} is not tracked",
                }
            # A native-Windows ROM has no emulator/core step at all (ADR-0030) —
            # refuse before any write rather than depending on "win" resolving to
            # an empty ES-DE options list. See the matching guard in
            # _platform_core_info_io / _clear_game_core_io.
            if rom.platform_slug == "win":
                return self._windows_unsupported(rom_id)
            backend_id = self._active_backend_id()
            system = self._resolve_system(rom.platform_slug)
            invocation = label_to_invocation(self._core_info.get_emulator_options(system)["options"], label)
            if invocation is None:
                # Hard-fail BEFORE any write — never persist a label that does not
                # resolve to a bakeable emulator (unknown / needs_setup / un-bakeable)
                # on the ACTIVE backend's own catalogue.
                return {
                    "success": False,
                    "reason": "core_unavailable",
                    "message": f"Emulator '{label}' is not available for {rom.platform_slug}",
                }
            # Enforce the aggregate invariant (strip / reject blank) via the
            # verb method, then persist the resulting label through the pin-only
            # write path (never the sync UPSERT) — scoped to the active backend,
            # leaving any other backend's pin for this ROM untouched.
            rom.pin_emulator_override(backend_id, label)
            # Mutually exclusive with a cross-backend pin (the symmetric half of
            # set_game_cross_backend_pin's own clear): cross_backend_render_for_rom
            # is checked BEFORE this override at every bake site, so a stale pin
            # left in place here would silently keep winning over this fresh pick.
            rom.clear_cross_backend_emulator()
            uow.roms.set_emulator_override(rom_id, backend_id, rom.emulator_override_for(backend_id))
            uow.roms.set_cross_backend_pin(rom_id, rom.cross_backend_pin)
            install = uow.rom_installs.get(rom_id)
        # Bake outside the committed write UoW, uniform with the clear path (the
        # pinned override is the just-resolved emulator, so there is no resolver
        # read and no commit-ordering subtlety here).
        launch_options, app_id = self._launch_options_for(rom, install, invocation)
        return {"success": True, "launch_options": launch_options, "app_id": app_id}

    async def set_game_cross_backend_pin(self, rom_id: int, backend_id: str, label: str) -> dict[str, Any]:
        """Pin ``rom_id`` to always launch through *backend_id*'s emulator *label*.

        Additive and separate from :meth:`set_game_core`'s ``emulator_overrides``
        pin: this pin ignores which backend is globally active — the ROM
        renders through *backend_id*'s own instance every time, mutually
        exclusive with the active-backend-scoped override (setting this clears
        the CURRENTLY active backend's ``emulator_overrides`` entry for this
        ROM, so at most one deviation type is ever in effect at once).

        *label* is resolved against *backend_id*'s OWN catalogue FIRST — never
        the active backend's — mirroring :meth:`set_game_core`'s "resolve
        first, hard-fail if it doesn't resolve, write only on success"
        discipline. *backend_id* not registered or not detected on this
        machine is ``reason: "unknown_backend"``; a *label* that does not
        resolve to a bakeable emulator on *backend_id* is ``reason:
        "core_unavailable"`` — both hard failures, **nothing is written**. On
        success the response carries the freshly-baked ``launch_options`` (now
        rendered through *backend_id*'s own instance) and ``app_id`` for an
        installed+bound ROM, mirroring :meth:`set_game_core`'s response shape
        exactly (``None``/``None`` for an uninstalled or unbound ROM).
        """
        return await self._loop.run_in_executor(None, self._set_game_cross_backend_pin_io, rom_id, backend_id, label)

    def _set_game_cross_backend_pin_io(self, rom_id: int, backend_id: str, label: str) -> dict[str, Any]:
        backend = self._backend_binder.bind_backend(backend_id)
        if backend is None:
            return {
                "success": False,
                "reason": "unknown_backend",
                "message": f"Launcher backend {backend_id!r} is not installed on this machine",
            }
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            if rom is None:
                return {
                    "success": False,
                    "reason": "not_found",
                    "message": f"ROM {rom_id} is not tracked",
                }
            if rom.platform_slug == "win":
                return self._windows_unsupported(rom_id)
            system = self._resolve_system(rom.platform_slug)
            invocation = label_to_invocation(backend.get_emulator_options(system)["options"], label)
            if invocation is None:
                # Hard-fail BEFORE any write — mirrors set_game_core's discipline,
                # against backend_id's OWN catalogue rather than the active one.
                return {
                    "success": False,
                    "reason": "core_unavailable",
                    "message": f"Emulator '{label}' is not available for {rom.platform_slug} on {backend_id}",
                }
            rom.pin_cross_backend_emulator(backend_id, label)
            # Mutually exclusive with the active backend's own emulator_overrides
            # pin (avoids "which one wins" ambiguity) — clear whichever backend is
            # CURRENTLY active, leaving any OTHER backend's independent pin alone.
            active_backend_id = self._active_backend_id()
            rom.clear_emulator_override(active_backend_id)
            uow.roms.set_cross_backend_pin(rom_id, rom.cross_backend_pin)
            uow.roms.set_emulator_override(rom_id, active_backend_id, rom.emulator_override_for(active_backend_id))
            install = uow.rom_installs.get(rom_id)
        launch_options, app_id = self._launch_options_for(rom, install, None)
        return {"success": True, "launch_options": launch_options, "app_id": app_id}

    async def clear_game_cross_backend_pin(self, rom_id: int) -> dict[str, Any]:
        """Clear ``rom_id``'s cross-backend pin (Follow default / Reset).

        Drops the pin so the ROM falls through to its normal active-backend
        precedence (per-game override → per-platform core → default), then
        returns the recomputed ``launch_options``/``app_id`` for an
        installed+bound ROM, mirroring :meth:`clear_game_core`'s shape exactly.
        """
        return await self._loop.run_in_executor(None, self._clear_game_cross_backend_pin_io, rom_id)

    def _clear_game_cross_backend_pin_io(self, rom_id: int) -> dict[str, Any]:
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            if rom is None:
                return {
                    "success": False,
                    "reason": "not_found",
                    "message": f"ROM {rom_id} is not tracked",
                }
            rom.clear_cross_backend_emulator()
            uow.roms.set_cross_backend_pin(rom_id, rom.cross_backend_pin)
            install = uow.rom_installs.get(rom_id)
        if rom.shortcut_app_id is None or install is None:
            return {"success": True, "launch_options": None, "app_id": None}
        emulator = self._active_core.active_emulator_for_rom(rom_id)
        launch_options, app_id = self._launch_options_for(rom, install, emulator)
        return {"success": True, "launch_options": launch_options, "app_id": app_id}

    async def clear_game_core(self, rom_id: int) -> dict[str, Any]:
        """Clear the per-game override for ``rom_id`` (Follow default / Reset).

        Drops the pin (stores SQL NULL) so the ROM follows the per-platform/system
        default, then returns the recomputed ``launch_options`` and ``app_id`` for
        an installed+bound ROM so the frontend confirm-sets the now-default launch
        on the live shortcut. Because the resolved default may itself be a
        per-platform core, the recomputed command bakes the ROM's FULL active core
        (the ``-e`` override form, or the plain launch when the platform resolves
        to ``(None, None)``) — never an unconditional plain launch. Clearing
        needs no label to resolve, so it is otherwise always valid — except a
        native-Windows ROM (``platform_slug == "win"``, ADR-0030), which has no
        emulator-override concept and is refused with the canonical failure
        shape before any write. When the ROM is unknown the same canonical
        failure shape is returned; when it is uninstalled or unbound the NULL
        still lands and ``launch_options``/``app_id`` are ``None``.

        This is the picker's ONE clear-to-default action (no separate Reset
        item), so it also clears any cross-backend pin on ``rom_id`` — leaving
        it in place would keep winning over the just-restored default at every
        bake site, since a cross-backend pin is checked first.
        """
        return await self._loop.run_in_executor(None, self._clear_game_core_io, rom_id)

    def _clear_game_core_io(self, rom_id: int) -> dict[str, Any]:
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            if rom is None:
                return {
                    "success": False,
                    "reason": "not_found",
                    "message": f"ROM {rom_id} is not tracked",
                }
            # A native-Windows ROM has no emulator/core concept to clear
            # (ADR-0030) — same guard as _set_game_core_io, so a stray clear can
            # never re-bake the shortcut through the RetroDECK/active_core path
            # (which would discard the Proton-wrapped exe launch for the raw
            # install file_path).
            if rom.platform_slug == "win":
                return self._windows_unsupported(rom_id)
            backend_id = self._active_backend_id()
            rom.clear_emulator_override(backend_id)
            # "Use System Override" is the one clear-to-default action the picker
            # offers (no separate Reset item) — it must drop BOTH deviation types,
            # or a cross-backend pin would survive and keep winning at bake time
            # even though the user just asked to follow the default.
            rom.clear_cross_backend_emulator()
            uow.roms.set_emulator_override(rom_id, backend_id, rom.emulator_override_for(backend_id))
            uow.roms.set_cross_backend_pin(rom_id, rom.cross_backend_pin)
            install = uow.rom_installs.get(rom_id)
        # Cleared pin → follow the per-platform/system default. The write UoW has
        # committed, so the resolver's own UoW now reads the landed NULL and
        # returns the POST-clear core — a per-platform core (or standalone system
        # default) still bakes its -e form. Resolving here (outside the closed
        # UoW) is also what keeps active_emulator_for_rom's BEGIN IMMEDIATE from
        # blocking on our write lock (#1047 / #1134). Skip the resolve entirely
        # when there is no live shortcut to update.
        if rom.shortcut_app_id is None or install is None:
            return {"success": True, "launch_options": None, "app_id": None}
        emulator = self._active_core.active_emulator_for_rom(rom_id)
        launch_options, app_id = self._launch_options_for(rom, install, emulator)
        return {"success": True, "launch_options": launch_options, "app_id": app_id}

    def _launch_options_for(
        self,
        rom: Rom,
        install: RomInstall | None,
        emulator: EmulatorInvocation | None,
    ) -> tuple[str | None, int | None]:
        """Bake the launch command for *rom* with *emulator*, or ``(None, None)``.

        Takes the ROM's ``RomInstall`` snapshot directly (``None`` when
        uninstalled) so the bake runs with no open Unit of Work — the callers
        snapshot the install inside their write UoW and close it before baking,
        since the shared active-core resolver opens its own UoW and the
        per-connection ``BEGIN IMMEDIATE`` write lock is not re-entrant.

        An installed (``RomInstall`` with a ``file_path``) **and** bound
        (``shortcut_app_id`` set) ROM gets the full launch command — the ``-e``
        form when *emulator* is set (libretro core or standalone), the plain form
        when it is ``None`` — over the disc-resolved bake path (the ROM's persisted
        ``selected_disc`` for a multi-disc ROM, its ``file_path`` unchanged for a
        single-disc ROM), paired with its Steam ``app_id``. An uninstalled or
        unbound ROM has no live shortcut to update, so both are ``None`` and the
        stored pin/clear applies on the next download/sync.
        """
        app_id = rom.shortcut_app_id
        if app_id is None or install is None:
            return (None, None)
        # Fold the ROM's persisted disc pick over the install so a per-game core
        # pin/clear re-bakes the pinned disc, not disc 1 / the m3u. A single-disc
        # ROM resolves to its own file_path.
        bake_path = self._disc_resolver.resolve_for_install(install, rom.selected_disc)
        rom_dict = {"id": rom.rom_id, "platform_slug": rom.platform_slug}
        cross_rendered = self._active_core.cross_backend_render_for_rom(rom.rom_id, rom_dict, bake_path)
        if cross_rendered is not None:
            return (cross_rendered, app_id)
        invocation = self._launch_renderer.resolve_invocation(rom_dict, emulator)
        return (self._launch_renderer.build_launch_options(invocation, bake_path), app_id)

    def _read_rom(self, rom_id: int) -> Rom | None:
        with self._uow_factory() as uow:
            return uow.roms.get(rom_id)

    def _windows_unsupported(self, rom_id: int) -> dict[str, Any]:
        """Canonical refusal shape for a native-Windows ROM's core pin/clear (ADR-0030)."""
        return {
            "success": False,
            "reason": ErrorCode.UNSUPPORTED.value,
            "message": f"ROM {rom_id} is a native-Windows ROM — use the executable picker instead",
        }
