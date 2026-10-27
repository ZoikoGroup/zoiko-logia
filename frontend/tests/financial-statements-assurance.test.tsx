import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  list: vi.fn(), latest: vi.fn(), run: vi.fn(), decide: vi.fn(), materiality: vi.fn(), misstatement: vi.fn(),
  upload: vi.fn(), withdraw: vi.fn(), attest: vi.fn(), release: vi.fn(), summary: vi.fn(),
}));
vi.mock("@/lib/financial-statements-api", () => ({
  listPackages: api.list, getLatestAssurance: api.latest, runAssurance: api.run, decideFinding: api.decide,
  setMateriality: api.materiality, recordMisstatement: api.misstatement, uploadEvidence: api.upload,
  withdrawEvidence: api.withdraw, attestRun: api.attest, releaseRun: api.release, downloadAssuranceSummary: api.summary,
}));
import { AssurancePanel } from "@/components/financial-statements/AssurancePanel";

const finding = (code: string, severity: string, extra = {}) => ({ key: `Document 07:${code}`, source: "Document 07", code, severity,
  message: `${code} message`, rule: "QA-024", assertion: "disclosure", risk_domain: null, amount: null, action: "Upload evidence.",
  state: "OPEN", decisions: [], waiver: null, ...extra });
const VIEW = {
  id: "run1", package_id: "pkg1", package_version: 1, status: "FINDINGS_OPEN", input_hash: "sha256:abc123", snapshot_hash: "sha256:def456",
  standards_profile_hash: "sha256:x", ruleset: { id: "FS-ASSURANCE", version: "1", status: "UNREVIEWED_TEST_PACK" },
  header: { tenant_id: "t1", entity: "Northbridge Trading Ltd", period_start: "2025-04-01", period_end: "2026-03-31", framework: "FRS102_1A",
    edition: "FRS102_1A@2022-01", scope: "individual", statements: ["balance_sheet", "profit_or_loss"] },
  result: { evidence_scope: "uploaded_trial_balance_only",
    gates: [{ gate_id: "QG-X-01", title: "Statement of financial position", scope: "cross-statement", status: "PASS", method: "Σ assets − Σ liabilities − Σ equity = 0", source: "Document 05" },
      { gate_id: "QG-RISK-going_concern", title: "Going concern", scope: "evidence", status: "CANNOT_VERIFY", method: "Linked evidence", source: "none" }],
    risk_domains: [{ domain: "going_concern", title: "Going concern", applies: true, covered: false, evidence_needed: "Forecasts", evidence_ids: [] }],
    misstatements: { gross: "0", net: "0", overall_materiality: null, items: [] },
    negative: { untested_assertions: ["A balanced trial balance proves arithmetic only, not recognition or completeness (NB-06)."], missing_data: [] } },
  findings: [finding("EVIDENCE_GOING_CONCERN", "BLOCKER"), finding("MATERIALITY_NOT_APPROVED", "MATERIAL")],
  open: [finding("EVIDENCE_GOING_CONCERN", "BLOCKER"), finding("MATERIALITY_NOT_APPROVED", "MATERIAL")], closed_findings: [],
  attestations: {}, certificate: null,
  claims: [{ claim: "DRAFT_SOURCE_LIMITED", allowed: true, text: "Draft based on supplied trial balance; evidence and comparatives outstanding.", missing: [] },
    { claim: "AUDITED", allowed: false, text: null, missing: ["ZoikoLogia does not perform audits"] }],
  control_statement: {}, materiality: {}, evidence: [], ledger: [], preparer: "prep", superseded_by: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([{ id: "pkg1", version: 1, state: "RECONCILED", trial_balance_id: "tb1", resolution_id: "r1", entity: "Northbridge Trading Ltd", counts: {}, created_at: null }]);
  api.latest.mockResolvedValue(null);
  api.run.mockResolvedValue(VIEW);
  api.decide.mockResolvedValue(VIEW);
});

async function runIt() {
  render(<AssurancePanel />);
  const select = await screen.findByLabelText("Report package");
  await waitFor(() => expect(screen.getByRole("option", { name: /Northbridge/ })).toBeTruthy());
  fireEvent.change(select, { target: { value: "pkg1" } });
  await screen.findByText(/No run yet/);
  fireEvent.click(screen.getByRole("button", { name: "Run quality gates" }));
  await screen.findByRole("status");
}

describe("Assurance workbench (Document 07)", () => {
  it("shows the blocked status, gate matrix, what was not checked and refused claims", async () => {
    await runIt();
    expect(within(screen.getByRole("status")).getByText(/FINDINGS OPEN · 2 open/)).toBeTruthy();
    expect(screen.getByText("cannot verify")).toBeTruthy();
    expect(screen.getByText(/proves arithmetic only/)).toBeTruthy();
    expect(screen.getByText("ZoikoLogia does not perform audits")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Issue internal release" })).toHaveProperty("disabled", true);
  });

  it("records a decision on a finding with its owner and due date", async () => {
    await runIt();
    fireEvent.click(screen.getByRole("button", { name: /evidence going concern/ }));
    fireEvent.change(screen.getByLabelText("Owner"), { target: { value: "prep" } });
    fireEvent.change(screen.getByLabelText("Due"), { target: { value: "2026-11-15" } });
    fireEvent.click(screen.getByRole("button", { name: "Record decision" }));
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith("run1", expect.objectContaining({
      finding_key: "Document 07:EVIDENCE_GOING_CONCERN", decision: "request_evidence", owner: "prep", due: "2026-11-15" })));
  });
});
