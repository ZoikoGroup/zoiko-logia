import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

// Each page loads through useLiveData; feed real-shaped data per key and check
// what renders, and that none of the design mock-ups' sample records appear.
const live = vi.hoisted(() => ({ byKey: {} as Record<string, unknown> }));
vi.mock("@/components/overview/useLiveData", () => ({
  useLiveData: (key: string) => ({
    data: live.byKey[key.startsWith("audit-events:") ? "audit-events" : key.startsWith("replay:") ? "replay" : key] ?? null,
    error: "", loading: false, signedOut: false, reload: () => {},
  }),
}));
vi.mock("@/hooks/useAuth", () => ({ useAuth: () => ({ profile: { id: "me", role: "Admin" } }) }));
vi.mock("@/components/governance/LiveSourceStatus", () => ({ LiveSourceStatus: () => null }));
vi.mock("next/link", () => ({ default: ({ href, children }: { href: string; children: React.ReactNode }) => <a href={href}>{children}</a> }));
vi.mock("next/navigation", () => ({ useSearchParams: () => new URLSearchParams() }));

import EscalationQueuePage from "@/app/escalation-queue/page";
import SupportTicketsPage from "@/app/support-tickets/page";
import IncidentResponsePage from "@/app/incident-response/page";
import AuditLogsPage from "@/app/audit-logs/page";
import AuditReplayPage from "@/app/audit-replay/page";

const NOW = "2026-10-15T10:00:00Z";

describe("Review, Escalation & Audit pages", () => {
  it("Escalation Queue sends a question with an open review case to Review Tasks", () => {
    live.byKey = { "escalation-queue": {
      escalations: [{
        id: "ESC-1", queryId: "q1", question: "Is this lease IFRS 16?", topic: "Lease classification", severity: "High", riskLevel: "HIGH",
        subClass: null, trigger: "Risk classification", jurisdiction: "UK", status: "open", rawStatus: "PENDING", origin: "auto",
        requesterId: "u2", requester: "Ann", assigneeId: null, assignee: null, reviewerRole: "SME Reviewer", decidedBy: null, decision: null,
        slaDeadline: NOW, sla: "overdue", createdAt: NOW, resolvedAt: null, detail: "Auto-escalated", routeReason: "high_risk",
        evidenceRefs: [], reviewCase: { id: "rc1-abcdef", status: "open", decision: null, source: "escalation" },
        closureRestricted: true, closureReason: "The answer is decided in Review Tasks", nextSteps: ["Assign expert"], history: [],
      }],
      summary: { open: 1, critical: 0, overdue: 1, expertReview: 0, closureRestricted: 1, unassigned: 1, linkedToReview: 1,
        bySeverity: { Critical: 0, High: 1, Medium: 0, Low: 0 } },
      overrides: [], generatedAt: NOW,
    } };
    render(<EscalationQueuePage />);
    expect(screen.getByText("Decide in Review Tasks")).toHaveAttribute("href", "/review-tasks");
    expect(screen.queryByRole("button", { name: "Approve closure" })).not.toBeInTheDocument();
    expect(screen.getAllByText("Overdue").length).toBeGreaterThan(0);
    expect(screen.queryByText(/ESC-2026-124|Conflicting lease classification/)).not.toBeInTheDocument();
  });

  it("Support Tickets shows the live SLA clock and full ticket detail", () => {
    live.byKey = { "support-tickets": {
      tickets: [{
        id: "t1", ref: "SUP-2026-0001", subject: "SSO sign-in loop", description: "Two users loop at sign-in", category: "access_identity",
        priority: "P1", priorityLabel: "Urgent", status: "in_progress", jurisdiction: "UK", requesterId: "u2", requester: "Ann",
        ownerId: null, owner: null, queryId: null, sourceId: null, createdAt: NOW, firstResponseAt: null, resolvedAt: null,
        resolutionNote: "", escalationId: null, incidentId: null,
        sla: { state: "at_risk", dueAt: NOW, remainingSeconds: 3000, firstResponseDueAt: NOW, firstResponseMet: false, targetHours: 8, firstResponseHours: 1 },
        messages: [{ at: NOW, kind: "customer", actorId: "u2", actor: "Ann", body: "Two users loop at sign-in" }],
      }],
      summary: { open: 1, atRisk: 1, breaches: 0, waitingCustomer: 0, escalated: 0, unassigned: 1, firstResponsePct: null, resolutionPct: null,
        byPriority: { P1: 1, P2: 0, P3: 0, P4: 0 } },
      policy: [{ priority: "P1", label: "Urgent", firstResponseHours: 1, resolutionHours: 8 }], categories: ["access_identity"],
      activity: [], generatedAt: NOW,
    } };
    render(<SupportTicketsPage />);
    expect(screen.getAllByText("SSO sign-in loop").length).toBeGreaterThan(0);
    expect(screen.getAllByText("50m").length).toBeGreaterThan(0);
    expect(screen.getByText("Assign an owner.")).toBeInTheDocument();
    expect(screen.queryByText(/SUP-2026-0247|Kriton cites superseded UK guidance/)).not.toBeInTheDocument();
  });

  it("Incident Response shows real incidents with owner and audit linkage", () => {
    live.byKey = { "incident-response": {
      incidents: [{
        id: "inc-1", title: "Pre-screen security incident: prompt_injection", severity: "High", status: "OPEN", source: "PROMPT_INJECTION",
        sourceLabel: "Prompt Injection", queryId: "q9", subClass: null, ownerId: null, owner: null, openedAt: NOW, resolvedAt: null,
        resolutionNote: "", hoursOpen: 2, linkedEventIds: [], ticketId: null, timeline: [],
      }],
      summary: { open: 1, contained: 0, critical: 0, high: 1, unowned: 1, resolved30d: 0, mttrHours: null,
        bySeverity: { Critical: 0, High: 1, Medium: 0, Low: 0 } },
      sources30d: [{ source: "Prompt Injection", count: 1 }], generatedAt: NOW,
    } };
    render(<IncidentResponsePage />);
    expect(screen.getAllByText("Pre-screen security incident: prompt_injection").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Mark contained" })).toBeInTheDocument();
    expect(screen.queryByText(/Suspicious prompt bypass attempt detected/)).not.toBeInTheDocument();
  });

  it("Audit Logs classifies real events and keeps payloads hidden by default", () => {
    const event = { id: "evt-abc123456789", event: "access_denied", family: "access", familyLabel: "Access denials", risk: "high",
      outcome: "denied", at: NOW, ingestedAt: NOW, actorId: "u2", actor: "Ann", actorType: "user", service: "identity",
      subjectType: "permission", subjectId: "admin", correlationId: "q1", chainHashed: true, classification: "INTERNAL", payload: { secret: "x" } };
    live.byKey = {
      "audit-overview": { summary: { total: 140332, last30d: 5000, denied30d: 3, deniedHighRisk30d: 3, openInvestigations: 1,
        investigationsWithEvidence: 0, chainPassed: true, eventsChecked: 140332, brokenAt: null, chainVerifiedAt: NOW, exportsPending: 0,
        ingestionLagP95Seconds: 0.4 }, families: [{ key: "access", label: "Access denials", count: 3, pct: 1 }], priority: [], exports: [], generatedAt: NOW },
      "audit-events": { events: [event], total: 1, offset: 0, families: {}, windowDays: 30, generatedAt: NOW },
    };
    render(<AuditLogsPage />);
    expect(screen.getAllByText("140,332").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Denied").length).toBeGreaterThan(0);
    expect(screen.getByText("No payload displayed")).toBeInTheDocument();
    expect(screen.queryByText(/EVT-2026-10518|svc-ret-02/)).not.toBeInTheDocument();
  });

  it("Audit Replay lists recorded traces and flags exceptions", () => {
    live.byKey = {
      "audit-traces": {
        traces: [{ correlationId: "qry-4181007f4773", title: "What is IFRS 16?", kind: "Kriton answer", events: 14, firstAt: NOW, lastAt: NOW,
          integrity: "verified", complete: false, state: "partial", reviewCase: null, reviewStatus: null, incident: null, refused: false, humanReview: false }],
        summary: { recorded30d: 120, shown: 1, replayReady: 0, holds: 1, humanReviewsOpen: 2, exportHolds: 0 },
        integrity: { hashed: 1, complete: 0, reviewed: 0, total: 1 }, generatedAt: NOW,
      },
      replay: { correlation_id: "qry-4181007f4773", completeness_status: "PARTIAL_KNOWN_GAPS", known_gaps: [], manifest_trustworthiness: "LIMITED",
        chain_verification_result: "PASS", generated_by: "replay", generated_at: NOW, events: [], manifest_hash: "abc" },
    };
    render(<AuditReplayPage />);
    expect(screen.getAllByText("What is IFRS 16?").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Partial").length).toBeGreaterThan(0);
    expect(screen.getByText("Replay / export restrictions apply")).toBeInTheDocument();
    expect(screen.queryByText(/AR-2026-0228|Lease classification conflict/)).not.toBeInTheDocument();
  });
});
