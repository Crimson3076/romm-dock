"""EmuDeck launcher backend — the second concrete ``LauncherBackend`` (issue #918, Wave B).

Installation detection and ROM/BIOS/save roots come from `emu-atlas
<https://github.com/danielcopper/emu-atlas>`_'s ``EmuDeck`` installation
handle (``atlas.detect(home)``) — the library this project has already
committed to for exactly this knowledge (epic #1735), so this backend does not
re-parse ``settings.sh`` or ``retroarch.cfg`` itself.

Launch-command rendering is the one piece atlas deliberately does not own
(it answers *where things live*, not *how to invoke them* — that is this
seam). The ROM's system's ES-DE catalogue entry is read through the same
atlas handle (``installation.emulators_for(system)``) and classified for
bakeability with the plugin's existing, frontend-agnostic ES-DE command rules
(``domain.emulator_commands`` — the same kernel RetroDECK's own
``adapters.es_de_config.CoreResolver`` uses; ES-DE ``<command>`` syntax does
not change across frontends). The classified command's ``%EMULATOR_<NAME>%``
and ``%CORE_RETROARCH%`` placeholders are then resolved to real host paths via
EmuDeck's own ``es_find_rules.xml`` (:class:`EmuDeckFindRulesAdapter`) — which
is how EmuDeck itself wires those tokens onto its
``Emulation/tools/launchers/<name>.sh`` scripts, so EmuDeck stays responsible
for choosing between an AppImage, a Flatpak, a native binary, or a Proton
executable (each script's own probe), never this plugin.

No ``eval``, no unsafe shell-string construction: the resolved invocation is
plain text composed the same way ``domain.shortcut_data.build_launch_options``
already composes RetroDECK's, and the ROM path is appended by that same
function with its existing escaping.
"""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING, Any

from _vendor import atlas

from adapters.emudeck_find_rules import EmuDeckFindRulesAdapter
from domain.emulator_commands import classify_command, select_default_option
from domain.launcher_backend import EMUDECK_BACKEND_ID, BackendValidation, DetectedInstallation
from domain.shortcut_data import build_launch_options

if TYPE_CHECKING:
    import logging
    from collections.abc import Callable

    from domain.emulator_commands import EmulatorOption
    from domain.shortcut_data import EmulatorInvocation

# resolve_system is structurally the SystemResolver Protocol
# (services/protocols/paths.py) — not imported by name: adapters may not
# import services.protocols (import-linter "Adapters must not import
# services"), so it is typed as Callable here instead.

# es_find_rules.xml (and es_systems.xml, which atlas itself reads) live at a
# fixed location under an EmuDeck arrangement's home — where EmuDeck's own
# ES-DE installer deploys them (emuDeckESDE.sh), not something atlas exposes
# as a public path getter (its catalogue answers read the file; they do not
# hand back where it lives).
_FIND_RULES_SUFFIX = os.path.join("ES-DE", "custom_systems", "es_find_rules.xml")

_DISPLAY_NAME = "EmuDeck"

# The one %EMULATOR_<NAME>% (or none, for a command with no binary token) at
# the front of a command — mirrors adapters/es_de_config.py's own
# `_EMULATOR_TOKEN_RE`, kept as a private, adapter-local pure helper the same
# way that one is (not promoted to domain/: it is ES-DE find-rule vocabulary
# specific to resolving a placeholder, not shared compute).
_EMULATOR_TOKEN_RE = re.compile(r"%EMULATOR_([A-Z0-9_-]+)%")
_CORE_RETROARCH_TOKEN = "%CORE_RETROARCH%"
_ROM_TOKEN = "%ROM%"

# A command whose ROM argument carries a Windows drive-letter prefix
# (`z:%ROM%` / `Z:%ROM%`) is routed through Proton by an EmuDeck launcher
# script (cemu.sh -w, xenia.sh, bigpemu.sh's Proton form). Rewriting a host
# path into that form correctly needs Proton/Wine path mapping this backend
# does not implement — baking it verbatim would hand the emulator a bogus
# "z:/home/deck/..." path. Recognized and refused rather than silently wrong.
_PROTON_ROM_SUFFIX_RE = re.compile(r"[zZ]:%ROM%$")


class EmuDeckLauncherBackend:
    """EmuDeck bound to one detected installation. Implements ``LauncherBackend``."""

    backend_id = EMUDECK_BACKEND_ID

    def __init__(
        self,
        *,
        installation: atlas.EmuDeck,
        installation_id: str,
        find_rules: EmuDeckFindRulesAdapter,
        resolve_system: Callable[[str, str | None], str],
        logger: logging.Logger,
    ) -> None:
        self._installation = installation
        self.installation_id = installation_id
        self._find_rules = find_rules
        self._resolve_system = resolve_system
        self._logger = logger

    # -- LauncherBackend: paths ------------------------------------------------

    def roms_path(self) -> str:
        return self._installation.roms_dir() or ""

    def bios_path(self) -> str:
        return self._installation.bios_dir() or ""

    def saves_path(self) -> str:
        return self._installation.saves_root() or ""

    def states_path(self) -> str:
        """EmuDeck has no flat savestate root — atlas resolves it per-content, not as a directory."""
        return ""

    def validate(self) -> BackendValidation:
        """EmuDeck is switchable only when its own health finding is clean.

        Delegates to atlas's own ``health()`` finding rather than re-deriving
        it: a marker present-but-unreadable ``settings.sh`` is exactly the
        state atlas's detection already flags, and re-implementing that check
        here would risk disagreeing with it.
        """
        try:
            health = self._installation.health()
        except Exception as exc:  # atlas health reads are I/O; degrade, never raise
            self._logger.warning("emudeck_launcher_backend: health probe failed: %s", exc)
            return BackendValidation(ok=False, reason="health_probe_failed", message=str(exc))
        if health.issues:
            reasons = ", ".join(issue.code for issue in health.issues)
            return BackendValidation(
                ok=False,
                reason="unhealthy",
                message=f"EmuDeck installation reports: {reasons}",
            )
        return BackendValidation(ok=True)

    # -- LauncherBackend: rendering --------------------------------------------

    def resolve_invocation(self, rom: dict[str, Any], emulator: EmulatorInvocation | None) -> str:
        """Render *emulator* into a directly-executable command prefix.

        Ignores *emulator* (the plugin's already-resolved libretro/standalone
        pick) in favor of re-deriving the same ES-DE catalogue entry through
        atlas for this backend's system — mirroring
        ``domain.shortcut_data.resolve_emulator_invocation``'s own contract,
        where *rom* is "the per-emulator-branch seam" reserved for future use
        and the resolved invocation is a function of the ROM's system.
        Returns ``""`` — this backend's "no launch target" signal, handled by
        :meth:`build_launch_options` — when nothing renders safely (a stale
        pin, a Proton-routed command, an unbakeable or unresolvable entry).
        """
        system = self._resolve_system(rom.get("platform_slug", ""), rom.get("platform_fs_slug"))
        option = self._select_option(system, emulator)
        rendered = self._render_option(option) if option is not None else None
        return rendered or ""

    def build_launch_options(self, invocation: str, path: str) -> str:
        """Compose the launch command, or ``""`` when nothing resolvable was found.

        Unlike RetroDECK — which always has a plain ``flatpak run`` fallback
        ``run_game.sh`` itself can resolve an emulator for — EmuDeck has no
        single binary that accepts a bare ROM path, so an empty *invocation*
        from :meth:`resolve_invocation` means "no launch target", the same
        established empty-``launch_options`` state
        ``domain.shortcut_data.build_launch_options`` already documents for an
        uninstalled or unlaunchable ROM (never composed into a broken
        partial command).
        """
        if not invocation:
            return ""
        return build_launch_options(invocation, path)

    def _select_option(self, system: str, emulator: EmulatorInvocation | None) -> EmulatorOption | None:
        """Classify this system's catalogue entries and pick the pinned or default one.

        Reuses the plugin's own bakeability rules (``domain.emulator_commands``)
        against atlas's catalogue text — the same ES-DE ``<command>`` grammar
        RetroDECK's es_systems.xml uses. A per-game/per-platform pin
        (``emulator.label``) is matched by label first, exactly like
        ``label_to_invocation`` does for RetroDECK; an unmatched or
        unresolvable pin falls through to the system default.

        Does not run RetroDECK's ``not_installed`` existence probe
        (``downgrade_if_not_installed``) — that probe walks RetroDECK's
        sandboxed ``es_find_rules.xml`` staticpaths, which do not apply to
        EmuDeck's unsandboxed layout. A bakeable EmuDeck entry whose emulator
        the user has not actually installed is a known v1 gap: it bakes, and
        the launcher script itself reports the failure (each one already
        checks for its own binary before running, per
        ``Emulation/tools/launchers/*.sh``) rather than the picker disabling
        it up front.
        """
        answer = self._installation.emulators_for(system)
        options = [classify_command(entry.label, entry.command) for entry in answer.entries]
        if emulator is not None and emulator.label:
            pinned = next((o for o in options if o.label == emulator.label and o.status == "bakeable"), None)
            if pinned is not None:
                return pinned
        default = select_default_option(options)
        if default is None:
            caveats = ", ".join(caveat.code for caveat in answer.caveats) or "none"
            self._logger.warning(
                "emudeck_launcher_backend: no bakeable option for system %r (%d catalogue entries, "
                "statuses: %s, caveats: %s)",
                system,
                len(options),
                ", ".join(o.status for o in options) or "none",
                caveats,
            )
        return default

    def _render_option(self, option: EmulatorOption) -> str | None:
        command = option.command
        if _PROTON_ROM_SUFFIX_RE.search(command):
            self._logger.info(
                "emudeck_launcher_backend: %r is Proton-routed, not supported yet — falling through", option.label
            )
            return None
        if not command.endswith(_ROM_TOKEN):
            self._logger.warning(
                "emudeck_launcher_backend: %r does not end with %%ROM%%, refusing to bake: %r",
                option.label,
                command,
            )
            return None
        body = command[: -len(_ROM_TOKEN)].rstrip()
        if _CORE_RETROARCH_TOKEN in body:
            cores_dir = self._find_rules.resolve_core_dir("RETROARCH")
            if cores_dir is None:
                self._logger.warning("emudeck_launcher_backend: %%CORE_RETROARCH%% did not resolve for %r", command)
                return None
            body = body.replace(_CORE_RETROARCH_TOKEN, cores_dir)
        token_match = _EMULATOR_TOKEN_RE.search(body)
        if token_match:
            resolved = self._find_rules.resolve_emulator(token_match.group(1))
            if resolved is None:
                self._logger.warning(
                    "emudeck_launcher_backend: %s did not resolve for %r", token_match.group(0), command
                )
                return None
            body = body.replace(token_match.group(0), resolved)
        if "%" in body:
            # An unresolved placeholder outside the two handled above —
            # never bake a command that still carries one.
            self._logger.warning("emudeck_launcher_backend: unresolved placeholder in %r", body)
            return None
        return body


class EmuDeckLauncherBackendFactory:
    """Detects EmuDeck arrangements (via emu-atlas) and binds one.

    Real detection today probes exactly one home — the same resolved user
    home every other adapter uses (``decky.DECKY_USER_HOME``, threaded in as
    *user_home*; never a hardcoded username or a Bazzite-specific
    ``/home``-vs-``/var/home`` guess). ``detect_installations`` still returns a
    **list** — the extensibility point the "let the user choose" requirement
    needs — because ``atlas.detect`` itself is home-scoped and a future
    caller (a multi-user setup, a second mount point) can hand this factory
    more than one home without changing its shape.
    """

    backend_id = EMUDECK_BACKEND_ID
    display_name = _DISPLAY_NAME

    def __init__(
        self, *, user_home: str, resolve_system: Callable[[str, str | None], str], logger: logging.Logger
    ) -> None:
        self._user_home = user_home
        self._resolve_system = resolve_system
        self._logger = logger

    def detect_installations(self) -> list[DetectedInstallation]:
        emudeck = self._detect_emudeck(self._user_home)
        return [self._describe(self._user_home, emudeck)] if emudeck is not None else []

    def bind(self, installation_id: str) -> EmuDeckLauncherBackend | None:
        if installation_id != self._installation_id(self._user_home):
            return None
        emudeck = self._detect_emudeck(self._user_home)
        if emudeck is None:
            return None
        find_rules = EmuDeckFindRulesAdapter(
            find_rules_path=os.path.join(self._user_home, _FIND_RULES_SUFFIX),
            user_home=self._user_home,
            logger=self._logger,
        )
        return EmuDeckLauncherBackend(
            installation=emudeck,
            installation_id=installation_id,
            find_rules=find_rules,
            resolve_system=self._resolve_system,
            logger=self._logger,
        )

    def _detect_emudeck(self, home: str) -> atlas.EmuDeck | None:
        try:
            installations = atlas.detect(home)
        except Exception as exc:  # atlas.detect reads the filesystem; never propagate
            self._logger.warning("emudeck_launcher_backend: detection failed for %s: %s", home, exc)
            return None
        return next((inst for inst in installations if isinstance(inst, atlas.EmuDeck)), None)

    def _describe(self, home: str, emudeck: atlas.EmuDeck) -> DetectedInstallation:
        try:
            health = emudeck.health()
            healthy = not health.issues
            detail = "ok" if healthy else ", ".join(issue.code for issue in health.issues)
        except Exception as exc:  # health() reads config files; degrade, never raise
            healthy = False
            detail = str(exc)
        return DetectedInstallation(
            installation_id=self._installation_id(home),
            display_name=_DISPLAY_NAME,
            home=home,
            healthy=healthy,
            detail=detail,
        )

    @staticmethod
    def _installation_id(home: str) -> str:
        return f"{EMUDECK_BACKEND_ID}:{home}"
