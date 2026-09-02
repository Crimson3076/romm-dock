/**
 * ExeSelector — inline launch-target picker for native-Windows ROMs.
 *
 * Structural twin of DiscSelector (#865): sits immediately to its right in the
 * play-section row. For an installed native-Windows ROM whose install
 * enumerates at least one launchable target — a `.exe` (Proton-launched) or a
 * bundled `.sh` script (launched natively, no Proton) — it renders a compact,
 * icon-only trigger — neutral grey for the default pick (the first enumerated
 * target), accent-tinted when a specific one is pinned. Clicking it opens an
 * anchored `showContextMenu` list of the enumerated targets, rendered
 * identically regardless of kind — this component never reads which kind a
 * target is; that branch lives entirely in the backend's
 * `WindowsLaunchResolver`. Picking one rewrites the Steam shortcut's
 * `launch_options` to the freshly-baked launch command for that target and
 * persists the choice in the backend DB, so the Play button always launches
 * the currently-selected one.
 *
 * Unknown / not-installed / non-Windows / no-target ROMs render nothing — the
 * backend's `has_executables: false` covers every one of those cases. The
 * picker re-fetches on `download_complete` (a newly installed ROM may now
 * report launch targets) and hides on `romm_rom_uninstalled`.
 */

import { useState, useEffect, useRef, FC } from "react";
import { addEventListener, removeEventListener } from "@decky/api";
import { Menu, MenuItem, showContextMenu, DialogButton } from "@decky/ui";
import { FaWindows, FaChevronDown } from "react-icons/fa";
import { getCachedGameDetail, getWindowsExecutables, selectExecutable, logError, logWarn } from "../api/backend";
import type { WindowsExecutablesAnswer } from "../api/backend";
import { setLaunchOptionsConfirmed } from "../utils/steamShortcuts";
import { getEventTarget } from "../utils/events";
import { detach } from "../utils/detach";
import { showToast } from "../utils/toast";
import type { DownloadCompleteEvent } from "../types";
import {
  capturePruneLeaseAdmission,
  isPruneLeaseCancellation,
  mountPruneLeaseOwner,
  releasePruneLeasesByOwner,
  withPruneLease,
} from "../utils/pruneLease";

interface ExeSelectorProps {
  appId: number;
}

/** One menu option's `data` value: an exe filename, or `null` to clear back to the default. */
type ExeOptionData = string | null;

// Same palette as DiscSelector/VersionPicker — accent when pinned away from
// the default, neutral grey otherwise — so the game-detail pickers read as
// one system.
const EXE_GREY = "#dcdedf";
const EXE_ACCENT = "#59b6ff";

export const ExeSelector: FC<ExeSelectorProps> = ({ appId }) => {
  const leaseOwner = `exe-selector:${appId}`;
  const [answer, setAnswer] = useState<WindowsExecutablesAnswer | null>(null);
  // Locally-tracked pin: `selected` echoed by a successful selectExecutable.
  // Mirrors the persisted `roms.selected_exe` (null = following the default).
  const [selected, setSelected] = useState<ExeOptionData>(null);
  const romIdRef = useRef<number | null>(null);

  // Resolve rom_id from the cached detail and fetch the exe-picker state.
  const fetchExecutables = async (rid: number): Promise<void> => {
    try {
      const result = await getWindowsExecutables(rid);
      setAnswer(result);
      setSelected(result.selected ?? null);
    } catch (e) {
      logError(`ExeSelector: getWindowsExecutables failed: ${e}`);
    }
  };

  // Initial load: resolve rom_id from cache (instant), then fetch the picker state.
  useEffect(() => {
    mountPruneLeaseOwner(leaseOwner);
    let cancelled = false;

    async function init() {
      try {
        const cached = await getCachedGameDetail(appId);
        if (cancelled || !cached.found || cached.rom_id == null) return;
        romIdRef.current = cached.rom_id;
        if (!cached.installed) return;
        await fetchExecutables(cached.rom_id);
      } catch (e) {
        logError(`ExeSelector init error: ${e}`);
      }
    }

    detach(init());
    return () => {
      cancelled = true;
      detach(releasePruneLeasesByOwner(leaseOwner));
    };
  }, [appId, leaseOwner]);

  // Re-fetch on download_complete (a newly installed ROM may now report
  // executables); hide on uninstall.
  useEffect(() => {
    const completeListener = addEventListener<[DownloadCompleteEvent]>(
      "download_complete",
      (evt: DownloadCompleteEvent) => {
        if (evt.rom_id !== romIdRef.current) return;
        detach(fetchExecutables(evt.rom_id));
      },
    );

    const onUninstall = (e: Event) => {
      const rid = (e as CustomEvent).detail?.rom_id;
      if (rid !== romIdRef.current) return;
      setAnswer(null);
      setSelected(null);
    };
    globalThis.addEventListener("romm_rom_uninstalled", onUninstall);

    return () => {
      removeEventListener("download_complete", completeListener);
      globalThis.removeEventListener("romm_rom_uninstalled", onUninstall);
    };
  }, []);

  const handleChange = async (data: ExeOptionData): Promise<void> => {
    const rid = romIdRef.current;
    if (rid == null) return;
    const admission = capturePruneLeaseAdmission(leaseOwner);
    try {
      const result = await selectExecutable(rid, data);
      await withPruneLease(
        result.prune_lease_token,
        "ExeSelector",
        async (signal) => {
          if (result.success) {
            if (result.launch_options !== undefined) {
              if (signal.aborted) return;
              await setLaunchOptionsConfirmed(appId, result.launch_options);
            }
            if (signal.aborted) return;
            setSelected(result.selected ?? null);
          } else {
            showToast(result.message || "Failed to select executable");
          }
        },
        leaseOwner,
        admission,
      );
    } catch (e) {
      // Leaving the game page cancels the pick's continuation — the exe is
      // already persisted backend-side, so that is teardown and not a failure.
      if (isPruneLeaseCancellation(e, admission)) {
        logWarn(`ExeSelector: executable selection continuation was cancelled: ${e}`);
        return;
      }
      // Observable catch effect: surface the failure so the user knows the pick
      // didn't take, and leave `selected` unchanged (revert to the prior pin).
      logError(`ExeSelector: selectExecutable failed: ${e}`);
      showToast("Failed to select executable");
    }
  };

  // Unknown / not-installed / non-Windows / no-exe → render nothing.
  if (!answer?.has_executables || !answer.executables || answer.executables.length === 0) return null;

  const { executables } = answer;
  // The effective pin: an explicit selection, else the default (the first
  // enumerated `.exe`).
  const effectiveSelected: ExeOptionData = selected ?? executables[0]?.filename ?? null;
  const isPinned = selected !== null;

  const openMenu = (e: MouseEvent): void => {
    showContextMenu(
      <Menu label="Executable">
        {executables.map((exe) => {
          const active = exe.filename === effectiveSelected;
          return (
            <MenuItem key={exe.filename} onClick={() => detach(handleChange(exe.filename))}>
              <span
                style={{
                  display: "inline-flex",
                  alignItems: "center",
                  gap: "10px",
                  color: active ? EXE_ACCENT : undefined,
                }}
              >
                <FaWindows size={16} />
                <span>{exe.filename}</span>
                {active ? <span style={{ marginLeft: "6px", fontWeight: 700 }}>✓</span> : null}
              </span>
            </MenuItem>
          );
        })}
      </Menu>,
      getEventTarget(e),
    );
  };

  return (
    <DialogButton className="romm-disc-btn" onClick={openMenu} aria-label="Executable" title="Executable">
      <FaWindows size={22} color={isPinned ? EXE_ACCENT : EXE_GREY} />
      <FaChevronDown size={10} color="#cfd3d8" />
    </DialogButton>
  );
};
