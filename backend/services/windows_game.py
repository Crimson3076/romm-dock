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
        True, "executables": [{"filename"}, ...], "selected": <roms.selected_exe
        | None>}``. ``selected`` is down-validated: a stale pin whose file is no
        longer enumerated reports as ``None`` so the badge matches what the bake
        launches (the bake degrades the same stale pin to the default,
        mirroring the disc picker). Read-only over the local filesystem; the
        no-picker answers are the normal response, not failures.
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
        if not executables:
            return {"has_executables": False}
        if selected is not None and selected not in {exe.filename for exe in executables}:
            selected = None
        return {
            "has_executables": True,
            "executables": [{"filename": exe.filename} for exe in executables],
            "selected": selected,
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
