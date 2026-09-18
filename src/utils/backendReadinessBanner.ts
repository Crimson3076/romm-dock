/**
 * User-facing copy and the loud/quiet decision for the launcher-backend /
 * RetroArch readiness banner. The backend's `get_backend_readiness` returns
 * only the booleans plus its own message; this module decides whether to
 * show a banner at all and what title to give it, so the component stays
 * presentation-only — mirrors `retrodeckHealth.ts`'s split for the RetroDECK
 * path-resolution banner.
 */

import type { BackendReadiness } from "../types";

/** Title + body for a loud backend-readiness banner. */
export interface BackendReadinessBanner {
  title: string;
  message: string;
}

/**
 * Map a `BackendReadiness` probe to banner copy, or `null` when both the
 * active backend and RetroArch are installed. The backend-not-installed case
 * takes priority — RetroArch's own state is moot if the launcher itself isn't
 * there.
 */
export function backendReadinessBanner(status: BackendReadiness): BackendReadinessBanner | null {
  if (!status.backend_installed) {
    return { title: "Launcher not found", message: status.message };
  }
  if (!status.retroarch_installed) {
    return { title: "RetroArch not found", message: status.message };
  }
  return null;
}
