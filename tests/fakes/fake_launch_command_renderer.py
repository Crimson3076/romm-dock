"""In-memory ``LaunchCommandRenderer`` implementation for service tests."""

from __future__ import annotations

from typing import Any

from domain.shortcut_data import build_launch_options, resolve_emulator_invocation


class FakeLaunchCommandRenderer:
    """``LaunchCommandRenderer`` for tests — defaults to the real RetroDECK rendering.

    Delegating to ``domain.shortcut_data``'s real functions by default means
    every existing test written against the RetroDECK-shaped ``launch_options``
    string keeps asserting on the exact same output after this seam's
    injection replaced a direct import — the launcher-backend seam is
    invisible to a test that never asked to exercise it. A test that DOES
    care about the backend seam overrides ``resolve_invocation``/
    ``render_launch_options`` (constructor args) to a different shape,
    or reads ``calls`` to assert the seam was reached at all.
    """

    def __init__(
        self,
        *,
        resolve_invocation: Any = resolve_emulator_invocation,
        render_launch_options: Any = build_launch_options,
    ) -> None:
        self._resolve_invocation = resolve_invocation
        self._render_launch_options = render_launch_options
        self.calls: list[tuple[dict[str, Any], Any]] = []

    def resolve_invocation(self, rom: dict[str, Any], emulator: Any) -> str:
        self.calls.append((rom, emulator))
        return self._resolve_invocation(rom, emulator)

    def build_launch_options(self, invocation: str, path: str) -> str:
        return self._render_launch_options(invocation, path)
