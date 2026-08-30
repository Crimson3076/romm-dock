"""Tests for services.launcher_backend.registry.LauncherBackendRegistry."""

from __future__ import annotations

from fakes.fake_launcher_backend_factory import FakeLauncherBackendFactory

from services.launcher_backend.registry import LauncherBackendRegistry


class TestFactories:
    def test_returns_every_registered_factory(self):
        retrodeck = FakeLauncherBackendFactory("retrodeck")
        emudeck = FakeLauncherBackendFactory("emudeck")
        registry = LauncherBackendRegistry([retrodeck, emudeck])

        factories = registry.factories()
        assert {f.backend_id for f in factories} == {"retrodeck", "emudeck"}
        assert len(factories) == 2

    def test_preserves_insertion_order(self):
        # A dict keyed by backend_id preserves insertion order in Python 3.7+;
        # pinned here as current, deliberate behavior.
        emudeck = FakeLauncherBackendFactory("emudeck")
        retrodeck = FakeLauncherBackendFactory("retrodeck")
        registry = LauncherBackendRegistry([emudeck, retrodeck])

        assert [f.backend_id for f in registry.factories()] == ["emudeck", "retrodeck"]

    def test_empty_registry_returns_empty_list(self):
        registry = LauncherBackendRegistry([])
        assert registry.factories() == []


class TestGet:
    def test_returns_matching_factory(self):
        retrodeck = FakeLauncherBackendFactory("retrodeck")
        registry = LauncherBackendRegistry([retrodeck])
        assert registry.get("retrodeck") is retrodeck

    def test_returns_none_for_unknown_id(self):
        registry = LauncherBackendRegistry([FakeLauncherBackendFactory("retrodeck")])
        assert registry.get("nonexistent") is None

    def test_returns_none_on_empty_registry(self):
        registry = LauncherBackendRegistry([])
        assert registry.get("retrodeck") is None


class TestDuplicateBackendId:
    def test_second_registration_silently_wins(self):
        # Current, pinned behavior: the registry is a plain dict keyed by
        # backend_id, so two factories sharing an id collapse to the second
        # — no error, no merge. Documented here rather than treated as a bug:
        # wiring never registers two factories under the same id today.
        first = FakeLauncherBackendFactory("retrodeck", display_name="First")
        second = FakeLauncherBackendFactory("retrodeck", display_name="Second")
        registry = LauncherBackendRegistry([first, second])

        assert registry.get("retrodeck") is second
        assert len(registry.factories()) == 1
