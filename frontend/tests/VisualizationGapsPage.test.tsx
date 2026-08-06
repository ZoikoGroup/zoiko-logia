import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { ApiError, type VisualizationGapSummary, type EvidenceMonitoringStatus, type EvidenceMonitoringRunResult, type MonitoringRunSummary } from "@/lib/api";

const summaryResponse: VisualizationGapSummary = {
  total_visualization_requests: 0, total_fallback_events: 0, gap_rate: 0, rows: [], environment: "production",
};

function runSummary(overrides: Partial<MonitoringRunSummary> = {}): MonitoringRunSummary {
  return {
    tenant_id: "t1", started_at: "2026-08-03T06:00:00Z", completed_at: "2026-08-03T06:01:00Z", status: "succeeded",
    trigger_source: "scheduled", monitoring_period: "2026-08-03", evidence_version: "evidence-monitoring-1.0:abc",
    valid_event_count: 140, draft_created: true, alert_created: true, report_id: "report-1", failure_category: null,
    ...overrides,
  };
}

const collectingStatus: EvidenceMonitoringStatus = {
  tenant_id: "t1", valid_event_count: 12, distinct_conversation_count: 4, distinct_actor_count: 3,
  overall_evidence_status: "insufficient_evidence", monitoring_status: "collecting_evidence",
  next_eligible_finding: null, events_to_next_threshold: null, diversity_gate_blocking_next: false,
  last_aggregation_at: null, last_report: null,
  last_scheduled_run: null, last_manual_run: null, current_run: null, next_scheduled_run_at: "2026-08-04T06:00:00Z",
};

const directionalStatus: EvidenceMonitoringStatus = {
  ...collectingStatus, valid_event_count: 40, monitoring_status: "directional_signal", overall_evidence_status: "directional_signal",
};

const readyStatus: EvidenceMonitoringStatus = {
  ...collectingStatus, valid_event_count: 140, monitoring_status: "ready_for_review",
  overall_evidence_status: "eligible_for_review", last_aggregation_at: "2026-08-03T10:00:00Z",
  last_report: {
    id: "report-1", period_start: "2026-07-01", period_end: "2026-08-01", evidence_version: "evidence-monitoring-1.0:abc",
    approved_findings: [], artifact: {}, status: "draft", created_by: "system:evidence-monitoring", approved_by: null, approved_at: null,
  },
  last_scheduled_run: runSummary(),
};

const runResult: EvidenceMonitoringRunResult = {
  tenant_id: "t1", started_at: "2026-08-03T10:05:00Z", completed_at: "2026-08-03T10:06:00Z", status: "succeeded",
  trigger_source: "manual", monitoring_period: "2026-08-03", evidence_version: "evidence-monitoring-1.0:abc",
  valid_event_count: 140, distinct_conversation_count: 6, distinct_actor_count: 5,
  eligible_finding_count: 1, draft_created: true, alert_created: true, deduplicated: false, report_id: "report-1", failure_category: null,
};

let currentStatus = collectingStatus;
const runCalls: number[] = [];
let runShouldReject: ApiError | null = null;

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    getAuthToken: () => "test-token",
    getVisualizationGapSummary: vi.fn(async () => summaryResponse),
    getEvidenceMonitoringStatus: vi.fn(async () => currentStatus),
    runEvidenceMonitoring: vi.fn(async () => {
      runCalls.push(1);
      if (runShouldReject) throw runShouldReject;
      return runResult;
    }),
  };
});

const { default: VisualizationGapsPage } = await import("@/app/visualization-gaps/page");

describe("Visualization Gap Report — Evidence Monitoring section", () => {
  it("shows 'Collecting evidence' when thresholds are not met", async () => {
    currentStatus = collectingStatus;
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Collecting evidence")).toBeTruthy());
    expect(screen.getByText("12")).toBeTruthy();
    expect(screen.getAllByText("Never run yet").length).toBeGreaterThan(0);
  });

  it("shows 'Directional signal' between insufficient evidence and readiness", async () => {
    currentStatus = directionalStatus;
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Directional signal")).toBeTruthy());
  });

  it("shows 'Ready for review' once a draft is available", async () => {
    currentStatus = readyStatus;
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Ready for review")).toBeTruthy());
    expect(screen.getAllByText("draft").length).toBeGreaterThan(0);
  });

  it("shows 'Awaiting maker-checker approval' once submitted for review", async () => {
    currentStatus = { ...readyStatus, monitoring_status: "awaiting_approval", last_report: { ...readyStatus.last_report!, status: "under_review" } };
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Awaiting maker-checker approval")).toBeTruthy());
  });

  it("shows 'Approved findings available' once a report is approved", async () => {
    currentStatus = { ...readyStatus, monitoring_status: "approved_findings_available", last_report: { ...readyStatus.last_report!, status: "approved" } };
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Approved findings available")).toBeTruthy());
  });

  it("shows the last scheduled run, evidence version, and next scheduled run", async () => {
    currentStatus = readyStatus;
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Ready for review")).toBeTruthy());
    expect(screen.getByText(/Evidence evidence-monitoring-1\.0:abc/)).toBeTruthy();
    expect(screen.getByText("Last scheduled run")).toBeTruthy();
    expect(screen.getByText(new Date("2026-08-04T06:00:00Z").toLocaleString())).toBeTruthy();
  });

  it("disables the manual run button while a run is already active", async () => {
    currentStatus = { ...collectingStatus, current_run: runSummary({ status: "running", trigger_source: "scheduled" }) };
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByRole("button", { name: /Running…/i })).toBeTruthy());
    expect(screen.getByRole("button", { name: /Running…/i })).toBeDisabled();
  });

  it("never renders raw identifiers, errors, or values alongside the evidence-monitoring section", async () => {
    currentStatus = readyStatus;
    const { container } = render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Ready for review")).toBeTruthy());
    const html = container.innerHTML;
    expect(html).not.toContain("actor_id");
    expect(html).not.toContain("conversation_id");
    expect(html).not.toContain("query_id");
    expect(html).not.toContain("stack_trace");
  });

  it("clicking 'Run evidence monitoring' calls the API and reloads status", async () => {
    currentStatus = collectingStatus;
    runShouldReject = null;
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Collecting evidence")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Run evidence monitoring/i }));
    await waitFor(() => expect(runCalls.length).toBeGreaterThan(0));
  });

  it("shows a friendly message instead of crashing on a 409 duplicate-submission conflict", async () => {
    currentStatus = collectingStatus;
    runShouldReject = new ApiError(409, "A monitoring run is already active for this tenant — wait for it to finish.");
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText("Collecting evidence")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Run evidence monitoring/i }));
    await waitFor(() => expect(screen.getByText(/already active/i)).toBeTruthy());
    runShouldReject = null;
  });

  it("shows a friendly error instead of crashing when the status API call fails", async () => {
    const api = await import("@/lib/api");
    vi.mocked(api.getEvidenceMonitoringStatus).mockRejectedValueOnce(new Error("403"));
    render(<VisualizationGapsPage />);
    await waitFor(() => expect(screen.getByText(/Admin access/i)).toBeTruthy());
  });
});
