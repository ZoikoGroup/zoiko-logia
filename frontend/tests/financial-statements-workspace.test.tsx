import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ list: vi.fn(), get: vi.fn(), provenance: vi.fn(), download: vi.fn() }));
vi.mock("@/lib/financial-statements-api", () => ({
  listPackages: api.list, getWorkspace: api.get, getProvenance: api.provenance, downloadPackage: api.download,
}));
import { WorkspacePanel } from "@/components/financial-statements/WorkspacePanel";

const VIEW = {
  package_id: "pkg1", version: 1, state: "DRAFT_BLOCKED", release_status: "BLOCKED",
  banner: "Cannot be released: 2 hard stop(s) and 1 review item(s) are open. The first is: No approved prior-period snapshot.",
  counts: { HARD_STOP: 2, MATERIAL_REVIEW: 1, INFORMATION: 0 },
  rail: [
    { source: "Statements (Document 05)", severity: "HARD_STOP", code: "COMPARATIVES_MISSING", message: "No approved prior-period snapshot.", rule: "AT-16", action: "Attach the prior period.", refs: [] },
    { source: "Framework (Document 03)", severity: "HARD_STOP", code: "STATUTORY_NOT_PERMITTED", message: "Rule pack unreviewed.", rule: "AS-007", action: "Review the pack.", refs: [] },
    { source: "Workspace (Document 02)", severity: "MATERIAL_REVIEW", code: "MATERIALITY_UNDOCUMENTED", message: "No materiality policy.", rule: "§5.1", action: "Record materiality.", refs: [] },
  ],
  scope: { entity: "Northbridge Trading Ltd", scope: "individual", report_type: "annual", period_start: "2025-04-01", period_end: "2026-03-31",
    jurisdiction: "GB-ENG", resolution_id: "r1", resolution_state: "FROZEN" },
  framework: { framework: "FRS102_1A", edition: "FRS102_1A@2022-01", layout: "UK_COMPANIES_ACT",
    rules: [{ rule_id: "UK.SIZE_THRESHOLDS", outcome: "SMALL", effective: "years beginning before 6 April 2025", source: "S5", adoption: "MANDATORY", endorsement: "" }],
    citations: { S5: { publisher: "GOV.UK", title: "Accounts", url: "https://gov.example/s5", checked: "2026-10-24", snapshot: null } },
    rule_pack: { id: "UK", version: "1", status: "UNREVIEWED_TEST_PACK", checked: "2026-10-24", valid_until: "2027-04-22", owner: "x", digest: "sha256:a", capabilities: {} },
    assembly_ruleset: { id: "FS", version: "1", status: "UNREVIEWED_TEST_PACK" } },
  source: { trial_balance_id: "tb1", filename: "northbridge-tb.csv", version: 1, sha256: "abcdef123456", imported_at: "2026-10-26T10:00:00Z",
    state: "APPROVED_SNAPSHOT", snapshot_hash: "sha256:feed", prior_trial_balance_id: null },
  tabs: [{ statement_id: "profit_or_loss", title: "Profit and loss account", status: "ASSEMBLED", requiredness: "REQUIRED", omission: null },
    { statement_id: "cash_flows", title: "Statement of cash flows", status: "EXEMPT", requiredness: "EXEMPT",
      omission: { basis: "Small entities are exempt (FRS 102 Section 1A)", approved_by: "rev", resolution_revision: 1 } },
    { statement_id: "notes", title: "Notes", status: "ASSEMBLED", requiredness: "REQUIRED", omission: null }],
  statements: [{ statement_id: "profit_or_loss", title: "Profit and loss account", requiredness: "REQUIRED", status: "ASSEMBLED",
    lines: [{ line_id: "administrative_expenses", label: "Administrative expenses", kind: "line", amount: "902000", prior: null, concepts: ["pl.administrative_expenses"] },
      { line_id: "profit", label: "Profit for the financial year", kind: "total", amount: "-151000", prior: null, concepts: [] }] }],
  notes: [{ requirement_id: "N02", title: "Accounting policy: revenue recognition", rule: "AT-13", applicability: "REQUIRED", evidence_needed: "", severity: "P0",
    state: "REQUIRED_MISSING", text: "", amount: null, evidence_ref: "", submitted_by: null, approved_by: null, issues: [] }],
  assertions: [],
  review_sequence: [{ role: "preparer", label: "Preparer", signed: null, available: true }, { role: "publisher", label: "Publisher", signed: null, available: false }],
  export: { draft_allowed: true, draft_refusal: [], final_allowed: false, final_reasons: ["x"], publish_allowed: false,
    publish_reason: "Publishing and filing need the publication engine (Document 06)." },
  answers: [{ question: "Which standards and dates apply?", answer: "FRS102_1A (FRS102_1A@2022-01)." },
    { question: "What can be exported now, and with which status?", answer: "A watermarked draft only." }],
};
const PROVENANCE = {
  statement_id: "profit_or_loss", statement_title: "Profit and loss account", line: VIEW.statements[0].lines[0],
  concepts: [{ line_id: "pl.administrative_expenses", label: "Administrative expenses" }], computation: "Sum of the approved accounts.",
  accounts: [{ account_key: "6000", account_name: "Utilities", balance: "18400", line_id: "pl.administrative_expenses", allocations: [],
    status: "APPROVED", reviewer: "rev", evidence_ref: "meters-2026", basis: "", source_row: "CSV!R7" }],
  journals: [], supporting: [], rule: { layout: "UK_COMPANIES_ACT", edition: "FRS102_1A@2022-01", ruleset: "FS" },
  source_file: { filename: "northbridge-tb.csv", version: 1, sha256: "abc" }, snapshot_hash: "sha256:feed", line_checksum: "sha256:beef",
};

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([{ id: "pkg1", version: 1, state: "RECONCILED", trial_balance_id: "tb1", resolution_id: "r1", entity: "Northbridge Trading Ltd", counts: {}, created_at: null }]);
  api.get.mockResolvedValue(VIEW);
  api.provenance.mockResolvedValue(PROVENANCE);
});

async function openPackage() {
  render(<WorkspacePanel onOpen={vi.fn()} />);
  const select = await screen.findByLabelText("Report package");
  await waitFor(() => expect(screen.getByRole("option", { name: /Northbridge/ })).toBeTruthy());
  fireEvent.change(select, { target: { value: "pkg1" } });
  await screen.findByRole("status");
}

describe("Financial statements workspace (Document 02)", () => {
  it("shows the release status in text, the scope, framework and source, and never zero for a missing comparative", async () => {
    await openPackage();
    const status = screen.getByRole("status");
    expect(within(status).getByText("BLOCKED")).toBeTruthy();
    expect(within(status).getByText(/2 hard stop · 1 review/)).toBeTruthy();
    expect(screen.getByText("FRS102_1A@2022-01")).toBeTruthy();
    expect(screen.getByText("northbridge-tb.csv · v1")).toBeTruthy();
    expect(screen.getAllByText("not supplied").length).toBe(2);
    expect(screen.getByText("(151,000)")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Publish" })).toHaveProperty("disabled", true);
  });

  it("opens a row's lineage and keeps an exempt statement's legal basis", async () => {
    await openPackage();
    fireEvent.click(screen.getByRole("button", { name: "Administrative expenses" }));
    const drawer = await screen.findByRole("region", { name: "Source drill-down" });
    expect(within(drawer).getByText(/meters-2026/)).toBeTruthy();
    expect(api.provenance).toHaveBeenCalledWith("pkg1", "profit_or_loss", "administrative_expenses");
    fireEvent.click(screen.getByRole("tab", { name: /Statement of cash flows/ }));
    expect(screen.getByText(/Small entities are exempt/)).toBeTruthy();
  });

  it("filters the validation rail by severity", async () => {
    await openPackage();
    const rail = screen.getByRole("complementary", { name: "Validation rail" });
    fireEvent.click(within(rail).getByRole("button", { name: /Material review 1/ }));
    expect(within(rail).getByText("materiality undocumented")).toBeTruthy();
    expect(within(rail).queryByText("comparatives missing")).toBeNull();
  });
});
