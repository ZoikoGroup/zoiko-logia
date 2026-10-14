import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Each page gets its data through useLiveData; feed it a fixed response so the
// test checks what the page renders from real-shaped data.
const live = vi.hoisted(() => ({ data: null as unknown }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: () => ({ data: live.data, error: "", loading: false, signedOut: false, reload: () => {} }),
}));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));
vi.mock("@/components/governance/PageShell", () => ({ PageShell: ({ children }: { children: React.ReactNode }) => <main>{children}</main> }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));

import AlertsCenterPage from "@/app/alerts-center/page";
import StatusHealthPage from "@/app/status-health/page";
import ProviderRegisterPage from "@/app/provider-register/page";
import RolesPermissionsPage from "@/app/roles-permissions/page";
import EntitiesClientsPage from "@/app/entities-clients/page";
import BillingUsagePage from "@/app/billing-usage/page";

describe("Operations pages", () => {
  it("Alerts Center lists live exceptions, not the old fake outage", () => {
    live.data = { alerts: [{ id: "esc-overdue", severity: "High", domain: "AI Safety & Risk Controls",
      title: "2 escalations past SLA", detail: "", href: "/escalation-queue" }], generatedAt: "" };
    render(<AlertsCenterPage />);
    expect(screen.getByText("2 escalations past SLA")).toBeInTheDocument();
    expect(screen.queryByText(/LLM provider outage/)).not.toBeInTheDocument();
  });

  it("Alerts Center says when there is nothing to show", () => {
    live.data = { alerts: [], generatedAt: "" };
    render(<AlertsCenterPage />);
    expect(screen.getByText("No active alerts in this workspace.")).toBeInTheDocument();
  });

  it("Status & Health shows each live check with its state", () => {
    live.data = { checkedAt: new Date().toISOString(), checks: [
      { name: "Database", state: "operational", latencyMs: 120, detail: "Query succeeded" },
      { name: "Diagrams (Kroki)", state: "down", latencyMs: null, detail: "ConnectError" },
      { name: "Web search (SearXNG)", state: "not_configured", latencyMs: null, detail: "Not configured" },
    ] };
    render(<StatusHealthPage />);
    expect(screen.getByText("1 service down")).toBeInTheDocument();
    expect(screen.getByText("120 ms")).toBeInTheDocument();
    expect(screen.getByText("Not configured", { selector: "span.inline-flex" })).toBeInTheDocument();
    expect(screen.queryByText(/Source ingestion worker/)).not.toBeInTheDocument();
  });

  it("Provider Register shows configured providers and never claims due diligence", () => {
    live.data = {
      modelProviders: [{ key: "groq", name: "Groq", configured: true, purpose: "Answers", approved: null,
        models: { GROQ_MODEL: "llama" }, dueDiligence: "not_assessed" }],
      dataSources: [{ name: "FRED (St. Louis Fed)", category: "Economic data", access: "API key", configured: false }],
      integrations: [],
    };
    render(<ProviderRegisterPage />);
    expect(screen.getByText("Groq")).toBeInTheDocument();
    expect(screen.getAllByText("Not assessed").length).toBeGreaterThan(1);
    expect(screen.queryByText(/Zero-retention verified|OpenAI Enterprise/)).not.toBeInTheDocument();
  });
});

describe("Administration pages", () => {
  it("Roles & Permissions shows the enforced registry and flags permissionless roles", () => {
    live.data = { roles: [{ name: "SME Reviewer", purpose: "Reviews answers", permissions: ["review.read", "review.resolve"], activeUsers: 2 }],
      unrecognisedRoles: [{ name: "CFO", activeUsers: 1 }] };
    render(<RolesPermissionsPage />);
    expect(screen.getByText("review.resolve")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent('role "CFO"');
  });

  it("Entities/Clients shows the DPIA hold and no sample companies", () => {
    render(<EntitiesClientsPage />);
    expect(screen.getByText("Blocked pending DPIA sign-off")).toBeInTheDocument();
    expect(screen.queryByText(/Atlas Financial|Meridian Health/)).not.toBeInTheDocument();
  });

  it("Billing & Usage shows measured usage and an honest billing state", () => {
    live.data = {
      totals: { questions_all_time: 1366, questions_this_month: 42, active_users_this_month: 3, saved_answers: 15,
        drafts: 0, documents: 7, generated_files: 2 },
      questionsByMonth: [{ month: "2026-10", label: "Oct 2026", questions: 42 }],
      billing: { connected: false, reason: "No billing or subscription system is connected to this deployment yet." },
      generatedAt: "",
    };
    render(<BillingUsagePage />);
    expect(screen.getByText("1,366")).toBeInTheDocument();
    expect(screen.getByText(/No billing or subscription system/)).toBeInTheDocument();
    expect(screen.queryByText(/July platform invoice|82%/)).not.toBeInTheDocument();
  });
});
