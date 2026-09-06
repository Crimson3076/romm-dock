"""xemu.toml adapter — reads xemu's own configuration for the BIOS alignment check.

Resolves xemu's configuration file across its two known install shapes
(native and Flatpak), reads it, and delegates parsing to
``domain.xemu_config``. Uncached: this is a low-frequency System-page read,
not a hot path, matching ``RetroArchConfigAdapter``'s own choice to skip
caching for the same reason.
"""

from __future__ import annotations

import os
import tomllib
from typing import TYPE_CHECKING

from domain.xemu_config import parse_xemu_sys_files

if TYPE_CHECKING:
    import logging


class XemuConfigAdapter:
    """Adapter for reading xemu's ``[sys.files]`` configuration."""

    def __init__(self, *, user_home: str, logger: logging.Logger) -> None:
        self._user_home = user_home
        self._logger = logger

    def candidate_paths(self) -> list[str]:
        """xemu.toml's native and Flatpak locations, in probe order."""
        return [
            os.path.join(self._user_home, ".local", "share", "xemu", "xemu", "xemu.toml"),
            os.path.join(self._user_home, ".var", "app", "app.xemu.xemu", "data", "xemu", "xemu", "xemu.toml"),
        ]

    def get_sys_files(self) -> tuple[dict[str, str] | None, str | None]:
        """Read and parse the first candidate xemu.toml that exists.

        Returns ``(sys_files, config_path)`` on success. ``sys_files`` is
        ``None`` when no candidate exists at all, or when the one found could
        not be read or parsed (a warning is logged either way) —
        ``config_path`` still names which file was found unreadable/unparsable
        so the caller can report it, and is ``None`` only when nothing was
        found at any candidate location.
        """
        for path in self.candidate_paths():
            try:
                with open(path, encoding="utf-8") as f:
                    text = f.read()
            except FileNotFoundError:
                continue
            except OSError as e:
                self._logger.warning(f"xemu.toml found at {path} but could not be read: {e}")
                return None, path
            try:
                return parse_xemu_sys_files(text), path
            except tomllib.TOMLDecodeError as e:
                self._logger.warning(f"xemu.toml at {path} is not valid TOML: {e}")
                return None, path
        return None, None
