import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const live = vi.hoisted(() => ({ data: null as unknown, calls: 0 }));
const auth = vi.hoisted(() => ({ profile: null as unknown }));
const route = vi.hoisted(() => ({ section: "privileged-access" }));
vi.mock("next/navigation", () => ({ useParams: () => ({ section: route.section }), usePathname: () => "/super-admin" }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: () => { live.calls += 1; return { data: live.data, error: "", loading: false, signedOut: false, reload: () => {} }; },
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: auth.profile, profileLoading: false }) }));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));
vi.mock("@/components/platform/directory", () => ({ usePlatformDirectory: () => ({ data: null }) }));

import SectionPage from "@/app/super-admin/[section]/page";
import { NAV, SECTIONS } from "@/components/platform/sections";

const VIEW = {
  generatedAt: "2026-10-15T12:00:00Z",
  summary: {
    criticalIncidents: 0, openIncidents: 0, unassignedIncidents: 0, releaseHolds: 0, openReleases: 0,
    decisions: 2, decisionsByPriority: { Critical: 1, Medium: 1 }, isolation: "pass", availabilityPct: null,
    objectivePct: 99.5, privilegedRequests: 1, privilegedAwaitingApproval: 1, controlExceptions: 1,
  },
  decisions: [
    { id: "g1", ref: "BG-ABC123", priority: "Critical", title: "Emergency access request · 60 min", area: "Privileged access",
      owner: "Security approver", tenant: "Globex", since: "2026-10-15T11:00:00Z", state: "Awaiting independent approval" },
    { id: "d1", ref: "BIL-DEF456", priority: "Medium", title: "Usage charge under dispute · 2026-10", area: "Billing assurance",
      owner: "Billing assurance", tenant: "Acme", since: "2026-10-14T12:00:00Z", state: "Open dispute" },
  ],
  controls: [
    { key: "isolation", label: "Tenant isolation", state: "pass", detail: "Row-level security enforced" },
    { key: "privileged", label: "Privileged access", state: "review", detail: "1 awaiting approval · 0 active · 0 awaiting review" },
  ],
  health: { services: [], sampled: false, availabilityPct: null, objectivePct: 99.5, p95LatencyMs: null, degraded: 0, measured: 0, coreDown: [] },
  evaluation: { state: "unknown", latest: null, metrics: [], recent: { completed: 0, failed: 0 } },
  releases: { open: 0, held: 0, items: [] },
  tenants: { total: 2, withUsers: 2, active30d: 1, users: 3, withApprovedPlan: 0 },
  commercial: { month: "2026-10", invoiced: {}, collected: {}, receivable: {}, unpaidStatements: 0, openDisputes: 1, pendingCredits: 0 },
  privileged: { awaitingApproval: 1, active: 0, awaitingReview: 0, activeGrants: [] },
  audit: { events24h: 40, exportsPending: 0, deniedAttempts30d: 3 },
};

describe("Super Admin sidebar sections", () => {
  it("links every sidebar entry to a platform page that exists", () => {
    const built = new Set(["/super-admin", "/super-admin/companies", "/super-admin/accounts",
      ...SECTIONS.map((s) => `/super-admin/${s.slug}`)]);
    const hrefs = NAV.flatMap((g) => g.items.map((i) => i.href));
    expect(hrefs).toHaveLength(25);
    for (const href of hrefs) expect(built.has(href), href).toBe(true);
  });

  it("shows only its own area's decisions and controls", () => {
    auth.profile = { role: "Learner", platform_role: "super_admin" };
    live.data = VIEW;
    route.section = "privileged-access";
    render(<SectionPage />);
    expect(screen.getByRole("heading", { name: "Privileged Access" })).toBeInTheDocument();
    expect(screen.getByText("Emergency access request · 60 min")).toBeInTheDocument();
    expect(screen.queryByText("Usage charge under dispute · 2026-10")).not.toBeInTheDocument();
    expect(screen.queryByText("Tenant isolation")).not.toBeInTheDocument();
  });

  it("refuses anyone without the platform role, without calling the API", () => {
    auth.profile = { role: "Admin", platform_role: null };
    live.calls = 0;
    route.section = "billing-assurance";
    render(<SectionPage />);
    expect(screen.getByText("Platform Super Admin access required")).toBeInTheDocument();
    expect(live.calls).toBe(0);
  });

  it("says so for an unknown section", () => {
    route.section = "nope";
    render(<SectionPage />);
    expect(screen.getByText("No such platform page")).toBeInTheDocument();
  });
});
