"""Tests for services.launcher_backend.service.LauncherBackendService."""

from __future__ import annotations

import logging
from typing import Any

from fakes.fake_launcher_backend_factory import FakeLauncherBackend, FakeLauncherBackendFactory
from fakes.fake_relaunch_options_resolver import FakeRelaunchOptionsResolver
from fakes.fake_settings_persister import FakeSettingsPersister

from domain.launcher_backend import BackendValidation
from services.launcher_backend.registry import LauncherBackendRegistry
from services.launcher_backend.service import LauncherBackendService, LauncherBackendServiceConfig

_LOGGER = logging.getLogger("test")


def _service(
    *,
    factories: list[Any] | None = None,
    settings: dict[str, Any] | None = None,
    relaunch_items: FakeRelaunchOptionsResolver | None = None,
    settings_persister: FakeSettingsPersister | None = None,
) -> tuple[LauncherBackendService, dict[str, Any], FakeSettingsPersister, FakeRelaunchOptionsResolver]:
    settings = settings if settings is not None else {}
    persister = settings_persister if settings_persister is not None else FakeSettingsPersister()
    items = relaunch_items if relaunch_items is not None else FakeRelaunchOptionsResolver()
    registry = LauncherBackendRegistry(
        factories if factories is not None else [FakeLauncherBackendFactory("retrodeck")]
    )
    service = LauncherBackendService(
        config=LauncherBackendServiceConfig(
            registry=registry,
            settings=settings,
            settings_persister=persister,
            relaunch_items=items,
            logger=_LOGGER,
        )
    )
    return service, settings, persister, items


class TestConstructionDefaults:
    def test_empty_settings_bind_retrodeck(self):
        service, _settings, _persister, _items = _service()
        assert service.active_backend_id() == "retrodeck"
        assert service.active_installation_id() == "retrodeck"

    def test_settings_naming_a_registered_backend_binds_it(self):
        service, _settings, _persister, _items = _service(
            factories=[FakeLauncherBackendFactory("retrodeck"), FakeLauncherBackendFactory("emudeck")],
            settings={"launcher_backend": "emudeck", "launcher_backend_installation": "emudeck"},
        )
        assert service.active_backend_id() == "emudeck"
        assert service.active_installation_id() == "emudeck"


class TestFallbackBinding:
    def test_unregistered_backend_id_falls_back_to_retrodeck(self):
        service, _settings, _persister, _items = _service(
            settings={"launcher_backend": "does-not-exist", "launcher_backend_installation": "does-not-exist"},
        )
        assert service.active_backend_id() == "retrodeck"
        assert service.active_installation_id() == "retrodeck"

    def test_registered_backend_with_unrecognized_installation_falls_back(self):
        # bind() on the registered factory returns None for an installation
        # id it never detected -> falls back to RetroDECK.
        emudeck_factory = FakeLauncherBackendFactory("emudeck")
        service, _settings, _persister, _items = _service(
            factories=[FakeLauncherBackendFactory("retrodeck"), emudeck_factory],
            settings={"launcher_backend": "emudeck", "launcher_backend_installation": "stale-installation-id"},
        )
        assert service.active_backend_id() == "retrodeck"
        assert "stale-installation-id" in emudeck_factory.bound


class TestRenderingDelegation:
    def test_resolve_invocation_delegates_to_active_backend(self):
        service, _settings, _persister, _items = _service()
        rom: dict[str, Any] = {"platform_slug": "snes"}
        # FakeLauncherBackend.resolve_invocation delegates to the real
        # domain function with no emulator -> the plain RetroDECK invocation.
        assert service.resolve_invocation(rom, None) == "flatpak run net.retrodeck.retrodeck"

    def test_build_launch_options_delegates_to_active_backend(self):
        service, _settings, _persister, _items = _service()
        assert service.build_launch_options("flatpak run x", "") == ""
        assert service.build_launch_options("flatpak run x", "/roms/g.sfc") == 'flatpak run x "/roms/g.sfc"'

    def test_no_active_backend_degrades_to_empty_string(self):
        # Defensive branch: even the RetroDECK fallback bind fails only when
        # the registry itself carries no "retrodeck" factory at all -- a
        # mis-wired registry, never real production wiring. resolve_invocation/
        # build_launch_options must degrade rather than raise.
        service, _settings, _persister, _items = _service(factories=[])
        assert service.active_backend_id() == "retrodeck"
        assert service.resolve_invocation({"platform_slug": "snes"}, None) == ""
        assert service.build_launch_options("flatpak run x", "/roms/g.sfc") == ""

    def test_switch_takes_effect_on_the_very_next_call(self):
        # Two backends tagged with distinguishable rendering (rather than two
        # FakeLauncherBackend instances that would render identically) so the
        # assertion actually proves resolve_invocation routed through the
        # NEWLY bound backend, not just that active_backend_id() changed.
        class _TaggedBackend:
            def __init__(self, backend_id: str) -> None:
                self.backend_id = backend_id
                self.installation_id = backend_id

            def resolve_invocation(self, rom: dict[str, Any], emulator: Any) -> str:
                return f"invocation-from-{self.backend_id}"

            def build_launch_options(self, invocation: str, path: str) -> str:
                return invocation

            def roms_root(self) -> str:
                return ""

            def bios_root(self) -> str:
                return ""

            def saves_root(self) -> str:
                return ""

            def validate(self) -> BackendValidation:
                return BackendValidation(ok=True)

        class _TaggedFactory:
            def __init__(self, backend_id: str) -> None:
                self.backend_id = backend_id
                self.display_name = backend_id

            def detect_installations(self):
                from domain.launcher_backend import DetectedInstallation

                return [
                    DetectedInstallation(
                        installation_id=self.backend_id,
                        display_name=self.backend_id,
                        home="",
                        healthy=True,
                        detail="ok",
                    )
                ]

            def bind(self, installation_id: str):
                return _TaggedBackend(self.backend_id) if installation_id == self.backend_id else None

        service, _settings, _persister, _items = _service(
            factories=[_TaggedFactory("retrodeck"), _TaggedFactory("emudeck")],
        )
        rom: dict[str, Any] = {"platform_slug": "snes"}

        first = service.resolve_invocation(rom, None)
        assert first == "invocation-from-retrodeck"
        assert service.active_backend_id() == "retrodeck"

        result = service.set_active_backend("emudeck", "emudeck")
        assert result["success"] is True

        second = service.resolve_invocation(rom, None)
        assert second == "invocation-from-emudeck"
        assert service.active_backend_id() == "emudeck"


class TestListBackends:
    def test_one_entry_per_registered_factory(self):
        service, _settings, _persister, _items = _service(
            factories=[
                FakeLauncherBackendFactory("retrodeck"),
                FakeLauncherBackendFactory("emudeck", installations=[]),
            ],
        )
        backends = service.list_backends()
        assert {b["backend_id"] for b in backends} == {"retrodeck", "emudeck"}

    def test_installations_is_always_a_list_even_when_empty(self):
        service, _settings, _persister, _items = _service(
            factories=[
                FakeLauncherBackendFactory("retrodeck"),
                FakeLauncherBackendFactory("emudeck", installations=[]),
            ],
        )
        backends = {b["backend_id"]: b for b in service.list_backends()}
        assert backends["emudeck"]["installations"] == []
        assert isinstance(backends["retrodeck"]["installations"], list)

    def test_exactly_one_active_backend_and_installation_after_construction(self):
        service, _settings, _persister, _items = _service(
            factories=[FakeLauncherBackendFactory("retrodeck"), FakeLauncherBackendFactory("emudeck")],
        )
        backends = service.list_backends()
        active_backends = [b for b in backends if b["is_active"]]
        assert len(active_backends) == 1
        assert active_backends[0]["backend_id"] == "retrodeck"

        active_installations = [i for b in backends for i in b["installations"] if i["is_active"]]
        assert len(active_installations) == 1
        assert active_installations[0]["installation_id"] == "retrodeck"

    def test_exactly_one_active_backend_and_installation_after_switch(self):
        service, _settings, _persister, _items = _service(
            factories=[FakeLauncherBackendFactory("retrodeck"), FakeLauncherBackendFactory("emudeck")],
        )
        result = service.set_active_backend("emudeck", "emudeck")
        assert result["success"] is True

        backends = service.list_backends()
        active_backends = [b for b in backends if b["is_active"]]
        assert len(active_backends) == 1
        assert active_backends[0]["backend_id"] == "emudeck"

        active_installations = [i for b in backends for i in b["installations"] if i["is_active"]]
        assert len(active_installations) == 1
        assert active_installations[0]["installation_id"] == "emudeck"


class TestSetActiveBackendFailures:
    def test_unknown_backend_id(self):
        service, settings, persister, _items = _service()
        result = service.set_active_backend("does-not-exist", "does-not-exist")
        assert result == {
            "success": False,
            "reason": "unknown_backend",
            "message": "No launcher backend 'does-not-exist'.",
        }
        assert settings == {}
        assert persister.save_count == 0
        assert service.active_backend_id() == "retrodeck"

    def test_bind_returns_none_when_installation_not_detected(self):
        emudeck_factory = FakeLauncherBackendFactory("emudeck", installations=[])
        service, settings, persister, _items = _service(
            factories=[FakeLauncherBackendFactory("retrodeck"), emudeck_factory],
        )
        result = service.set_active_backend("emudeck", "some-installation")
        assert result["success"] is False
        assert result["reason"] == "not_detected"
        assert "some-installation" in result["message"]
        assert settings == {}
        assert persister.save_count == 0
        assert service.active_backend_id() == "retrodeck"

    def test_failed_validation_surfaces_the_same_reason_and_message(self):
        from domain.launcher_backend import DetectedInstallation

        broken_backend = FakeLauncherBackend(
            backend_id="emudeck",
            installation_id="emudeck",
            validation=BackendValidation(ok=False, reason="unhealthy", message="EmuDeck reports: root-missing"),
        )

        class _BrokenFactory:
            backend_id = "emudeck"
            display_name = "EmuDeck"

            def detect_installations(self) -> list[DetectedInstallation]:
                return [
                    DetectedInstallation(
                        installation_id="emudeck", display_name="EmuDeck", home="", healthy=False, detail="unhealthy"
                    )
                ]

            def bind(self, installation_id: str):
                return broken_backend if installation_id == "emudeck" else None

        service, settings, persister, _items = _service(
            factories=[FakeLauncherBackendFactory("retrodeck"), _BrokenFactory()],
        )
        result = service.set_active_backend("emudeck", "emudeck")
        assert result == {"success": False, "reason": "unhealthy", "message": "EmuDeck reports: root-missing"}
        assert settings == {}
        assert persister.save_count == 0
        # A failed switch leaves the previous backend active.
        assert service.active_backend_id() == "retrodeck"


class TestSetActiveBackendSuccess:
    def test_success_returns_rebake_items_persists_and_activates(self):
        rebake_items = [{"app_id": 1, "launch_options": "flatpak run x"}]
        items = FakeRelaunchOptionsResolver(items=rebake_items)
        service, settings, persister, items = _service(
            factories=[FakeLauncherBackendFactory("retrodeck"), FakeLauncherBackendFactory("emudeck")],
            relaunch_items=items,
        )

        result = service.set_active_backend("emudeck", "emudeck")

        assert result == {"success": True, "rebake_items": rebake_items}
        assert settings["launcher_backend"] == "emudeck"
        assert settings["launcher_backend_installation"] == "emudeck"
        assert persister.save_count == 1
        assert items.calls == 1
        assert service.active_backend_id() == "emudeck"
        assert service.active_installation_id() == "emudeck"
