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

/**
 * Response shape of `get_launch_readiness` — the PER-ROM, kind-aware sibling
 * of {@link BackendReadiness} the pre-launch gate uses instead of the blanket
 * banner check (`services/cores.py`'s `CoreService.get_launch_readiness`).
 * `retroarch_relevant` says whether this ROM's resolved active emulator is a
 * libretro core (routes through RetroArch) — `retroarch_installed` only
 * factors into `ready` when it is. `backend_installed` still blocks every
 * ROM regardless of kind.
 */
export interface LaunchReadiness {
  backend: string;
  backend_installed: boolean;
  retroarch_installed: boolean;
  retroarch_relevant: boolean;
  ready: boolean;
  message: string;
}
