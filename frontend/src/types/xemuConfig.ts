/**
 * xemu.toml alignment, surfaced to the Xbox section of the System page. The
 * backend checks whether xemu's own `[sys.files]` boot ROM and flash BIOS
 * paths point at this plugin's BIOS directory — the same information the
 * BIOS file list already shows as downloaded, viewed from xemu's side
 * instead. Anything describing how trustworthy that alignment is lives here.
 */

/** Discriminant for `check_xemu_config_alignment`. `not_found` means no
 *  xemu.toml exists yet at any known location (xemu likely hasn't been
 *  launched once). `unreadable` means one was found but could not be read
 *  or parsed. `misaligned` means it was read but its boot ROM and/or flash
 *  BIOS path does not point at this plugin's BIOS directory. */
export type XemuAlignmentStatus = "ok" | "misaligned" | "not_found" | "unreadable";

/** Per-key detail: the path xemu.toml names (`null` if the key is absent)
 *  and whether that path's directory matches this plugin's BIOS directory. */
export interface XemuFileAlignment {
  configured_path: string | null;
  in_plugin_bios_dir: boolean;
}

/** Discriminated-status response from `check_xemu_config_alignment`.
 *  `files` carries `bootrom_path` / `flashrom_path` / `hdd_path` — `hdd_path`
 *  is informational only and never drives `status` (see
 *  docs/user-guide/bios-management.md#xbox-xemu for why). */
export interface XemuAlignmentResult {
  status: XemuAlignmentStatus;
  config_path: string | null;
  files: Record<string, XemuFileAlignment>;
}
