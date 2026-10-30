import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const live = vi.hoisted(() => ({ data: null as unknown, calls: 0 }));
const auth = vi.hoisted(() => ({ profile: null as unknown }));
vi.mock("next/navigation", () => ({ usePathname: () => "/super-admin", useParams: () => ({}) }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: () => { live.calls += 1; return { data: live.data, error: "", loading: false, signedOut: false, reload: () => {} }; },
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: auth.profile, profileLoading: false }) }));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));
vi.mock("@/components/platform/directory", () => ({ usePlatformDirectory: () => ({ data: null }) }));

import SuperAdminPage from "@/app/super-admin/page";
import { SuperAdminChrome } from "@/components/platform/SuperAdminChrome";
import { navCounts } from "@/components/platform/sections";
import type { PlatformCommand } from "@/lib/api";

const VIEW = {
  generatedAt: "2026-10-28T12:00:00Z",
  summary: {
    criticalIncidents: 0, openIncidents: 3, unassignedIncidents: 0, releaseHolds: 1, openReleases: 2,
    decisions: 1, decisionsByPriority: { High: 1 }, isolation: "pass", availabilityPct: 99.9,
    objectivePct: 99.5, privilegedRequests: 0, privilegedAwaitingApproval: 0, controlExceptions: 2,
  },
  decisions: [{ id: "p1", ref: "PRV-1", priority: "High", title: "Provider review overdue", area: "Provider risk",
    owner: "Provider risk", tenant: "Globex", since: "2026-10-27T12:00:00Z", state: "Overdue" }],
  controls: [
    { key: "isolation", label: "Tenant isolation", state: "pass", detail: "Row-level security on 41 tenant tables" },
    { key: "releases", label: "Release gates", state: "fail", detail: "1 held of 2 open" },
    { key: "billing", label: "Billing integrity", state: "review", detail: "4 open dispute(s) · 0 credit(s) pending" },
  ],
  health: { services: [], sampled: false, availabilityPct: 99.9, objectivePct: 99.5, p95LatencyMs: null, degraded: 0, measured: 6, coreDown: [] },
  evaluation: { state: "pass", latest: null, metrics: [], recent: { completed: 3, failed: 0 } },
  releases: { open: 2, held: 1, items: [] },
  tenants: { total: 7, withUsers: 5, active30d: 4, users: 19, withApprovedPlan: 3 },
  commercial: { month: "2026-10", invoiced: {}, collected: {}, receivable: {}, unpaidStatements: 0, openDisputes: 4, pendingCredits: 0 },
  privileged: { awaitingApproval: 0, active: 0, awaitingReview: 0, activeGrants: [] },
  audit: { events24h: 12, exportsPending: 0, deniedAttempts30d: 0 },
} as unknown as PlatformCommand;

describe("Super Admin shows only live values", () => {
  it("states controls from their own evidence, never fixed wording", () => {
    auth.profile = { role: "Admin", platform_role: "super_admin" };
    live.data = VIEW;
    render(<SuperAdminPage />);
    // In the isolation tile and in the assurance list.
    expect(screen.getAllByText("Row-level security on 41 tenant tables")).toHaveLength(2);
    expect(screen.getByText("2 exceptions")).toBeInTheDocument();
    expect(screen.getByText("7 tenants · 19 accounts · 6 services monitored")).toBeInTheDocument();
    // In the assurance list and the Commercial Assurance card.
    expect(screen.getAllByText("4 open dispute(s) · 0 credit(s) pending")).toHaveLength(2);
    for (const fixed of ["No standing data access", "Restricted", "Two-person approval required before access",
      "Tenant names are metadata only", "Global platform · All tenants"]) {
      expect(screen.queryByText(fixed)).not.toBeInTheDocument();
    }
  });

  it("counts what is waiting beside the sidebar entries, hiding zeros", () => {
    const counts = navCounts(VIEW);
    expect(counts["/super-admin/incident-response"]).toEqual({ count: 3, attention: true });
    expect(counts["/super-admin/release-gates"]).toEqual({ count: 1, attention: true });
    expect(counts["/super-admin/provider-register"]).toEqual({ count: 1, attention: true });
    expect(counts["/super-admin/billing-assurance"]).toEqual({ count: 4, attention: true });
    expect(counts["/super-admin/companies"]).toEqual({ count: 7, attention: false });
    expect(counts["/super-admin/privileged-access"]).toBeUndefined();
  });

  it("shows the counts and the real platform role in the shell", () => {
    auth.profile = { full_name: "Ada Admin", role: "Admin", platform_role: "super_admin" };
    live.data = VIEW;
    render(<SuperAdminChrome><main /></SuperAdminChrome>);
    expect(screen.getByLabelText("3 needing attention")).toBeInTheDocument();
    expect(screen.getByText("Platform super admin")).toBeInTheDocument();
  });

  it("never calls the platform API for someone without the role", () => {
    auth.profile = { full_name: "Bo", role: "Admin", platform_role: null };
    live.calls = 0;
    render(<SuperAdminChrome><main /></SuperAdminChrome>);
    expect(live.calls).toBe(0);
    expect(screen.getByText("No platform role")).toBeInTheDocument();
  });
});
