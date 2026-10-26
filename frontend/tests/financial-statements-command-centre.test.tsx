import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({ list: vi.fn(), centre: vi.fn(), register: vi.fn(), golden: vi.fn() }));
vi.mock("@/lib/financial-statements-api", () => ({
  listPackages: api.list, getCommandCentre: api.centre, getAcceptanceRegister: api.register, runGolden: api.golden,
}));
import { CommandCentrePanel } from "@/components/financial-statements/CommandCentrePanel";

const gate = (g: string, title: string, status: string, code: string | null = null) =>
  ({ gate: g, title, status, owner: "Owner", detail: `${title} detail`, error_code: code, retriable: false, correlation_id: "c" });
const VIEW = {
  context: { entity: "Northbridge Trading Ltd", period_start: "2025-04-01", period_end: "2026-03-31", currency: "units",
    framework_edition: "FRS102_1A@2022-01", package_hash: "sha256:abc", variant: ["draft"], release_state: "DRAFT", applicability_decision_id: "r1@1" },
  chain: [gate("G0", "Scope", "PASS"), gate("G4", "Reconcile", "BLOCKED", "FR-DISCLOSURE-MISSING"), gate("G7", "File / close", "NOT_AVAILABLE", "FR-FILING-UNCONFIRMED")],
  invariants: [{ id: "INV-02", title: "Assets = liabilities + equity", status: "PASS", detail: "Σ" }],
  rail: { hard: [{ source: "Document 05", code: "COMPARATIVES_MISSING", message: "No prior period." }], soft: [] },
  manifest: { idempotency_key: "sha256:key1", status: "DRAFT", audit_event_root: "sha256:root1",
    sources: [{ source_id: "tb1", sha256: "abcdef1234567890", provenance: "tb.csv", ingestion_version: 1 }] },
  support: [{ scope: "US GAAP", level: "UNSUPPORTED", why: "Reference only." }], errors: {}, export_simulation: [],
  publication_disabled_reason: "Publication stays disabled until G0–G5 pass.",
};
const CASES = [
  { id: "PL-01", feature: "FR-013", stimulus: "£14,900 difference raises a comparison exception", coverage: "AUTOMATED",
    tests: ["tests/test_financial_statements_integration.py::test_kriton_versus_five_raises_a_classification_dispute"], note: "", status: "NOT_RUN_IN_PRODUCT" },
  { id: "BS-04", feature: "FR-012", stimulus: "Lease obligation coherent", coverage: "NOT_IMPLEMENTED", tests: [],
    note: "There are no lease concepts in the statement catalogue.", status: "NOT_RUN_IN_PRODUCT" },
];

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([{ id: "pkg1", version: 1, state: "RECONCILED", trial_balance_id: "tb1", resolution_id: "r1", entity: "Northbridge Trading Ltd", counts: {}, created_at: null }]);
  api.centre.mockResolvedValue(VIEW);
  api.register.mockResolvedValue({ cases: CASES, support: [], errors: {} });
  api.golden.mockResolvedValue({ fixture: "nb", label: "SYNTHETIC SEED", oracle_status: "UNREVIEWED", aborted: false,
    runs: { five_platform: { figures: { operating_profit: "218600", profit_before_tax: "216400", profit: "154400" }, findings: [], needs_evidence: [], balanced: true } },
    mismatches: { five_platform: [] },
    dispute: { code: "CLASSIFICATION_DISPUTE", difference: "14900.00", operating_profit: { five_platform: "218600", kriton_001: "233500" },
      accounts: ["Bank charges", "Interest received"], disposition: "Evidence required." } });
});

describe("Integration command centre (Document 08)", () => {
  it("shows the chain with error codes, invariants, hard blockers and the manifest", async () => {
    render(<CommandCentrePanel />);
    const select = await screen.findByLabelText("Report package");
    await waitFor(() => expect(screen.getByRole("option", { name: /Northbridge/ })).toBeTruthy());
    fireEvent.change(select, { target: { value: "pkg1" } });
    expect(await screen.findByText(/G4 Reconcile/)).toBeTruthy();
    expect(screen.getByText(/FR-DISCLOSURE-MISSING/)).toBeTruthy();
    expect(screen.getByText(/INV-02/)).toBeTruthy();
    expect(screen.getByText(/comparatives missing/)).toBeTruthy();
    expect(screen.getByText(/tb.csv v1/)).toBeTruthy();
  });

  it("lists the register honestly and runs the golden dataset with its dispute", async () => {
    render(<CommandCentrePanel />);
    expect(await screen.findByText(/£14,900 difference/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /not implemented 1/ }));
    expect(screen.queryByText(/£14,900 difference/)).toBeNull();
    expect(screen.getByText(/no lease concepts/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Run golden dataset" }));
    const dispute = await screen.findByText(/Classification dispute: £14900.00/);
    expect(within(dispute.parentElement as HTMLElement).getByText(/Bank charges, Interest received/)).toBeTruthy();
  });
});
