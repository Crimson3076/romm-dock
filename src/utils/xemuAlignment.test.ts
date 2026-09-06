import { describe, it, expect } from "vitest";
import { xemuAlignmentBanner } from "./xemuAlignment";

const CONFIG_PATH = "/home/deck/.local/share/xemu/xemu/xemu.toml";

describe("xemuAlignmentBanner", () => {
  it("returns null for 'ok' (healthy — stays quiet)", () => {
    expect(xemuAlignmentBanner("ok", CONFIG_PATH)).toBeNull();
  });

  it("returns null for 'not_found' (xemu likely never launched — stays quiet)", () => {
    expect(xemuAlignmentBanner("not_found", null)).toBeNull();
  });

  it("returns the misaligned banner with the checked config path", () => {
    const banner = xemuAlignmentBanner("misaligned", CONFIG_PATH);
    expect(banner).not.toBeNull();
    expect(banner!.title).toBe("xemu isn't configured to use these files");
    expect(banner!.message).toContain("won't be picked up until xemu.toml's [sys.files] paths match");
    expect(banner!.message).toContain(CONFIG_PATH);
  });

  it("returns the unreadable banner with the checked config path", () => {
    const banner = xemuAlignmentBanner("unreadable", CONFIG_PATH);
    expect(banner).not.toBeNull();
    expect(banner!.title).toBe("xemu configuration unreadable");
    expect(banner!.message).toContain(CONFIG_PATH);
  });

  it("omits the 'Checked:' suffix when configPath is null", () => {
    const banner = xemuAlignmentBanner("misaligned", null);
    expect(banner).not.toBeNull();
    expect(banner!.message).not.toContain("Checked:");
  });
});
