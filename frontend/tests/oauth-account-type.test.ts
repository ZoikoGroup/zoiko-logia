import { beforeEach, describe, expect, it, vi } from "vitest";

// "Continue with Google" from the login card carries no "Myself / My company"
// choice. That used to create a company workspace with the person as Admin;
// it must create an individual Learner account instead.
const calls = vi.hoisted(() => ({ provision: vi.fn(), signIn: vi.fn(), signOut: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  provisionProfile: calls.provision,
}));
vi.mock("@/lib/supabase", () => ({
  isSupabaseConfigured: () => true,
  supabase: { auth: { refreshSession: vi.fn(), signInWithPassword: calls.signIn, signOut: calls.signOut } },
}));

import { provisionAndRefresh, rememberSignupChoice, signInWithPassword } from "@/services/auth.service";
import { ApiError } from "@/lib/api";

beforeEach(() => {
  calls.provision.mockReset().mockResolvedValue({ role: "Learner" });
  calls.signOut.mockReset().mockResolvedValue({ error: null });
  calls.signIn.mockResolvedValue({ data: {
    session: { access_token: "token" }, user: { email_confirmed_at: "2026-01-01", user_metadata: {} },
  }, error: null });
  sessionStorage.clear();
});

it.each([403, 409, 422])("clears an incomplete sign-in and preserves the server's %s explanation", async (status) => {
  const message = "Account setup needs attention";
  calls.provision.mockRejectedValue(new ApiError(status, message));
  await expect(signInWithPassword("a@example.com", "password")).rejects.toThrow(message);
  expect(calls.signOut).toHaveBeenCalledOnce();
});

it("clears a rejected session and asks the user to sign in again on 401", async () => {
  calls.provision.mockRejectedValue(new ApiError(401, "Unauthorized"));
  await expect(signInWithPassword("a@example.com", "password")).rejects.toThrow(
    "Your session could not be validated by the server. Please sign in again.",
  );
  expect(calls.signOut).toHaveBeenCalledOnce();
});

const sent = () => calls.provision.mock.calls[0][1];

describe("OAuth first sign-in account type", () => {
  it("is an individual account when no choice was made", async () => {
    await provisionAndRefresh("t", { full_name: "Asha Rao", email: "a@example.com" });
    expect(sent()).toMatchObject({ account_type: "individual", adult_confirmed: false, first_name: "Asha" });
  });

  it("passes the adult confirmation given on the callback page", async () => {
    await provisionAndRefresh("t", {}, { adultConfirmed: true });
    expect(sent()).toMatchObject({ account_type: "individual", adult_confirmed: true });
  });

  it("never asks for a company workspace from a Google sign-in, even with a stale choice", async () => {
    rememberSignupChoice({ accountType: "company", adultConfirmed: true });
    await provisionAndRefresh("t", { full_name: "Asha Rao" });
    expect(sent()).toMatchObject({ account_type: "individual", adult_confirmed: true });
  });

  it("keeps the choice made at email sign-up", async () => {
    await provisionAndRefresh("t", { account_type: "company", company_name: "Acme" });
    expect(sent()).toMatchObject({ account_type: "company", company_name: "Acme" });
  });
});
