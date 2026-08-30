/**
 * Launcher backend picker (issue #918) — which launcher (RetroDECK / EmuDeck)
 * and which detected installation of it Tender launches ROMs through.
 *
 * Self-contained rather than SettingsPage-owned data — mirrors DiscSelector
 * (`../DiscSelector.tsx`): a backend switch's rebake fan-out
 * (`setLauncherBackend` → confirm-set every live shortcut's `launch_options`,
 * ADR-0029) needs its own prune-lease owner whose mount/unmount tracks this
 * section's own lifecycle, not SettingsPage's.
 *
 * `getLauncherBackends()` marks the CURRENTLY active backend/installation with
 * `is_active` on each entry (`LauncherBackendService.list_backends`), so the
 * initial dropdown selection is read from the response itself rather than
 * assumed — a prior session's switch to EmuDeck is reflected on load.
 */

import { useState, useEffect, FC } from "react";
import { PanelSection, PanelSectionRow, DropdownItem, Field } from "@decky/ui";
import { getLauncherBackends, setLauncherBackend, logError } from "../../api/backend";
import type { LauncherBackendInfo } from "../../api/backend";
import { detach } from "../../utils/detach";
import {
  capturePruneLeaseAdmission,
  isPruneLeaseCancellation,
  mountPruneLeaseOwner,
  releasePruneLeasesByOwner,
  withPruneLease,
} from "../../utils/pruneLease";
import { batchConfirmLaunchOptions } from "../../utils/launchOptionsReconcile";

// The plugin's documented default (py_modules/domain/launcher_backend.py's
// RETRODECK_BACKEND_ID) — only used until the first getLauncherBackends()
// response reports the actual active selection.
const DEFAULT_BACKEND_ID = "retrodeck";
const DEFAULT_INSTALLATION_ID = "retrodeck";

export const LauncherBackendSection: FC = () => {
  const leaseOwner = "launcher-backend-section";
  const [backends, setBackends] = useState<LauncherBackendInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [backendId, setBackendId] = useState(DEFAULT_BACKEND_ID);
  const [installationId, setInstallationId] = useState(DEFAULT_INSTALLATION_ID);
  const [switching, setSwitching] = useState(false);
  const [statusMessage, setStatusMessage] = useState("");

  async function refreshBackends() {
    setLoading(true);
    try {
      const result = await getLauncherBackends();
      setBackends(result);
      const activeBackend = result.find((b) => b.is_active);
      if (activeBackend) {
        setBackendId(activeBackend.backend_id);
        const activeInstallation = activeBackend.installations.find((i) => i.is_active);
        if (activeInstallation) setInstallationId(activeInstallation.installation_id);
      }
    } catch (e) {
      logError(`LauncherBackendSection: get_launcher_backends failed: ${e}`);
      setStatusMessage("Failed to load launcher backends");
    }
    setLoading(false);
  }

  useEffect(() => {
    mountPruneLeaseOwner(leaseOwner);
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial async data loads on mount are the standard React pattern; the rule is overzealous here
    detach(refreshBackends());
    return () => {
      detach(releasePruneLeasesByOwner(leaseOwner));
    };
  }, []);

  const applySwitch = async (newBackendId: string, newInstallationId: string): Promise<void> => {
    setSwitching(true);
    setStatusMessage("");
    const admission = capturePruneLeaseAdmission(leaseOwner);
    try {
      const result = await setLauncherBackend(newBackendId, newInstallationId);
      if (result.success) {
        setBackendId(newBackendId);
        setInstallationId(newInstallationId);
        await withPruneLease(
          result.prune_lease_token,
          "setLauncherBackend",
          (signal) => batchConfirmLaunchOptions(result.rebake_items ?? [], "setLauncherBackend", signal),
          leaseOwner,
          admission,
        );
      } else {
        // set_active_backend leaves the previous backend bound on any failure
        // (validation runs before anything is persisted or re-baked), so
        // backendId/installationId above are already the un-applied, correct
        // "reverted" selection — nothing else needs to change.
        setStatusMessage(result.message || "Failed to switch launcher backend");
      }
    } catch (e) {
      if (isPruneLeaseCancellation(e, admission)) return;
      logError(`LauncherBackendSection: setLauncherBackend failed: ${e}`);
      setStatusMessage(`Failed to switch launcher backend: ${e}`);
    }
    setSwitching(false);
  };

  const handleBackendChange = (newBackendId: string): void => {
    if (newBackendId === backendId) return;
    const backend = backends.find((b) => b.backend_id === newBackendId);
    const firstInstallation = backend?.installations[0];
    if (!backend || !firstInstallation) {
      setStatusMessage(`${backend?.display_name ?? newBackendId} has no detected installation on this machine`);
      return;
    }
    detach(applySwitch(newBackendId, firstInstallation.installation_id));
  };

  const handleInstallationChange = (newInstallationId: string): void => {
    if (newInstallationId === installationId) return;
    detach(applySwitch(backendId, newInstallationId));
  };

  const selectedBackend = backends.find((b) => b.backend_id === backendId);
  const installations = selectedBackend?.installations ?? [];
  const hasInstallations = installations.length > 0;
  const selectedInstallation = installations.find((i) => i.installation_id === installationId);

  return (
    <PanelSection title="Launcher">
      <PanelSectionRow>
        <DropdownItem
          label="Launcher"
          description="Which emulation frontend Tender launches games through"
          rgOptions={backends.map((b) => ({ data: b.backend_id, label: b.display_name }))}
          selectedOption={backendId}
          disabled={loading || switching || backends.length === 0}
          onChange={(option) => handleBackendChange(option.data as string)}
        />
      </PanelSectionRow>
      <PanelSectionRow>
        <DropdownItem
          label="Installation"
          description={
            hasInstallations
              ? (selectedInstallation?.home ?? "")
              : `No ${selectedBackend?.display_name ?? "launcher"} installation detected on this machine`
          }
          rgOptions={installations.map((i) => ({
            data: i.installation_id,
            label: i.healthy ? i.display_name : `${i.display_name} (${i.detail})`,
          }))}
          selectedOption={installationId}
          disabled={switching || !hasInstallations}
          onChange={(option) => handleInstallationChange(option.data as string)}
        />
      </PanelSectionRow>
      {statusMessage && (
        <PanelSectionRow>
          <Field label={statusMessage} />
        </PanelSectionRow>
      )}
    </PanelSection>
  );
};
