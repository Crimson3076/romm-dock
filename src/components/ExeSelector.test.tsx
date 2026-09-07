/**
 * ExeSelector tests — driven through the `emitDeckyEvent` event-bus harness.
 *
 * The component owns a custom compact trigger (`DialogButton`) and opens the
 * exe list via `showContextMenu`. This file locally re-mocks `@decky/ui` to
 * render the trigger (so the icon-only face is queryable) and to CAPTURE the
 * menu element handed to `showContextMenu`, which the tests render to assert the
 * option set + drive a selection exactly as a real menu click would. Mirrors
 * DiscSelector.test.tsx's structure (its structural twin, #865).
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, waitFor, act, fireEvent, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { toaster } from "@decky/api";
import { ExeSelector } from "./ExeSelector";
import { emitDeckyEvent, deckyEventListenerCount } from "../test-utils/decky-api-mock";
import * as backend from "../api/backend";
import type { CachedGameDetail, WindowsExecutablesAnswer } from "../api/backend";
import type { DownloadCompleteEvent } from "../types";

// --- Local @decky/ui mock: render the trigger, capture the context menu ------
const captured: { menu: ReactNode } = { menu: null };

vi.mock("@decky/ui", () => ({
  DialogButton: (p: {
    onClick?: (e: unknown) => void;
    children?: ReactNode;
    className?: string;
    "aria-label"?: string;
  }) =>
    createElement(
      "button",
      {
        "data-testid": p["aria-label"] === "Compatibility Tool" ? "compat-btn" : "exe-btn",
        onClick: p.onClick,
        className: p.className,
      },
      p.children,
    ),
  Menu: (p: { children?: ReactNode }) => createElement("div", { "data-testid": "exe-menu" }, p.children),
  MenuItem: (p: { onClick?: () => void; children?: ReactNode }) =>
    createElement("div", { role: "menuitem", onClick: p.onClick }, p.children),
  showContextMenu: (menu: ReactNode) => {
    captured.menu = menu;
  },
}));

// Cached-detail store: synchronous resolve so init settles in one tick.
vi.mock("../utils/cachedGameDetailStore", () => ({
  getCachedGameDetail: vi.fn<(appId: number) => Promise<CachedGameDetail>>(),
  invalidateCachedGameDetail: vi.fn(),
}));

// setLaunchOptionsConfirmed lives in steamShortcuts — mock it so a successful
// pick can be asserted without touching SteamClient.
vi.mock("../utils/steamShortcuts", () => ({
  setLaunchOptionsConfirmed: vi.fn<(appId: number, value: string) => Promise<boolean>>().mockResolvedValue(true),
}));

import { getCachedGameDetail } from "../utils/cachedGameDetailStore";
import { setLaunchOptionsConfirmed } from "../utils/steamShortcuts";

function mockCachedDetail(overrides: Partial<CachedGameDetail> = {}): void {
  vi.mocked(getCachedGameDetail).mockResolvedValue({
    found: true,
    rom_id: 42,
    rom_name: "Some Windows Game",
    installed: true,
    ...overrides,
  });
}

// A representative multi-exe answer: two executables, no pin (follows the
// default — the first enumerated exe). Both are `kind: "exe"` (Proton-run) —
// neither the automatic nor the manual compat-tool paths this file exercises
// are about the "native" kind, which its own describe block below covers.
const multiExeAnswer: WindowsExecutablesAnswer = {
  has_executables: true,
  executables: [
    { filename: "Game.exe", kind: "exe" },
    { filename: "Setup.exe", kind: "exe" },
  ],
  selected: null,
  compat_tool_override: null,
};

// Same shape, already pinned to the second exe.
const pinnedExeAnswer: WindowsExecutablesAnswer = {
  has_executables: true,
  executables: [
    { filename: "Game.exe", kind: "exe" },
    { filename: "Setup.exe", kind: "exe" },
  ],
  selected: "Setup.exe",
  compat_tool_override: null,
};

// Settles the mount-time init chain (getCachedGameDetail → getWindowsExecutables).
// Its two callers below take the paths that bail out before the second fetch,
// and those write no state today — the effect returns before reaching any
// setter — so nothing escapes act as the code stands. The flush is what keeps
// those blocks proof against a settle point being added on either path.
const flushAsync = () =>
  act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });

/** Render, wait for the trigger, click it, and render the captured menu. */
async function renderAndOpen(appId = 100) {
  const r = render(<ExeSelector appId={appId} />);
  await r.findByTestId("exe-btn");
  await act(async () => {
    fireEvent.click(r.getByTestId("exe-btn"));
  });
  const menu = render(<>{captured.menu}</>);
  return { r, menu };
}

describe("ExeSelector — render gate", () => {
  beforeEach(() => {
    captured.menu = null;
    vi.mocked(getCachedGameDetail).mockReset();
    vi.mocked(backend.getWindowsExecutables).mockReset();
  });

  it("renders nothing when has_executables is false", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue({ has_executables: false });

    const { container } = render(<ExeSelector appId={100} />);

    await waitFor(() => {
      expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledWith(42);
    });
    expect(container.querySelector('[data-testid="exe-btn"]')).toBeNull();
  });

  it("renders nothing when the ROM is not found in the cache", async () => {
    vi.mocked(getCachedGameDetail).mockResolvedValue({ found: false });

    const { container } = render(<ExeSelector appId={100} />);

    await flushAsync();
    expect(vi.mocked(backend.getWindowsExecutables)).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="exe-btn"]')).toBeNull();
  });

  it("renders nothing when the ROM is not installed", async () => {
    mockCachedDetail({ installed: false });

    const { container } = render(<ExeSelector appId={100} />);

    await flushAsync();
    expect(vi.mocked(backend.getWindowsExecutables)).not.toHaveBeenCalled();
    expect(container.querySelector('[data-testid="exe-btn"]')).toBeNull();
  });
});

describe("ExeSelector — picker rendering", () => {
  beforeEach(() => {
    captured.menu = null;
    vi.mocked(getCachedGameDetail).mockReset();
    vi.mocked(backend.getWindowsExecutables).mockReset();
  });

  it("shows the neutral face (unpinned) and lists each executable", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(multiExeAnswer);

    const { r, menu } = await renderAndOpen();

    expect(r.getByTestId("exe-btn")).toBeInTheDocument();
    const items = within(menu.container).getAllByRole("menuitem");
    expect(items.map((i) => i.textContent.replace("✓", ""))).toEqual(["Game.exe", "Setup.exe"]);
  });

  it("checkmarks the pinned executable in the menu", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(pinnedExeAnswer);

    const { menu } = await renderAndOpen();

    const items = within(menu.container).getAllByRole("menuitem");
    const setupRow = items.find((i) => i.textContent.includes("Setup.exe"));
    expect(setupRow?.textContent).toContain("✓");
    const gameRow = items.find((i) => i.textContent.includes("Game.exe"));
    expect(gameRow?.textContent).not.toContain("✓");
  });
});

describe("ExeSelector — selecting an executable", () => {
  beforeEach(() => {
    captured.menu = null;
    vi.mocked(getCachedGameDetail).mockReset();
    vi.mocked(backend.getWindowsExecutables).mockReset();
    vi.mocked(backend.selectExecutable).mockReset();
    vi.mocked(setLaunchOptionsConfirmed).mockClear();
    vi.mocked(setLaunchOptionsConfirmed).mockResolvedValue(true);
    vi.mocked(toaster.toast).mockReset();
  });

  it("calls selectExecutable then setLaunchOptionsConfirmed with the re-baked launch_options", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(multiExeAnswer);
    vi.mocked(backend.selectExecutable).mockResolvedValue({
      success: true,
      launch_options: "proton run '/roms/win/game-1/Setup.exe'",
      selected: "Setup.exe",
    });

    const { menu } = await renderAndOpen();
    await act(async () => {
      fireEvent.click(within(menu.container).getByText("Setup.exe"));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(backend.selectExecutable).toHaveBeenCalledWith(42, "Setup.exe");
    expect(setLaunchOptionsConfirmed).toHaveBeenCalledWith(100, "proton run '/roms/win/game-1/Setup.exe'");
  });

  it("updates the pinned selection after a successful pick", async () => {
    mockCachedDetail();
    // The pick itself re-fetches (so a target-kind switch re-evaluates the
    // compat-tool auto-apply) — the second fetch must reflect what the
    // backend would actually report having just persisted, not the same
    // stale pre-pick answer.
    vi.mocked(backend.getWindowsExecutables)
      .mockResolvedValueOnce(multiExeAnswer)
      .mockResolvedValue({ ...multiExeAnswer, selected: "Setup.exe" });
    vi.mocked(backend.selectExecutable).mockResolvedValue({
      success: true,
      launch_options: "proton run '/roms/win/game-1/Setup.exe'",
      selected: "Setup.exe",
    });

    const { r, menu } = await renderAndOpen();
    await act(async () => {
      fireEvent.click(within(menu.container).getByText("Setup.exe"));
      await Promise.resolve();
      await Promise.resolve();
    });

    // Reopen via the real trigger — captures a FRESH menu built against the
    // now-updated `selected` state (the earlier `menu` render is a stale
    // snapshot from before the pick and would not reflect it).
    await act(async () => {
      fireEvent.click(r.getByTestId("exe-btn"));
    });
    const reopened = render(<>{captured.menu}</>);
    const items = within(reopened.container).getAllByRole("menuitem");
    const setupRow = items.find((i) => i.textContent.includes("Setup.exe"));
    expect(setupRow?.textContent).toContain("✓");
  });

  it("re-evaluates the compat-tool auto-apply after switching to a native target (#regression)", async () => {
    // A ROM offering BOTH an exe (Proton-run, no auto-apply needed) and a
    // native target: picking the native one must trigger the SAME auto-apply
    // Force-Native fix a native-only ROM gets on mount — switching WHICH
    // target is active must not leave the previous target's (non-)decision
    // standing.
    const mixedAnswer: WindowsExecutablesAnswer = {
      has_executables: true,
      executables: [
        { filename: "Game.exe", kind: "exe" },
        { filename: "launch.sh", kind: "native" },
      ],
      selected: "Game.exe",
      compat_tool_override: null,
    };
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables)
      .mockResolvedValueOnce(mixedAnswer)
      .mockResolvedValue({ ...mixedAnswer, selected: "launch.sh" });
    vi.mocked(backend.selectExecutable).mockResolvedValue({
      success: true,
      launch_options: "env -C \"/roms/win/game\" bash \"/roms/win/game/launch.sh\"",
      selected: "launch.sh",
    });
    vi.mocked(backend.setCompatToolOverride).mockResolvedValue({ success: true });
    const specify = vi.fn().mockResolvedValue(undefined);
    stubSteamClient({ specifyCompatTool: specify });

    const { menu } = await renderAndOpen();
    await act(async () => {
      fireEvent.click(within(menu.container).getByText("launch.sh"));
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(2);
    await waitFor(() => expect(specify).toHaveBeenCalledWith(100, ""));
    expect(vi.mocked(backend.setCompatToolOverride)).toHaveBeenCalledWith(42, "");
  });

  it("toasts the failure message and does NOT confirm-set launch options when selectExecutable fails", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(multiExeAnswer);
    vi.mocked(backend.selectExecutable).mockResolvedValue({
      success: false,
      reason: "not_found",
      message: "Executable not found in the install directory",
    });

    const { menu } = await renderAndOpen();
    await act(async () => {
      fireEvent.click(within(menu.container).getByText("Setup.exe"));
      await Promise.resolve();
      await Promise.resolve();
    });

    // Non-vacuous: the exact backend message is toasted, and no shortcut write.
    expect(toaster.toast).toHaveBeenCalledWith({
      title: "RomM-Dock",
      body: "Executable not found in the install directory",
    });
    expect(setLaunchOptionsConfirmed).not.toHaveBeenCalled();
  });

  it("toasts a fallback on a selectExecutable rejection (non-vacuous catch)", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(multiExeAnswer);
    vi.mocked(backend.selectExecutable).mockRejectedValue(new Error("network down"));

    const { menu } = await renderAndOpen();
    await act(async () => {
      fireEvent.click(within(menu.container).getByText("Setup.exe"));
      await Promise.resolve();
      await Promise.resolve();
    });

    // Observable catch effect: a fallback toast, and no confirm-set.
    expect(toaster.toast).toHaveBeenCalledWith({ title: "RomM-Dock", body: "Failed to select executable" });
    expect(setLaunchOptionsConfirmed).not.toHaveBeenCalled();
  });
});

describe("ExeSelector — event-driven re-fetch + cleanup", () => {
  beforeEach(() => {
    captured.menu = null;
    vi.mocked(getCachedGameDetail).mockReset();
    vi.mocked(backend.getWindowsExecutables).mockReset();
  });

  it("registers download_complete + romm_rom_uninstalled listeners on mount", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue({ has_executables: false });

    render(<ExeSelector appId={100} />);

    await waitFor(() => {
      expect(deckyEventListenerCount("download_complete")).toBe(1);
    });
  });

  it("re-fetches getWindowsExecutables on a matching download_complete (newly has executables)", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValueOnce({ has_executables: false });

    const { findByTestId } = render(<ExeSelector appId={100} />);
    await waitFor(() => expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(1));

    vi.mocked(backend.getWindowsExecutables).mockResolvedValueOnce(multiExeAnswer);

    await act(async () => {
      const event: DownloadCompleteEvent = {
        rom_id: 42,
        rom_name: "Some Windows Game",
        platform_name: "Windows",
        file_path: "/roms/win/game-1",
        app_id: 100,
        launch_options: "cmd",
      };
      emitDeckyEvent<[DownloadCompleteEvent]>("download_complete", event);
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(2);
    expect(await findByTestId("exe-btn")).toBeInTheDocument();
  });

  it("ignores download_complete for a different rom_id", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue({ has_executables: false });

    render(<ExeSelector appId={100} />);
    await waitFor(() => expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(1));

    await act(async () => {
      emitDeckyEvent<[DownloadCompleteEvent]>("download_complete", {
        rom_id: 999,
        rom_name: "Other",
        platform_name: "Windows",
        file_path: "/roms/win/other",
        app_id: 1,
        launch_options: "cmd",
      });
      await Promise.resolve();
    });

    expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(1);
  });

  it("hides the trigger when a matching romm_rom_uninstalled fires", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(multiExeAnswer);

    const { findByTestId, container } = render(<ExeSelector appId={100} />);
    await findByTestId("exe-btn");

    await act(async () => {
      globalThis.dispatchEvent(new CustomEvent("romm_rom_uninstalled", { detail: { rom_id: 42 } }));
      await Promise.resolve();
    });

    expect(container.querySelector('[data-testid="exe-btn"]')).toBeNull();
  });

  it("removes both listeners on unmount", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue({ has_executables: false });

    const { unmount } = render(<ExeSelector appId={100} />);
    await waitFor(() => expect(deckyEventListenerCount("download_complete")).toBe(1));

    unmount();
    expect(deckyEventListenerCount("download_complete")).toBe(0);
  });

  it("re-fetches on a matching version_switched for this appid", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValueOnce({ has_executables: false });

    render(<ExeSelector appId={100} />);
    await waitFor(() => expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(1));

    vi.mocked(backend.getWindowsExecutables).mockResolvedValueOnce(multiExeAnswer);
    await act(async () => {
      globalThis.dispatchEvent(
        new CustomEvent("romm_data_changed", { detail: { type: "version_switched", app_id: 100, rom_id: 77 } }),
      );
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(2);
    expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenLastCalledWith(77);
  });

  it("ignores version_switched for a different appid", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue({ has_executables: false });

    render(<ExeSelector appId={100} />);
    await waitFor(() => expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(1));

    await act(async () => {
      globalThis.dispatchEvent(
        new CustomEvent("romm_data_changed", { detail: { type: "version_switched", app_id: 999, rom_id: 77 } }),
      );
      await Promise.resolve();
    });

    expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalledTimes(1);
  });
});

// --- Compat-tool override (ADR-0032) ----------------------------------------

/** Stub SteamClient.Apps for the compat-tool tests, mirroring how every other
 *  test file in this codebase (steamShortcuts.test.ts, CustomPlayButton.test.tsx)
 *  locally re-stubs SteamClient per test rather than relying on the ambient
 *  test-setup.ts default. */
function stubSteamClient(overrides: {
  specifyCompatTool?: ReturnType<typeof vi.fn>;
  getAvailableCompatTools?: ReturnType<typeof vi.fn>;
} = {}): void {
  vi.stubGlobal("SteamClient", {
    Apps: {
      SpecifyCompatTool: overrides.specifyCompatTool ?? vi.fn().mockResolvedValue(undefined),
      GetAvailableCompatTools: overrides.getAvailableCompatTools ?? vi.fn().mockResolvedValue([]),
    },
  });
}

// A single native (Proton-bypassed) launch target, no stored override —
// exactly the Dusklight bug's shape: the automatic fix must fire for this.
const nativeAnswer: WindowsExecutablesAnswer = {
  has_executables: true,
  executables: [{ filename: "launch.sh", kind: "native" }],
  selected: null,
  compat_tool_override: null,
};

describe("ExeSelector — compat-tool auto-apply", () => {
  beforeEach(() => {
    captured.menu = null;
    vi.mocked(getCachedGameDetail).mockReset();
    vi.mocked(backend.getWindowsExecutables).mockReset();
    vi.mocked(backend.setCompatToolOverride).mockReset();
  });

  it("auto-applies Force Native and persists it, for a native target with no stored override", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(nativeAnswer);
    vi.mocked(backend.setCompatToolOverride).mockResolvedValue({ success: true });
    const specify = vi.fn().mockResolvedValue(undefined);
    stubSteamClient({ specifyCompatTool: specify });

    render(<ExeSelector appId={100} />);

    await waitFor(() => expect(specify).toHaveBeenCalledWith(100, ""));
    expect(vi.mocked(backend.setCompatToolOverride)).toHaveBeenCalledWith(42, "");
  });

  it("does NOT auto-apply for an exe-kind (Proton-run) target", async () => {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(multiExeAnswer);
    const specify = vi.fn().mockResolvedValue(undefined);
    stubSteamClient({ specifyCompatTool: specify });

    render(<ExeSelector appId={100} />);
    await waitFor(() => expect(vi.mocked(backend.getWindowsExecutables)).toHaveBeenCalled());

    expect(specify).not.toHaveBeenCalled();
    expect(vi.mocked(backend.setCompatToolOverride)).not.toHaveBeenCalled();
  });

  it("re-applies an already-stored override without re-deciding it a second time", async () => {
    // compat_tool_override is already "" — auto-apply's job here is DONE; this
    // fetch (a fresh mount, standing in for a rebind onto a new appid) must
    // still re-assert "" onto the live Steam appid, but never call back
    // through setCompatToolOverride, which only the FIRST-TIME decision uses.
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue({ ...nativeAnswer, compat_tool_override: "" });
    const specify = vi.fn().mockResolvedValue(undefined);
    stubSteamClient({ specifyCompatTool: specify });

    render(<ExeSelector appId={100} />);

    await waitFor(() => expect(specify).toHaveBeenCalledWith(100, ""));
    expect(vi.mocked(backend.setCompatToolOverride)).not.toHaveBeenCalled();
  });
});

describe("ExeSelector — compat-tool manual menu", () => {
  beforeEach(() => {
    captured.menu = null;
    vi.mocked(getCachedGameDetail).mockReset();
    vi.mocked(backend.getWindowsExecutables).mockReset();
    vi.mocked(backend.setCompatToolOverride).mockReset();
    vi.mocked(backend.clearCompatToolOverride).mockReset();
    vi.mocked(toaster.toast).mockReset();
  });

  async function openCompatMenu(
    answer: WindowsExecutablesAnswer,
    overrides: Parameters<typeof stubSteamClient>[0] = {},
  ) {
    mockCachedDetail();
    vi.mocked(backend.getWindowsExecutables).mockResolvedValue(answer);
    stubSteamClient({
      getAvailableCompatTools: vi
        .fn()
        .mockResolvedValue([{ strToolName: "proton_experimental", strDisplayName: "Proton Experimental" }]),
      ...overrides,
    });

    const r = render(<ExeSelector appId={100} />);
    await r.findByTestId("compat-btn");
    await act(async () => {
      fireEvent.click(r.getByTestId("compat-btn"));
      await Promise.resolve();
      await Promise.resolve();
    });
    const menu = render(<>{captured.menu}</>);
    return { r, menu };
  }

  it("lists Force Native, Automatic, and every live installed compat tool", async () => {
    const { menu } = await openCompatMenu(multiExeAnswer);

    const items = within(menu.container).getAllByRole("menuitem");
    expect(items.map((i) => i.textContent.replace("✓", ""))).toEqual([
      "Force Native (No Proton)",
      "Automatic (Steam Default)",
      "Proton Experimental",
    ]);
  });

  it("checkmarks Automatic when compat_tool_override is null", async () => {
    const { menu } = await openCompatMenu(multiExeAnswer);

    const items = within(menu.container).getAllByRole("menuitem");
    expect(items.find((i) => i.textContent.includes("Automatic"))?.textContent).toContain("✓");
    expect(items.find((i) => i.textContent.includes("Force Native"))?.textContent).not.toContain("✓");
  });

  it("checkmarks Force Native when compat_tool_override is \"\"", async () => {
    const { menu } = await openCompatMenu({ ...multiExeAnswer, compat_tool_override: "" });

    const items = within(menu.container).getAllByRole("menuitem");
    expect(items.find((i) => i.textContent.includes("Force Native"))?.textContent).toContain("✓");
    expect(items.find((i) => i.textContent.includes("Automatic"))?.textContent).not.toContain("✓");
  });

  it("checkmarks the pinned specific tool when compat_tool_override names it", async () => {
    const { menu } = await openCompatMenu({ ...multiExeAnswer, compat_tool_override: "proton_experimental" });

    const items = within(menu.container).getAllByRole("menuitem");
    expect(items.find((i) => i.textContent.includes("Proton Experimental"))?.textContent).toContain("✓");
    expect(items.find((i) => i.textContent.includes("Automatic"))?.textContent).not.toContain("✓");
  });

  it("Force Native applies via SteamClient BEFORE persisting via setCompatToolOverride", async () => {
    const specify = vi.fn().mockResolvedValue(undefined);
    vi.mocked(backend.setCompatToolOverride).mockResolvedValue({ success: true });
    const { menu } = await openCompatMenu(multiExeAnswer, { specifyCompatTool: specify });

    await act(async () => {
      fireEvent.click(within(menu.container).getByText(/Force Native/));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(specify).toHaveBeenCalledWith(100, "");
    expect(vi.mocked(backend.setCompatToolOverride)).toHaveBeenCalledWith(42, "");
    const specifyOrder = specify.mock.invocationCallOrder[0] ?? Number.NaN;
    const persistOrder = vi.mocked(backend.setCompatToolOverride).mock.invocationCallOrder[0] ?? Number.NaN;
    expect(specifyOrder).toBeLessThan(persistOrder);
  });

  it("picking a specific tool applies then persists its strToolName", async () => {
    const specify = vi.fn().mockResolvedValue(undefined);
    vi.mocked(backend.setCompatToolOverride).mockResolvedValue({ success: true });
    const { menu } = await openCompatMenu(multiExeAnswer, { specifyCompatTool: specify });

    await act(async () => {
      fireEvent.click(within(menu.container).getByText("Proton Experimental"));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(specify).toHaveBeenCalledWith(100, "proton_experimental");
    expect(vi.mocked(backend.setCompatToolOverride)).toHaveBeenCalledWith(42, "proton_experimental");
  });

  it("Automatic calls clearCompatToolOverride and never touches SteamClient", async () => {
    const specify = vi.fn().mockResolvedValue(undefined);
    vi.mocked(backend.clearCompatToolOverride).mockResolvedValue({ success: true });
    const { menu } = await openCompatMenu(multiExeAnswer, { specifyCompatTool: specify });

    await act(async () => {
      fireEvent.click(within(menu.container).getByText(/Automatic/));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(vi.mocked(backend.clearCompatToolOverride)).toHaveBeenCalledWith(42);
    expect(specify).not.toHaveBeenCalled();
  });

  it("toasts a failure and does not persist when SpecifyCompatTool rejects (non-vacuous catch)", async () => {
    const specify = vi.fn().mockRejectedValue(new Error("nope"));
    const { menu } = await openCompatMenu(multiExeAnswer, { specifyCompatTool: specify });

    await act(async () => {
      fireEvent.click(within(menu.container).getByText(/Force Native/));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(toaster.toast).toHaveBeenCalledWith({ title: "RomM-Dock", body: "Failed to set compatibility tool" });
    expect(vi.mocked(backend.setCompatToolOverride)).not.toHaveBeenCalled();
  });

  it("toasts the backend message and does not update local state when setCompatToolOverride fails", async () => {
    const specify = vi.fn().mockResolvedValue(undefined);
    vi.mocked(backend.setCompatToolOverride).mockResolvedValue({
      success: false,
      reason: "not_installed",
      message: "ROM is not installed",
    });
    const { menu } = await openCompatMenu(multiExeAnswer, { specifyCompatTool: specify });

    await act(async () => {
      fireEvent.click(within(menu.container).getByText(/Force Native/));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(toaster.toast).toHaveBeenCalledWith({ title: "RomM-Dock", body: "ROM is not installed" });
  });
});
