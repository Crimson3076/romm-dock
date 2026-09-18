import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import {
  getBackendReadinessState,
  onBackendReadinessChange,
  refreshBackendReadiness,
  useBackendReadiness,
} from "./backendReadinessStore";
import * as backend from "../api/backend";

vi.mock("../api/backend", () => ({
  getBackendReadiness: vi.fn(),
  logError: vi.fn(),
}));

const OK = {
  backend: "retrodeck",
  backend_installed: true,
  retroarch_installed: true,
  message: "RetroDECK and RetroArch are both installed.",
};

const NOT_READY = {
  backend: "retrodeck",
  backend_installed: false,
  retroarch_installed: true,
  message: "RetroDECK was not found on this device — games will fail to launch until it is installed.",
};

describe("backendReadinessStore", () => {
  beforeEach(() => {
    vi.mocked(backend.getBackendReadiness).mockReset();
    vi.mocked(backend.logError).mockReset();
  });

  it("publishes the probed state", async () => {
    vi.mocked(backend.getBackendReadiness).mockResolvedValueOnce(OK);
    await refreshBackendReadiness();
    expect(getBackendReadinessState()).toEqual(OK);
  });

  it("leaves the previous verdict in place on a failed probe", async () => {
    vi.mocked(backend.getBackendReadiness).mockResolvedValueOnce(NOT_READY);
    await refreshBackendReadiness();
    expect(getBackendReadinessState()).toEqual(NOT_READY);

    vi.mocked(backend.getBackendReadiness).mockRejectedValueOnce(new Error("bridge down"));
    await refreshBackendReadiness();
    expect(getBackendReadinessState()).toEqual(NOT_READY);
    expect(backend.logError).toHaveBeenCalledWith(expect.stringContaining("refreshBackendReadiness failed"));
  });

  it("notifies subscribers on every refresh", async () => {
    let calls = 0;
    const unsub = onBackendReadinessChange(() => {
      calls += 1;
    });
    vi.mocked(backend.getBackendReadiness).mockResolvedValueOnce(OK);
    await refreshBackendReadiness();
    expect(calls).toBe(1);
    unsub();
    vi.mocked(backend.getBackendReadiness).mockResolvedValueOnce(NOT_READY);
    await refreshBackendReadiness();
    expect(calls).toBe(1);
  });

  describe("useBackendReadiness", () => {
    it("re-renders on a refresh", async () => {
      vi.mocked(backend.getBackendReadiness).mockResolvedValueOnce(OK);
      const { result, unmount } = renderHook(() => useBackendReadiness());
      await act(async () => {
        await refreshBackendReadiness();
      });
      expect(result.current).toEqual(OK);
      unmount();
    });
  });
});
