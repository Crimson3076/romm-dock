/**
 * ExeSelector — inline launch-target picker for native-Windows ROMs, plus the
 * per-game Steam compat-tool override picker (ADR-0032).
 *
 * Structural twin of DiscSelector (#865): sits immediately to its right in the
 * play-section row. For an installed native-Windows ROM whose install
 * enumerates at least one launchable target — a `.exe` (Proton-launched) or a
 * bundled `.sh` script (launched natively, no Proton) — it renders a compact,
 * icon-only trigger — neutral grey for the default pick (the first enumerated
 * target), accent-tinted when a specific one is pinned. Clicking it opens an
 * anchored `showContextMenu` list of the enumerated targets. Picking one
 * rewrites the Steam shortcut's `launch_options` to the freshly-baked launch
 * command for that target and persists the choice in the backend DB, so the
 * Play button always launches the currently-selected one.
 *
 * A second trigger, gated on the same `has_executables` answer, is the
 * compat-tool override picker: "Force Native (No Proton)", "Automatic (Steam
 * Default)", and one entry per `SteamClient.Apps.GetAvailableCompatTools`
 * result on this machine. This is the actual fix for a native launch target
 * that Steam's own "Enable Steam Play for all other titles" setting would
 * otherwise force-wrap in Proton (see ADR-0032 for the full incident) — a
 * non-Steam shortcut's Properties → Compatibility UI has no "off" option once
 * that global setting is on, so `SpecifyCompatTool(appId, "")` is the only
 * confirmed way to force none for one shortcut. Every fetch below (mount,
 * `download_complete`, `version_switched`) re-derives this ROM's active
 * launch target's `kind` and, when the backend has never recorded an override
 * for this ROM (`compat_tool_override === null`), auto-applies "" the first
 * time that target is `"native"` — no user action required. Once an override
 * is recorded (auto-applied or explicit), every subsequent fetch re-applies
 * the SAME stored value via `SpecifyCompatTool` rather than re-deciding it —
 * this is what survives an appId rebind (a version switch, an
 * uninstall/reinstall that assigns a fresh Steam appId per CLAUDE.md's
 * "shortcut appId is assigned, not derived" trap): Steam's own per-appId
 * compat-tool setting does not carry over to the new appId, so the plugin's
 * remembered intent has to be re-asserted onto it.
 *
 * Unknown / not-installed / non-Windows / no-target ROMs render nothing — the
 * backend's `has_executables: false` covers every one of those cases. Both
 * pickers re-fetch on `download_complete` (a newly installed ROM may now
 * report launch targets) and on `version_switched` for this appId (a version
 * switch rebinds the shortcut to a different rom_id, whose own override may
 * differ), and hide on `romm_rom_uninstalled`.
 */

import { useState, useEffect, useRef, FC } from "react";
import { addEventListener, removeEventListener } from "@decky/api";
import { Menu, MenuItem, showContextMenu, DialogButton } from "@decky/ui";
import { FaWindows, FaChevronDown, FaCog } from "react-icons/fa";
import {
  getCachedGameDetail,
  getWindowsExecutables,
  selectExecutable,
  setCompatToolOverride,
  clearCompatToolOverride,
  logError,
  logWarn,
} from "../api/backend";
import type { WindowsExecutablesAnswer } from "../api/backend";
import { setLaunchOptionsConfirmed } from "../utils/steamShortcuts";
import { getEventTarget } from "../utils/events";
import { detach } from "../utils/detach";
import { showToast } from "../utils/toast";
import type { DownloadCompleteEvent } from "../types";
import type { RommDataChangedDetail } from "../types/events";
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

/** One `SteamClient.Apps.GetAvailableCompatTools` entry — a Proton build installed on this machine. */
type CompatToolOption = { strToolName: string; strDisplayName: string };

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
  // Locally-tracked compat-tool override (ADR-0032): mirrors the persisted
  // `roms.compat_tool_override`. `null` = no override, `""` = force native
  // (Proton bypassed), any other string = force that `strToolName`.
  const [compatOverride, setCompatOverride] = useState<string | null>(null);
  const romIdRef = useRef<number | null>(null);

  // Apply (or auto-decide) this ROM's compat-tool override against the LIVE
  // Steam appid, then mirror whatever took effect into local state.
  //
  // `compat_tool_override === null` means the backend has never recorded a
  // decision for this ROM — the one case this component decides FOR itself,
  // and only ever towards "" (force native), and only when the ROM's current
  // active target is a native (Proton-bypassing) one. An "exe" target under
  // `null` is left alone: Steam's own default Proton behavior is already
  // correct for it.
  //
  // A non-null override (auto-applied earlier, or an explicit user pick) is
  // never re-decided here — it is re-APPLIED verbatim via `SpecifyCompatTool`
  // on every call. That un-conditional re-assert, run from every fetch site
  // (mount, download_complete, version_switched), is what survives an appId
  // rebind: `SpecifyCompatTool` is scoped to a Steam appId, Steam does not
  // carry a shortcut's compat-tool setting over to a newly assigned appId,
  // and this plugin's own appIds are reassigned over a ROM's lifetime (a
  // version switch, an uninstall/reinstall — CLAUDE.md's "shortcut appId is
  // assigned, not derived" trap) with no signal the backend can see to tell
  // this component to re-apply just once.
  const applyCompatToolOverride = async (rid: number, ans: WindowsExecutablesAnswer): Promise<void> => {
    if (!ans.has_executables || !ans.executables || ans.executables.length === 0) return;
    const effective = ans.selected ?? ans.executables[0]?.filename ?? null;
    const activeExe = ans.executables.find((exe) => exe.filename === effective) ?? ans.executables[0];
    const stored = ans.compat_tool_override ?? null;

    if (stored === null) {
      if (activeExe?.kind !== "native") return;
      try {
        await SteamClient.Apps.SpecifyCompatTool(appId, "");
      } catch (e) {
        // Nothing persisted when the live apply itself failed — a later fetch
        // (still seeing `null`) gets another chance to auto-apply, rather than
        // this component recording a fix that never actually took.
        logError(`ExeSelector: auto SpecifyCompatTool("") failed: ${e}`);
        return;
      }
      try {
        const result = await setCompatToolOverride(rid, "");
        if (result.success) {
          setCompatOverride("");
        } else {
          logWarn(`ExeSelector: setCompatToolOverride failed after auto-apply: ${result.message}`);
        }
      } catch (e) {
        logError(`ExeSelector: setCompatToolOverride threw after auto-apply: ${e}`);
      }
      return;
    }

    try {
      await SteamClient.Apps.SpecifyCompatTool(appId, stored);
    } catch (e) {
      logError(`ExeSelector: re-apply SpecifyCompatTool failed: ${e}`);
    }
    setCompatOverride(stored);
  };

  // Resolve rom_id from the cached detail and fetch the exe-picker state.
  const fetchExecutables = async (rid: number): Promise<void> => {
    try {
      const result = await getWindowsExecutables(rid);
      setAnswer(result);
      setSelected(result.selected ?? null);
      setCompatOverride(result.compat_tool_override ?? null);
      await applyCompatToolOverride(rid, result);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetchExecutables closes over `appId` (via applyCompatToolOverride) only, and `appId` is already listed; it is otherwise stable per render.
  }, [appId, leaseOwner]);

  // Re-fetch on download_complete (a newly installed ROM may now report
  // executables, and a reinstall may have rebound the appid — see
  // applyCompatToolOverride) and on version_switched for this appid (the
  // shortcut is now bound to a different rom_id, whose own kind/override this
  // component has never read); hide on uninstall.
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
      setCompatOverride(null);
    };
    globalThis.addEventListener("romm_rom_uninstalled", onUninstall);

    const onDataChanged = (e: Event) => {
      const detail = (e as CustomEvent<RommDataChangedDetail>).detail;
      if (detail.type !== "version_switched" || detail.app_id !== appId) return;
      romIdRef.current = detail.rom_id;
      detach(fetchExecutables(detail.rom_id));
    };
    globalThis.addEventListener("romm_data_changed", onDataChanged);

    return () => {
      removeEventListener("download_complete", completeListener);
      globalThis.removeEventListener("romm_rom_uninstalled", onUninstall);
      globalThis.removeEventListener("romm_data_changed", onDataChanged);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- fetchExecutables closes over `appId` (via applyCompatToolOverride) only, and `appId` is already listed; it is otherwise stable per render.
  }, [appId]);

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
            // Switching WHICH target is selected can change its kind (exe <->
            // native) — re-fetch so applyCompatToolOverride re-evaluates against
            // the newly active target, not the one this component decided (or
            // deliberately left alone) for the PREVIOUS selection.
            await fetchExecutables(rid);
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

  // Apply one compat-tool choice: SteamClient FIRST, persist through the
  // callable SECOND — so a rejected SpecifyCompatTool (the live Steam-side
  // half) never gets falsely recorded as applied. Shared by every menu entry,
  // including "" (Force Native) and a specific `strToolName`; "Automatic"
  // uses the separate clear path below instead (there is nothing to apply).
  const handleCompatPick = async (value: string): Promise<void> => {
    const rid = romIdRef.current;
    if (rid == null) return;
    try {
      await SteamClient.Apps.SpecifyCompatTool(appId, value);
    } catch (e) {
      logError(`ExeSelector: SpecifyCompatTool failed: ${e}`);
      showToast("Failed to set compatibility tool");
      return;
    }
    try {
      const result = await setCompatToolOverride(rid, value);
      if (result.success) {
        setCompatOverride(value);
      } else {
        logError(`ExeSelector: setCompatToolOverride failed: ${result.message}`);
        showToast(result.message || "Failed to save compatibility tool setting");
      }
    } catch (e) {
      logError(`ExeSelector: setCompatToolOverride threw: ${e}`);
      showToast("Failed to save compatibility tool setting");
    }
  };

  // "Automatic (Steam Default)": drop the stored override entirely. No
  // SpecifyCompatTool call — there is no confirmed way to hand a non-Steam
  // shortcut back to Steam's own default decision (which, under the global
  // Steam Play setting, IS Proton); this only stops the plugin from touching
  // this ROM's setting going forward.
  const handleCompatClear = async (): Promise<void> => {
    const rid = romIdRef.current;
    if (rid == null) return;
    try {
      const result = await clearCompatToolOverride(rid);
      if (result.success) {
        setCompatOverride(null);
      } else {
        logError(`ExeSelector: clearCompatToolOverride failed: ${result.message}`);
        showToast(result.message || "Failed to reset compatibility tool setting");
      }
    } catch (e) {
      logError(`ExeSelector: clearCompatToolOverride threw: ${e}`);
      showToast("Failed to reset compatibility tool setting");
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

  // One compat-tool menu row: an icon + label, tinted + checkmarked when it
  // matches the current `compatOverride`. Mirrors the exe list's own row
  // shape above so the two pickers read as one system.
  const compatEntry = (active: boolean, text: string, onClick: () => void, key: string) => (
    <MenuItem key={key} onClick={onClick}>
      <span
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: "10px",
          color: active ? EXE_ACCENT : undefined,
        }}
      >
        <FaCog size={16} />
        <span>{text}</span>
        {active ? <span style={{ marginLeft: "6px", fontWeight: 700 }}>✓</span> : null}
      </span>
    </MenuItem>
  );

  // The live tool list is fetched fresh on every open (never cached) since it
  // reflects what is installed on THIS machine right now. The event target is
  // captured synchronously, before the `await`, since the originating
  // MouseEvent should not be trusted to still be valid by the time the fetch
  // resolves.
  const openCompatMenu = (e: MouseEvent): void => {
    const rid = romIdRef.current;
    if (rid == null) return;
    const target = getEventTarget(e);
    detach(
      (async () => {
        let tools: CompatToolOption[] = [];
        try {
          tools = await SteamClient.Apps.GetAvailableCompatTools(appId);
        } catch (err) {
          // The two fixed entries (Force Native / Automatic) still work when
          // the live tool list can't be read — only the per-build list is empty.
          logError(`ExeSelector: GetAvailableCompatTools failed: ${err}`);
        }
        showContextMenu(
          <Menu label="Compatibility Tool">
            {compatEntry(
              compatOverride === "",
              "Force Native (No Proton)",
              () => detach(handleCompatPick("")),
              "compat-native",
            )}
            {compatEntry(
              compatOverride === null,
              "Automatic (Steam Default)",
              () => detach(handleCompatClear()),
              "compat-auto",
            )}
            {tools.map((tool) =>
              compatEntry(
                compatOverride === tool.strToolName,
                tool.strDisplayName,
                () => detach(handleCompatPick(tool.strToolName)),
                `compat-${tool.strToolName}`,
              ),
            )}
          </Menu>,
          target,
        );
      })(),
    );
  };

  return (
    <>
      <DialogButton className="romm-disc-btn" onClick={openMenu} aria-label="Executable" title="Executable">
        <FaWindows size={22} color={isPinned ? EXE_ACCENT : EXE_GREY} />
        <FaChevronDown size={10} color="#cfd3d8" />
      </DialogButton>
      <DialogButton
        className="romm-disc-btn"
        onClick={openCompatMenu}
        aria-label="Compatibility Tool"
        title="Compatibility Tool"
      >
        <FaCog size={22} color={compatOverride !== null ? EXE_ACCENT : EXE_GREY} />
        <FaChevronDown size={10} color="#cfd3d8" />
      </DialogButton>
    </>
  );
};
