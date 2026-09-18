import { describe, it, expect } from "vitest";
import { backendReadinessBanner } from "./backendReadinessBanner";

describe("backendReadinessBanner", () => {
  it("returns null when the backend and RetroArch are both installed", () => {
    expect(
      backendReadinessBanner({
        backend: "retrodeck",
        backend_installed: true,
        retroarch_installed: true,
        message: "RetroDECK and RetroArch are both installed.",
      }),
    ).toBeNull();
  });

  it("returns the launcher-not-found banner when the backend isn't installed", () => {
    const banner = backendReadinessBanner({
      backend: "retrodeck",
      backend_installed: false,
      retroarch_installed: true,
      message: "RetroDECK was not found on this device — games will fail to launch until it is installed.",
    });
    expect(banner).not.toBeNull();
    expect(banner!.title).toBe("Launcher not found");
    expect(banner!.message).toContain("RetroDECK was not found");
  });

  it("returns the RetroArch-not-found banner when only RetroArch is missing", () => {
    const banner = backendReadinessBanner({
      backend: "emudeck",
      backend_installed: true,
      retroarch_installed: false,
      message: "RetroArch was not found — libretro-core games will fail to launch until it is installed.",
    });
    expect(banner).not.toBeNull();
    expect(banner!.title).toBe("RetroArch not found");
    expect(banner!.message).toContain("RetroArch was not found");
  });

  it("prioritizes the backend-not-found case when both are missing", () => {
    const banner = backendReadinessBanner({
      backend: "emudeck",
      backend_installed: false,
      retroarch_installed: false,
      message: "EmuDeck was not found on this device — games will fail to launch until it is installed.",
    });
    expect(banner!.title).toBe("Launcher not found");
  });
});
