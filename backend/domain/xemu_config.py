"""Pure parsing and alignment check for xemu's own configuration file.

``xemu.toml`` is the emulator's own config, not this plugin's — its
``[sys.files]`` table names the exact paths xemu reads its boot ROM, flash
BIOS, and hard disk image from. This module owns turning that table into a
per-key alignment verdict against this plugin's own BIOS directory; reading
the file and resolving which candidate path exists stays in
``adapters/xemu_config.py``.
"""

from __future__ import annotations

import os
import tomllib
from typing import Any

SYS_FILES_KEYS = ("bootrom_path", "flashrom_path", "hdd_path")


def parse_xemu_sys_files(toml_text: str) -> dict[str, str]:
    """Parse xemu.toml's ``[sys.files]`` table into ``{key: path}``.

    Only the three keys this plugin cares about are kept, and only when their
    value is a string (a malformed document with the wrong value type for a
    key is treated as that key being absent, not as a parse failure — the
    document as a whole is still valid TOML). Raises
    ``tomllib.TOMLDecodeError`` on genuinely malformed TOML.
    """
    doc = tomllib.loads(toml_text)
    sys_files = doc.get("sys", {}).get("files", {})
    if not isinstance(sys_files, dict):
        return {}
    return {key: sys_files[key] for key in SYS_FILES_KEYS if isinstance(sys_files.get(key), str)}


def compute_xemu_alignment(sys_files: dict[str, str], expected_dir: str) -> dict[str, dict[str, Any]]:
    """Compare each of xemu's configured file paths against this plugin's BIOS directory.

    Returns one entry per key in :data:`SYS_FILES_KEYS`, each carrying the
    ``configured_path`` xemu.toml names (``None`` when the key is absent) and
    ``in_plugin_bios_dir`` — whether that path's directory is exactly this
    plugin's resolved BIOS root. This says whether xemu is looking in the
    same place the plugin downloads to, not whether the file exists there;
    the existing per-file BIOS status already answers that.
    """
    normalized_expected = os.path.normpath(expected_dir) if expected_dir else ""
    result: dict[str, dict[str, Any]] = {}
    for key in SYS_FILES_KEYS:
        path = sys_files.get(key)
        path_dir = os.path.normpath(os.path.dirname(path)) if path else ""
        in_dir = bool(path_dir) and bool(normalized_expected) and path_dir == normalized_expected
        result[key] = {"configured_path": path, "in_plugin_bios_dir": in_dir}
    return result
