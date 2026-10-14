import { afterEach, beforeEach, expect, it, vi } from "vitest";
const auth = vi.hoisted(() => ({ refreshSession: vi.fn(), getSession: vi.fn() }));
vi.mock("@/lib/supabase", () => ({ supabase: { auth } }));
import { fetchWithSession } from "@/lib/auth-fetch";
import { setCurrentAccessToken } from "@/lib/session-token";
beforeEach(() => { vi.clearAllMocks(); setCurrentAccessToken("old"); });
afterEach(() => vi.unstubAllGlobals());
it("shares one refresh across expired audit and safety requests", async () => {
  let resolve: (value: unknown) => void = () => {};
  auth.refreshSession.mockImplementation(() => new Promise(r => { resolve = r; }));
  const fetcher = vi.fn().mockImplementation((_url, init) => Promise.resolve(new Response("{}", { status: init.headers.get("Authorization") === "Bearer fresh" ? 200 : 401 })));
  vi.stubGlobal("fetch", fetcher);
  const requests = [fetchWithSession("/audit/events", "old"), fetchWithSession("/safety/summary", "old")];
  await vi.waitFor(() => expect(auth.refreshSession).toHaveBeenCalledTimes(1));
  resolve({ data: { session: { access_token: "fresh" } }, error: null });
  expect((await Promise.all(requests)).map(r => r.status)).toEqual([200, 200]);
  expect(fetcher).toHaveBeenCalledTimes(4);
});
it("does not loop when the renewed token is rejected", async () => {
  auth.refreshSession.mockResolvedValue({ data: { session: { access_token: "fresh" } }, error: null });
  const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 401 }));
  vi.stubGlobal("fetch", fetcher);
  expect((await fetchWithSession("/audit/events", "old")).status).toBe(401);
  expect(fetcher).toHaveBeenCalledTimes(2);
});
it("does not refresh a permission denial", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("{}", { status: 403 })));
  expect((await fetchWithSession("/audit/events", "old")).status).toBe(403);
  expect(auth.refreshSession).not.toHaveBeenCalled();
});
it("waits for the session and never sends an empty bearer token", async () => {
  auth.getSession.mockResolvedValue({ data: { session: null } });
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  await expect(fetchWithSession("/safety/summary", "")).rejects.toThrow("Sign in");
  expect(fetcher).not.toHaveBeenCalled();
});
