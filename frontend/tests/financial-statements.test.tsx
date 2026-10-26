import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  list: vi.fn(), get: vi.fn(), catalogue: vi.fn(), decide: vi.fn(), propose: vi.fn(), review: vi.fn(),
  approve: vi.fn(), upload: vi.fn(), supporting: vi.fn(), lineage: vi.fn(), original: vi.fn(),
}));
vi.mock("@/lib/financial-statements-api", () => ({
  listTrialBalances: api.list, getTrialBalance: api.get, getCatalogue: api.catalogue, decideMapping: api.decide,
  proposeJournal: api.propose, reviewJournal: api.review, approveSnapshot: api.approve, uploadTrialBalance: api.upload,
  addSupporting: api.supporting, getLineage: api.lineage, downloadOriginal: api.original,
}));
import FinancialStatementsPage from "@/app/financial-statements/page";

const SUMMARY = { id: "tb1", filename: "tb.csv", sha256: "abc123def456", version: 1, kind: "TRIAL_BALANCE",
  state: "MAPPING_REVIEW", uploaded_by: "prep", created_at: "2026-10-26T10:00:00Z", supersedes_id: null,
  superseded_by: null, balanced: true, hard_stops: 0 };
const mapping = (over: object) => ({ id: "m1", account_key: "4000", account_name: "Revenue", balance: "-1000",
  status: "SUGGESTED", line_id: "pl.revenue", line_label: "Revenue", candidates: [], evidence_required: "",
  basis: "Suggested from the account name", allocations: [], reviewer: null, evidence_ref: "", source: "CSV!R2",
  decided_at: null, ...over });
const DETAIL = { ...SUMMARY, units: "units", sign_convention: "DEBIT_CREDIT_COLUMNS", period_end: null,
  sheets: { sheets: ["CSV"], hidden_sheets: [] },
  integrity: { total_debits: "1000.00", total_credits: "1000.00", difference: "0.00", balanced: true,
    basis: "debit and credit columns", note: "Debits equal credits proves the arithmetic only." },
  findings: [{ code: "COMPARATIVE_MISSING", severity: "REVIEW", message: "No prior-year figures.", rule: "SD-008", refs: [] }],
  lines: [], mapping_counts: { APPROVED: 0 }, journals: [], supporting: [], snapshots: [],
  history: [{ action: "uploaded", actor_id: "prep", at: "2026-10-26T10:00:00Z", detail: {} }],
  status_note: "Mappings are proposals until a reviewer other than the uploader approves them.",
  mappings: [mapping({}), mapping({ id: "m2", account_key: "6000", account_name: "Utilities", balance: "1000",
    status: "NEEDS_EVIDENCE", line_id: null, line_label: null, evidence_required: "site invoices or cost centres",
    candidates: [{ line_id: "pl.cost_of_sales", label: "Cost of sales" }, { line_id: "pl.administrative_expenses", label: "Administrative expenses" }] })] };
const CATALOGUE = { lines: [{ line_id: "pl.revenue", label: "Revenue", section: "profit_or_loss" },
  { line_id: "pl.cost_of_sales", label: "Cost of sales", section: "profit_or_loss" },
  { line_id: "pl.administrative_expenses", label: "Administrative expenses", section: "profit_or_loss" }],
  correction_types: [{ code: "PRESENTATION", treatment: "Reclassification between lines only." },
    { code: "CURRENT_PERIOD", treatment: "Correction of the current period." }],
  supporting_kinds: [{ code: "receivables_ageing", line_id: "bs.trade_receivables", label: "Trade and other receivables" }] };

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.list.mockResolvedValue([SUMMARY]);
  api.get.mockResolvedValue(DETAIL);
  api.catalogue.mockResolvedValue(CATALOGUE);
  api.decide.mockResolvedValue(DETAIL);
});

async function openUpload() {
  render(<FinancialStatementsPage />);
  fireEvent.click(await screen.findByRole("button", { name: /tb\.csv/ }));
  await screen.findByText("Account mapping");
}

describe("Financial Statements — trial balance intake", () => {
  it("shows the checks, findings and that a balanced TB proves the arithmetic only", async () => {
    await openUpload();
    expect(screen.getByText("Mapping review")).toBeInTheDocument();
    expect(screen.getByText("Debits equal credits proves the arithmetic only.")).toBeInTheDocument();
    expect(screen.getByText(/COMPARATIVE MISSING/)).toBeInTheDocument();
  });

  it("approves a suggested line and requires evidence for a needs-evidence account", async () => {
    await openUpload();
    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);
    await waitFor(() => expect(api.decide).toHaveBeenCalledWith("tb1", "m1", { action: "approve", line_id: "pl.revenue", evidence_ref: "" }));
    const approveUtilities = screen.getAllByRole("button", { name: "Approve" })[1];
    expect(approveUtilities).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Evidence reference for Utilities"), { target: { value: "INV-7" } });
    expect(approveUtilities).not.toBeDisabled();
  });

  it("keeps snapshot approval disabled until every check passes", async () => {
    await openUpload();
    expect(screen.getByRole("button", { name: "Approve snapshot" })).toBeDisabled();
  });

  it("only proposes a balanced journal, and says it is not posted", async () => {
    await openUpload();
    const submit = screen.getByRole("button", { name: /Propose journal \(not posted\)/ });
    fireEvent.change(screen.getByLabelText("Reason"), { target: { value: "Factory utilities" } });
    fireEvent.change(screen.getByLabelText("Line 1 statement line"), { target: { value: "pl.cost_of_sales" } });
    fireEvent.change(screen.getByLabelText("Line 1 debit"), { target: { value: "100" } });
    fireEvent.change(screen.getByLabelText("Line 2 statement line"), { target: { value: "pl.administrative_expenses" } });
    fireEvent.change(screen.getByLabelText("Line 2 credit"), { target: { value: "90" } });
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Line 2 credit"), { target: { value: "100" } });
    expect(submit).not.toBeDisabled();
  });
});
