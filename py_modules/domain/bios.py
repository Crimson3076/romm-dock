"""Pure BIOS-status formatting and the BIOS classification boundary.

Domain owns the unmanaged/ok/partial/missing CLASSIFICATION (``compute_bios_level``)
and the compact status token (``compute_bios_label``) — the single source of truth
for the BIOS readiness decision that every surface (game-detail panel,
play-section row, System page) renders. Verbose, per-surface phrasing and the
status-dot color are UI-layer concerns and deliberately do NOT live here. The
System page's richer two-axis summary (the optional-missing / launch-risk
breakdown the 3-state level doesn't model) is likewise a frontend concern.

Anything that takes raw firmware-check inputs and returns a readiness level,
label, or the structured ``BiosStatus`` shape belongs here; anything that decides
how a level reads or which color it shows belongs in the frontend.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AvailableCore:
    """A RetroArch core available for a platform."""

    core_so: str
    label: str
    is_default: bool


@dataclass(frozen=True)
class BiosFileEntry:
    """Status of a single BIOS/firmware file."""

    file_name: str
    downloaded: bool
    local_path: str
    required: bool
    description: str
    classification: str  # "required" | "optional" | "unknown"
    cores: dict[str, dict[str, Any]]  # {core_so: {"required": bool}}
    used_by_active: bool


@dataclass(frozen=True)
class BiosStatus:
    """Aggregated BIOS status for a platform, ready for frontend display."""

    platform_slug: str
    server_count: int
    local_count: int
    all_downloaded: bool
    required_count: int | None
    required_downloaded: int | None
    files: tuple[BiosFileEntry, ...]
    active_core: str | None
    active_core_label: str | None
    available_cores: tuple[AvailableCore, ...]
    # Count of server files the plugin's registry recognises (classification in
    # "required"/"optional"). ``None`` means the caller did not supply it, so the
    # "unmanaged" decision is not made; ``0`` with server files present means the
    # platform has no registry coverage at all.
    known_count: int | None = None
    cached_at: float = 0.0


def format_bios_status(bios: dict[str, Any], platform_slug: str, *, cached_at: float = 0.0) -> BiosStatus:
    """Build a frontend-ready BiosStatus dataclass from raw firmware check result."""
    raw_files = bios.get("files", [])
    if raw_files and isinstance(raw_files[0], dict):
        files: tuple[BiosFileEntry, ...] = tuple(
            BiosFileEntry(
                file_name=f.get("file_name", ""),
                downloaded=f.get("downloaded", False),
                local_path=f.get("local_path", ""),
                required=f.get("required", False),
                description=f.get("description", ""),
                classification=f.get("classification", "unknown"),
                cores=f.get("cores", {}),
                used_by_active=f.get("used_by_active", True),
            )
            for f in raw_files
        )
    else:
        files = tuple(raw_files)

    raw_cores = bios.get("available_cores", [])
    available_cores: tuple[AvailableCore, ...] = tuple(
        AvailableCore(
            core_so=c.get("core_so", c.get("core", "")),
            label=c.get("label", ""),
            is_default=c.get("is_default", False),
        )
        for c in raw_cores
    )

    return BiosStatus(
        platform_slug=platform_slug,
        server_count=bios.get("server_count", 0),
        local_count=bios.get("local_count", 0),
        all_downloaded=bios.get("all_downloaded", False),
        required_count=bios.get("required_count"),
        required_downloaded=bios.get("required_downloaded"),
        files=files,
        active_core=bios.get("active_core"),
        active_core_label=bios.get("active_core_label"),
        available_cores=available_cores,
        known_count=bios.get("known_count"),
        cached_at=cached_at,
    )


def resolve_registry_entry(
    registry_platform: dict[str, Any],
    file_name: str,
    md5: str = "",
) -> dict[str, Any] | None:
    """Look up a registry entry by exact file name, falling back to content hash.

    A server file whose name does not match any registry key can still be
    identified by its md5 — RomM reports a hash for every firmware file, so a
    user's differently-named BIOS dump (renamed, or a distribution using a
    different filename convention than the registry's canonical key) still
    classifies correctly instead of falling to "unknown". ``md5`` is optional
    so callers that have not resolved a hash keep the exact-name-only behavior.
    """
    entry = registry_platform.get(file_name)
    if entry is not None:
        return entry
    if not md5:
        return None
    md5_lower = md5.lower()
    for candidate in registry_platform.values():
        if candidate.get("md5", "").lower() == md5_lower:
            return candidate
    return None


def classify_firmware_file(
    reg_entry: dict[str, Any] | None,
    file_name: str,
    active_core_so: str | None,
) -> tuple[bool, str, str]:
    """Classify a firmware file as required/optional/unknown based on active core.

    Returns (is_required, classification, description).
    """
    if active_core_so and reg_entry and "cores" in reg_entry:
        is_required = reg_entry["cores"][active_core_so]["required"] if active_core_so in reg_entry["cores"] else False
        description = reg_entry.get("description", file_name)
        classification = "required" if is_required else "optional"
    elif reg_entry:
        is_required = reg_entry.get("required", True)
        classification = "required" if is_required else "optional"
        description = reg_entry.get("description", file_name)
    else:
        is_required = False
        classification = "unknown"
        description = file_name
    return is_required, classification, description


def build_cores_info(reg_entry: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Build per-core info dict for frontend display."""
    if not reg_entry or "cores" not in reg_entry:
        return {}
    return {
        core_so_key: {"required": core_data.get("required", True)}
        for core_so_key, core_data in reg_entry["cores"].items()
    }


def is_used_by_active_core(reg_entry: dict[str, Any] | None, active_core_so: str | None) -> bool:
    """Check if a firmware file is used by the active core."""
    if not active_core_so or not reg_entry or "cores" not in reg_entry:
        return True
    return active_core_so in reg_entry["cores"]


def build_file_entry(
    file_name: str,
    downloaded: bool,
    dest: str,
    reg_entry: dict[str, Any] | None,
    active_core_so: str | None,
) -> BiosFileEntry:
    """Build a single file status entry as a BiosFileEntry dataclass."""
    is_required, classification, description = classify_firmware_file(reg_entry, file_name, active_core_so)
    return BiosFileEntry(
        file_name=file_name,
        downloaded=downloaded,
        local_path=dest,
        required=is_required,
        description=description,
        classification=classification,
        cores=build_cores_info(reg_entry),
        used_by_active=is_used_by_active_core(reg_entry, active_core_so),
    )


def collect_firmware_status(
    items: list[dict[str, Any]],
    registry_platform: dict[str, Any],
    active_core_so: str | None,
) -> tuple[BiosFileEntry, ...]:
    """Build BiosFileEntry objects for a list of pre-resolved firmware items.

    Each item must have keys: file_name, downloaded, dest, and may optionally
    carry md5. Looks up reg_entry from registry_platform by file_name, falling
    back to an item's md5 (see resolve_registry_entry) when the name does not
    match, and calls build_file_entry for each item.
    """
    return tuple(
        build_file_entry(
            item["file_name"],
            item["downloaded"],
            item["dest"],
            resolve_registry_entry(registry_platform, item["file_name"], item.get("md5", "")),
            active_core_so,
        )
        for item in items
    )


def compute_bios_level(status: BiosStatus) -> str:
    """Compute BIOS status level: 'unmanaged', 'ok', 'partial', or 'missing'.

    ``'unmanaged'`` means the plugin has no registry coverage for this platform's
    firmware — the server has files but none map to a registry entry, so no
    readiness claim can be made. It is checked first, before the required-count
    logic, and only fires when the caller supplied ``known_count`` (else the
    decision is deferred to the existing ok/partial/missing logic). Because
    ``known_count == 0`` implies ``required_count == 0``, it can only ever
    displace a false ``'ok'`` — never mask a real ``'missing'``.
    """
    if status.known_count is not None and status.server_count > 0 and status.known_count == 0:
        return "unmanaged"
    req_count = status.required_count
    req_done = status.required_downloaded
    if req_count is not None and req_done is not None:
        if req_done >= req_count:
            return "ok"
        if req_done > 0:
            return "partial"
        return "missing"
    if status.all_downloaded:
        return "ok"
    if (status.local_count or 0) > 0:
        return "partial"
    return "missing"


def compute_bios_label(status: BiosStatus) -> str:
    """Compute the compact BIOS status token (verbose phrasing stays per-surface)."""
    if status.known_count is not None and status.server_count > 0 and status.known_count == 0:
        return "Not managed"
    req_count = status.required_count
    req_done = status.required_downloaded
    if req_count is not None and req_done is not None:
        if req_done >= req_count:
            return "OK"
        if req_done > 0:
            return f"{req_done}/{req_count} required"
        return "Missing"
    if status.all_downloaded:
        return "OK"
    if (status.local_count or 0) > 0:
        return f"{status.local_count}/{status.server_count}"
    return "Missing"
