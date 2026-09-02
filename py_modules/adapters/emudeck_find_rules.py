"""EmuDeck's ``es_find_rules.xml`` — resolves ES-DE ``%EMULATOR_<NAME>%`` /
``%CORE_RETROARCH%`` placeholders to real host paths.

RetroDECK's own find-rules reader (``adapters/es_de_config.py``) maps sandboxed
``/app`` and ``/var/{data,config}`` prefixes onto the flatpak's host trees,
because RetroDECK runs ES-DE *inside* its sandbox. EmuDeck runs ES-DE
unsandboxed — every ``staticpath``/``corepath`` entry EmuDeck ships
(``.../ES-DE/custom_systems/es_find_rules.xml``) is already a plain host path
(a ``tools/launchers/<name>.sh`` script, or the bare RetroArch flatpak's cores
directory under ``~/.var/app/org.libretro.RetroArch``), so no sandbox-prefix
mapping applies here — only ``~`` expansion against the resolved user home
(never a hardcoded username or a Bazzite-specific ``/home`` vs ``/var/home``
assumption; the caller passes the same ``user_home`` every other adapter
resolves against, e.g. Decky's own ``DECKY_USER_HOME``).
"""

from __future__ import annotations

import glob
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import logging

# The two rule kinds this adapter reads: an <emulator> block's binary
# location, and a <core name="RETROARCH">'s cores directory.
_STATICPATH = "staticpath"
_COREPATH = "corepath"


class EmuDeckFindRulesAdapter:
    """Read-only accessor for one ``es_find_rules.xml`` file, mtime-cached."""

    def __init__(self, *, find_rules_path: str, user_home: str, logger: logging.Logger) -> None:
        self._find_rules_path = find_rules_path
        self._user_home = user_home
        self._logger = logger
        self._emulators_cache: dict[str, tuple[str, ...]] | None = None
        self._cores_cache: dict[str, tuple[str, ...]] | None = None
        self._mtime: float | None = None

    def reset_cache(self) -> None:
        self._emulators_cache = None
        self._cores_cache = None
        self._mtime = None

    def resolve_emulator(self, token: str) -> str | None:
        """Resolve an ``%EMULATOR_<token>%`` placeholder to an existing host path.

        Returns the first ``staticpath`` entry for *token* that exists on disk
        (glob-aware — EmuDeck's AppImage entries carry a version wildcard),
        or ``None`` when the token is unknown or nothing it names exists.
        """
        emulators, _ = self._load()
        return self._first_existing(emulators.get(token, ()))

    def resolve_core_dir(self, token: str) -> str | None:
        """Resolve a ``<core name="<token>">`` ``corepath`` rule to its directory.

        Returns the rule's entry verbatim (expanded) without an existence
        check — the directory may not exist yet for a core the user has not
        installed, and a missing cores directory is not this adapter's call to
        make; the caller (bake-time rendering) treats a resolvable directory as
        sufficient the same way RetroDECK's cores dir is baked unconditionally.
        """
        _, cores = self._load()
        entries = cores.get(token, ())
        return self._expand(entries[0]) if entries else None

    def _first_existing(self, entries: tuple[str, ...]) -> str | None:
        for raw in entries:
            expanded = self._expand(raw)
            if not expanded:
                continue
            matches = sorted(glob.glob(expanded))
            if matches:
                return matches[0]
            if os.path.exists(expanded):
                return expanded
        return None

    def _expand(self, entry: str) -> str:
        """Strip a trailing ``|<launch-command>`` and expand a leading ``~``."""
        path = entry.split("|", 1)[0].strip()
        if not path:
            return ""
        if path == "~":
            return self._user_home
        if path.startswith("~/"):
            return os.path.join(self._user_home, path[2:])
        return path

    def _load(self) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
        try:
            current_mtime = os.path.getmtime(self._find_rules_path)
        except OSError:
            current_mtime = None

        if self._emulators_cache is not None and self._cores_cache is not None and self._mtime == current_mtime:
            return self._emulators_cache, self._cores_cache

        emulators, cores = self._parse(self._find_rules_path)
        self._emulators_cache = emulators
        self._cores_cache = cores
        self._mtime = current_mtime
        return emulators, cores

    def _parse(self, xml_path: str) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[str, ...]]]:
        """Parse ``<emulator name="X"><rule type="staticpath"><entry>`` and
        ``<core name="X"><rule type="corepath"><entry>`` into two name->entries maps.

        Uses ``xml.parsers.expat`` (Decky's frozen Python bundles it, not
        ``xml.etree``) — mirrors ``CoreResolver.parse_es_find_rules``. Returns
        ``({}, {})`` on any read/parse failure.
        """
        try:
            from xml.parsers import expat
        except ImportError:
            self._logger.warning("emudeck_find_rules: xml.parsers.expat not available")
            return {}, {}

        try:
            with open(xml_path, "rb") as f:
                data = f.read()
        except OSError as e:
            self._logger.warning("emudeck_find_rules: failed to read %s: %s", xml_path, e)
            return {}, {}

        emulators: dict[str, list[str]] = {}
        cores: dict[str, list[str]] = {}
        state: dict[str, Any] = {"text": "", "tag": None, "name": None, "rule_type": None}

        def start(name: str, attrs: dict[str, str]) -> None:
            state["text"] = ""
            if name in ("emulator", "core"):
                state["tag"] = name
                state["name"] = attrs.get("name")
                target = emulators if name == "emulator" else cores
                if state["name"]:
                    target.setdefault(state["name"], [])
            elif name == "rule":
                state["rule_type"] = attrs.get("type")

        def end(name: str) -> None:
            if name == "entry" and state["name"] and state["tag"] is not None:
                wanted = _STATICPATH if state["tag"] == "emulator" else _COREPATH
                if state["rule_type"] == wanted:
                    target = emulators if state["tag"] == "emulator" else cores
                    target[state["name"]].append(state["text"].strip())
            elif name in ("emulator", "core"):
                state["tag"] = None
                state["name"] = None
            elif name == "rule":
                state["rule_type"] = None
            state["text"] = ""

        def char_data(data: str) -> None:
            state["text"] += data

        parser = expat.ParserCreate()
        parser.StartElementHandler = start
        parser.EndElementHandler = end
        parser.CharacterDataHandler = char_data

        try:
            parser.Parse(data, True)
        except expat.ExpatError as e:
            self._logger.warning("emudeck_find_rules: failed to parse %s: %s", xml_path, e)
            return {}, {}

        return (
            {name: tuple(entries) for name, entries in emulators.items()},
            {name: tuple(entries) for name, entries in cores.items()},
        )
