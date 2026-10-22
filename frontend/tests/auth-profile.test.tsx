import { act, render, screen } from "@testing-library/react";
import { useContext } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// One signed-in session; /auth/me is scripted per test.
const SESSION = { access_token: "tok", user: { id: "u1" } };
const me = vi.hoisted(() => ({ results: [] as (unknown | Error)[], calls: 0 }));
const authEvents = vi.hoisted(() => ({
  refreshing: false,
  listener: null as null | ((event: string, session: typeof SESSION) => void),
}));
vi.mock("@/lib/auth-fetch", () => ({ isSessionRefreshInProgress: () => authEvents.refreshing }));
vi.mock("@/lib/supabase", () => ({
  supabase: { auth: {
    getSession: () => Promise.resolve({ data: { session: SESSION } }),
    onAuthStateChange: (listener: typeof authEvents.listener) => {
      authEvents.listener = listener;
      return { data: { subscription: { unsubscribe: () => {} } } };
    },
  } },
}));
vi.mock("@/services/auth.service", () => ({ signOut: () => Promise.resolve() }));
vi.mock("@/lib/api", async () => {
  class ApiError extends Error { constructor(public status: number, message: string) { super(message); } }
  return {
    ApiError,
    getMe: () => {
      const next = me.results[Math.min(me.calls++, me.results.length - 1)];
      const isProfile = typeof next === "object" && next !== null && "role" in next;
      return isProfile ? Promise.resolve(next) : Promise.reject(next);
    },
  };
});

import { AuthContext, AuthProvider } from "@/contexts/AuthContext";
import { ApiError } from "@/lib/api";

function Role() {
  const ctx = useContext(AuthContext);
  return <p>{ctx?.profileLoading ? "loading" : ctx?.profile?.role ?? "no profile"}</p>;
}
const ADMIN = { id: "u1", email: "a@x.com", first_name: "A", last_name: "", full_name: "A", role: "Admin", tenant_id: "t1" };

async function mount() {
  render(<AuthProvider><Role /></AuthProvider>);
  await act(async () => { await vi.advanceTimersByTimeAsync(7000); });
}

describe("Profile loading", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    me.calls = 0;
    authEvents.refreshing = false;
    const storage = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => storage.set(key, value),
      removeItem: (key: string) => storage.delete(key),
      clear: () => storage.clear(),
    });
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("retries a transient failure instead of dropping to Learner", async () => {
    me.results = [new TypeError("Failed to fetch"), ADMIN];
    await mount();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(me.calls).toBe(2);
  });

  it("keeps the last verified role when the backend never answers", async () => {
    localStorage.setItem("zoiko_profile", JSON.stringify(ADMIN));
    me.results = [new DOMException("timed out", "TimeoutError")];
    await mount();
    expect(screen.getByText("Admin")).toBeInTheDocument();
    expect(me.calls).toBe(3);
  });

  it("drops the profile when the server refuses it", async () => {
    localStorage.setItem("zoiko_profile", JSON.stringify(ADMIN));
    me.results = [new ApiError(401, "Could not fetch current user")];
    await mount();
    expect(screen.getByText("no profile")).toBeInTheDocument();
    expect(me.calls).toBe(1);
  });

  it("fails closed when nothing was ever verified", async () => {
    me.results = [new TypeError("Failed to fetch")];
    await mount();
    expect(screen.getByText("no profile")).toBeInTheDocument();
  });

  it("does not reload a refused profile for a request's own token refresh", async () => {
    me.results = [new ApiError(401, "Unauthorized")];
    await mount();
    authEvents.refreshing = true;
    await act(async () => {
      authEvents.listener?.("TOKEN_REFRESHED", { ...SESSION, access_token: "renewed" });
    });
    expect(me.calls).toBe(1);
    expect(screen.getByText("no profile")).toBeInTheDocument();
  });

  it("reloads a missing profile after an independent provisioning refresh", async () => {
    me.results = [new ApiError(401, "Unauthorized"), ADMIN];
    await mount();
    await act(async () => {
      authEvents.listener?.("TOKEN_REFRESHED", { ...SESSION, access_token: "provisioned" });
    });
    expect(me.calls).toBe(2);
    expect(screen.getByText("Admin")).toBeInTheDocument();
  });
});
