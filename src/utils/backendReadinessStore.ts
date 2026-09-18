/**
 * Module-level launcher-backend / RetroArch readiness store.
 *
 * Refreshed by:
 *   - MainPage.tsx on mount (QAM panel open)
 *   - LauncherBackendSection.tsx after a successful backend switch — the
 *     active backend just changed, so the previous verdict is stale
 *
 * Read by:
 *   - MainPage.tsx, through {@link useBackendReadiness}, for the readiness
 *     banner
 *   - launchGate.ts's backend-readiness check, through {@link getBackendReadinessState}
 *     outside of any render
 *
 * Mirrors migrationStore.ts's shape: every write installs a NEW state object
 * and notifies, so {@link getBackendReadinessState} can serve as a
 * `useSyncExternalStore` snapshot.
 */

import { useSyncExternalStore } from "react";
import type { BackendReadiness } from "../types";
import { getBackendReadiness, logError } from "../api/backend";

let _state: BackendReadiness | null = null;
let _listeners: Array<() => void> = [];

function publish(next: BackendReadiness | null): void {
  _state = next;
  _listeners.forEach((fn) => fn());
}

export function getBackendReadinessState(): BackendReadiness | null {
  return _state;
}

export function onBackendReadinessChange(fn: () => void): () => void {
  _listeners.push(fn);
  return () => {
    _listeners = _listeners.filter((l) => l !== fn);
  };
}

/** Re-probe and publish. Failure logs and leaves the previous verdict in
 *  place — a transient callable error must not flip a healthy banner to
 *  "unknown" (or worse, block a launch on it). */
export async function refreshBackendReadiness(): Promise<void> {
  try {
    publish(await getBackendReadiness());
  } catch (e) {
    logError(`refreshBackendReadiness failed: ${e}`);
  }
}

/** Subscribe to the readiness state from a component. */
export function useBackendReadiness(): BackendReadiness | null {
  return useSyncExternalStore(onBackendReadinessChange, getBackendReadinessState);
}
