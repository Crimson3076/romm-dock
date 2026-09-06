/**
 * Shared builder for the emulator-picker context menu (#1210).
 *
 * Both pickers — the game-detail core menu (`RomMPlaySection`) and the System
 * page per-platform menu (`SystemPage`) — render the same list: every ES-DE
 * `<command>` classified for bakeability, with the bakeable ones clickable and
 * the un-bakeable ones shown disabled with a short reason. The frontend owns the
 * reason copy; the backend only ships the reason slug. Keys are the emulator
 * LABEL (not `core_so`), since a standalone emulator has no core.
 */

import type { ReactNode } from "react";
import { Menu, MenuItem, MenuSeparator } from "@decky/ui";
import type { EmulatorOption } from "../types";

/**
 * Map a backend un-bakeable reason slug to short menu copy.
 *
 * `activeBackendDisplayName` names the launcher backend (RetroDECK / EmuDeck)
 * the "not_installed" copy is about, when the caller has it in scope — the
 * generic fallback stands when it does not.
 */
export function reasonCopy(reason: string | null, activeBackendDisplayName?: string | null): string {
  switch (reason) {
    case "inject":
      return "needs setup files (launch via ES-DE once)";
    case "not_installed":
      return activeBackendDisplayName ? `not provided by ${activeBackendDisplayName}` : "emulator not installed";
    case "shortcut_script":
      return "script/shortcut form";
    default:
      // no_rom_target / quoting / startdir / unknown_placeholder / null
      return "not launchable from Steam";
  }
}

export interface EmulatorMenuConfig {
  emulators: EmulatorOption[];
  /** False when es_systems.xml can't be read — the menu says so instead of showing an empty list. */
  emulatorDataAvailable: boolean;
  /** The active emulator's label — marked with a checkmark. */
  activeLabel: string | null;
  /** The per-platform override label — marked "(system)". Null on the System page (redundant there). */
  platformCoreLabel: string | null;
  /**
   * The active launcher backend's display name (RetroDECK / EmuDeck), when the
   * caller has it in scope — threaded into `reasonCopy` so a "not_installed"
   * entry names the backend it wasn't found in rather than saying so generically.
   */
  activeBackendDisplayName?: string | null;
  /**
   * Game-detail only: the "Use System Override" reset item that CLEARS the
   * per-game pin. Omit on the System page, where picking the default entry is
   * itself the clear-to-empty-label action.
   */
  followSystem?: { hasGameOverride: boolean; onFollowSystem: () => void };
  /** Called with the picked emulator LABEL when a bakeable entry is chosen. */
  onPick: (label: string) => void;
  /**
   * Game-detail only: every OTHER installed backend's own catalogue, for
   * cross-backend pinning. Omitted (or empty) on the System page.
   */
  otherBackends?: Array<{ backendId: string; displayName: string; emulators: EmulatorOption[] }>;
  /** Game-detail only: the ROM's current cross-backend pin, or null. */
  crossBackendPin?: { backendId: string; label: string } | null;
  /** Game-detail only: called with (backendId, label) when a cross-backend entry is picked. */
  onPickCrossBackend?: (backendId: string, label: string) => void;
}

/**
 * "(RetroArch)" for a libretro entry whose own label doesn't already say so.
 *
 * ES-DE's own catalogue labels a standalone entry distinctly ("Dolphin
 * (Standalone)") but often labels its libretro sibling with the bare
 * emulator name ("Dolphin") — nothing in that text says it's the RetroArch
 * core, so next to its standalone namesake it reads as unidentified rather
 * than as the RetroArch option. Applied to every libretro entry (bakeable or
 * not) so a disabled "needs setup" one is just as identifiable.
 */
function kindMark(e: EmulatorOption): string {
  return e.kind === "libretro" && !/retroarch/i.test(e.label) ? " (RetroArch)" : "";
}

/**
 * The entry text for a bakeable emulator: its label plus the markers saying what
 * it is. "(default)" is the es_systems default, "(system)" the per-platform
 * override, ✓ the one actually in effect — one entry can carry all three, which
 * is why they are suffixes rather than a single state.
 */
function emulatorEntryLabel(e: EmulatorOption, isActive: boolean, isPlatformCore: boolean): string {
  const defaultMark = e.is_default ? " (default)" : "";
  const systemMark = isPlatformCore ? " (system)" : "";
  const activeMark = isActive ? " ✓" : "";
  return `${e.label}${kindMark(e)}${defaultMark}${systemMark}${activeMark}`;
}

/**
 * Render one emulator entry — disabled with its reason copy when un-bakeable,
 * clickable with its active/default/system markers otherwise. Shared between
 * the native (active-backend) list and every foreign backend's own list, so a
 * `namePrefix` (e.g. `"EmuDeck: "`) is threaded through for the latter.
 */
function renderEntry(
  e: EmulatorOption,
  key: string,
  isActive: boolean,
  isPlatformCore: boolean,
  onClickPick: () => void,
  activeBackendDisplayName: string | null | undefined,
  namePrefix = "",
): ReactNode {
  if (!e.bakeable) {
    return (
      <MenuItem key={key} disabled={true}>
        {`${namePrefix}${e.label}${kindMark(e)} — ${reasonCopy(e.reason, activeBackendDisplayName)}`}
      </MenuItem>
    );
  }
  return (
    <MenuItem key={key} onClick={onClickPick}>
      {`${namePrefix}${emulatorEntryLabel(e, isActive, isPlatformCore)}`}
    </MenuItem>
  );
}

/** Build the `<Menu>` element for `showContextMenu`. */
export function buildEmulatorMenu(config: EmulatorMenuConfig): ReactNode {
  const {
    emulators,
    emulatorDataAvailable,
    activeLabel,
    platformCoreLabel,
    activeBackendDisplayName,
    followSystem,
    onPick,
    otherBackends,
    crossBackendPin,
    onPickCrossBackend,
  } = config;

  if (!emulatorDataAvailable) {
    return (
      <Menu label="Emulator">
        <MenuItem key="unavailable" disabled={true}>
          Emulator list unavailable — RetroDECK installation not found
        </MenuItem>
      </Menu>
    );
  }

  const defaultLabel = emulators.find((e) => e.is_default)?.label ?? null;
  // The active emulator is "the default" when nothing overrides it (no active
  // label, or it equals the default) — the checkmark then sits on the default.
  const activeIsDefault = !activeLabel || activeLabel === defaultLabel;

  const children: ReactNode[] = [
    <MenuItem key="compat" disabled={true}>
      Switching cores may affect save compatibility
    </MenuItem>,
    <MenuSeparator key="compat-sep" />,
  ];

  if (followSystem) {
    // The core the game falls back to with no per-game pin: the per-platform
    // override when set, else the es_systems default. ✓ sits here when the game
    // already follows the system (no per-game pin AND no cross-backend pin —
    // a cross-backend pin always wins over the active backend's own catalogue,
    // so it must never coincide with this checkmark). "System Override" stays
    // distinct from the "(default)" marker so the menu never shows two defaults.
    const fallbackLabel = platformCoreLabel ?? defaultLabel ?? null;
    const fallbackSuffix = fallbackLabel ? ` (${fallbackLabel})` : "";
    const followsSystemMark = !followSystem.hasGameOverride && !crossBackendPin ? " ✓" : "";
    children.push(
      <MenuItem key="follow-system" onClick={followSystem.onFollowSystem}>
        {`Use System Override${fallbackSuffix}${followsSystemMark}`}
      </MenuItem>,
      <MenuSeparator key="follow-sep" />,
    );
  }

  for (const e of emulators) {
    const key = `emu-${e.label}`;
    // A cross-backend pin always wins over the active backend's own catalogue
    // (checked first at every bake site), so none of THIS backend's entries —
    // not even the one matching the active label — may carry the ✓ while a
    // cross-backend pin is in effect. Only the foreign pinned entry below does.
    const isActive = !crossBackendPin && (activeIsDefault ? e.is_default : activeLabel === e.label);
    const isPlatformCore = platformCoreLabel !== null && e.label === platformCoreLabel;
    children.push(renderEntry(e, key, isActive, isPlatformCore, () => onPick(e.label), activeBackendDisplayName));
  }

  if (otherBackends && otherBackends.length > 0) {
    // Flat, prefixed list rather than a nested submenu — no nested-`<Menu>`
    // pattern exists anywhere else in this codebase's @decky/ui usage, so a
    // flyout submenu here would be an unproven UI shape.
    children.push(<MenuSeparator key="other-backends-sep" />);
    for (const backend of otherBackends) {
      for (const e of backend.emulators) {
        const key = `emu-${backend.backendId}-${e.label}`;
        const isActive = !!crossBackendPin && crossBackendPin.backendId === backend.backendId && crossBackendPin.label === e.label;
        children.push(
          renderEntry(
            e,
            key,
            isActive,
            false,
            () => onPickCrossBackend?.(backend.backendId, e.label),
            activeBackendDisplayName,
            `${backend.displayName}: `,
          ),
        );
      }
    }
  }

  return <Menu label="Emulator Core">{children}</Menu>;
}
