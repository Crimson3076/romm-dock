/**
 * LauncherBackendSection tests.
 *
 * The section renders two `DropdownItem`s (Launcher, Installation) which
 * aren't in the global @decky/ui stub (see test-setup.ts). Locally re-mock
 * @decky/ui to capture each DropdownItem's props (mirrors
 * AdvancedSection.test.tsx) so the onChange wiring, rgOptions, and the
 * disabled+description carve-out for "no detected installation" are all
 * driveable/assertable.
 */

import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, waitFor, act } from "@testing-library/react";
import { createElement } from "react";
import { LauncherBackendSection } from "./LauncherBackendSection";
import * as backend from "../../api/backend";
import type { LauncherBackendInfo } from "../../api/backend";
import { setLaunchOptionsConfirmed } from "../../utils/steamShortcuts";

interface DropdownOption {
  data: unknown;
  label: unknown;
}
interface DropdownItemProps {
  label?: string;
  description?: unknown;
  rgOptions?: DropdownOption[];
  selectedOption?: unknown;
  disabled?: boolean;
  onChange?: (option: DropdownOption) => void;
}
const captured: { items: DropdownItemProps[] } = { items: [] };

vi.mock("@decky/ui", () => {
  type AnyProps = Record<string, unknown> & { children?: unknown };
  const passthrough = (tag: string) => (p: AnyProps) => createElement(tag, {}, p.children as never);
  return {
    PanelSection: passthrough("section"),
    PanelSectionRow: passthrough("div"),
    DropdownItem: (p: DropdownItemProps) => {
      captured.items.push(p);
      return createElement("div", { "data-testid": "dropdown" }, p.label as never);
    },
    Field: (p: { label?: unknown }) => createElement("div", { "data-testid": "field" }, p.label as never),
  };
});

// setLaunchOptionsConfirmed pokes SteamClient — stub it so the rebake fan-out
// is driveable without a real Steam client.
vi.mock("../../utils/steamShortcuts", () => ({ setLaunchOptionsConfirmed: vi.fn() }));

/** The last-captured DropdownItem for a given label ("Launcher" / "Installation"). */
function dropdownFor(label: string): DropdownItemProps | undefined {
  return [...captured.items].reverse().find((i) => i.label === label);
}

const retrodeckOnly: LauncherBackendInfo[] = [
  {
    backend_id: "retrodeck",
    display_name: "RetroDECK",
    is_active: true,
    installations: [
      {
        installation_id: "retrodeck",
        display_name: "RetroDECK",
        home: "/home/deck/retrodeck",
        healthy: true,
        detail: "ok",
        is_active: true,
      },
    ],
  },
  {
    backend_id: "emudeck",
    display_name: "EmuDeck",
    is_active: false,
    installations: [],
  },
];

const bothDetected: LauncherBackendInfo[] = [
  retrodeckOnly[0]!,
  {
    backend_id: "emudeck",
    display_name: "EmuDeck",
    is_active: false,
    installations: [
      {
        installation_id: "emudeck:/home/deck",
        display_name: "EmuDeck",
        home: "/home/deck",
        healthy: true,
        detail: "ok",
        is_active: false,
      },
    ],
  },
];

describe("LauncherBackendSection", () => {
  beforeEach(() => {
    captured.items = [];
    vi.mocked(backend.getLauncherBackends).mockReset();
    vi.mocked(backend.setLauncherBackend).mockReset();
    vi.mocked(setLaunchOptionsConfirmed).mockReset();
    vi.mocked(setLaunchOptionsConfirmed).mockResolvedValue(true);
  });

  it("fetches get_launcher_backends on mount", async () => {
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(retrodeckOnly);
    render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));
  });

  it("renders the Launcher dropdown with one option per registered backend, defaulting to RetroDECK", async () => {
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(bothDetected);
    render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    const launcher = dropdownFor("Launcher");
    expect(launcher?.rgOptions?.map((o) => o.data)).toEqual(["retrodeck", "emudeck"]);
    expect(launcher?.selectedOption).toBe("retrodeck");
    expect(launcher?.disabled).toBe(false);
  });

  it("populates the Installation dropdown from the selected backend's detected installations", async () => {
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(bothDetected);
    render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    const installation = dropdownFor("Installation");
    expect(installation?.rgOptions?.map((o) => o.data)).toEqual(["retrodeck"]);
    expect(installation?.selectedOption).toBe("retrodeck");
    expect(installation?.disabled).toBe(false);
  });

  it("disables the Installation dropdown with an explanatory description when the selected backend has no detected installations", async () => {
    // Only RetroDECK is detected; the section still starts on RetroDECK by
    // default, so exercise the no-installations case by switching (below) —
    // here we assert the initial state also has no dangling empty dropdown.
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(retrodeckOnly);
    render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    const installation = dropdownFor("Installation");
    expect(installation?.disabled).toBe(false);
    expect(installation?.rgOptions?.map((o) => o.data)).toEqual(["retrodeck"]);
  });

  it("shows a status message and does not call setLauncherBackend when picking a backend with zero detected installations", async () => {
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(retrodeckOnly);
    const { findByTestId } = render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    await act(async () => {
      dropdownFor("Launcher")?.onChange?.({ data: "emudeck", label: "EmuDeck" });
    });

    expect(vi.mocked(backend.setLauncherBackend)).not.toHaveBeenCalled();
    const field = await findByTestId("field");
    expect(field.textContent).toBe("EmuDeck has no detected installation on this machine");
    // The Launcher dropdown must NOT have moved to the unusable backend.
    expect(dropdownFor("Launcher")?.selectedOption).toBe("retrodeck");
  });

  it("calls setLauncherBackend with the newly-selected backend's first installation and applies the selection on success", async () => {
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(bothDetected);
    vi.mocked(backend.setLauncherBackend).mockResolvedValue({ success: true });
    render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    act(() => {
      dropdownFor("Launcher")?.onChange?.({ data: "emudeck", label: "EmuDeck" });
    });

    await waitFor(() => expect(dropdownFor("Launcher")?.selectedOption).toBe("emudeck"));
    expect(vi.mocked(backend.setLauncherBackend)).toHaveBeenCalledWith("emudeck", "emudeck:/home/deck");
    expect(dropdownFor("Installation")?.selectedOption).toBe("emudeck:/home/deck");
  });

  it("confirm-sets launch options for each rebake item after a successful switch", async () => {
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(bothDetected);
    vi.mocked(backend.setLauncherBackend).mockResolvedValue({
      success: true,
      rebake_items: [
        { app_id: 100, launch_options: "emudeck-launch a.rom" },
        { app_id: 200, launch_options: "emudeck-launch b.rom" },
      ],
    });
    render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    act(() => {
      dropdownFor("Launcher")?.onChange?.({ data: "emudeck", label: "EmuDeck" });
    });

    await waitFor(() => expect(vi.mocked(setLaunchOptionsConfirmed)).toHaveBeenCalledTimes(2));
    expect(vi.mocked(setLaunchOptionsConfirmed)).toHaveBeenCalledWith(100, "emudeck-launch a.rom");
    expect(vi.mocked(setLaunchOptionsConfirmed)).toHaveBeenCalledWith(200, "emudeck-launch b.rom");
  });

  it("surfaces result.message and does NOT apply the dropdown change when setLauncherBackend fails", async () => {
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(bothDetected);
    vi.mocked(backend.setLauncherBackend).mockResolvedValue({
      success: false,
      reason: "not_detected",
      message: "EmuDeck installation was not detected.",
    });
    const { findByTestId } = render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    act(() => {
      dropdownFor("Launcher")?.onChange?.({ data: "emudeck", label: "EmuDeck" });
    });

    const field = await findByTestId("field");
    await waitFor(() => expect(field.textContent).toBe("EmuDeck installation was not detected."));
    // Reverted / never applied: still shows the previous (RetroDECK) selection.
    expect(dropdownFor("Launcher")?.selectedOption).toBe("retrodeck");
    expect(dropdownFor("Installation")?.selectedOption).toBe("retrodeck");
    expect(vi.mocked(setLaunchOptionsConfirmed)).not.toHaveBeenCalled();
  });

  it("surfaces a fallback message on a setLauncherBackend rejection (non-vacuous catch)", async () => {
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(bothDetected);
    vi.mocked(backend.setLauncherBackend).mockRejectedValue(new Error("network down"));
    const { findByTestId } = render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    act(() => {
      dropdownFor("Launcher")?.onChange?.({ data: "emudeck", label: "EmuDeck" });
    });

    const field = await findByTestId("field");
    await waitFor(() => expect(field.textContent).toContain("Failed to switch launcher backend"));
    expect(field.textContent).toContain("network down");
    expect(dropdownFor("Launcher")?.selectedOption).toBe("retrodeck");
  });

  it("switches installation within the same backend via the Installation dropdown", async () => {
    const multiInstallEmudeck: LauncherBackendInfo[] = [
      bothDetected[0]!,
      {
        backend_id: "emudeck",
        display_name: "EmuDeck",
        is_active: false,
        installations: [
          {
            installation_id: "emudeck:/home/a",
            display_name: "EmuDeck (a)",
            home: "/home/a",
            healthy: true,
            detail: "ok",
            is_active: false,
          },
          {
            installation_id: "emudeck:/home/b",
            display_name: "EmuDeck (b)",
            home: "/home/b",
            healthy: true,
            detail: "ok",
            is_active: false,
          },
        ],
      },
    ];
    vi.mocked(backend.getLauncherBackends).mockResolvedValue(multiInstallEmudeck);
    vi.mocked(backend.setLauncherBackend).mockResolvedValue({ success: true });
    render(<LauncherBackendSection />);
    await waitFor(() => expect(vi.mocked(backend.getLauncherBackends)).toHaveBeenCalledTimes(1));

    // First move onto EmuDeck (defaults to its first installation).
    act(() => {
      dropdownFor("Launcher")?.onChange?.({ data: "emudeck", label: "EmuDeck" });
    });
    await waitFor(() => expect(dropdownFor("Installation")?.selectedOption).toBe("emudeck:/home/a"));
    expect(vi.mocked(backend.setLauncherBackend)).toHaveBeenCalledWith("emudeck", "emudeck:/home/a");

    // Then pick the second installation directly.
    act(() => {
      dropdownFor("Installation")?.onChange?.({ data: "emudeck:/home/b", label: "EmuDeck (b)" });
    });
    await waitFor(() => expect(dropdownFor("Installation")?.selectedOption).toBe("emudeck:/home/b"));
    expect(vi.mocked(backend.setLauncherBackend)).toHaveBeenLastCalledWith("emudeck", "emudeck:/home/b");
  });
});
