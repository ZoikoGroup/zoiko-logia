import { beforeEach, describe, expect, it, vi } from "vitest";

// "Continue with Google" from the login card carries no "Myself / My company"
// choice. That used to create a company workspace with the person as Admin;
// it must create an individual Learner account instead.
const calls = vi.hoisted(() => ({ provision: vi.fn() }));
vi.mock("@/lib/api", async (orig) => ({
  ...(await orig<typeof import("@/lib/api")>()),
  provisionProfile: calls.provision,
}));
vi.mock("@/lib/supabase", () => ({ supabase: { auth: { refreshSession: vi.fn() } } }));

import { provisionAndRefresh, rememberSignupChoice } from "@/services/auth.service";

beforeEach(() => {
  calls.provision.mockReset().mockResolvedValue({ role: "Learner" });
  sessionStorage.clear();
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

  it("creates a company workspace only when the person chose My company", async () => {
    rememberSignupChoice({ accountType: "company", adultConfirmed: false });
    await provisionAndRefresh("t", {});
    expect(sent()).toMatchObject({ account_type: "company" });
  });

  it("keeps the choice made at email sign-up", async () => {
    await provisionAndRefresh("t", { account_type: "company", company_name: "Acme" });
    expect(sent()).toMatchObject({ account_type: "company", company_name: "Acme" });
  });
});
