"""Pure value objects for the launcher-backend seam (issue #918).

A launcher backend renders launch invocations and resolves ROM/BIOS/save
roots for one launcher (RetroDECK, EmuDeck, ...). These are its detection and
validation vocabulary — no I/O, no service or adapter imports.
"""

from __future__ import annotations

from dataclasses import dataclass

# The backend id RetroDECK keeps as the plugin's default — the identity
# preserved by every fresh install and every existing settings.json that
# predates this seam (see domain/state_migrations.py).
RETRODECK_BACKEND_ID = "retrodeck"
EMUDECK_BACKEND_ID = "emudeck"


@dataclass(frozen=True, slots=True)
class DetectedInstallation:
    """One concrete installation of a launcher backend found on this machine.

    ``installation_id`` is stable and opaque to the frontend — the value a
    user's pick round-trips through ``set_launcher_backend``. RetroDECK has
    exactly one installation, so its id is the backend id itself; EmuDeck can
    have more than one arrangement on a machine (rare, but a second drive or
    a reinstalled home makes it possible), so its id is derived from the
    installation's own home path.
    """

    installation_id: str
    display_name: str
    home: str
    healthy: bool
    detail: str


@dataclass(frozen=True, slots=True)
class BackendValidation:
    """Whether a backend+installation is safe to switch to, and why not.

    ``reason`` is a stable machine-readable slug (e.g. ``"not_detected"``,
    ``"launcher_scripts_missing"``) the frontend can key copy on;
    ``message`` is the human-readable detail. Both are ``None`` when
    ``ok`` is ``True``.
    """

    ok: bool
    reason: str | None = None
    message: str | None = None
