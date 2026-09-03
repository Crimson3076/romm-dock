"""In-memory ``XemuConfigReader`` implementation for service tests."""

from __future__ import annotations


class FakeXemuConfigReader:
    """Returns a preset ``get_sys_files()`` result.

    Defaults to "no xemu.toml found anywhere" (``(None, None)``), matching
    the common case in tests that don't exercise the xemu alignment check at
    all. Set ``sys_files``/``config_path`` directly to exercise the other
    three outcomes (misaligned, unreadable, ok).
    """

    def __init__(self, *, sys_files: dict[str, str] | None = None, config_path: str | None = None) -> None:
        self.sys_files = sys_files
        self.config_path = config_path

    def get_sys_files(self) -> tuple[dict[str, str] | None, str | None]:
        return self.sys_files, self.config_path
