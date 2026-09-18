/**
 * Launcher-backend / RetroArch readiness surfaced to the QAM banner and the
 * pre-launch gate. Mirrors the backend's `get_backend_readiness` callable
 * (`services/launcher_backend/service.py`): whether the ACTIVE launcher
 * backend (RetroDECK or EmuDeck) and RetroArch are genuinely installed on
 * this device, not merely assumed.
 */

/** Response shape of `get_backend_readiness`. Always succeeds — both probes
 *  are best-effort filesystem checks, so there is no `success`/`reason` pair;
 *  `backend_installed`/`retroarch_installed` ARE the verdict. */
export interface BackendReadiness {
  backend: string;
  backend_installed: boolean;
  retroarch_installed: boolean;
  message: string;
}
