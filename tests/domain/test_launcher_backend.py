"""Unit tests for ``domain/launcher_backend`` — value objects and id constants."""

from __future__ import annotations

from domain.launcher_backend import (
    EMUDECK_BACKEND_ID,
    RETRODECK_BACKEND_ID,
    BackendValidation,
    DetectedInstallation,
)


class TestBackendIdConstants:
    def test_retrodeck_backend_id(self):
        assert RETRODECK_BACKEND_ID == "retrodeck"

    def test_emudeck_backend_id(self):
        assert EMUDECK_BACKEND_ID == "emudeck"

    def test_ids_are_distinct(self):
        assert RETRODECK_BACKEND_ID != EMUDECK_BACKEND_ID


class TestDetectedInstallation:
    def test_construction(self):
        installation = DetectedInstallation(
            installation_id="retrodeck",
            display_name="RetroDECK",
            home="/home/deck",
            healthy=True,
            detail="ok",
        )
        assert installation.installation_id == "retrodeck"
        assert installation.display_name == "RetroDECK"
        assert installation.home == "/home/deck"
        assert installation.healthy is True
        assert installation.detail == "ok"

    def test_unhealthy_installation(self):
        installation = DetectedInstallation(
            installation_id="emudeck:/home/deck",
            display_name="EmuDeck",
            home="/home/deck",
            healthy=False,
            detail="root_missing",
        )
        assert installation.healthy is False
        assert installation.detail == "root_missing"

    def test_is_frozen(self):
        installation = DetectedInstallation(
            installation_id="retrodeck", display_name="RetroDECK", home="", healthy=True, detail="ok"
        )
        try:
            installation.healthy = False  # type: ignore[misc]
        except AttributeError:
            pass
        else:
            raise AssertionError("DetectedInstallation must be immutable")

    def test_equality_by_value(self):
        a = DetectedInstallation(
            installation_id="retrodeck", display_name="RetroDECK", home="", healthy=True, detail="ok"
        )
        b = DetectedInstallation(
            installation_id="retrodeck", display_name="RetroDECK", home="", healthy=True, detail="ok"
        )
        assert a == b


class TestBackendValidation:
    def test_ok_defaults_reason_and_message_to_none(self):
        validation = BackendValidation(ok=True)
        assert validation.ok is True
        assert validation.reason is None
        assert validation.message is None

    def test_failure_carries_reason_and_message(self):
        validation = BackendValidation(ok=False, reason="not_detected", message="EmuDeck was not found.")
        assert validation.ok is False
        assert validation.reason == "not_detected"
        assert validation.message == "EmuDeck was not found."

    def test_is_frozen(self):
        validation = BackendValidation(ok=True)
        try:
            validation.ok = False  # type: ignore[misc]
        except AttributeError:
            pass
        else:
            raise AssertionError("BackendValidation must be immutable")
