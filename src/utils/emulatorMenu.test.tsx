import { describe, it, expect, vi } from "vitest";
import type { ReactElement } from "react";

// The builder is inspected as a React element tree, not rendered, so the
// @decky/ui menu components only need to be distinguishable element types. The
// global stub omits MenuSeparator; a local passthrough mock supplies all three.
vi.mock("@decky/ui", () => ({
  Menu: "Menu",
  MenuItem: "MenuItem",
  MenuSeparator: "MenuSeparator",
}));

import { buildEmulatorMenu, reasonCopy, type EmulatorMenuConfig } from "./emulatorMenu";
import { libretroEmu, standaloneEmu } from "../test-utils/coreFixtures";

// The builder returns a <Menu> element; walk its child MenuItem elements without
// rendering (the @decky/ui Menu/MenuItem are stubs). A MenuItem carries its label
// as a string child; MenuSeparators have no string child and are filtered out.
interface Item {
  text: string;
  disabled: boolean;
  onClick: (() => void) | undefined;
}
function items(menu: unknown): Item[] {
  const el = menu as ReactElement<{ children?: unknown }>;
  const kids = ([] as unknown[])
    .concat(el.props.children as unknown[])
    .flat(Infinity)
    .filter(Boolean);
  return kids
    .map((k) => k as ReactElement<{ children?: unknown; disabled?: boolean; onClick?: () => void }>)
    .filter((k) => typeof k.props.children === "string")
    .map((k) => ({ text: k.props.children as string, disabled: !!k.props.disabled, onClick: k.props.onClick }));
}

function baseConfig(overrides: Partial<EmulatorMenuConfig> = {}): EmulatorMenuConfig {
  return {
    emulators: [libretroEmu("mgba_libretro", "mGBA", true), libretroEmu("vbam_libretro", "VBA-M")],
    emulatorDataAvailable: true,
    activeLabel: null,
    platformCoreLabel: null,
    onPick: vi.fn(),
    ...overrides,
  };
}

describe("reasonCopy", () => {
  it("maps known reason slugs to distinct copy", () => {
    expect(reasonCopy("inject")).toBe("needs setup files (launch via ES-DE once)");
    expect(reasonCopy("not_installed")).toBe("emulator not installed");
    expect(reasonCopy("shortcut_script")).toBe("script/shortcut form");
  });

  it("falls back to a generic message for other slugs", () => {
    for (const r of ["no_rom_target", "quoting", "startdir", "unknown_placeholder", null]) {
      expect(reasonCopy(r)).toBe("not launchable from Steam");
    }
  });

  it("names the active launcher backend for not_installed when given a display name", () => {
    expect(reasonCopy("not_installed", "EmuDeck")).toBe("not provided by EmuDeck");
    expect(reasonCopy("not_installed", "RetroDECK")).toBe("not provided by RetroDECK");
  });

  it("falls back to the generic not_installed copy when no backend name is given", () => {
    expect(reasonCopy("not_installed")).toBe("emulator not installed");
    expect(reasonCopy("not_installed", null)).toBe("emulator not installed");
  });

  it("does not use the backend name for any other reason slug", () => {
    expect(reasonCopy("inject", "EmuDeck")).toBe("needs setup files (launch via ES-DE once)");
    expect(reasonCopy("shortcut_script", "EmuDeck")).toBe("script/shortcut form");
  });
});

describe("buildEmulatorMenu", () => {
  it("renders a single disabled notice when emulator data is unavailable", () => {
    const menu = buildEmulatorMenu(baseConfig({ emulators: [], emulatorDataAvailable: false }));
    const its = items(menu);
    expect(its).toHaveLength(1);
    expect(its[0]!.disabled).toBe(true);
    expect(its[0]!.text).toBe("Emulator list unavailable — RetroDECK installation not found");
  });

  it("marks the default emulator and dispatches its label on pick", () => {
    const onPick = vi.fn();
    const menu = buildEmulatorMenu(baseConfig({ onPick }));
    const its = items(menu);
    const mgba = its.find((i) => i.text.startsWith("mGBA"))!;
    expect(mgba.text).toContain("(default)");
    expect(mgba.disabled).toBe(false);
    mgba.onClick!();
    expect(onPick).toHaveBeenCalledWith("mGBA");
  });

  it("tags a bakeable libretro entry as (RetroArch) when its own label doesn't already say so", () => {
    const menu = buildEmulatorMenu(baseConfig());
    const its = items(menu);
    expect(its.find((i) => i.text.startsWith("mGBA"))!.text).toBe("mGBA (RetroArch) (default) ✓");
    expect(its.find((i) => i.text.startsWith("VBA-M"))!.text).toBe("VBA-M (RetroArch)");
  });

  it("does not double-tag a libretro entry whose own label already names RetroArch", () => {
    const menu = buildEmulatorMenu(
      baseConfig({ emulators: [libretroEmu("retroarch_core", "RetroArch (Snes9x)", true)] }),
    );
    expect(items(menu).find((i) => i.text.startsWith("RetroArch"))!.text).toBe("RetroArch (Snes9x) (default) ✓");
  });

  it("does not tag a standalone entry as (RetroArch)", () => {
    const menu = buildEmulatorMenu(baseConfig({ emulators: [standaloneEmu("Dolphin (Standalone)", true)] }));
    expect(items(menu).find((i) => i.text.startsWith("Dolphin"))!.text).toBe("Dolphin (Standalone) (default) ✓");
  });

  it("renders an un-bakeable emulator as disabled with its reason copy", () => {
    const menu = buildEmulatorMenu(
      baseConfig({
        emulators: [
          libretroEmu("mgba_libretro", "mGBA", true),
          standaloneEmu("RPCS3 Shortcut (Standalone)", false, { bakeable: false, reason: "shortcut_script" }),
          standaloneEmu("Vita3K (Standalone)", false, { bakeable: false, reason: "inject" }),
        ],
      }),
    );
    const its = items(menu);
    const shortcut = its.find((i) => i.text.startsWith("RPCS3 Shortcut"))!;
    expect(shortcut.disabled).toBe(true);
    expect(shortcut.text).toBe("RPCS3 Shortcut (Standalone) — script/shortcut form");
    expect(shortcut.onClick).toBeUndefined();
    const inject = its.find((i) => i.text.startsWith("Vita3K"))!;
    expect(inject.disabled).toBe(true);
    expect(inject.text).toBe("Vita3K (Standalone) — needs setup files (launch via ES-DE once)");
  });

  it("renders a not-installed standalone emulator as disabled with its reason copy", () => {
    const menu = buildEmulatorMenu(
      baseConfig({
        emulators: [
          libretroEmu("mgba_libretro", "mGBA", true),
          standaloneEmu("Ryubing (Standalone)", false, { bakeable: false, reason: "not_installed" }),
        ],
      }),
    );
    const ryubing = items(menu).find((i) => i.text.startsWith("Ryubing"))!;
    expect(ryubing.disabled).toBe(true);
    expect(ryubing.text).toBe("Ryubing (Standalone) — emulator not installed");
    expect(ryubing.onClick).toBeUndefined();
  });

  it("renders a not-installed LIBRETRO core disabled with the same reason copy as standalone — the code path is not kind-special-cased", () => {
    const menu = buildEmulatorMenu(
      baseConfig({
        emulators: [
          libretroEmu("mgba_libretro", "mGBA", true),
          {
            label: "Dolphin",
            kind: "libretro" as const,
            core_so: "dolphin_libretro",
            is_default: false,
            bakeable: false,
            reason: "not_installed",
          },
        ],
      }),
    );
    const dolphin = items(menu).find((i) => i.text.startsWith("Dolphin"))!;
    expect(dolphin.disabled).toBe(true);
    expect(dolphin.text).toBe("Dolphin (RetroArch) — emulator not installed");
    expect(dolphin.onClick).toBeUndefined();
  });

  it("threads activeBackendDisplayName through to a not_installed entry's copy, for both libretro and standalone", () => {
    const menu = buildEmulatorMenu(
      baseConfig({
        activeBackendDisplayName: "EmuDeck",
        emulators: [
          libretroEmu("mgba_libretro", "mGBA", true),
          {
            label: "Dolphin",
            kind: "libretro" as const,
            core_so: "dolphin_libretro",
            is_default: false,
            bakeable: false,
            reason: "not_installed",
          },
          standaloneEmu("Ryubing (Standalone)", false, { bakeable: false, reason: "not_installed" }),
        ],
      }),
    );
    const its = items(menu);
    expect(its.find((i) => i.text.startsWith("Dolphin"))!.text).toBe("Dolphin (RetroArch) — not provided by EmuDeck");
    expect(its.find((i) => i.text.startsWith("Ryubing"))!.text).toBe("Ryubing (Standalone) — not provided by EmuDeck");
  });

  it("dispatches a bakeable standalone emulator's label on pick", () => {
    const onPick = vi.fn();
    const menu = buildEmulatorMenu(
      baseConfig({
        emulators: [standaloneEmu("RPCS3 Directory (Standalone)", true), standaloneEmu("RPCS3 ISO (Standalone)")],
        onPick,
      }),
    );
    const dir = items(menu).find((i) => i.text.startsWith("RPCS3 Directory"))!;
    expect(dir.disabled).toBe(false);
    dir.onClick!();
    expect(onPick).toHaveBeenCalledWith("RPCS3 Directory (Standalone)");
  });

  it("marks the checkmark on the default when no active override is set", () => {
    const menu = buildEmulatorMenu(baseConfig({ activeLabel: null }));
    const mgba = items(menu).find((i) => i.text.startsWith("mGBA"))!;
    expect(mgba.text).toContain("✓");
  });

  it("moves the checkmark onto the active override when one is set", () => {
    const menu = buildEmulatorMenu(baseConfig({ activeLabel: "VBA-M" }));
    const its = items(menu);
    expect(its.find((i) => i.text.startsWith("VBA-M"))!.text).toContain("✓");
    expect(its.find((i) => i.text.startsWith("mGBA"))!.text).not.toContain("✓");
  });

  it("marks the per-platform override with (system)", () => {
    const menu = buildEmulatorMenu(baseConfig({ platformCoreLabel: "VBA-M" }));
    expect(items(menu).find((i) => i.text.startsWith("VBA-M"))!.text).toContain("(system)");
  });

  it("adds the follow-system reset item (game-detail) and fires it", () => {
    const onFollowSystem = vi.fn();
    const menu = buildEmulatorMenu(baseConfig({ followSystem: { hasGameOverride: true, onFollowSystem } }));
    const follow = items(menu).find((i) => i.text.startsWith("Use System Override"))!;
    expect(follow.text).toBe("Use System Override (mGBA)");
    follow.onClick!();
    expect(onFollowSystem).toHaveBeenCalledOnce();
  });

  it("checkmarks the follow-system item when the game already follows the system", () => {
    const menu = buildEmulatorMenu(baseConfig({ followSystem: { hasGameOverride: false, onFollowSystem: vi.fn() } }));
    expect(items(menu).find((i) => i.text.startsWith("Use System Override"))!.text).toContain("✓");
  });

  it("omits the follow-system item on the System page (no followSystem)", () => {
    const menu = buildEmulatorMenu(baseConfig());
    expect(items(menu).some((i) => i.text.startsWith("Use System Override"))).toBe(false);
  });
});
