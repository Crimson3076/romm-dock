"""Launcher-backend Protocols — issue #918's seam.

A launcher backend answers, per (system, emulator, rom): the launch
invocation and the roms/bios/saves roots. RetroDECK is the first concrete
implementation (a behavior-preserving wrapper over the existing
``domain.shortcut_data``/``adapters.retrodeck_paths`` logic); EmuDeck is the
second. Call sites depend on :class:`LauncherBackend`, never on a concrete
adapter or the hardcoded ``RETRODECK_INVOCATION`` constant.

Two Protocols because detection and rendering answer different questions at
different times: :class:`LauncherBackendFactory` is asked once per QAM open
("what's installed, and what could I bind to?"); :class:`LauncherBackend` is
the bound instance every bake site renders through. A backend with exactly
one possible installation (RetroDECK) still implements both — its factory's
``detect_installations`` returns at most one entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

from services.protocols.paths import CoreInfoProvider

if TYPE_CHECKING:
    from domain.launcher_backend import BackendValidation, DetectedInstallation
    from domain.shortcut_data import EmulatorInvocation


class LauncherBackend(CoreInfoProvider, Protocol):
    """One launcher, bound to a concrete installation.

    ``resolve_invocation``/``build_launch_options`` mirror
    ``domain.shortcut_data``'s free functions of the same name — a backend
    renders the CHOSEN :class:`~domain.shortcut_data.EmulatorInvocation`
    (which command WINS stays :class:`services.active_core_resolver.
    ActiveCoreResolver`'s job, unchanged by which backend is active) into an
    OS-executable command line. The path getters use the same names as
    :class:`RetroDeckPaths` on purpose — same shape, same best-effort/never-raise
    contract, so a backend is a drop-in behind :class:`LauncherPaths` wherever a
    service used to read RetroDECK's paths directly. ``states_path`` may return
    ``""`` where a backend has no flat savestate root to offer (EmuDeck's
    savestate location is per-core/per-content, not a single directory the way
    saves/roms/bios are) — callers already treat an empty path as "nothing
    here", the same degradation an unresolved RetroDECK root uses.

    Extends :class:`CoreInfoProvider` so ``ActiveCoreResolver`` decides WHICH
    invocation wins from THIS backend's own catalogue (its own
    ``get_emulator_options``/``get_default_emulator``/``get_active_core``), not
    always RetroDECK's — the per-game/per-platform picker menu now follows the
    active backend exactly like rendering and file placement already do.
    """

    backend_id: str
    installation_id: str

    def resolve_invocation(self, rom: dict[str, Any], emulator: EmulatorInvocation | None) -> str: ...

    def build_launch_options(self, invocation: str, path: str) -> str: ...

    def roms_path(self) -> str: ...

    def bios_path(self) -> str: ...

    def saves_path(self) -> str: ...

    def states_path(self) -> str: ...

    def validate(self) -> BackendValidation: ...


class LaunchCommandRenderer(Protocol):
    """The live-active backend's rendering half, injected at every bake site.

    A narrower seam than :class:`LauncherBackend` on purpose: a bake site
    (``DiscService``, ``RelaunchOptionsResolver``, ``CoreService``,
    ``RomInstallRecorder``, the sync orchestrator) needs only "render this
    invocation right now," never the backend's paths or its own detection
    surface. ``LauncherBackendService`` implements this by delegating to
    whichever :class:`LauncherBackend` is currently active, so switching the
    launcher backend takes effect at every bake site's very next call — no
    re-wiring, no stale reference to a backend that was replaced.
    """

    def resolve_invocation(self, rom: dict[str, Any], emulator: EmulatorInvocation | None) -> str: ...

    def build_launch_options(self, invocation: str, path: str) -> str: ...


class LauncherPaths(Protocol):
    """The live-active backend's ROM/BIOS/save/savestate roots, injected wherever
    a service used to read ``RetroDeckPaths`` directly for file placement.

    ``LauncherBackendService`` implements this the same way it implements
    :class:`LaunchCommandRenderer` — delegating to whichever
    :class:`LauncherBackend` is currently bound — so switching backends moves
    where downloads, BIOS files, and saves land on the very next call, with no
    re-wiring. Deliberately narrower than :class:`RetroDeckPaths`: it omits
    ``retrodeck_home``/``config_path``/``config_health``, which are RetroDECK's
    own migration-detection and health-banner vocabulary with no backend-
    neutral equivalent — ``MigrationService`` and ``StartupHealingService``
    keep depending on the concrete ``RetroDeckPaths`` for those, unaffected by
    which backend is active (RetroDECK-home migration is a RetroDECK concept
    regardless of which backend currently launches games).
    """

    def roms_path(self) -> str: ...

    def bios_path(self) -> str: ...

    def saves_path(self) -> str: ...

    def states_path(self) -> str: ...


class LauncherBackendFactory(Protocol):
    """Detects installations of one launcher and binds a backend to one of them.

    Held by the :class:`~services.launcher_backend.LauncherBackendRegistry`
    — the extensibility seam a third backend registers against without any
    call-site change. ``bind`` returns ``None`` for an ``installation_id`` this
    factory's own last :meth:`detect_installations` did not report, so a stale
    or forged id from the frontend never binds a backend that was never
    detected.
    """

    backend_id: str
    display_name: str

    def detect_installations(self) -> list[DetectedInstallation]: ...

    def bind(self, installation_id: str) -> LauncherBackend | None: ...
