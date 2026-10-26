import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  tbs: vi.fn(), resolutions: vi.fn(), packages: vi.fn(), build: vi.fn(), get: vi.fn(), submit: vi.fn(), approve: vi.fn(),
  dispose: vi.fn(), sign: vi.fn(), release: vi.fn(), download: vi.fn(),
}));
vi.mock("@/lib/financial-statements-api", () => ({
  listTrialBalances: api.tbs, listResolutions: api.resolutions, listPackages: api.packages, buildPackage: api.build,
  getPackage: api.get, submitDisclosure: api.submit, approveDisclosure: api.approve, disposeFinding: api.dispose,
  signPackage: api.sign, packageReleaseCheck: api.release, downloadPackage: api.download,
}));
import { StatementsPanel } from "@/components/financial-statements/StatementsPanel";

const PACKAGE = {
  id: "pkg1", version: 1, state: "RECONCILED", stored_state: "RECONCILED", stale_reasons: [], trial_balance_id: "tb1",
  prior_trial_balance_id: null, resolution_id: "r1", fingerprint: "sha256:abcdef1234", created_by: "prep", superseded_by: null,
  created_at: null, signoffs: {}, history: [{ action: "assembled", actor_id: "prep", at: "2026-10-26T10:00:00Z", version: 1 }],
  result: {
    state: "RECONCILED", halted: null, watermark: "DRAFT — NOT FOR STATUTORY USE", fingerprint: "sha256:abcdef1234", schedules: {},
    profile: { family: "UK_COMPANIES_ACT", framework: "FRS102_1A", edition: "FRS102_1A@2022-01", resolution_id: "r1",
      resolution_revision: 1, resolution_state: "FROZEN", entity: "Northbridge Trading Ltd", period_start: "2025-04-01",
      period_end: "2026-03-31", scope: "individual", report_type: "annual", units: "units",
      ruleset: { id: "FS-ASSEMBLY-2026.10-TEST", version: "2026.10.26", status: "UNREVIEWED_TEST_PACK" } },
    manifest: [], counts: { P0: 1, P1: 0, P2: 1, P3: 0 }, ready_for_signoff: false, release_reasons: ["Statutory claim not permitted."],
    headline: { revenue: "3182000", profit_before_tax: "-151000", profit: "-151000", net_assets: "826000", cash: "512000" },
    cash_flow_data_fields: { tax_paid: "Tax paid in cash" },
    statements: [
      { statement_id: "profit_or_loss", title: "Profit and loss account", requiredness: "REQUIRED", status: "ASSEMBLED",
        lines: [{ line_id: "revenue", label: "Turnover", kind: "line", amount: "3182000", prior: null, concepts: ["pl.revenue"] }] },
      { statement_id: "cash_flows", title: "Statement of cash flows", requiredness: "EXEMPT", status: "EXEMPT", lines: [],
        note: "Small entities are exempt." }],
    assertions: [{ assertion_id: "X-01", title: "Statement of financial position", formula: "Σ assets − Σ liabilities − Σ equity = 0",
      operands: { assets: "1215000" }, residual: "0", status: "PASS", severity: "P0", detail: "", candidates: [] },
      { assertion_id: "X-07.receivables", title: "Note schedule", formula: "schedule = line", operands: {}, residual: "-10000",
        status: "FAIL", severity: "P0", detail: "", candidates: ["the receivables ageing total"] }],
    notes: [{ requirement_id: "N02", title: "Accounting policy: revenue recognition", rule: "AT-13", applicability: "REQUIRED",
      evidence_needed: "The entity's approved revenue policy.", severity: "P0", state: "REQUIRED_MISSING", text: "", amount: null,
      evidence_ref: "", submitted_by: null, approved_by: null, issues: [] }],
    findings: [{ code: "NOTE_PENDING_N03", severity: "P2", message: "Awaiting approval.", rule: "AS-043", owner: "Technical reviewer",
      action: "Approve.", refs: [], release_only: false, disposition: null }],
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  api.tbs.mockResolvedValue([{ id: "tb1", filename: "tb.csv", version: 1, state: "APPROVED_SNAPSHOT" },
    { id: "tb2", filename: "draft.csv", version: 1, state: "MAPPING_REVIEW" }]);
  api.resolutions.mockResolvedValue([{ id: "r1", revision: 1, state: "FROZEN", facts: { entity_name: "Northbridge Trading Ltd" } }]);
  api.packages.mockResolvedValue([]);
  api.build.mockResolvedValue(PACKAGE);
});

describe("Statements workspace (Document 05)", () => {
  it("assembles only from approved snapshots and shows readiness, statements, checks and notes", async () => {
    render(<StatementsPanel />);
    const select = await screen.findByLabelText("Approved trial balance");
    await waitFor(() => expect(screen.getAllByRole("option", { name: "tb.csv · v1" }).length).toBeGreaterThan(0));
    expect(screen.queryByRole("option", { name: "draft.csv · v1" })).toBeNull();
    fireEvent.change(select, { target: { value: "tb1" } });
    fireEvent.click(screen.getByRole("button", { name: "Assemble" }));
    expect(await screen.findByText(/P0 1 · P1 0 · P2 1/)).toBeTruthy();
    expect(screen.getByText("Turnover")).toBeTruthy();
    expect(screen.getByText(/difference -10,000/)).toBeTruthy();
    expect(screen.getByText("N02 Accounting policy: revenue recognition")).toBeTruthy();
    expect(api.build).toHaveBeenCalledWith({ trial_balance_id: "tb1", resolution_id: null, prior_trial_balance_id: null, schedules: {} });
  });

  it("submits a note with evidence, disposes a P2 item and keeps sign-off disabled while items are open", async () => {
    api.submit.mockResolvedValue(PACKAGE);
    api.dispose.mockResolvedValue(PACKAGE);
    render(<StatementsPanel />);
    fireEvent.change(await screen.findByLabelText("Approved trial balance"), { target: { value: "tb1" } });
    fireEvent.click(screen.getByRole("button", { name: "Assemble" }));
    fireEvent.click(await screen.findByRole("button", { name: "Provide" }));
    fireEvent.change(screen.getByLabelText("Text for N02"), { target: { value: "Revenue on delivery." } });
    fireEvent.change(screen.getByLabelText("Evidence for N02"), { target: { value: "policy-7" } });
    fireEvent.click(screen.getByRole("button", { name: "Submit" }));
    await waitFor(() => expect(api.submit).toHaveBeenCalledWith("pkg1", { requirement_id: "N02", decision: "include",
      text: "Revenue on delivery.", rationale: "", evidence_ref: "policy-7" }));
    fireEvent.change(screen.getByLabelText("Disposition for NOTE_PENDING_N03"), { target: { value: "Immaterial" } });
    fireEvent.click(screen.getByRole("button", { name: "Dispose" }));
    await waitFor(() => expect(api.dispose).toHaveBeenCalledWith("pkg1", "NOTE_PENDING_N03", "Immaterial"));
    expect(screen.getAllByRole("button", { name: "Sign" }).every((b) => (b as HTMLButtonElement).disabled)).toBe(true);
  });
});
