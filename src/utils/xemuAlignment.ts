/**
 * User-facing copy and the loud/quiet decision for the xemu.toml alignment
 * warning on the System page's Xbox section. The backend's
 * `check_xemu_config_alignment` returns only the discriminant plus paths;
 * the human-readable banner copy lives here so the component stays
 * presentation-only. Mirrors `utils/retrodeckHealth.ts`'s shape.
 */

import type { XemuAlignmentStatus } from "../types";

/** Title + body for a loud xemu-alignment warning. */
export interface XemuAlignmentBanner {
  title: string;
  message: string;
}

/**
 * Map a xemu alignment status to warning copy, or `null` when nothing should
 * be shown. `ok` and `not_found` stay quiet: `ok` is healthy, and `not_found`
 * usually just means xemu hasn't been launched once yet (no config exists),
 * which is the legitimate fresh-install case. Only `misaligned` and
 * `unreadable` are loud.
 */
export function xemuAlignmentBanner(status: XemuAlignmentStatus, configPath: string | null): XemuAlignmentBanner | null {
  switch (status) {
    case "misaligned":
      return {
        title: "xemu isn't configured to use these files",
        message:
          "xemu's own configuration doesn't point at this plugin's BIOS folder for the boot ROM and/or flash BIOS — " +
          "downloaded files won't be picked up until xemu.toml's [sys.files] paths match." +
          (configPath ? ` Checked: ${configPath}` : ""),
      };
    case "unreadable":
      return {
        title: "xemu configuration unreadable",
        message:
          "Found xemu's configuration but couldn't read it, so alignment with this plugin's BIOS folder can't be verified." +
          (configPath ? ` Checked: ${configPath}` : ""),
      };
    default:
      // "ok" and "not_found" stay quiet.
      return null;
  }
}
