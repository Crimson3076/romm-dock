"""In-memory ``PlatformCoreReader`` implementation for service tests.

Mirrors the ``settings.json`` ``platform_cores`` map (``backend_id`` -> RomM
platform slug -> core label) so tests can exercise the per-platform layer of
the active-core resolver without wiring a real ``PlatformCoreReaderAdapter``
over a settings dict.
"""

from __future__ import annotations


class FakePlatformCoreReader:
    """Maps a (backend_id, platform slug) pair to its configured core label.

    ``mapping`` is ``{backend_id: {platform_slug: label}}``, mutable so a test
    can seed a per-platform core after construction; ``calls`` records each
    queried ``(backend_id, platform_slug)`` pair. A convenience constructor
    kwarg, ``retrodeck``, seeds the ``"retrodeck"`` backend directly — the
    shape most pre-existing (single-backend) tests still want.
    """

    def __init__(
        self, mapping: dict[str, dict[str, str]] | None = None, *, retrodeck: dict[str, str] | None = None
    ) -> None:
        self.mapping: dict[str, dict[str, str]] = mapping if mapping is not None else {}
        if retrodeck is not None:
            self.mapping.setdefault("retrodeck", {}).update(retrodeck)
        self.calls: list[tuple[str, str]] = []

    def get_platform_core(self, backend_id: str, platform_slug: str) -> str | None:
        self.calls.append((backend_id, platform_slug))
        return self.mapping.get(backend_id, {}).get(platform_slug)
