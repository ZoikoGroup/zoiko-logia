import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  list: vi.fn(), overview: vi.fn(), preview: vi.fn(), render: vi.fn(), issue: vi.fn(), filing: vi.fn(), reimport: vi.fn(), download: vi.fn(),
}));
vi.mock("@/lib/financial-statements-api", () => ({
  listPackages: api.list, getPublication: api.overview, previewPublication: api.preview, renderPublication: api.render,
  issuePublication: api.issue, submitFiling: api.filing, reimportWord: api.reimport, downloadArtifact: api.download,
}));
import { PublicationPanel } from "@/components/financial-statements/PublicationPanel";

const MODEL = {
  audience: "member_accounts", audience_title: "Annual report and financial statements", scale: "units", unit_label: "£", state: "WORKING_DRAFT",
  status_label: "DRAFT — NOT FOR STATUTORY USE", draft: true,
  masthead: { entity: "Northbridge Trading Ltd", period_start: "2025-04-01", period_end: "2026-03-31", framework: "FRS102_1A", edition: "FRS102_1A@2022-01" },
  statements: [{ statement_id: "profit_or_loss", title: "Profit and loss account", status: "ASSEMBLED", note: "",
    lines: [{ concept_id: "profit_or_loss.cost_of_sales", label: "Cost of sales", kind: "line", amount: "2431000", display: "(2,431,000)", prior_display: "not provided" }] }],
  omitted: [], notes: [], analysis: null, rounding: [], blockers: [], model_hash: "sha256:abc123",
};
const OVERVIEW = {
  package_id: "pkg1", package_version: 1, state: "WORKING_DRAFT", entity: "Northbridge Trading Ltd", framework: "FRS102_1A@2022-01",
  assurance_status: null, release_id: null, misleading: [],
  audiences: [{ key: "member_accounts", title: "Annual report and financial statements", statutory: true, public: false,
    issue_blockers: ["The package is working draft; issue needs the Document 07 internal release of this package version."] }],
  audience_matrix: { id: "UK-AUDIENCE-2026.10", status: "UNREVIEWED", notes: ["The paused small/micro profit-and-loss filing proposal is not treated as a current requirement (PUB-T024)."] },
  adapters: { UK_COMPANIES_HOUSE: { title: "Companies House accounts filing", status: "NOT_CERTIFIED" } },
  taxonomies: { "FRC-2026": { title: "FRC taxonomies 2026", installed: false, licence: "Not verified" } },
  artifacts: [{ id: "a1", kind: "RENDER", audience: "member_accounts", channel: "pdf", scale: "units", state: "WORKING_DRAFT", filename: "nb.pdf",
    sha256: "deadbeefcafe0000", size_bytes: 100, created_at: null, source_artifact_id: null,
    validation: { parity: { ok: true, issues: [] }, sensitive: { ok: true, hits: [], blocking: false }, accessibility: { ok: true, failed: [], limitation: "" } } }],
  issues: [],
};

beforeEach(() => {
  vi.clearAllMocks();
  api.list.mockResolvedValue([{ id: "pkg1", version: 1, state: "RECONCILED", trial_balance_id: "tb1", resolution_id: "r1", entity: "Northbridge Trading Ltd", counts: {}, created_at: null }]);
  api.overview.mockResolvedValue(OVERVIEW);
  api.preview.mockResolvedValue({ model: MODEL, state: "WORKING_DRAFT", issue_blockers: [] });
  api.render.mockResolvedValue(OVERVIEW.artifacts[0]);
});

async function openIt() {
  render(<PublicationPanel />);
  const select = await screen.findByLabelText("Report package");
  await waitFor(() => expect(screen.getByRole("option", { name: /Northbridge/ })).toBeTruthy());
  fireEvent.change(select, { target: { value: "pkg1" } });
  await screen.findByRole("status");
}

describe("Publication workspace (Document 06)", () => {
  it("previews the draft with its status label, parentheses and no invented comparative, and blocks issue", async () => {
    await openIt();
    expect(screen.getByText("DRAFT — NOT FOR STATUTORY USE")).toBeTruthy();
    expect(screen.getByText("(2,431,000)")).toBeTruthy();
    expect(screen.getByText("not provided")).toBeTruthy();
    expect(within(screen.getByRole("status")).getByText(/issue needs the Document 07 internal release/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Issue this audience" })).toHaveProperty("disabled", true);
    expect(screen.getByText("parity ok")).toBeTruthy();
    expect(screen.getAllByText("not certified").length).toBeGreaterThan(0);
  });

  it("renders a channel from the approved model", async () => {
    await openIt();
    fireEvent.click(screen.getByRole("button", { name: "Word" }));
    await waitFor(() => expect(api.render).toHaveBeenCalledWith("pkg1", { audience: "member_accounts", channel: "docx", scale: "units" }));
  });
});
