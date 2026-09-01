"""In-memory ``ProtonLocator`` implementation for service tests."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from domain.proton import ProtonInstallation


class FakeProtonLocator:
    """Controllable ``ProtonLocator`` for tests.

    ``installation`` is a mutable attribute so a test can flip between "Proton
    found" and "no Proton installed" (``None``) without rebuilding the fake.
    Defaults to ``None`` — matching a fresh environment with nothing installed
    — so a test opts into the happy path explicitly.
    """

    def __init__(
        self,
        *,
        installation: ProtonInstallation | None = None,
        runtime_dir: str = "/fake/runtime",
    ) -> None:
        self.installation = installation
        self.runtime_dir = runtime_dir

    def locate(self) -> ProtonInstallation | None:
        return self.installation

    def compat_data_path(self, rom_id: int) -> str:
        return os.path.join(self.runtime_dir, "proton-prefixes", str(rom_id))
