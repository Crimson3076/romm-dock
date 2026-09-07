"""WindowsGameService — the native-Windows launch-target picker's read + write callables.

Owns the two frontend callables behind the exe picker: ``get_windows_executables``
reports whether a ROM is a native-Windows install and, if so, the launchable
target candidates (a ``.exe`` run through Proton, or a bundled ``.sh`` run
natively — see ``domain.windows_launch.WindowsExecutable.kind``) plus the
current selection; ``select_executable`` pins one (or clears the pin back to
the default) and returns the freshly-baked launch command for the frontend to
confirm-set on the live Steam shortcut.

The exe pick lands on the ``Rom`` aggregate via the Unit-of-Work (the pin-only
``set_selected_exe`` write path, never the sync UPSERT), mirroring
:class:`services.disc.DiscService`. Enumeration and launch resolution both go
through the shared :class:`services.windows_launch_resolver.WindowsLaunchResolver`
seam so the list the picker shows is the list the bake resolves over, and the
baked launch command never diverges from the picker's selection.

Also owns ``set_compat_tool_override``/``clear_compat_tool_override`` (ADR-0032)
— persistence only for the per-game Steam compat-tool override that fixes a
native-Windows launch getting force-wrapped in Proton by Steam's own "Enable
Steam Play for all other titles" setting. This service never calls
``SteamClient.Apps.SpecifyCompatTool`` itself — that call is frontend-only
(``SteamClient`` is a browser-context global unreachable from Python) and is
made by the frontend, both when the user picks an override explicitly and
automatically the first time a ROM's launch target resolves to
``kind == "native"``. This backend half exists purely so that decision can be
remembered and RE-APPLIED whenever the ROM's Steam shortcut is later rebound to
a new appId (``SpecifyCompatTool`` is scoped to an appId, which is assigned by
Steam and can change over a ROM's lifetime — see CLAUDE.md's "shortcut appId is
assigned, not derived" trap). ``kind`` and the current override are surfaced
through ``get_windows_executables`` so the frontend can act on both without a
second round trip.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from lib.list_result import ErrorCode

if TYPE_CHECKING:
    import asyncio
    import logging

    from services.protocols import UnitOfWorkFactory, WindowsResolver


@dataclass(frozen=True)
class WindowsGameServiceConfig:
    """Frozen wiring bundle handed to ``WindowsGameService.__init__``.

    Carries the runtime infrastructure (event loop, logger), the SQLite
    Unit-of-Work factory (to read the ROM + its install and write the exe pin),
    and the shared per-ROM ``windows_resolver`` (enumeration + launch
    resolution).
    """

    loop: asyncio.AbstractEventLoop
    logger: logging.Logger
    uow_factory: UnitOfWorkFactory
    windows_resolver: WindowsResolver


class WindowsGameService:
    """Exe-picker reads (``get_windows_executables``) and writes (``select_executable``)."""

    def __init__(self, *, config: WindowsGameServiceConfig) -> None:
        self._loop = config.loop
        self._logger = config.logger
        self._uow_factory = config.uow_factory
        self._windows_resolver = config.windows_resolver

    async def get_windows_executables(self, rom_id: int) -> dict[str, Any]:
        """Report the exe picker's state for ``rom_id``.

        Returns ``{"has_executables": False}`` when the ROM is unknown, not
        installed, is not a native-Windows ROM (raw ``platform_slug != "win"``),
        or its install enumerates no launchable target at all — the frontend renders no
        picker in any of those cases. Otherwise returns ``{"has_executables":
        True, "executables": [{"filename", "kind"}, ...], "selected":
        <roms.selected_exe | None>, "compat_tool_override": <roms.compat_tool_override
        | None>}``. ``selected`` is down-validated: a stale pin whose file is no
        longer enumerated reports as ``None`` so the badge matches what the bake
        launches (the bake degrades the same stale pin to the default,
        mirroring the disc picker). ``kind`` (``"exe"`` | ``"native"``) and
        ``compat_tool_override`` are surfaced verbatim so the frontend can
        decide whether to auto-apply a native compat-tool override without a
        second callable round trip (ADR-0032) — this service never makes that
        decision or the ``SteamClient`` call itself. Read-only over the local
        filesystem; the no-picker answers are the normal response, not
        failures.
        """
        return await self._loop.run_in_executor(None, self._get_windows_executables_io, rom_id)

    def _get_windows_executables_io(self, rom_id: int) -> dict[str, Any]:
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            install = uow.rom_installs.get(rom_id)
            if rom is None or install is None or rom.platform_slug != "win":
                return {"has_executables": False}
            executables = self._windows_resolver.enumerate_executables(install)
            selected = rom.selected_exe
            compat_tool_override = rom.compat_tool_override
        if not executables:
            return {"has_executables": False}
        if selected is not None and selected not in {exe.filename for exe in executables}:
            selected = None
        return {
            "has_executables": True,
            "executables": [{"filename": exe.filename, "kind": exe.kind} for exe in executables],
            "selected": selected,
            "compat_tool_override": compat_tool_override,
        }

    async def select_executable(self, rom_id: int, filename: str | None) -> dict[str, Any]:
        """Pin (or clear with ``None``) the launch-target selection for ``rom_id``.

        ``filename is None`` clears the pin so the ROM follows the default (the
        first enumerated target). A non-``None`` *filename* must name one of
        the enumerated targets — an unknown filename is a hard
        ``not_found`` failure and **nothing is written**. The ROM must be an
        installed native-Windows ROM: an unknown/uninstalled ROM or a
        non-Windows ROM returns the canonical failure shape (``not_installed`` /
        ``unsupported``) and writes nothing. On success the pick is persisted
        via the pin-only ``set_selected_exe`` write path and the response
        carries the freshly-baked ``launch_options`` for the frontend to
        confirm-set on the live Steam shortcut, plus the now-effective
        ``selected`` value.
        """
        return await self._loop.run_in_executor(None, self._select_executable_io, rom_id, filename)

    def _select_executable_io(self, rom_id: int, filename: str | None) -> dict[str, Any]:
        # The validate + write run inside one UoW; the bake — which calls the
        # shared ``windows_resolver`` (a real Proton filesystem probe) — runs
        # AFTER this UoW closes, mirroring DiscService's non-nesting rule.
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            install = uow.rom_installs.get(rom_id)
            if rom is None or install is None:
                return {
                    "success": False,
                    "reason": "not_installed",
                    "message": f"ROM {rom_id} is not installed as a native-Windows game",
                }
            if rom.platform_slug != "win":
                return {
                    "success": False,
                    "reason": ErrorCode.UNSUPPORTED.value,
                    "message": f"ROM {rom_id} is not a native-Windows ROM",
                }
            executables = self._windows_resolver.enumerate_executables(install)
            if filename is not None and filename not in {exe.filename for exe in executables}:
                # Hard-fail BEFORE any write — never pin an exe no enumeration
                # can resolve to a launchable path.
                return {
                    "success": False,
                    "reason": ErrorCode.NOT_FOUND.value,
                    "message": f"'{filename}' is not an executable of ROM {rom_id}",
                }
            if filename is None:
                rom.clear_selected_exe()
            else:
                rom.pin_selected_exe(filename)
            uow.roms.set_selected_exe(rom_id, rom.selected_exe)
            selected = rom.selected_exe
        launch_options = self._windows_resolver.resolve_launch_options(install, selected)
        return {"success": True, "launch_options": launch_options, "selected": selected}

    async def set_compat_tool_override(self, rom_id: int, value: str) -> dict[str, Any]:
        """Pin the per-game Steam compat-tool override for ``rom_id`` to *value* (ADR-0032).

        *value* may legitimately be ``""`` — that is "force no compat tool"
        (native launch), a real held state, NOT a request to clear the
        override; clearing it entirely is a separate call
        (:meth:`clear_compat_tool_override`). *value* is opaque here — never
        validated or interpreted against any known Proton build, since the
        backend has no knowledge of what compat tools exist on the user's
        machine. Same not-installed/unsupported guards as
        :meth:`select_executable`. This setting never touches the baked
        ``launch_options`` — the response carries no such key — because
        applying it is a separate Steam-side call
        (``SteamClient.Apps.SpecifyCompatTool``) the frontend makes directly,
        never something this backend can bake into the shortcut's command.
        """
        return await self._loop.run_in_executor(None, self._set_compat_tool_override_io, rom_id, value)

    def _set_compat_tool_override_io(self, rom_id: int, value: str) -> dict[str, Any]:
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            install = uow.rom_installs.get(rom_id)
            if rom is None or install is None:
                return {
                    "success": False,
                    "reason": "not_installed",
                    "message": f"ROM {rom_id} is not installed as a native-Windows game",
                }
            if rom.platform_slug != "win":
                return {
                    "success": False,
                    "reason": ErrorCode.UNSUPPORTED.value,
                    "message": f"ROM {rom_id} is not a native-Windows ROM",
                }
            rom.pin_compat_tool_override(value)
            uow.roms.set_compat_tool_override(rom_id, rom.compat_tool_override)
        return {"success": True}

    async def clear_compat_tool_override(self, rom_id: int) -> dict[str, Any]:
        """Drop the per-game Steam compat-tool override for ``rom_id`` entirely (ADR-0032).

        Distinct from pinning ``""`` (which forces no compat tool, a held
        state) — this reverts to ``None`` ("no override"; the plugin no longer
        touches this ROM's compat-tool setting). Same not-installed/unsupported
        guards as :meth:`select_executable`; no ``launch_options`` in the
        response, for the same reason as :meth:`set_compat_tool_override`.
        """
        return await self._loop.run_in_executor(None, self._clear_compat_tool_override_io, rom_id)

    def _clear_compat_tool_override_io(self, rom_id: int) -> dict[str, Any]:
        with self._uow_factory() as uow:
            rom = uow.roms.get(rom_id)
            install = uow.rom_installs.get(rom_id)
            if rom is None or install is None:
                return {
                    "success": False,
                    "reason": "not_installed",
                    "message": f"ROM {rom_id} is not installed as a native-Windows game",
                }
            if rom.platform_slug != "win":
                return {
                    "success": False,
                    "reason": ErrorCode.UNSUPPORTED.value,
                    "message": f"ROM {rom_id} is not a native-Windows ROM",
                }
            rom.clear_compat_tool_override()
            uow.roms.set_compat_tool_override(rom_id, rom.compat_tool_override)
        return {"success": True}
