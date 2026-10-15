import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Each page gets its data through useLiveData; feed it a fixed response so the
// test checks what the page renders from real-shaped data.
const live = vi.hoisted(() => ({ data: null as unknown }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: (key: string) => ({ data: key === "ops-assignees" ? [] : live.data, error: "", loading: false, signedOut: false, reload: () => {} }),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: { role: "Admin" } }) }));
// Recharts measures its container; jsdom has no layout, so render charts as nothing.
vi.mock("@/components/operations/charts", () => ({
  AvailabilityChart: () => null, LatencyChart: () => null, SeverityDonut: () => null,
}));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import AlertsCenterPage from "@/app/alerts-center/page";
import StatusHealthPage from "@/app/status-health/page";
import ProviderRegisterPage from "@/app/provider-register/page";
import IntegrationsPage from "@/app/integrations/page";
import BillingUsagePage from "@/app/billing-usage/page";

const ALERT = {
  id: "a1", ref: "ALT-2026-0001", origin: "governance", category: "AI safety", severity: "High",
  title: "2 escalations past SLA", detail: "Escalations waiting beyond their SLA.", href: "/escalation-queue",
  serviceKey: null, state: "unacknowledged", ownerId: null, owner: null, detectedAt: "2026-10-15T10:00:00Z",
  lastSeenAt: "2026-10-15T11:00:00Z", acknowledgedAt: null, acknowledgedBy: null, resolvedAt: null, resolvedBy: null,
  history: [{ at: "2026-10-15T10:00:00Z", action: "detected", actorId: null, actor: "System", note: "" }],
};
const alertsView = (alerts: unknown[], active: number) => ({
  alerts,
  summary: { active, critical: 0, unacknowledged: active, unowned: active, safetyBlocks: 0,
    bySeverity: { Critical: 0, High: active, Medium: 0, Low: 0 }, byCategory: active ? [{ category: "AI safety", count: active }] : [] },
  delivery: { channelConfigured: false, channel: "In-app (this console)" }, generatedAt: "2026-10-15T11:00:00Z",
});
const service = (key: string, name: string, state: string, extra: object = {}) => ({
  key, name, component: "c", category: "Platform", location: "Local", state, latencyMs: 120, detail: "HTTP 200",
  availability24h: 99.9, samples24h: 12, p95LatencyMs24h: 140, errorRate24h: null, lastSampleAt: null,
  ownerId: null, owner: null, openAlerts: [], dependsOn: [], ...extra,
});
const gates = (passed: number, total: number) => Array.from({ length: total }, (_, i) => ({
  key: `g${i}`, label: `Gate ${i}`, status: i < passed ? "pass" : "open", note: "" }));

describe("Operations pages", () => {
  it("Alerts Center lists live alerts with their lifecycle, not the old fake register", () => {
    live.data = alertsView([ALERT], 1);
    render(<AlertsCenterPage />);
    expect(screen.getAllByText("2 escalations past SLA").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ALT-2026-0001").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Acknowledge" })).toBeInTheDocument();
    expect(screen.queryByText(/Source rights unverified|M\. Chen/)).not.toBeInTheDocument();
  });

  it("Alerts Center says when there is nothing to show", () => {
    live.data = alertsView([], 0);
    render(<AlertsCenterPage />);
    expect(screen.getByText("No active alerts in this workspace.")).toBeInTheDocument();
  });

  it("Status & Health shows measured services and flags an outage", () => {
    live.data = {
      checkedAt: "2026-10-15T11:00:00Z",
      summary: { platformState: "degraded", impacted: ["Web search"], availability24h: 97.5, availabilityObjective: 99.5,
        apiP95Ms: 310, apiP95ObjectiveMs: 2000, activeAlerts: 1, unavailable: 1, blockedJobs: 0 },
      services: [service("database", "Database", "operational"),
        service("searxng", "Web search", "down", { latencyMs: null, detail: "ConnectError" })],
      hourly: [], dependencyMap: { key: "api", name: "Kriton API", state: "impacted", children: [
        { key: "searxng", name: "Web search", state: "down", children: [] }] },
      events: [], slo: [],
      jobs: { sampler: { enabled: true, intervalSeconds: 300, retentionDays: 30, lastSampleAt: null },
        documents: { available: true, stuck: 0, processing: 0, failed24h: 0 }, queue: { state: "not_configured", detail: "Not configured" } },
    };
    render(<StatusHealthPage />);
    expect(screen.getByText("Web search is unavailable")).toBeInTheDocument();
    expect(screen.getByText("310 ms")).toBeInTheDocument();
    expect(screen.getByText("No history yet")).toBeInTheDocument();
    expect(screen.queryByText(/SVC-202|Source Retrieval|99\.92%/)).not.toBeInTheDocument();
  });

  it("Provider Register prompts to register providers that are in use, and never invents vendors", () => {
    live.data = {
      providers: [], detected: [{ configKey: "groq", name: "Groq", category: "ai_model", service: "Answers" }],
      summary: { registered: 0, approved: 0, inReview: 0, conditional: 0, underReview: 0, blocked: 0, reviewActions: 0 },
      resilience: { critical: 0, fallbackDocumented: 0, untestedExits: 0 }, categories: {}, generatedAt: "2026-10-15T11:00:00Z",
    };
    render(<ProviderRegisterPage />);
    expect(screen.getByRole("button", { name: "Register Groq" })).toBeInTheDocument();
    expect(screen.getByText("No providers registered yet")).toBeInTheDocument();
    expect(screen.queryByText(/Inference Provider|PRV-027/)).not.toBeInTheDocument();
  });

  it("Integrations shows a registered connection with its derived gates and routing block", () => {
    live.data = {
      integrations: [{
        id: "i1", ref: "INT-001", name: "General ledger", category: "accounting", categoryLabel: "Accounting systems",
        providerId: null, provider: null, healthKey: null, health: "not_enabled", healthDetail: "Not enabled until authorized",
        healthCheckedAt: null, authorization: "pending", dataFlow: "inbound", region: "UK", riskTier: "high", authMethod: "OAuth",
        scopesRequested: ["read:ledger"], scopesApproved: [], ownerId: null, owner: null, gates: gates(2, 7),
        gatesPassed: 2, gatesTotal: 7, scopeException: false, createdBy: "A", createdAt: "", decidedBy: null, decidedAt: null, history: [],
      }],
      detected: [], summary: { registered: 1, approved: 0, pending: 1, degraded: 0, blocked: 0, scopeExceptions: 0 },
      controls: { least_privilege: { passed: 0, total: 1 }, secret_vault: { passed: 0, total: 1 },
        replay_idempotency: { passed: 0, total: 1 }, residency_privacy: { passed: 0, total: 1 } },
      exceptions: [], categories: { accounting: "Accounting systems" }, providers: [], generatedAt: "",
    };
    render(<IntegrationsPage />);
    expect(screen.getAllByText("General ledger").length).toBeGreaterThan(0);
    expect(screen.getByText("ROUTING RESTRICTION ACTIVE")).toBeInTheDocument();
    expect(screen.getByText("Mandatory release gates · 2/7 passed")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Enable connector" })).toBeDisabled();
  });
});

describe("Billing & Usage", () => {
  const meters = [{ key: "kriton_interactions", label: "Kriton interactions", unit: "interaction", event: "query_received" }];
  const base = {
    period: "2026-10", now: "2026-10-15T10:00:00Z", meters,
    current: { period: "2026-10", planVersion: null, currency: "USD", subtotalCents: 0, creditsCents: 0, totalCents: 0, variableCents: 0,
      excludedCents: 0, priced: false,
      lines: [{ key: "kriton_interactions", label: "Kriton interactions", unit: "interaction", quantity: 42, included: 0, billable: 42,
        rateCents: 0, amountCents: 0, status: "unpriced", excluded: false }],
      usage: { totals: { kriton_interactions: 42 }, daily: { "2026-10-14": { kriton_interactions: 42 } }, engagements: { "": 42 } } },
    summary: { estimatedCents: 0, commitmentCents: 0, variableCents: 0, interactions: 42, softBudgetCents: 0, hardCapCents: 0,
      budgetUsedPct: null, projectedCents: null, openDisputes: 0, excludedCents: 0, priced: false },
    trend: [{ period: "2026-10", totalCents: 0, interactions: 42, estimate: true, priced: false }],
    allocation: [{ engagementId: null, name: "Unassigned (no engagement)", interactions: 42, share: 1, amountCents: 0 }],
    plan: null, pendingPlan: null, planHistory: [], adjustments: [], statements: [], closablePeriods: [], trail: [],
  };

  it("measures usage and prices nothing until a plan is approved", () => {
    live.data = base;
    render(<BillingUsagePage />);
    expect(screen.getByText(/No approved plan yet/)).toBeInTheDocument();
    expect(screen.getAllByText("42").length).toBeGreaterThan(0);
    expect(screen.getAllByText("No rate card").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Sample Finance Co|INV-2026-009|\$14,100/)).not.toBeInTheDocument();
  });
});
