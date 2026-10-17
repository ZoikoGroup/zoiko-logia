import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const live = vi.hoisted(() => ({ data: null as unknown }));
const auth = vi.hoisted(() => ({ profile: { role: "Admin", platform_role: "super_admin" } as unknown }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: () => ({ data: live.data, error: "", loading: false, signedOut: false, reload: () => {} }),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: auth.profile, profileLoading: false }) }));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));

import AccountsPage from "@/app/super-admin/accounts/page";
import CompaniesPage from "@/app/super-admin/companies/page";

const account = (over: Record<string, unknown>) => ({
  id: "x", name: "X", email: "x@x.com", role: "Admin", platformRole: null, tenantId: "t-acme", tenant: "Acme Ltd",
  status: "active", createdAt: "2026-10-01T00:00:00Z", emailConfirmed: true, lastSignInAt: "2026-10-17T11:00:00Z",
  lastSeenAt: null, lastActivityAt: null, online: false, activeSessions: 0, mfa: false, providers: ["email"], ...over,
});

live.data = {
  generatedAt: "2026-10-17T12:00:00Z",
  signInDataAvailable: true,
  summary: {
    companies: 1, personalWorkspaces: 1, companiesOnline: 1, companiesSignedIn24h: 1, companiesActive30d: 1,
    accounts: 3, online: 1, signedIn24h: 2, signedIn7d: 2, statuses: { active: 2, unconfirmed: 1 },
    roles: { Admin: 1, Learner: 2 }, withMfa: 0,
  },
  companies: [
    { id: "t-acme", name: "Acme Ltd", type: "company", state: "online", createdAt: "2026-10-01T00:00:00Z", members: 2,
      activeMembers: 1, online: 1, signedIn24h: 1, signedIn7d: 1, roles: { Admin: 1, Learner: 1 },
      admins: [{ name: "Ann Admin", email: "ann@acme.com" }], lastSignInAt: "2026-10-17T11:00:00Z",
      lastActivityAt: "2026-10-17T11:30:00Z", billingPlan: false, issues: 1 },
    { id: "t-ada", name: "Ada Lovelace", type: "personal", state: "active", createdAt: null, members: 1, activeMembers: 1,
      online: 0, signedIn24h: 1, signedIn7d: 1, roles: { Learner: 1 }, admins: [], lastSignInAt: "2026-10-17T09:00:00Z",
      lastActivityAt: null, billingPlan: false, issues: 0 },
  ],
  accounts: [
    account({ id: "a1", name: "Ann Admin", email: "ann@acme.com", online: true, activeSessions: 1 }),
    account({ id: "a2", name: "Leo Learner", email: "leo@acme.com", role: "Learner", status: "unconfirmed", emailConfirmed: false, lastSignInAt: null }),
    account({ id: "a3", name: "Ada Lovelace", email: "ada@example.com", role: "Learner", tenantId: "t-ada", tenant: "Ada Lovelace" }),
  ],
};

describe("Super Admin directory", () => {
  it("lists every account across companies and roles, filterable by status", () => {
    render(<AccountsPage />);
    const table = screen.getByRole("table");
    for (const email of ["ann@acme.com", "leo@acme.com", "ada@example.com"]) {
      expect(within(table).getByText(email)).toBeInTheDocument();
    }
    fireEvent.click(screen.getByRole("tab", { name: /Email unverified/ }));
    expect(within(screen.getByRole("table")).queryByText("ann@acme.com")).not.toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("leo@acme.com")).toBeInTheDocument();
  });

  it("shows companies with their admin and opens a company's accounts", () => {
    render(<CompaniesPage />);
    expect(screen.getByText("ann@acme.com")).toBeInTheDocument();
    expect(screen.queryByText("Ada Lovelace")).not.toBeInTheDocument(); // personal workspaces on their own tab
    fireEvent.click(screen.getByRole("button", { name: "Acme Ltd" }));
    expect(screen.getByText("Accounts (2)")).toBeInTheDocument();
    expect(screen.getByText("leo@acme.com")).toBeInTheDocument();
  });

  it("is closed to anyone without the platform role", () => {
    auth.profile = { role: "Admin", platform_role: null };
    render(<AccountsPage />);
    expect(screen.getByText("Platform Super Admin access required")).toBeInTheDocument();
    auth.profile = { role: "Admin", platform_role: "super_admin" };
  });
});
